"""
Gap proof: a hard reload must not drop the user back on the watchlist when
they were looking at a specific case. st.query_params survives a reload
(it's part of the URL) even though st.session_state does not, so ui.py
mirrors view/case_id/thread_id into the URL and reads them back on a fresh
session. Verified with Streamlit's AppTest, which supports presetting
query_params before the first run -- simulating exactly what a reload looks
like: a brand new session_state, but the same URL.
"""

from __future__ import annotations

import pytest
from streamlit.testing.v1 import AppTest

from submission.graph.workflow import compile_graph
from submission.state.state import create_initial_state
from submission.tests.reset_db import reset_business_state


@pytest.fixture(scope="module", autouse=True)
def clean_state():
    reset_business_state()
    yield


def test_reload_with_case_id_in_url_restores_the_case_screen_not_the_watchlist():
    graph, conn = compile_graph()
    try:
        state = create_initial_state("AC-001", "DEL-01", target_cover_days=7)  # healthy -> NO_ACTION
        result = graph.invoke(state, config={"configurable": {"thread_id": state["thread_id"]}})
    finally:
        conn.close()
    case_id = result["case_id"]

    at = AppTest.from_file("submission/ui.py", default_timeout=60)
    at.query_params["view"] = "case"
    at.query_params["case_id"] = case_id
    at.run()

    assert not at.exception, [str(e.value) for e in at.exception]
    assert at.title, "expected the case screen to render a title, not stay on the watchlist"
    assert at.title[0].value != "Which products need attention?"


def test_reload_with_no_query_params_falls_back_to_the_watchlist():
    at = AppTest.from_file("submission/ui.py", default_timeout=60)
    at.run()

    assert not at.exception, [str(e.value) for e in at.exception]
    assert at.title[0].value == "Which products need attention?"
