"""
Gap 6 proof: route_after_revalidation must branch on WHICH check failed, not
just whether something failed. A hash mismatch is structural -- the
proposal doesn't match its own content hash, which re-running risk
assessment cannot fix -- so it fails closed immediately. Budget, stock, and
offer changes are all genuinely re-checkable on a fresh read, so those get
the one bounce (scenario 7 explicitly expects "case re-enters risk
assessment with new facts" for a budget change during the pause).
"""

from __future__ import annotations

from domain.tool_models import RevalidationResult
from submission.graph.routes import route_after_revalidation


def _result(**overrides) -> RevalidationResult:
    base = dict(
        proposal_id="PROP-1",
        proposal_hash="abc",
        hash_matches=True,
        stock_valid=True,
        offer_valid=True,
        budget_valid=True,
        all_checks_pass=True,
        error_details=None,
    )
    base.update(overrides)
    base["all_checks_pass"] = all(
        base[k] for k in ("hash_matches", "stock_valid", "offer_valid", "budget_valid")
    )
    return RevalidationResult(**base)


def test_hash_mismatch_fails_closed_immediately():
    state = {"revalidation": _result(hash_matches=False), "retry_counts": {"revalidate": 1}}
    assert route_after_revalidation(state) == "blocked"


def test_budget_shortfall_gets_the_one_bounce():
    # Scenario 7 (fixtures/scenarios.json APPROVAL_DATA_CHANGE): "case
    # re-enters risk assessment with new facts" -- a budget change during
    # the pause must bounce, not fail closed immediately.
    state = {"revalidation": _result(budget_valid=False), "retry_counts": {"revalidate": 1}}
    assert route_after_revalidation(state) == "retry_from_risk"


def test_budget_shortfall_still_blocks_once_the_bounce_is_spent():
    state = {"revalidation": _result(budget_valid=False), "retry_counts": {"revalidate": 2}}
    assert route_after_revalidation(state) == "blocked"


def test_stale_stock_gets_the_one_bounce():
    state = {"revalidation": _result(stock_valid=False), "retry_counts": {"revalidate": 1}}
    assert route_after_revalidation(state) == "retry_from_risk"


def test_invalid_offer_gets_the_one_bounce():
    state = {"revalidation": _result(offer_valid=False), "retry_counts": {"revalidate": 1}}
    assert route_after_revalidation(state) == "retry_from_risk"


def test_retryable_failure_still_blocks_once_the_bounce_is_spent():
    state = {"revalidation": _result(stock_valid=False), "retry_counts": {"revalidate": 2}}
    assert route_after_revalidation(state) == "blocked"


def test_all_checks_pass_routes_to_execution():
    state = {"revalidation": _result(), "retry_counts": {}}
    assert route_after_revalidation(state) == "pass"
