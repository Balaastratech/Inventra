"""
Regression guard for the pending-scan cost fix (B4 groundwork).

list_pending_cases() used to call compile_graph() -- a fresh SQLite
connection to the checkpoint file plus a full build_graph().compile() -- and
latest_thread_id() once per pending case, inside the loop. The Streamlit
sidebar calls list_pending_cases() on every rerun, so the cost scaled with
the size of the operator's to-do list and multiplied concurrent access to
checkpoints.sqlite for no benefit (the graph topology is identical every
time).

These tests assert the fix behaviourally -- exactly one compile regardless
of how many cases are pending -- rather than asserting on timings, which
would be flaky. Also pins latest_thread_ids() to agree with the single-case
latest_thread_id() it now backs, since a drift between them would silently
resume the wrong run of a case.
"""

from __future__ import annotations

import pytest

from submission.graph import workflow
from submission.graph.workflow import compile_graph, latest_thread_id, latest_thread_ids
from submission.portfolio import list_pending_cases
from submission.state.state import create_initial_state
from submission.tests.reset_db import reset_business_state


@pytest.fixture(scope="module", autouse=True)
def clean_state():
    reset_business_state()
    yield


def _run(sku, warehouse_id, target_cover_days=None):
    graph, conn = compile_graph()
    try:
        state = create_initial_state(sku, warehouse_id, target_cover_days)
        return graph.invoke(state, config={"configurable": {"thread_id": state["thread_id"]}})
    finally:
        conn.close()


def test_scan_compiles_the_graph_once_for_multiple_pending_cases(monkeypatch):
    """The actual regression: N pending cases must still cost one compile."""
    # Two genuinely paused cases. The missing-SKU pause is deliberately used
    # for the second one because it stops at validate_request without
    # spending a model call.
    first = _run("AC-003", "DEL-01")
    assert "__interrupt__" in first
    second = _run("", "DEL-01")
    assert "__interrupt__" in second

    calls = {"count": 0}
    real_compile = workflow.compile_graph

    def counting_compile():
        calls["count"] += 1
        return real_compile()

    # Patched on the workflow module because portfolio.list_pending_cases
    # imports it lazily, inside the function body.
    monkeypatch.setattr(workflow, "compile_graph", counting_compile)

    pending = list_pending_cases()

    assert len(pending) >= 2, "fixture did not leave two cases paused"
    assert calls["count"] == 1, (
        f"expected a single compile_graph() for the whole scan, got {calls['count']} "
        f"across {len(pending)} pending case(s)"
    )


def test_batch_thread_id_lookup_agrees_with_the_single_case_form():
    """latest_thread_id now delegates to latest_thread_ids; if the two ever
    disagreed, a resume would act on a different run than the UI displayed."""
    _run("AC-003", "DEL-06")

    from submission.portfolio import list_cases

    case_ids = [c["case_id"] for c in list_cases()]
    assert case_ids, "no cases recorded, nothing to compare"

    batch = latest_thread_ids(case_ids)
    for case_id in case_ids:
        assert batch.get(case_id) == latest_thread_id(case_id), case_id


def test_batch_thread_id_lookup_handles_empty_and_unknown_input():
    assert latest_thread_ids([]) == {}
    assert latest_thread_ids(["CASE-DOES-NOT-EXIST-XX"]) == {}
