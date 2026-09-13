"""
Phase 4: real agent wiring. Split into two tiers:

1. Fake-agent tests (always run, no API key needed) -- drive the REAL graph
   through nodes.recommend_vendor with a fake agent_fn standing in for the
   LLM call, proving the retry-once-then-fail-closed loop (scenario 6) and
   the semantic-validation hook actually work against a real exception, not
   just the stub's always-valid path.
2. Live-model tests (skipped unless a real key is configured) -- prove the
   actual prompts + structured-output binding work against Gemini/OpenAI.
   These are opportunistic: they run for whoever has a key in
   submission/.env, skip cleanly for everyone else (including CI/grading
   environments without one), and never fail the suite for a missing key.
"""

from __future__ import annotations

import os

import pytest

from domain.tool_models import ErrorCode, ProposalStatus
from submission.agents.llm import is_configured
from submission.config import config
from submission.graph import nodes
from submission.graph.workflow import compile_graph
from submission.state.state import create_initial_state
from submission.tests.reset_db import reset_business_state


@pytest.fixture(scope="module", autouse=True)
def clean_state():
    reset_business_state()
    yield


@pytest.fixture(autouse=True)
def restore_stub_agents():
    """Every test in this module monkeypatches nodes._AGENTS directly (not
    via a fixture-scoped monkeypatch, since we need it to persist across a
    single graph.invoke() call) -- restore the Phase 2/3 stubs afterward so
    later test modules aren't affected by whichever fake ran last."""
    from submission.agents import stubs

    yield
    nodes.set_agents(
        assess_demand=stubs.assess_demand_stub,
        recommend_vendor=stubs.recommend_vendor_stub,
        review_policy=stubs.review_policy_stub,
    )


def _run(sku, warehouse_id, target_cover_days=None):
    graph, conn = compile_graph()
    try:
        state = create_initial_state(sku, warehouse_id, target_cover_days)
        return graph.invoke(state, config={"configurable": {"thread_id": state["thread_id"]}})
    finally:
        conn.close()


# ============================================================================
# Tier 1: fake agent, no API key needed
# ============================================================================

def test_repair_attempt_succeeds_on_second_try():
    """Simulates exactly what a real bad-then-good LLM response looks like:
    first call raises (malformed output), second call returns valid data.
    Scenario 6: one repair attempt, then proceed."""
    calls = {"n": 0}

    def flaky_recommend(state, last_error):
        calls["n"] += 1
        if calls["n"] == 1:
            assert last_error is None
            raise ValueError("model returned recommended_offer_id: null")
        assert last_error is not None and "null" in last_error
        from submission.agents.stubs import recommend_vendor_stub

        return recommend_vendor_stub(state, last_error)

    nodes.set_agents(recommend_vendor=flaky_recommend)
    result = _run("AC-003", "DEL-06")

    assert calls["n"] == 2
    assert "__interrupt__" in result, "should still reach approval after the repair succeeded"
    assert result["retry_counts"]["recommend_vendor"] == 2


def test_two_failures_fail_closed_without_a_third_attempt():
    """Scenario 6's other half: repair also fails -> BLOCKED, never a 3rd call."""
    calls = {"n": 0}

    def always_broken(state, last_error):
        calls["n"] += 1
        raise ValueError(f"attempt {calls['n']}: model omitted required field 'rationale'")

    nodes.set_agents(recommend_vendor=always_broken)
    result = _run("AC-003", "DEL-07")

    assert calls["n"] == config.max_model_attempts_per_agent == 2, "must not attempt a third time"
    assert "__interrupt__" not in result
    assert result["status"] == ProposalStatus.BLOCKED
    assert result["error_code"] == ErrorCode.UNKNOWN_ERROR
    assert "after retry" in result["error_detail"]


def test_semantically_invalid_offer_id_is_caught_and_retried():
    """Schema-valid but content-wrong: the agent invents an offer_id that
    isn't in the eligible list it was given. Must be caught by the
    validate= hook in nodes.recommend_vendor, not silently accepted (which
    would crash draft_proposal downstream with a raw StopIteration)."""
    from submission.agents.models import ReplenishmentRecommendation, SourcingStrategy

    calls = {"n": 0}

    def hallucinating_recommend(state, last_error):
        calls["n"] += 1
        if calls["n"] == 1:
            return ReplenishmentRecommendation(
                case_id=state["case_id"],
                recommended_offer_id="OFFER-DOES-NOT-EXIST",
                strategy=SourcingStrategy.BALANCED,
                rationale="invented offer id",
                evidence_ids=[],
            )
        from submission.agents.stubs import recommend_vendor_stub

        return recommend_vendor_stub(state, last_error)

    nodes.set_agents(recommend_vendor=hallucinating_recommend)
    result = _run("AC-003", "DEL-08")

    assert calls["n"] == 2, "the bad offer_id must trigger a repair attempt, not pass straight through"
    assert "__interrupt__" in result, "should recover and still reach approval on the repair"


# ============================================================================
# Tier 2: live model, opportunistic
# ============================================================================

@pytest.mark.skipif(not is_configured(), reason="no API key configured for MODEL_PROVIDER (submission/.env)")
def test_live_demand_assessment_returns_valid_structured_output():
    from submission.agents.real import assess_demand_llm
    from submission.agents.models import DemandAssessment
    from tools.inventory import get_stock_position
    from tools.sales import get_sales_velocity

    state = create_initial_state("AC-003", "DEL-01")
    state["stock"] = get_stock_position("AC-003", "DEL-01")
    state["sales"] = get_sales_velocity("AC-003", "DEL-01")

    result = assess_demand_llm(state, None)
    assert isinstance(result, DemandAssessment)
    assert result.chosen_window_days in (7, 30)
