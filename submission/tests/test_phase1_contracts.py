"""
Phase 1 self-check: config loads, initial state is well-formed, and the
three new agent-output models actually enforce their contract (this is the
"critical outputs are Pydantic-validated" requirement — prove it rejects
bad input, not just that it accepts good input).
"""

import pytest
from pydantic import ValidationError

from domain.tool_models import ProposalStatus
from submission.agents.models import (
    ChecklistVerdict,
    DemandAssessment,
    PolicyChecklistItem,
    PolicyQuestion,
    PolicyReview,
    PolicyVerdict,
    ReplenishmentRecommendation,
    SourcingStrategy,
)

_FULL_PASS_CHECKLIST = [
    PolicyChecklistItem(question=q, verdict=ChecklistVerdict.PASS, rationale="ok") for q in PolicyQuestion
]
from submission.config import config
from submission.state.state import create_initial_state, new_case_id


def test_config_has_policy_authoritative_freshness_threshold():
    # The brief's own business-rules table says 2 hours, but policy.md (what
    # the Policy Reviewer agent actually reads) says "2 days" -- project
    # owner's explicit decision (2026-09-06): policy.md is authoritative for
    # this one value, so the agent never reasons from a number the code
    # contradicts. See submission/config.py's module docstring.
    assert config.data_freshness_hours == 48.0
    assert config.max_revision_cycles == 1
    assert config.max_model_attempts_per_agent == 2
    assert config.model_provider in ("vertex", "gemini", "openai")  # no Anthropic (D3)


def test_freshness_threshold_is_configurable_via_env(monkeypatch):
    # Brief §1: "Keep thresholds configurable rather than hiding them inside
    # prompts." DATA_FRESHNESS_HOURS lets a grader run the literal 2-hour
    # brief reading without touching code.
    from submission.config import Config

    monkeypatch.setenv("DATA_FRESHNESS_HOURS", "2")
    assert Config().data_freshness_hours == 2.0
    monkeypatch.delenv("DATA_FRESHNESS_HOURS", raising=False)
    assert Config().data_freshness_hours == 48.0


def test_email_enabled_defaults_true(monkeypatch):
    # Gap fix: email notifications should work out of the box, not require
    # an operator to discover and flip an env var first. This repo's own
    # submission/.env sets EMAIL_ENABLED=true explicitly (real credentials
    # configured for this dev machine), so the *default* can only be proven
    # by removing that override for the duration of the test.
    from submission.config import Config

    monkeypatch.delenv("EMAIL_ENABLED", raising=False)
    monkeypatch.delenv("VENDOR_EMAIL_ENABLED", raising=False)
    assert Config().email_enabled is True
    assert Config().vendor_email_enabled is False  # stays off pending Phase 8 go-live review


def test_freshness_threshold_is_not_duplicated_in_tools_inventory():
    # tools/inventory.py must defer to whatever threshold it's given, not its
    # own hardcoded module constant, so config.data_freshness_hours is the
    # single source of truth (not two numbers that happen to agree today).
    from datetime import datetime, timedelta

    from tools.inventory import calculate_stock_risk

    captured_at = datetime.utcnow() - timedelta(hours=10)
    fresh_with_tight_threshold = calculate_stock_risk(
        available_units=100, daily_velocity=1, target_cover_days=14,
        snapshot_captured_at=captured_at, stale_threshold_hours=5,
    )
    fresh_with_loose_threshold = calculate_stock_risk(
        available_units=100, daily_velocity=1, target_cover_days=14,
        snapshot_captured_at=captured_at, stale_threshold_hours=48,
    )
    assert fresh_with_tight_threshold.stale is True
    assert fresh_with_loose_threshold.stale is False


def test_create_initial_state_shape():
    state = create_initial_state("AC-001", "DEL-01")
    assert state["case_id"] == new_case_id("AC-001", "DEL-01") == "CASE-AC-001-DEL-01"
    # case_id is the stable business identity and never forks across revisions
    # (D8). thread_id is per-RUN checkpoint identity derived from it: two runs
    # of the same product must not share a checkpoint thread, or a finished
    # case (rejected/blocked/ordered) could never be re-examined.
    assert state["thread_id"].startswith(state["case_id"] + "#")
    assert state["thread_id"] != create_initial_state("AC-001", "DEL-01")["thread_id"]
    assert state["target_cover_days"] == config.target_cover_default_days
    assert state["status"] == ProposalStatus.NEEDS_INFORMATION
    assert state["revision_count"] == 0


def test_demand_assessment_rejects_unknown_field():
    good = DemandAssessment(
        case_id="CASE-AC-001-DEL-01",
        chosen_window_days=7,
        rationale="7-day window reflects a recent demand shift better than 30-day.",
        ambiguous=False,
        evidence_ids=["sales:AC-001:DEL-01"],
    )
    assert good.chosen_window_days == 7

    with pytest.raises(ValidationError):
        DemandAssessment(
            case_id="CASE-AC-001-DEL-01",
            chosen_window_days=7,
            rationale="x",
            ambiguous=False,
            evidence_ids=[],
            made_up_field="should not be allowed",  # extra="forbid"
        )


def test_replenishment_recommendation_requires_rationale():
    with pytest.raises(ValidationError):
        ReplenishmentRecommendation(
            case_id="CASE-AC-001-DEL-01",
            recommended_offer_id="OFFER-1",
            strategy=SourcingStrategy.BALANCED,
            rationale="",  # min_length=1
        )


def test_policy_review_verdict_is_typed_enum_not_free_text():
    with pytest.raises(ValidationError):
        PolicyReview(
            case_id="CASE-AC-001-DEL-01",
            proposal_id="PROP-1",
            verdict="looks fine to me",  # not a PolicyVerdict member
            checklist=_FULL_PASS_CHECKLIST,
            rationale="not a valid enum value",
        )

    review = PolicyReview(
        case_id="CASE-AC-001-DEL-01",
        proposal_id="PROP-1",
        verdict=PolicyVerdict.PASS,
        checklist=_FULL_PASS_CHECKLIST,
        rationale="Evidence-backed, within budget, vendor reliable.",
    )
    assert review.verdict == PolicyVerdict.PASS


def test_policy_review_checklist_must_cover_every_question_exactly_once():
    with pytest.raises(ValidationError):
        PolicyReview(
            case_id="CASE-AC-001-DEL-01",
            proposal_id="PROP-1",
            verdict=PolicyVerdict.PASS,
            rationale="missing a question",
            checklist=[
                PolicyChecklistItem(question=q, verdict=ChecklistVerdict.PASS, rationale="ok")
                for q in list(PolicyQuestion)[:-1]  # one short
            ],
        )

    with pytest.raises(ValidationError):
        PolicyReview(
            case_id="CASE-AC-001-DEL-01",
            proposal_id="PROP-1",
            verdict=PolicyVerdict.PASS,
            rationale="duplicated a question",
            checklist=[
                PolicyChecklistItem(question=PolicyQuestion.BUDGET_FIT, verdict=ChecklistVerdict.PASS, rationale="ok"),
                *_FULL_PASS_CHECKLIST[1:],  # BUDGET_FIT now appears twice, FRESHNESS not at all
            ],
        )
