"""
Phase 6 tests.

Two things the earlier phases never covered:

1. The bounded revision cycle. The brief's constraint is "maximum one
   revision cycle", checked by a graph test that proves termination. Before
   this phase the graph had a revise edge that could never fire (the cap was
   compared with >= against an already-incremented counter), so REVISE went
   straight to BLOCKED -- zero revisions, not one. These tests pin both
   halves: the first REVISE really re-runs, the second really terminates.

2. The operator read models the UI depends on (portfolio.scan_portfolio,
   read_case_history). Pure reads, but the watchlist is now the entry point
   to the whole system, so "it silently returned nothing" has to be a test
   failure rather than an empty screen.

Stub agents throughout (wire_agents is not called), so these are fast and
deterministic -- the revision behaviour under test is graph routing, not
model judgment.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from langgraph.types import Command

from domain.tool_models import ProposalStatus
from submission.agents.models import ReplenishmentRecommendation
from submission.config import config
from submission.graph import nodes, routes
from submission.graph.workflow import compile_graph
from submission.portfolio import (
    STATUS_HEALTHY,
    STATUS_NEEDS_ATTENTION,
    list_cases,
    list_warehouses,
    read_case_history,
    scan_portfolio,
)
from submission.state.state import create_initial_state
from submission.tests.reset_db import reset_business_state

RISKY_SKU, RISKY_WAREHOUSE = "AC-003", "DEL-01"


@pytest.fixture(scope="module", autouse=True)
def clean_state():
    """The watchlist assertions below name specific seeded products (the
    stale AC-002 snapshot, the thin-history AC-003/DEL-09 fixture), so this
    module needs the seed exactly as provided, not whatever an earlier run
    left behind."""
    reset_business_state()
    yield


def _decision(case_id: str, proposal, verdict: str, comment: str | None = None) -> dict:
    return {
        "case_id": case_id,
        "proposal_id": proposal.proposal_id,
        "proposal_hash": proposal.proposal_hash,
        "decision": verdict,
        "approver": "Test Approver",
        "comments": comment,
        "approved_at": datetime.now(timezone.utc).isoformat(),
    }


@pytest.fixture
def paused_case():
    """Run a risky case up to the approval interrupt on a throwaway thread."""
    graph, conn = compile_graph()
    state = create_initial_state(RISKY_SKU, RISKY_WAREHOUSE)
    # Unique thread per test: case_id/thread_id is derived from sku+warehouse
    # alone, so without this a rerun would land on a previous run's checkpoint.
    state["thread_id"] = f"{state['case_id']}-phase6-{datetime.now().timestamp()}"
    cfg = {"configurable": {"thread_id": state["thread_id"]}}
    result = graph.invoke(state, config=cfg)
    assert "__interrupt__" in result, "expected the case to pause for approval"
    try:
        yield graph, cfg, result
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# 1. bounded revision
# ---------------------------------------------------------------------------

def test_route_allows_exactly_one_revision():
    """Unit-level guard on the off-by-one, independent of the graph."""
    assert routes.route_after_decision(
        {"approval_decision": _fake("REVISE"), "revision_count": 1}
    ) == "revise"
    assert routes.route_after_decision(
        {"approval_decision": _fake("REVISE"), "revision_count": config.max_revision_cycles + 1}
    ) == "revision_limit_exceeded"


class _fake:
    def __init__(self, decision):
        self.decision = decision


def test_first_revise_reruns_and_pauses_again(paused_case):
    graph, cfg, result = paused_case
    first_proposal = graph.get_state(cfg).values["proposal"]

    after = graph.invoke(
        Command(resume=_decision(cfg["configurable"]["thread_id"], first_proposal,
                                 "REVISE", "prefer the cheaper supplier")),
        config=cfg,
    )

    # It came back for approval rather than terminating.
    assert "__interrupt__" in after, "a first REVISE must produce a new proposal, not block"
    values = graph.get_state(cfg).values
    assert values["revision_count"] == 1
    assert values["status"] == ProposalStatus.AWAITING_APPROVAL

    # A genuinely new proposal version, and the approver's comment is on the record
    # so the revision can be explained after the fact.
    assert values["proposal"].proposal_id != first_proposal.proposal_id
    revision_events = [
        e for e in read_case_history(values["case_id"])
        if e.raw.get("approver_comment") == "prefer the cheaper supplier"
    ]
    assert revision_events, "the approver's revision instruction should be in the audit trail"
    assert revision_events[0].who == "Test Approver"


def test_second_revise_terminates(paused_case):
    """Termination proof: the loop cannot run twice."""
    graph, cfg, _ = paused_case
    thread = cfg["configurable"]["thread_id"]

    proposal = graph.get_state(cfg).values["proposal"]
    graph.invoke(Command(resume=_decision(thread, proposal, "REVISE", "cheaper please")), config=cfg)

    revised = graph.get_state(cfg).values["proposal"]
    final = graph.invoke(Command(resume=_decision(thread, revised, "REVISE", "still not right")), config=cfg)

    assert "__interrupt__" not in final, "a second REVISE must terminate, not pause again"
    assert final["status"] == ProposalStatus.BLOCKED
    assert graph.get_state(cfg).values["revision_count"] == 2


def test_revision_reenters_at_evidence_collection(paused_case):
    """A revision must re-read stock, not reuse the pre-pause snapshot --
    otherwise it proposes against data the freshness rule already rejects."""
    graph, cfg, _ = paused_case
    thread = cfg["configurable"]["thread_id"]
    proposal = graph.get_state(cfg).values["proposal"]
    before = graph.get_state(cfg).values["stock"].retrieved_at

    graph.invoke(Command(resume=_decision(thread, proposal, "REVISE", "try again")), config=cfg)
    after = graph.get_state(cfg).values["stock"].retrieved_at

    assert after >= before
    events = [e.what for e in read_case_history(graph.get_state(cfg).values["case_id"])]
    assert sum("current stock level and recent sales" in w for w in events) >= 2, (
        "stock/sales should have been read twice: once originally, once for the revision"
    )


def test_prepare_revision_keeps_the_comment_and_clears_the_proposal():
    """The approver's comment is the only input to a revision, so it must
    survive; everything derived from the rejected proposal must not."""
    from domain.tool_models import ApprovalDecision

    decision = ApprovalDecision(
        case_id="CASE-X", proposal_id="P1", proposal_hash="H1", decision="REVISE",
        approver="Test Approver", comments="use the cheaper supplier",
        approved_at=datetime.now(timezone.utc),
    )
    state = {
        "case_id": "CASE-X", "trace_id": "T", "revision_count": 1,
        "approval_decision": decision,
        "proposal": object(), "policy_review": object(),
        "replenishment_recommendation": object(), "revalidation": object(),
        "error_code": None, "error_detail": "stale failure text",
    }
    nodes.prepare_revision(state)

    assert state["approval_decision"] is decision  # the instruction survives
    assert state["proposal"] is None
    assert state["policy_review"] is None
    assert state["replenishment_recommendation"] is None
    assert state["revalidation"] is None
    assert state["error_detail"] is None  # a stale error must not misroute the retry pass


def test_revision_comment_reaches_the_strategist_prompt():
    """The prompt must carry the approver's instruction, visibly separated
    from the untrusted evidence block."""
    from domain.tool_models import ApprovalDecision
    from submission.prompts._shared import render_approver_feedback

    decision = ApprovalDecision(
        case_id="C", proposal_id="P", proposal_hash="H", decision="REVISE",
        approver="Priya", comments="the extra buffer is not worth the money",
        approved_at=datetime.now(timezone.utc),
    )
    text = render_approver_feedback(decision)
    assert "REVISION REQUEST" in text
    assert "Priya" in text
    assert "the extra buffer is not worth the money" in text
    assert "not database content" in text  # the trust boundary is stated to the model

    # And nothing is injected when there is no revision in play.
    assert render_approver_feedback(None) == ""
    approved = decision.model_copy(update={"decision": "APPROVED"})
    assert render_approver_feedback(approved) == ""


# ---------------------------------------------------------------------------
# 2. operator read models behind the UI
# ---------------------------------------------------------------------------

def test_watchlist_covers_every_stocked_product_and_ranks_worst_first():
    rows = scan_portfolio(target_cover_days=14)
    assert rows, "the watchlist is the entry point; an empty list is a failure, not a state"

    # Every product/warehouse pair that holds stock appears exactly once.
    pairs = [(r.sku, r.warehouse_id) for r in rows]
    assert len(pairs) == len(set(pairs))
    assert (RISKY_SKU, RISKY_WAREHOUSE) in pairs

    # Worst-first: the urgency ordering is monotonic.
    assert [r.sort_key for r in rows] == sorted(r.sort_key for r in rows)

    # Every row is safe to put in front of a non-technical user.
    for r in rows:
        assert r.headline and r.headline[0].isupper() and r.headline.endswith(".")
        assert r.product_name


def test_watchlist_surfaces_unassessable_products_instead_of_hiding_them():
    rows = {(r.sku, r.warehouse_id): r for r in scan_portfolio(target_cover_days=14)}

    # AC-002/DEL-01 is seeded with a deliberately stale snapshot.
    stale = rows[("AC-002", "DEL-01")]
    assert stale.status == STATUS_NEEDS_ATTENTION
    assert "old" in stale.headline.lower()

    # AC-003/DEL-09 (seed_extra) has too little sales history to forecast.
    thin = rows[("AC-003", "DEL-09")]
    assert thin.status == STATUS_NEEDS_ATTENTION
    assert thin.days_of_stock is None


def test_watchlist_flags_disagreeing_sales_trends():
    """AC-001/DEL-22 (seed_extra.py TRENDING_CASE) is at risk on the 30-day
    trend and healthy on the 7-day one -- demand that genuinely slowed down
    recently, not a rounding artifact. That disagreement decides
    buy-vs-do-nothing, so it must not be collapsed into one number."""
    rows = {(r.sku, r.warehouse_id): r for r in scan_portfolio(target_cover_days=14)}
    row = rows[("AC-001", "DEL-22")]
    assert row.windows_disagree
    assert row.days_of_stock_best > row.days_of_stock


def test_warehouse_filter_narrows_the_watchlist():
    warehouses = list_warehouses()
    assert RISKY_WAREHOUSE in warehouses
    filtered = scan_portfolio(target_cover_days=14, warehouse_id=RISKY_WAREHOUSE)
    assert filtered
    assert {r.warehouse_id for r in filtered} == {RISKY_WAREHOUSE}


def test_case_history_is_readable_and_leaks_no_reasoning(paused_case):
    graph, cfg, _ = paused_case
    case_id = graph.get_state(cfg).values["case_id"]

    events = read_case_history(case_id)
    assert events, "the audit trail must be reconstructable"
    assert [e.at for e in events] == sorted(e.at for e in events)
    for e in events:
        assert e.who and e.what
        assert "_" not in e.what, f"raw event type leaked into operator text: {e.what!r}"

    # Structured summaries only -- no free-text model reasoning fields.
    for e in events:
        assert not any(k in e.raw for k in ("justification", "rationale", "reasoning", "thoughts"))


def test_ambiguous_sales_trends_park_with_the_disagreement_explained():
    """Irreconcilable trends are terminal and parked, never paused for a
    human to choose a window. The human still receives both conflicting
    figures and the precise explanation of why the case cannot continue."""
    from tools.parking import get_open_parked_items

    graph, conn = compile_graph()
    try:
        state = create_initial_state("AC-001", "DEL-22", 14)
        state["thread_id"] = f"{state['case_id']}-notes-{datetime.now().timestamp()}"
        cfg = {"configurable": {"thread_id": state["thread_id"]}}
        result = graph.invoke(state, config=cfg)
    finally:
        conn.close()

    assert "__interrupt__" not in result
    assert result["status"] == ProposalStatus.NEEDS_INFORMATION
    assert "disagree on whether this SKU is at risk" in result["error_detail"]
    parked = get_open_parked_items("DEL-22")
    note = next(item.note for item in parked if item.sku == "AC-001")
    assert "7-day trend:" in note and "30-day trend:" in note


def test_no_spurious_warnings_when_the_order_matches_the_need():
    """The warnings have to be signal, not decoration. AC-003/DEL-01 is sized
    to exactly what it needs and both trends agree it is at risk, so no note
    should appear.

    This test previously failed for a revealing reason: _approval_notes
    re-derived the shortfall by hand, and once lead-time demand entered the
    sizing formula the two drifted, producing a minimum-order warning on an
    order that was sized correctly. The notes now read the computed figures
    from graph/economics.py instead of recomputing them.
    """
    from submission.ui import _approval_notes

    graph, conn = compile_graph()
    try:
        state = create_initial_state(RISKY_SKU, RISKY_WAREHOUSE, 14)
        state["thread_id"] = f"{state['case_id']}-nonotes-{datetime.now().timestamp()}"
        cfg = {"configurable": {"thread_id": state["thread_id"]}}
        assert "__interrupt__" in graph.invoke(state, config=cfg)
        values = graph.get_state(cfg).values
    finally:
        conn.close()

    assert _approval_notes(values) == []


def test_amounts_in_approver_text_are_escaped_so_streamlit_does_not_typeset_them():
    """Streamlit's markdown supports LaTeX, so a *pair* of dollar signs in one
    string is read as math delimiters and everything between them is typeset as
    an equation -- spaces stripped, serif math font. Every sentence that quotes
    two amounts hits it, and the supplier-comparison note quotes six. On the
    live screen it rendered as an unreadable run of glyphs:

        This order is $550 more than FastShip Inc., but the two are not the
        same purchase: $29 units here against 25 there...

    No existing test caught it: the notes are asserted as plain strings, and
    the string was always correct -- only its rendering was broken. So this
    checks the render boundary (ui._md), not the note text.
    """
    from submission.ui import _approval_notes, _md

    assert _md("$18,900 against $18,500.") == r"\$18,900 against \$18,500."
    assert _md(None) == "—"

    # AC-004/DEL-01 is the case where the chosen supplier's invoice is bigger
    # than the cash-cheapest one, so the comparison note actually fires.
    graph, conn = compile_graph()
    try:
        state = create_initial_state("AC-004", "DEL-01", 14)
        state["thread_id"] = f"{state['case_id']}-escape-{datetime.now().timestamp()}"
        cfg = {"configurable": {"thread_id": state["thread_id"]}}
        graph.invoke(state, config=cfg)
        values = graph.get_state(cfg).values
    finally:
        conn.close()

    notes = _approval_notes(values)
    assert notes, "the invoice-comparison note must fire on this case"
    comparison = next((n for n in notes if "smaller invoice" in n), None)
    assert comparison is not None

    rendered = _md(comparison)
    assert "$" not in rendered.replace(r"\$", ""), (
        "an unescaped dollar sign reached the markdown renderer; a pair of them "
        "will be typeset as LaTeX and the sentence becomes unreadable"
    )
    # And it is broken into paragraphs rather than one long block -- a warning
    # an approver cannot scan is a warning they learn to ignore.
    assert "\n\n" in comparison
    assert ".." not in comparison, "double period from a vendor name ending in '.'"


def test_minimum_order_overshoot_is_reported_when_it_happens():
    """The minimum-order warning, tested directly rather than through a
    fixture.

    Worth recording why: this used to be demonstrated end-to-end on
    AC-001/DEL-04, where 1 unit was needed and every supplier's minimum was
    5 -- roughly $1,100 to close a one-unit gap. Adding lead-time demand to
    the sizing made that situation disappear, because the "1 unit" was itself
    an artefact of a formula that sized for cover starting today and ignored
    the stock consumed while the delivery was in transit. The real need is
    8-18 units, comfortably above every minimum. So the warning is exercised
    against explicit inputs instead of a fixture whose arithmetic legitimately
    moved.
    """
    from submission.graph.economics import required_quantity, size_order_quantity

    # Plenty of stock relative to demand, and a supplier with a big minimum.
    needed = required_quantity(
        available_units=100, daily_velocity=1.0, target_cover_days=7, lead_time_days=2, fill_rate=1.0
    )
    assert needed == 0, "no units are genuinely required when stock already exceeds the target"

    ordered = size_order_quantity(
        available_units=100,
        daily_velocity=1.0,
        target_cover_days=7,
        moq=25,
        lead_time_days=2,
        fill_rate=1.0,
    )
    assert ordered == 25, "the supplier's minimum becomes the order when nothing is needed"
    assert ordered - needed == 25, "the whole order is overshoot, and must be reported as such"


def test_order_quantity_covers_the_target_after_the_delivery_lands():
    """The regression guard for the sizing bug.

    Every order the system wrote used to under-deliver its own stated target
    by exactly lead_time x velocity, because it sized for cover starting
    today while the goods only start covering demand when they arrive.
    Measured on AC-004/DEL-01 (velocity 2.9, available 12, order 29): a 2-day
    lead time gave 12.1 days of cover against a 14-day target and a 5-day
    lead time gave 9.1, going negative before arrival.
    """
    from submission.graph.economics import size_order_quantity

    available, velocity, target = 12, 2.9, 14
    for lead_time in (2, 3, 5, 7):
        quantity = size_order_quantity(
            available_units=available,
            daily_velocity=velocity,
            target_cover_days=target,
            moq=1,
            lead_time_days=lead_time,
            fill_rate=1.0,
        )
        on_hand_at_arrival = available - velocity * lead_time
        cover_after_arrival = (on_hand_at_arrival + quantity) / velocity
        assert cover_after_arrival >= target - 0.5, (
            f"lead_time={lead_time}d: {quantity} units gives only "
            f"{cover_after_arrival:.1f} days cover against a {target}-day target"
        )


def test_fill_rate_grosses_up_the_order():
    """fill_rate was fetched, passed into the prompt, and used for nothing.
    A 0.90 fill rate means a 29-unit order lands about 26 units."""
    from submission.graph.economics import required_quantity

    kwargs = dict(available_units=12, daily_velocity=2.9, target_cover_days=14, lead_time_days=3)
    perfect = required_quantity(**kwargs, fill_rate=1.0)
    short_shipper = required_quantity(**kwargs, fill_rate=0.90)

    assert short_shipper > perfect
    # Ordering the grossed-up amount must actually deliver what was needed.
    assert short_shipper * 0.90 >= perfect - 1


def test_worse_value_options_are_refused_and_the_ranking_is_internally_consistent():
    """The core economic gate, and the reason it is code and not a prompt.

    A live run recommended paying $1,450 extra for one extra day of buffer
    and called it "a justified investment" -- while also misreporting the
    figure as $450. Both options arrived before the projected stockout, so
    the premium bought insurance against a delay, not the avoidance of a
    stockout.

    The gate itself then turned out to be measuring the wrong thing: it ranked
    on total_cost, and order quantities differ per supplier because the cover
    target is measured from arrival. See
    test_the_smallest_invoice_is_not_the_best_value below. The ranking is now
    all-in cost per day of cover; this test asserts the result is
    self-consistent and that the winner is always an acceptable pick.
    """
    from submission.graph.economics import (
        ACCEPTABLE_VERDICTS,
        BASIS_ABSOLUTE,
        BASIS_PER_DAY,
        VERDICT_BEST_VALUE,
        VERDICT_WORSE_VALUE,
    )

    graph, conn = compile_graph()
    try:
        state = create_initial_state("AC-003", "DEL-08", 14)
        state["thread_id"] = f"{state['case_id']}-premium-{datetime.now().timestamp()}"
        cfg = {"configurable": {"thread_id": state["thread_id"]}}
        assert "__interrupt__" in graph.invoke(state, config=cfg)
        values = graph.get_state(cfg).values
    finally:
        conn.close()

    economics = values["economics"]
    assert economics is not None, "the economics block must be computed and kept on state"
    assert economics.ranking_basis in (BASIS_PER_DAY, BASIS_ABSOLUTE)

    # Exactly one winner, and it is always acceptable.
    best = [o for o in economics.options if o.verdict == VERDICT_BEST_VALUE]
    assert len(best) == 1
    assert best[0].offer_id == economics.best_value_offer_id
    assert economics.best_value_offer_id in economics.acceptable_offer_ids()

    # The winner really is the minimum on the declared ranking basis, and
    # every refused option is strictly worse on it.
    score = (
        (lambda o: o.all_in_cost_per_day_of_cover)
        if economics.ranking_basis == BASIS_PER_DAY
        else (lambda o: o.all_in_cost)
    )
    assert score(best[0]) == min(score(o) for o in economics.options)
    for o in economics.options:
        assert o.verdict_explanation
        if o.verdict == VERDICT_WORSE_VALUE:
            assert o.extra_cost_per_day_vs_best_value > 0, (
                f"{o.offer_id} was refused but is not worse than the winner"
            )
            assert o.offer_id not in economics.acceptable_offer_ids()

    # Whatever the agent chose, it had to be an acceptable verdict -- the
    # validation hook in nodes.recommend_vendor refuses anything else.
    proposal = values["proposal"]
    chosen = economics.by_offer_for_proposal(proposal)
    assert chosen is not None, "the approved proposal must map back to a scored option"
    assert chosen.verdict in ACCEPTABLE_VERDICTS, (
        f"agent picked an option the arithmetic refuses: {chosen.verdict} — {chosen.verdict_explanation}"
    )

    # And every assumption behind the valuation is disclosed, not buried.
    assert economics.assumed_gross_margin_rate == config.assumed_gross_margin_rate
    assert economics.assumed_annual_carrying_rate == config.assumed_annual_carrying_rate
    assert economics.assumed_late_days_when_late == config.assumed_late_days_when_late
    assert any("no selling price" in c for c in economics.caveats)
    assert any("carrying cost" in c.lower() for c in economics.caveats)
    assert any("promised-date" in c for c in economics.caveats)
    assert any("billing terms" in c for c in economics.caveats)
    assert any("not on total_cost" in c for c in economics.caveats)


def test_worse_value_pick_is_actually_rejected_by_the_validation_hook():
    """Directly exercise the gate: hand nodes._validate_recommendation a pick
    the arithmetic refuses and confirm it returns an error (which routes into
    the one repair attempt)."""
    from submission.graph.economics import ACCEPTABLE_VERDICTS
    from submission.graph.nodes import _validate_recommendation

    graph, conn = compile_graph()
    try:
        state = create_initial_state("AC-003", "DEL-08", 14)
        state["thread_id"] = f"{state['case_id']}-gate-{datetime.now().timestamp()}"
        cfg = {"configurable": {"thread_id": state["thread_id"]}}
        graph.invoke(state, config=cfg)
        values = dict(graph.get_state(cfg).values)
    finally:
        conn.close()

    economics = values["economics"]
    refused = [o for o in economics.options if o.verdict not in ACCEPTABLE_VERDICTS]
    if not refused:
        pytest.skip("no refusable option in this fixture; covered by the synthetic verdict test above")

    rec = ReplenishmentRecommendation(
        case_id=values["case_id"],
        recommended_offer_id=refused[0].offer_id,
        strategy="balanced",
        rationale="Paying more for the faster supplier feels safer.",
        evidence_ids=[],
    )
    problem = _validate_recommendation(values, rec)
    assert problem is not None, "the gate must refuse an option the arithmetic rejects"
    assert refused[0].offer_id in problem
    assert economics.best_value_offer_id in problem, "the refusal must name the option to pick instead"


def _synthetic_perf(now, *rows):
    """VendorPerformanceList for a synthetic economics case.
    rows are (vendor_id, on_time_rate, fill_rate)."""
    from domain.tool_models import VendorPerformance, VendorPerformanceList

    return VendorPerformanceList(
        vendors=[
            VendorPerformance(
                vendor_id=vid,
                vendor_name=vid,
                on_time_rate=on_time,
                fill_rate=fill,
                quality_score=1.0,
                reliability=round((on_time + fill + 1.0) / 3, 4),
                eligible=True,
                evidence_id=f"perf:{vid}",
            )
            for vid, on_time, fill in rows
        ],
        retrieved_at=now,
    )


def test_the_smallest_invoice_is_not_the_best_value():
    """The regression guard for the ranking bug, using the case that exposed it.

    Order quantities are sized per supplier from that supplier's lead time,
    because the requirement is N days of cover *once the goods land*. A slower
    supplier therefore has to fund more days of demand and legitimately needs
    more units. The old ranking was min(total_cost), which compared those
    different-sized orders by their invoice totals:

        FastShip   lead 2d, fill 0.98, $500/unit  ->  25 units, $12,500
        Standard   lead 3d, fill 0.94, $450/unit  ->  29 units, $13,050

    and declared FastShip "cheaper overall" -- then the validation gate
    *forced* that pick. But Standard's four extra units are not $550 of waste:
    three are one more day of demand FastShip never had to cover and about one
    is fill-rate shrinkage, and all of them get sold. Per unit actually
    delivered, Standard is $478.72 against FastShip's $510.20.

    So: the cash-cheapest option and the best-value option must be allowed to
    differ, and the recommendation must follow value.
    """
    from domain.tool_models import StockRisk, VendorOption
    from submission.graph.economics import (
        VERDICT_BEST_VALUE,
        VERDICT_WORSE_VALUE,
        evaluate_options,
    )

    now = datetime.now(timezone.utc)
    # 12 usable units, 3/day, 10-day target -> stockout in 4 days.
    risk = StockRisk(
        available_units=12, daily_velocity=3.0, cover_days=4.0,
        projected_stockout_date=now + timedelta(days=4),
        target_cover_days=10, at_risk=True, freshness_hours=1.0, stale=False,
    )
    fastship = VendorOption(
        offer_id="OFFER-FAST", vendor_id="V-FAST", vendor_name="FastShip Inc.",
        quantity=25, unit_price=500.0, total_cost=12500.0, lead_time_days=2,
        expected_arrival=now + timedelta(days=2), meets_deadline=True,
        reliable=True, eligible=True,
    )
    standard = VendorOption(
        offer_id="OFFER-STD", vendor_id="V-STD", vendor_name="Standard Supplier",
        quantity=29, unit_price=450.0, total_cost=13050.0, lead_time_days=3,
        expected_arrival=now + timedelta(days=3), meets_deadline=True,
        reliable=True, eligible=True,
    )

    economics = evaluate_options(
        risk,
        [fastship, standard],
        _synthetic_perf(now, ("V-FAST", 0.95, 0.98), ("V-STD", 0.93, 0.94)),
    )
    by_id = {o.offer_id: o for o in economics.options}

    # The smaller invoice is still correctly identified as the smaller invoice.
    assert economics.cheapest_offer_id == "OFFER-FAST"
    # But it is not the better buy, and the recommendation follows value.
    assert economics.best_value_offer_id == "OFFER-STD"
    assert by_id["OFFER-STD"].verdict == VERDICT_BEST_VALUE
    assert by_id["OFFER-FAST"].verdict == VERDICT_WORSE_VALUE
    assert economics.acceptable_offer_ids() == {"OFFER-STD"}

    # ...on cost per unit actually delivered, and per day of cover.
    assert by_id["OFFER-STD"].effective_cost_per_delivered_unit < (
        by_id["OFFER-FAST"].effective_cost_per_delivered_unit
    )
    assert by_id["OFFER-STD"].all_in_cost_per_day_of_cover < (
        by_id["OFFER-FAST"].all_in_cost_per_day_of_cover
    )
    # The slower supplier funds more days of demand -- that is why it needs
    # more units, and it is the fact the old ranking threw away.
    assert by_id["OFFER-STD"].days_of_cover_funded > by_id["OFFER-FAST"].days_of_cover_funded
    # And the approver is still told the invoice is bigger.
    assert by_id["OFFER-STD"].extra_cost_vs_cheapest == 550.0


def test_a_near_tie_that_arrives_earlier_is_left_to_the_agent():
    """The ranking must not collapse the Strategist into a rubber stamp.

    Once delivery risk is priced inside each option's score there is no
    separate "is the premium justified" judgment left, so a pure argmin would
    leave the agent with no decision at all -- a design regression, since the
    brief asks for agent judgment and the code gate exists to bound it, not to
    delete it. An option within config.vendor_value_tolerance_rate of the
    winner that also arrives earlier stays acceptable.
    """
    from domain.tool_models import StockRisk, VendorOption
    from submission.graph.economics import (
        VERDICT_BEST_VALUE,
        VERDICT_WITHIN_TOLERANCE,
        evaluate_options,
    )

    now = datetime.now(timezone.utc)
    risk = StockRisk(
        available_units=15, daily_velocity=2.0, cover_days=7.5,
        projected_stockout_date=now + timedelta(days=7),
        target_cover_days=14, at_risk=True, freshness_hours=1.0, stale=False,
    )
    # Sized exactly to need: ceil(2 * (14 + lead) - 15).
    slow_and_marginally_cheaper = VendorOption(
        offer_id="OFFER-SLOW", vendor_id="V-SLOW", vendor_name="Slow Vendor",
        quantity=27, unit_price=20.0, total_cost=540.0, lead_time_days=7,
        expected_arrival=now + timedelta(days=7), meets_deadline=True,
        reliable=True, eligible=True,
    )
    fast_and_a_hair_dearer = VendorOption(
        offer_id="OFFER-FAST", vendor_id="V-FAST", vendor_name="Fast Vendor",
        quantity=17, unit_price=20.2, total_cost=343.4, lead_time_days=2,
        expected_arrival=now + timedelta(days=2), meets_deadline=True,
        reliable=True, eligible=True,
    )

    economics = evaluate_options(
        risk,
        [slow_and_marginally_cheaper, fast_and_a_hair_dearer],
        _synthetic_perf(now, ("V-SLOW", 0.95, 1.0), ("V-FAST", 0.95, 1.0)),
    )
    by_id = {o.offer_id: o for o in economics.options}

    assert by_id["OFFER-SLOW"].verdict == VERDICT_BEST_VALUE
    assert by_id["OFFER-FAST"].verdict == VERDICT_WITHIN_TOLERANCE
    assert economics.acceptable_offer_ids() == {"OFFER-SLOW", "OFFER-FAST"}
    gap_rate = by_id["OFFER-FAST"].extra_cost_per_day_rate_vs_best_value
    assert 0 < gap_rate <= config.vendor_value_tolerance_rate
    assert by_id["OFFER-FAST"].verdict_explanation  # formatted without raising


def test_a_supplier_minimum_earns_no_coverage_credit():
    """Removing total_cost as the ranking metric removed the only thing that
    was pushing back on a large order, so the per-day metric has to refuse to
    credit stock nobody asked for. Otherwise a supplier with a 200-unit
    minimum posts a beautiful cost-per-day figure by handing over two months
    of inventory.
    """
    from domain.tool_models import StockRisk, VendorOption
    from submission.graph.economics import VERDICT_BEST_VALUE, evaluate_options

    now = datetime.now(timezone.utc)
    risk = StockRisk(
        available_units=15, daily_velocity=2.0, cover_days=7.5,
        projected_stockout_date=now + timedelta(days=7),
        target_cover_days=14, at_risk=True, freshness_hours=1.0, stale=False,
    )
    right_sized = VendorOption(
        offer_id="OFFER-RIGHT", vendor_id="V-RIGHT", vendor_name="Right Sized",
        quantity=17, unit_price=20.0, total_cost=340.0, lead_time_days=2,
        expected_arrival=now + timedelta(days=2), meets_deadline=True,
        reliable=True, eligible=True,
    )
    # Same lead time, cheaper per unit, but a 200-unit minimum against a
    # 17-unit need. On raw price per unit it wins; it must still lose.
    bulk_minimum = VendorOption(
        offer_id="OFFER-BULK", vendor_id="V-BULK", vendor_name="Bulk Only",
        quantity=200, unit_price=19.0, total_cost=3800.0, lead_time_days=2,
        expected_arrival=now + timedelta(days=2), meets_deadline=True,
        reliable=True, eligible=True,
    )

    economics = evaluate_options(
        risk,
        [right_sized, bulk_minimum],
        _synthetic_perf(now, ("V-RIGHT", 0.95, 1.0), ("V-BULK", 0.95, 1.0)),
    )
    by_id = {o.offer_id: o for o in economics.options}

    assert by_id["OFFER-BULK"].moq_overbuy_units == 183
    # The overshoot funds no coverage: both options cover the same target.
    assert by_id["OFFER-BULK"].days_of_cover_funded == by_id["OFFER-RIGHT"].days_of_cover_funded
    # And it carries a real cost, so the cheaper unit price does not win.
    assert by_id["OFFER-BULK"].carrying_cost > by_id["OFFER-RIGHT"].carrying_cost
    assert economics.best_value_offer_id == "OFFER-RIGHT"
    assert by_id["OFFER-RIGHT"].verdict == VERDICT_BEST_VALUE


def test_ui_script_renders_the_watchlist_without_error():
    """The screen is now the entry point to the whole system, so a crash on
    load is a total outage. AppTest executes ui.py for real."""
    from streamlit.testing.v1 import AppTest

    at = AppTest.from_file("submission/ui.py", default_timeout=180)
    at.run()

    assert not at.exception, [str(e.value) for e in at.exception]
    assert at.title[0].value == "Which products need attention?"
    # At least one product is actionable from the screen itself.
    assert any(b.label == "Look into this" for b in at.button)


def test_checkpoint_allowlist_covers_everything_a_paused_case_stores(paused_case):
    """Resume is the load-bearing behaviour here, so the checkpoint
    serializer's allowlist must actually cover every type a paused case
    holds.

    Previously the serializer ran in LangGraph's permissive mode
    (allowed_msgpack_modules=True), which deserializes anything and logs
    "Deserializing unregistered type ... will be blocked in a future
    version" for each one. That is an upgrade-triggered break of the human
    approval gate waiting to happen. This test fails if any type slips out
    of the allowlist -- e.g. a new model added to CaseState.
    """
    import logging

    from submission.graph.workflow import checkpoint_allowlist

    graph, cfg, _ = paused_case
    allowed = {(t.__module__, t.__name__) for t in checkpoint_allowlist()}

    # Every custom type sitting in the paused state must be allowlisted.
    for key, value in graph.get_state(cfg).values.items():
        if value is None or isinstance(value, (str, int, float, bool, dict, list)):
            continue
        cls = type(value)
        if cls.__module__.startswith(("domain.", "submission.")):
            assert (cls.__module__, cls.__name__) in allowed, (
                f"state[{key!r}] holds {cls.__module__}.{cls.__name__}, which is not in the "
                "checkpoint allowlist -- a paused case would fail to resume under strict msgpack"
            )

    # And reading the checkpoint back must emit no serde warnings at all.
    emitted: list[str] = []

    class _Capture(logging.Handler):
        def emit(self, record):
            emitted.append(record.getMessage())

    serde_log = logging.getLogger("langgraph.checkpoint.serde.jsonplus")
    handler = _Capture()
    serde_log.addHandler(handler)
    try:
        graph.get_state(cfg)
    finally:
        serde_log.removeHandler(handler)

    assert not emitted, f"checkpoint deserialization warned: {emitted}"


def test_list_cases_reports_a_plain_language_outcome(paused_case):
    graph, cfg, _ = paused_case
    case_id = graph.get_state(cfg).values["case_id"]
    found = {c["case_id"]: c for c in list_cases()}
    assert case_id in found
    assert found[case_id]["outcome"]
    assert found[case_id]["event_count"] > 0
