"""
Operator screen.  Run with:  streamlit run submission/ui.py

Written for the person the brief describes -- a regional inventory planner,
not an engineer. Three screens, each one a step of their actual job:

    Watchlist  -> which products need me today?          (portfolio.scan_portfolio)
    Case       -> what does the system recommend, and do I approve it?
    History    -> what happened, and what did we decide before?

Deliberately not a dashboard. There are no charts, no KPIs and no analytics
here: the brief says a large dashboard earns no marks and that complexity
must solve a stated requirement. Each screen exists because a required step
of the workflow is otherwise unreachable -- there was previously no way to
find an at-risk product, no way to see a proposal before approving it, and
no way to read the audit trail back. The CLI (submission/app.py) remains the
primary entry point and this file calls the exact same functions, so the two
cannot drift apart.

Vocabulary is deliberately non-technical: "product" not SKU, "supplier" not
vendor, "days of stock left" not cover_days, "order" not purchase request.
Identifiers and hashes are still available, tucked behind a details toggle,
because an auditor needs them and a planner does not.

Styling rule, learned the hard way: **no hardcoded colours and no custom
CSS.** The first version hand-rolled a <style> block with light-mode hex
values (white card backgrounds, grey captions, pastel status pills) and set
no foreground colour, so under a dark theme the card text rendered white on
white and was invisible. Everything here now uses theme-aware Streamlit
primitives -- st.container(border=True), st.metric, st.badge, st.caption and
semantic markdown colours -- which follow the active theme automatically.
The theme itself is pinned in .streamlit/config.toml so it is identical on
every machine. A test asserts this file contains no hex colour literals.
"""

from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import streamlit as st
import streamlit.components.v1 as components

# Allow `streamlit run submission/ui.py` from the repo root without
# requiring the package to be installed.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from submission.agents.models import POLICY_QUESTION_TEXT, ChecklistVerdict, PolicyQuestion  # noqa: E402
from submission.app import (  # noqa: E402
    cancel_order,
    load_case,
    resume_case,
    resume_manual_cover,
    resume_vendor_send,
    resume_missing_info,
    run_case,
)
from submission.config import config  # noqa: E402
from submission.ui_messages import manual_cover_warning  # noqa: E402
from submission.portfolio import (  # noqa: E402
    STATUS_AT_RISK,
    STATUS_BORDERLINE,
    STATUS_CRITICAL,
    STATUS_HEALTHY,
    STATUS_NEEDS_ATTENTION,
    get_purchase_request,
    list_cases,
    list_pending_cases,
    list_warehouses,
    read_case_history,
    scan_portfolio,
)

st.set_page_config(page_title="Inventra — stock watch", page_icon="📦", layout="wide")

# Streamlit's own semantic badge colours, not hex -- these resolve against
# whichever theme is active.
STATUS_BADGE_COLOUR = {
    STATUS_CRITICAL: "red",
    STATUS_AT_RISK: "orange",
    STATUS_BORDERLINE: "violet",
    STATUS_NEEDS_ATTENTION: "blue",
    STATUS_HEALTHY: "green",
}

CHECKLIST_VERDICT_COLOUR = {
    ChecklistVerdict.PASS: "green",
    ChecklistVerdict.FAIL: "red",
    ChecklistVerdict.NA: "grey",
}

# Rows the code re-derives from state and stamps regardless of what the
# model answered (see nodes._override_policy_checklist) -- flagged in the
# UI so a reader can tell "the system verified this" from "the model's own
# read of policy.md", which used to be indistinguishable in a single
# free-text verdict.
SYSTEM_CHECKED_QUESTIONS = {
    PolicyQuestion.FRESHNESS,
    PolicyQuestion.AT_RISK,
    PolicyQuestion.SALES_SUFFICIENCY,
    PolicyQuestion.VENDOR_VALIDITY,
    PolicyQuestion.ARRIVAL_BEATS_STOCKOUT,
    PolicyQuestion.BUDGET_FIT,
    PolicyQuestion.EVIDENCE_TRACEABLE,
    PolicyQuestion.POLICY_FLOOR,
}

STATUS_ORDER = [
    STATUS_CRITICAL,
    STATUS_AT_RISK,
    STATUS_BORDERLINE,
    STATUS_NEEDS_ATTENTION,
    STATUS_HEALTHY,
]


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _money(value) -> str:
    try:
        return f"${float(value):,.0f}"
    except (TypeError, ValueError):
        return "—"


def _md(text) -> str:
    """Make text safe to hand to a Streamlit markdown renderer.

    Streamlit's markdown supports LaTeX, so a **pair** of dollar signs in one
    string is read as math delimiters and everything between them is typeset as
    an equation -- which strips the spacing and renders the words in a serif
    math font. Any sentence quoting two amounts hits this. It turned the
    supplier-comparison note into an unreadable run of glyphs:

        This order is $550 more than FastShip Inc. ... this one costs $1,440
        against $1,534

    became one long equation from the first `$` to the second, and another from
    the third onward. The same bug was silently mangling the budget caption
    ("budget before $15,000 -> after $1,950") and the order-detail table.

    Escaping to `\\$` is Streamlit's documented fix. Applied at the render
    boundary rather than inside _money, because st.metric values are not
    markdown-parsed and would show the backslash literally -- and because the
    text that needs escaping also includes agent prose and error strings
    produced elsewhere, which never went through _money at all.
    """
    if text is None:
        return "—"
    return str(text).replace("$", r"\$")


def _when(value) -> str:
    """Dates for humans. Accepts datetime or the string sqlite hands back."""
    if value is None:
        return "—"
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value)
        except ValueError:
            return value
    return value.strftime("%d %b %Y, %H:%M")


def _monitor_when(value) -> str:
    """Show monitor timestamps in the operator's India time, explicitly.

    The worker persists UTC timestamps so they remain unambiguous across
    processes.  The monitor is a local planner screen, so presenting those
    raw UTC values without a label was needlessly confusing.
    """
    if value is None:
        return "—"
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value)
        except ValueError:
            return value
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(ZoneInfo("Asia/Kolkata")).strftime("%d %b %Y, %H:%M IST")


def _day(value) -> str:
    if value is None:
        return "—"
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value)
        except ValueError:
            return value
    return value.strftime("%d %b")


_DEEP_LINK_KEYS = ("view", "case_id", "thread_id")


def _sync_query_params() -> None:
    """Mirrors the handful of session-state keys that identify "where the
    user is" into the URL, so a hard reload (which throws away
    st.session_state entirely, but not the URL) can restore it instead of
    always falling back to the watchlist."""
    for key in _DEEP_LINK_KEYS:
        value = st.session_state.get(key)
        if value:
            st.query_params[key] = str(value)
        else:
            st.query_params.pop(key, None)


def _goto(view: str, **kw) -> None:
    st.session_state.view = view
    st.session_state.update(kw)
    _sync_query_params()
    st.rerun()


def _approval_notes(values: dict) -> list[str]:
    """Things the system already knows and would otherwise never tell the
    approver.

    Presentation-only and computed from state that deterministic nodes
    already produced -- no new arithmetic, no model involvement. Kept as a
    standalone function so the approval email can reuse it verbatim.

    1. Minimum-order overshoot. The supplier's minimum order can be several
       times the actual shortfall, which turns a one-unit gap into a
       four-figure purchase. That is a legitimate business decision, but it
       has to be a visible one.
    2. Disagreeing sales trends. When the 7-day and 30-day trends land on
       different sides of the target, the whole buy-or-not decision rests on
       which one the Demand analyst chose. The approver should know their
       signature is on that choice.
    """
    notes: list[str] = []
    proposal, risk, sales = values.get("proposal"), values.get("risk"), values.get("sales")
    if proposal is None or risk is None:
        return notes

    # Every figure below is read from graph/economics.py, never recomputed
    # here. An earlier version re-derived the shortfall in this function and
    # drifted the moment lead-time demand entered the sizing formula, firing a
    # minimum-order warning on orders that were sized exactly right -- the
    # fastest way to teach an approver to ignore these warnings.
    economics = values.get("economics")
    chosen = economics.by_offer_for_proposal(proposal) if economics else None

    # 1. The supplier's minimum order exceeds what is actually needed.
    if chosen is not None and chosen.moq_overbuy_units > 0:
        notes.append(
            f"**The supplier's minimum order is larger than what you actually need.** "
            f"{chosen.required_quantity} unit(s) would cover {risk.target_cover_days} days once "
            f"the delivery lands, but the smallest order this supplier accepts is "
            f"{proposal.quantity}. You are buying {chosen.moq_overbuy_units} extra unit(s), "
            f"roughly {_money(chosen.moq_overbuy_units * proposal.unit_price)} of stock you do "
            f"not need yet."
        )

    # 2. A bigger invoice than another supplier would have sent. Rendered from
    #    the same computed figures the agent was given and the validation gate
    #    enforced -- never from the agent's prose, which on one live run
    #    reported a $1,450 premium as "$450".
    #
    #    Deliberately framed as "bigger invoice", not "not the cheapest": a
    #    bigger total here usually means MORE UNITS, because a slower supplier
    #    has to fund the extra days in transit and those units get sold. The
    #    comparison that decides the pick is cost per day of cover, so that is
    #    the figure quoted alongside it. Calling the larger invoice "more
    #    expensive" was the exact error this whole change fixed.
    #
    #    Written as short paragraphs rather than one block. The first version
    #    was a single ~90-word run that also appended verdict_explanation,
    #    repeating the per-day figure and the unit count a second time. An
    #    approver cannot find the one number they need in that, and a warning
    #    nobody reads is worse than no warning.
    if chosen is not None and chosen.extra_cost_vs_cheapest > 0:
        cheapest = economics.by_offer(economics.cheapest_offer_id)
        cheaper_name = cheapest.vendor_name if cheapest else "another supplier"

        lines = [
            f"**A different supplier would have sent a smaller invoice.** "
            f"{_money(proposal.total_cost)} here against "
            f"{_money(cheapest.total_cost) if cheapest else '—'} from {cheaper_name}, "
            f"a difference of {_money(chosen.extra_cost_vs_cheapest)}."
        ]

        if cheapest is not None and chosen.quantity != cheapest.quantity:
            why = (
                "a slower delivery has to cover more days of demand while it is in transit"
                if chosen.quantity > cheapest.quantity
                else "a faster delivery needs fewer units to cover the time in transit"
            )
            lines.append(
                f"They are not the same purchase, so the totals are not comparable: "
                f"**{chosen.quantity} units here against {cheapest.quantity}** from "
                f"{cheaper_name}, because {why}. Those extra units are stock you will sell, "
                f"not waste."
            )

        if (
            chosen.all_in_cost_per_day_of_cover is not None
            and cheapest is not None
            and cheapest.all_in_cost_per_day_of_cover is not None
        ):
            # Vendor name deliberately not sentence-final here: seeded names
            # like "FastShip Inc." already end in a period, which produced
            # "...from FastShip Inc.." on the live screen.
            lines.append(
                f"**The comparison the choice was made on** is cost per day of stock bought: "
                f"**{_money(chosen.all_in_cost_per_day_of_cover)} a day here against "
                f"{cheaper_name}'s {_money(cheapest.all_in_cost_per_day_of_cover)}**. "
                f"Per unit actually delivered that is "
                f"{_money(chosen.effective_cost_per_delivered_unit)} against "
                f"{_money(cheapest.effective_cost_per_delivered_unit)}."
            )

        lines.append(
            f"Those two figures include delivery risk and the cost of holding stock. They assume "
            f"each unit earns {economics.assumed_gross_margin_rate:.0%} of its purchase price and "
            f"costs {economics.assumed_annual_carrying_rate:.0%} a year to hold — this database "
            f"has no selling price and no warehousing cost, so both are configured assumptions."
        )
        notes.append("\n\n".join(lines))

    assessment = values.get("demand_assessment")
    if sales is not None and assessment is not None:
        target = risk.target_cover_days
        avail = risk.available_units
        covers = {
            7: (avail / sales.window_7_days) if sales.window_7_days else None,
            30: (avail / sales.window_30_days) if sales.window_30_days else None,
        }
        if all(v is not None for v in covers.values()):
            at_risk = {w: c < target for w, c in covers.items()}
            if at_risk[7] != at_risk[30]:
                calm = 7 if not at_risk[7] else 30
                notes.append(
                    f"**The two sales trends disagree about whether this is urgent.** "
                    f"On the {calm}-day trend there is enough stock "
                    f"({covers[calm]:.0f} days against a {target}-day target) and no order would be "
                    f"needed at all. The analyst chose the {assessment.chosen_window_days}-day trend. "
                    f"If you think the {calm}-day figure is the truer picture, reject this."
                )
    return notes


def _status_sentence(values: dict, order_row: dict | None = None) -> tuple[str, str]:
    """(kind, plain-language sentence) for a finished case.

    order_row, when given, is the live purchase_requests row and outranks the
    case's in-memory status. A cancelled order still leaves the case at
    PURCHASE_REQUEST_CREATED -- cancelling does not rewind the workflow -- so
    reading status alone would announce "Order placed" in green above a panel
    showing it had been withdrawn.
    """
    status = values.get("status")
    status = status.value if hasattr(status, "value") else str(status or "")
    detail = values.get("error_detail") or ""
    if status == "NO_ACTION":
        return "success", "No order needed. There is enough stock to cover the target period."
    if status == "PURCHASE_REQUEST_CREATED":
        pr = values.get("purchase_result")
        rid = getattr(pr, "request_id", None)
        cost = getattr(pr, "total_cost", None)
        if order_row is not None and order_row.get("status") == "CANCELLED":
            who = order_row.get("cancelled_by") or "someone"
            return "warning", (
                f"Order {rid} was cancelled by {who}. Nothing is on its way — "
                f"if this product is still at risk, start a new case for it."
            )
        return "success", f"Order placed. Purchase request {rid} has been created ({_money(cost)})."
    if status == "NEEDS_INFORMATION":
        return "warning", f"More information is needed before this can be assessed. {detail}"
    if status == "BLOCKED":
        return "error", f"This could not go ahead. {detail}"
    if status == "AWAITING_APPROVAL":
        return "info", "Waiting for a person to approve."
    return "info", status or "Unknown."


# ---------------------------------------------------------------------------
# sidebar
# ---------------------------------------------------------------------------

# Restore from the URL on a fresh session (a hard reload wipes
# st.session_state but not st.query_params), so reopening/refreshing a case
# link lands back on that case instead of the watchlist (Gap: UI state lost
# on reload).
st.session_state.setdefault("view", st.query_params.get("view", "watchlist"))
st.session_state.setdefault("case_id", st.query_params.get("case_id") or None)
st.session_state.setdefault("thread_id", st.query_params.get("thread_id") or None)

with st.sidebar:
    st.markdown("### 📦 Inventra")
    st.caption("Stock watch and restock approvals")

    if st.button("Stock watchlist", use_container_width=True):
        _goto("watchlist")
    _pending_count = len(list_pending_cases())
    pending_label = "Needs my decision" + (f" ({_pending_count})" if _pending_count else "")
    if st.button(pending_label, use_container_width=True, type="primary" if _pending_count else "secondary"):
        _goto("pending")
    if st.button("Past cases", use_container_width=True):
        _goto("history")
    if st.button("Autonomous monitor", use_container_width=True):
        _goto("monitor")

    st.divider()
    st.markdown("**Settings**")
    warehouses = ["All warehouses"] + list_warehouses()
    picked = st.selectbox("Warehouse", warehouses, key="wh_filter")
    st.divider()
    st.caption(
        f"Stock figures older than {config.data_freshness_hours:.0f} hours are not trusted "
        "for ordering."
    )

warehouse_filter = None if picked == "All warehouses" else picked


# ---------------------------------------------------------------------------
# screen: watchlist
# ---------------------------------------------------------------------------

def screen_watchlist() -> None:
    st.title("Which products need attention?")
    st.caption(
        "Every product held at your warehouses, worst first. "
        "Days of stock left is worked out from recorded sales, not estimated."
    )

    with st.spinner("Checking stock levels…"):
        rows = scan_portfolio(None, warehouse_filter)

    counts: dict[str, int] = {}
    for r in rows:
        counts[r.status] = counts.get(r.status, 0) + 1

    for col, status in zip(st.columns(len(STATUS_ORDER)), STATUS_ORDER):
        with col:
            st.metric(status, counts.get(status, 0), border=True)

    show_healthy = st.toggle("Also show products that are fine", value=False)
    st.write("")

    visible = [r for r in rows if show_healthy or r.status != STATUS_HEALTHY]
    if not visible:
        st.success("Nothing needs attention right now.")
        return

    for row in visible:
        with st.container(border=True):
            left, mid, right = st.columns([5, 3, 2], vertical_alignment="center")
            with left:
                st.badge(row.status, color=STATUS_BADGE_COLOUR.get(row.status, "blue"))
                st.markdown(f"**{row.product_name}**")
                st.caption(f"Product code {row.sku} · warehouse {row.warehouse_id}")
                st.write(row.headline)
            with mid:
                if row.days_of_stock is not None:
                    st.metric("Days of stock left", f"{row.days_of_stock:g}")
                bits = []
                if row.units_available is not None:
                    bits.append(f"{row.units_available} units on hand")
                if row.runs_out_on is not None:
                    bits.append(f"forecast to run out {_day(row.runs_out_on)}")
                if row.daily_sales_7d is not None:
                    bits.append(f"selling ~{row.daily_sales_7d:g}/day")
                if bits:
                    st.caption(" · ".join(bits))
                if row.target_basis_label:
                    st.caption(f"target: {row.target_basis_label}")
            with right:
                if row.can_investigate:
                    if st.button(
                        "Look into this",
                        key=f"go-{row.sku}-{row.warehouse_id}",
                        use_container_width=True,
                        type="primary" if row.status == STATUS_CRITICAL else "secondary",
                    ):
                        _goto("investigate", sku=row.sku, warehouse_id=row.warehouse_id)
                else:
                    st.button(
                        "Nothing to do",
                        key=f"no-{row.sku}-{row.warehouse_id}",
                        disabled=True,
                        use_container_width=True,
                    )


# ---------------------------------------------------------------------------
# screen: investigate (runs the graph)
# ---------------------------------------------------------------------------

def screen_investigate() -> None:
    sku = st.session_state.get("sku")
    warehouse_id = st.session_state.get("warehouse_id")
    if not sku or not warehouse_id:
        _goto("watchlist")
        return

    st.title(f"{sku} at {warehouse_id}")
    st.caption(
        "The system is reading current stock, recent sales, supplier offers and the budget, "
        "then deciding whether an order is needed. Nothing is ordered without your approval."
    )

    with st.spinner("Working through the case… this can take up to a minute."):
        try:
            result = run_case(sku, warehouse_id)
        except Exception as exc:  # surfaced, never swallowed
            st.error("The case could not be completed.")
            st.exception(exc)
            if st.button("Back to watchlist"):
                _goto("watchlist")
            return

    _goto("case", case_id=result.get("case_id"), thread_id=result.get("thread_id"))


# ---------------------------------------------------------------------------
# screen: case (approval + outcome + timeline)
# ---------------------------------------------------------------------------

def screen_case() -> None:
    case_id = st.session_state.get("case_id")
    if not case_id:
        _goto("watchlist")
        return

    values, awaiting = load_case(case_id, st.session_state.get("thread_id"))
    if not values:
        st.warning(f"No record found for {case_id}.")
        if st.button("Back to watchlist"):
            _goto("watchlist")
        return

    product = values.get("product")
    name = getattr(product, "name", None) or values.get("sku", case_id)
    st.title(name)
    st.caption(
        f"Product code {values.get('sku')} · warehouse {values.get('warehouse_id')} · case {case_id}"
    )

    status = values.get("status")
    status = status.value if hasattr(status, "value") else str(status or "")

    assessment = values.get("demand_assessment")
    if awaiting and status == "AWAITING_VENDOR_APPROVAL":
        _render_vendor_send_approval(case_id, values)
    elif awaiting and values.get("proposal") is not None:
        _render_approval(case_id, values)
    elif awaiting and values.get("target_mode") == "MANUAL_COVER_REQUIRED":
        _render_manual_cover_form(case_id, values)
    elif awaiting and status == "NEEDS_INFORMATION":
        _render_missing_info_form(case_id, values)
    else:
        has_order = values.get("proposal") is not None and values.get("purchase_result") is not None
        # Read the row once and reuse it for both the banner and the panel, so
        # the two can never describe different states of the same order.
        order_row = get_purchase_request(case_id) if has_order else None
        kind, sentence = _status_sentence(values, order_row)
        # _md: the sentence can carry an order total, and BLOCKED/
        # NEEDS_INFORMATION versions embed error_detail, which for a budget
        # failure states two amounts. See _md.
        {"success": st.success, "warning": st.warning, "error": st.error, "info": st.info}[kind](
            _md(sentence)
        )
        if has_order:
            _render_proposal_summary(values, heading="What was ordered")
            _render_order_proof(case_id, proposal=values.get("proposal"), row=order_row)
        _render_no_action_reasoning(values)
        _render_blocked_reasoning(values)
        if values.get("policy_review") is not None:
            _render_policy_checklist(values["policy_review"])

    st.write("")
    _render_timeline(case_id, values.get("trace_id"))

    st.write("")
    if st.button("← Back to watchlist"):
        _goto("watchlist")


def _render_no_action_reasoning(values: dict) -> None:
    """A "no order needed" result is only trustworthy if the numbers behind
    it are visible. The evidence already exists on StockRisk; it was simply
    never shown, so the good-news outcome looked like the system had done
    nothing."""
    status = values.get("status")
    status = status.value if hasattr(status, "value") else str(status or "")
    risk = values.get("risk")
    if status != "NO_ACTION" or risk is None:
        return

    assessment = values.get("demand_assessment")
    a, b, c = st.columns(3)
    with a:
        st.metric("Units available", risk.available_units, border=True)
    with b:
        st.metric("Days of stock left", f"{risk.cover_days:.1f}" if risk.cover_days is not None else "—", border=True)
    with c:
        st.metric("Target to hold", f"{risk.target_cover_days} days", border=True)
    st.caption(
        f"Selling about {risk.daily_velocity:g} a day"
        + (f", using the {assessment.chosen_window_days}-day sales trend" if assessment else "")
        + (
            f". At that rate stock would run out around {_day(risk.projected_stockout_date)}, "
            f"which is beyond the {risk.target_cover_days}-day target."
            if risk.projected_stockout_date
            else "."
        )
    )


def _render_missing_info_form(case_id: str, values: dict) -> None:
    """The system paused because validate_request found a missing or
    invalid field (Gap 1). Collects corrected values and resumes the same
    paused case instead of starting a brand new investigation."""
    st.warning("More information is needed before this can continue.")
    st.markdown(_md(values.get("error_detail") or "Some fields need correcting."))

    sku = st.text_input("Product code (SKU)", value=values.get("sku") or "", key="fix_sku")
    warehouse_id = st.text_input("Warehouse", value=values.get("warehouse_id") or "", key="fix_warehouse")
    if st.button("Continue with this information", type="primary"):
        with st.spinner("Re-checking…"):
            try:
                resume_missing_info(
                    case_id,
                    sku.strip() or None,
                    warehouse_id.strip() or None,
                    thread_id=st.session_state.get("thread_id"),
                )
            except Exception as exc:
                st.error("The correction could not be applied.")
                st.exception(exc)
                return
        _goto("case", case_id=case_id)


def _render_manual_cover_form(case_id: str, values: dict) -> None:
    """The one permitted numerical form, shown only after valid sales and
    an immature SKU policy. Demand and quantity are never editable."""
    st.warning("Sales are usable, but the policy is not mature enough to derive the stock target.")
    st.markdown(_md(values.get("error_detail") or "Enter only days of stock to hold."))
    cover = st.slider(
        "Days of stock to hold",
        min_value=config.target_cover_min_days,
        max_value=config.target_cover_max_days,
        value=config.target_cover_default_days,
        key="manual_cover_days",
    )
    requested_by = st.text_input(
        "Your name",
        key="manual_cover_requested_by",
        help="Required. This manual cover target is recorded against a named person.",
    )
    if st.button("Continue with this cover target", type="primary", disabled=not requested_by.strip()):
        with st.spinner("Computing the order plan…"):
            try:
                resume_manual_cover(
                    case_id,
                    cover,
                    requested_by.strip(),
                    thread_id=st.session_state.get("thread_id"),
                )
            except Exception as exc:
                st.error("The cover target could not be applied.")
                st.exception(exc)
                return
        _goto("case", case_id=case_id)


def _render_blocked_reasoning(values: dict) -> None:
    """A BLOCKED "no eligible vendors" outcome is only actionable if the
    approver can see which supplier failed on what (Gap 2). Renders the same
    per-vendor breakdown notify_blocked emails, computed once in
    nodes.build_options and never re-derived here."""
    status = values.get("status")
    status = status.value if hasattr(status, "value") else str(status or "")
    rejection = values.get("vendor_rejection_detail")
    if status != "BLOCKED" or not rejection:
        return

    st.subheader("Why no supplier could be used")
    for row in rejection["considered"]:
        with st.container(border=True):
            st.markdown(f"**{row['vendor_name']}** ({row['offer_id']})")
            st.caption("; ".join(row["reasons"]) or "—")
    excluded = []
    if rejection.get("expired_count"):
        excluded.append(f"{rejection['expired_count']} expired offer(s)")
    if rejection.get("inactive_count"):
        excluded.append(f"{rejection['inactive_count']} from inactive vendor(s)")
    if excluded:
        st.caption("Also excluded: " + ", ".join(excluded))


def _render_proposal_summary(values: dict, heading: str = "The recommendation") -> None:
    p = values.get("proposal")
    risk = values.get("risk")
    budget = values.get("budget")
    st.subheader(heading)

    a, b, c = st.columns(3)
    with a:
        with st.container(border=True):
            st.metric("Order", f"{p.quantity} units")
            st.caption(f"from **{p.recommended_vendor_name}** · {_md(_money(p.unit_price))} each")
    with b:
        with st.container(border=True):
            st.metric("Expected to arrive", _day(p.expected_arrival))
            bits = []
            if risk is not None and risk.projected_stockout_date and p.expected_arrival:
                days = (risk.projected_stockout_date - p.expected_arrival).total_seconds() / 86400
                bits.append(f"{days:.1f} days before you run out")
            bits.append(f"you run out around {_day(p.projected_stockout_date)}")
            st.caption(" · ".join(bits))
    with c:
        with st.container(border=True):
            # st.metric values are not markdown-parsed, so this one stays raw.
            # The caption below it is, and quotes two amounts -- hence _md.
            st.metric("Total cost", _money(p.total_cost))
            st.caption(
                f"budget before {_md(_money(getattr(budget, 'remaining', None)))} → "
                f"after {_md(_money(p.budget_remaining))}"
            )
    if any(value is not None for value in (p.policy_floor_units, p.statistical_target_units, p.active_target_units)):
        st.caption(
            "Target basis: "
            f"policy floor **{p.policy_floor_units if p.policy_floor_units is not None else '—'}** units · "
            f"statistical target **{p.statistical_target_units if p.statistical_target_units is not None else '—'}** units · "
            f"active target **{p.active_target_units if p.active_target_units is not None else '—'}** units "
            f"({p.target_basis}, {p.target_provenance})."
        )


def _revalidation_failure_reason(revalidation) -> str:
    """Same priority order as notifications/email.py's version -- structural
    hash mismatch and budget first, since those are the least recoverable by
    a simple retry. Prefers revalidation.error_details, which now states the
    exact numbers graph/revalidation.py just read from the database (e.g.
    "$15,500.00 ordered, only $15,000.00 remains"), over a generic label."""
    if revalidation.error_details:
        return revalidation.error_details
    if not revalidation.hash_matches:
        return "The proposal no longer matches what was approved."
    if not revalidation.budget_valid:
        return "The remaining budget dropped below the approved cost."
    if not revalidation.stock_valid:
        return "The stock snapshot is no longer fresh enough to trust."
    if not revalidation.offer_valid:
        return "The supplier's offer changed price, or is no longer valid."
    return "The underlying facts changed after approval."


def _render_revalidation_bounce_banner(values: dict) -> None:
    """Gap 7/UX: when a previous approval bounces at the final live-data
    recheck (graph/routes.py route_after_revalidation -> retry_from_risk),
    the case is silently rebuilt into a brand-new proposal and a brand-new
    approval screen that looks identical to the last one. Nothing in the UI
    previously said why -- an approver would click "Approve and order"
    again, watch two agents re-run, and land back here with no visible
    explanation, unable to tell whether anything had actually changed.

    invalidate_approval (graph/nodes.py) clears approval_decision, proposal,
    error_code and error_detail on the bounce, but deliberately never clears
    state["revalidation"] -- so the failed result from the previous attempt
    is still sitting in state when this new screen renders. This function is
    the first thing to use it: a prominent, code-computed explanation of
    exactly what failed, is shown BEFORE the (new) recommendation below it."""
    revalidation = values.get("revalidation")
    if revalidation is None or revalidation.all_checks_pass:
        return
    st.error(
        "**Your last approval could not be honored -- nothing was ordered.** "
        "A final check against live data, done automatically right before writing the order, "
        "found this had changed since you approved it:"
    )
    st.markdown(f"> {_md(_revalidation_failure_reason(revalidation))}")
    st.caption(
        "The recommendation below has been rebuilt from current stock, prices and budget. "
        "If the underlying issue (e.g. the budget) hasn't been fixed yet, approving again will "
        "very likely bounce back here again with the same reason -- fix the real cause first. "
        "You do not need to tell the system you fixed it: the same live check runs automatically "
        "every time you approve, against whatever is in the database at that moment."
    )


_PENDING_EXPLANATION = (
    "**PENDING** means the internal purchase request record was written successfully -- "
    "nothing more. Nothing in this system currently moves a request out of PENDING: there is "
    "no vendor confirmation step, no receiving/goods-in check, no status webhook. It will stay "
    "PENDING indefinitely unless a future process (or a person, editing the database directly) "
    "changes it. Do not read PENDING as \"the supplier confirmed this.\""
)


def _render_order_proof(case_id: str, proposal=None, row: dict | None = None) -> None:
    """Verifies the order actually exists by querying purchase_requests
    directly (portfolio.get_purchase_request), instead of only trusting the
    PURCHASE_REQUEST_CREATED status label already sitting in graph state.
    That label and this query come from two different reads of two
    different things -- state.status is set in nodes.execute_purchase right
    after the write, this is a fresh SELECT against the same table -- so if
    they ever disagree, that is itself worth surfacing rather than hiding.

    `row` may be passed in by a caller that already read it, so one screen
    render never reads the same order twice and risks showing two states."""
    if row is None:
        row = get_purchase_request(case_id)
    if row is None:
        st.error(
            "The case says an order was placed, but no matching row was found in the "
            "purchase_requests table just now. Do not treat this as ordered -- investigate "
            "before assuming stock is on the way."
        )
        return
    if row["status"] == "CANCELLED":
        st.warning(
            f"🚫 Cancelled in the database: request **{row['request_id']}**, "
            f"withdrawn by **{row.get('cancelled_by') or 'unknown'}** on "
            f"{_when(row.get('cancelled_at'))}."
        )
        if row.get("cancel_reason"):
            st.markdown(f"> {row['cancel_reason']}")
    else:
        st.success(
            f"✅ Verified in the database: request **{row['request_id']}**, "
            f"status **{row['status']}**."
        )
    with st.container(border=True):
        arrival_row = ""
        if proposal is not None and getattr(proposal, "expected_arrival", None):
            arrival_row = f"| Expected to ship/arrive by | {_when(proposal.expected_arrival)} |\n"
        vendor_sent = None
        st.markdown(
            f"""
| | |
|---|---|
| Request ID | `{row['request_id']}` |
| Status | {row['status']} |
| Supplier | {row['vendor_id']} |
| Quantity | {row['quantity']} units |
| Unit price | {_md(_money(row['unit_price']))} |
| Total cost | {_md(_money(row['total_cost']))} |
{arrival_row}| Approved by | {row['approved_by']} |
| Approved at | {_when(row['approved_at'])} |
| Written to database at | {_when(row['created_at'])} |
"""
        )
        if proposal is not None and getattr(proposal, "expected_arrival", None):
            st.caption(
                "Expected arrival comes from the supplier's quoted lead time at the time this "
                "was proposed, not from the purchase_requests table (that table has no delivery-"
                "date column) -- it is not re-confirmed by the supplier after the order is placed."
            )
        st.caption(
            "The table above (except arrival) is read directly from the `purchase_requests` "
            "table, not from this page's in-memory state."
        )
        with st.expander("What does 'PENDING' actually mean?"):
            st.markdown(_PENDING_EXPLANATION)
            sent_status = row.get("vendor_send_status")
            if sent_status == "SENT":
                st.caption("The supplier PO email was sent for this request.")
            elif sent_status == "FAILED":
                st.caption("A supplier PO email was attempted but failed to send.")
            else:
                st.caption(
                    "No supplier PO email has been sent for this request (vendor email is "
                    "disabled by default pending a domain-authentication review)."
                )

    _render_cancel_control(case_id, row)


def _render_cancel_control(case_id: str, row: dict) -> None:
    """Withdraw a PENDING order (B3). Creating a purchase request used to be
    a one-way door: a mistake could only be undone by editing the database.

    Only offered when the order is actually cancellable. The two refusals
    below are shown as plain statements rather than a disabled button with no
    explanation, because "why can't I cancel this" is the immediate next
    question in both cases."""
    if row["status"] == "CANCELLED":
        return
    if row["status"] != "PENDING":
        st.caption(
            f"This order is {row['status']} and can no longer be cancelled here — "
            "only a PENDING order can be withdrawn."
        )
        return
    if row.get("vendor_send_status") == "SENT":
        st.caption(
            "The purchase order has already been sent to the supplier, so it cannot be "
            "cancelled here. Cancelling only our copy would leave the supplier expecting "
            "to fulfil it. Contact them to retract it first."
        )
        return

    with st.expander("Cancel this order"):
        if row.get("committed_budget_month"):
            st.warning(
                f"This withdraws the order and releases the {_md(_money(row['total_cost']))} it "
                f"reserved from the {row['committed_budget_month']} budget."
            )
        else:
            st.warning(
                "This withdraws the order. It does not free up any budget, because placing "
                "this particular order never reserved any."
            )
        who = st.text_input(
            "Your name",
            key=f"cancel_by_{row['request_id']}",
            placeholder="e.g. Yuvraj Singh",
            help="Required. Cancellations are recorded against a named person.",
        )
        why = st.text_area(
            "Why are you cancelling?",
            key=f"cancel_reason_{row['request_id']}",
            placeholder="e.g. duplicate of PR-0123, raised in error",
            height=80,
            max_chars=500,
        )
        confirmed = st.checkbox(
            f"I understand this cancels order {row['request_id']}",
            key=f"cancel_confirm_{row['request_id']}",
        )
        ready = bool(who.strip() and why.strip() and confirmed)
        if not ready:
            st.caption("Enter your name, a reason, and tick the box to enable the button.")
        if st.button(
            "Cancel this order",
            type="primary",
            disabled=not ready,
            key=f"cancel_btn_{row['request_id']}",
        ):
            with st.spinner("Cancelling…"):
                try:
                    result = cancel_order(row["request_id"], who.strip(), why.strip())
                except Exception as exc:
                    st.error("The cancellation could not be applied.")
                    st.exception(exc)
                    return
            if not result.cancelled:
                # A refusal here is a real business rule (status moved, or the
                # supplier was already emailed), not a UI failure -- state it.
                st.error(_md(result.error_details or "The order could not be cancelled."))
                return
            _goto("case", case_id=case_id)


def _render_policy_checklist(review) -> None:
    """One row per policy.md review question, replacing what used to be a
    single blended verdict. A question can no longer be silently skipped --
    PolicyReview requires all 9 -- and most rows are re-derived in code from
    state the graph already has, not just the model's own read of the
    policy doc. Only "which tradeoff is being made" is left as the model's
    call; everything else here is verified, not merely reported."""
    checked = sum(1 for i in (review.checklist if review else []) if i.verdict != ChecklistVerdict.PASS)
    label = f"Policy checklist — all 9 review questions ({'no concerns' if not checked else f'{checked} flagged'})"
    with st.expander(label):
        if review is None or not review.checklist:
            st.write("No checklist available for this case.")
            return
        st.caption(
            "Every policy.md review question gets its own verdict. 🔒 marks a row the system "
            "re-derives from state and cannot be overridden by the model's answer."
        )
        by_question = {item.question: item for item in review.checklist}
        header = st.columns([0.4, 3, 1, 4])
        for col, text in zip(header, ["#", "Question", "Verdict", "Why"]):
            col.markdown(f"**{text}**")
        for i, question in enumerate(PolicyQuestion, start=1):
            item = by_question.get(question)
            if item is None:
                continue
            lock = " 🔒" if question in SYSTEM_CHECKED_QUESTIONS else ""
            num_col, q_col, v_col, why_col = st.columns([0.4, 3, 1, 4])
            num_col.write(str(i))
            q_col.write(POLICY_QUESTION_TEXT[question] + lock)
            with v_col:
                st.badge(item.verdict.value, color=CHECKLIST_VERDICT_COLOUR.get(item.verdict, "grey"))
            why_col.markdown(_md(item.rationale))


def _render_approval(case_id: str, values: dict) -> None:
    p = values["proposal"]
    review = values.get("policy_review")
    assessment = values.get("demand_assessment")

    _render_revalidation_bounce_banner(values)

    warning = manual_cover_warning(values)
    if warning:
        st.warning(warning)

    st.info("This needs your approval. Nothing has been ordered yet.")
    _render_proposal_summary(values)

    # _md on everything below: these strings quote two or more amounts, and
    # Streamlit reads a pair of dollar signs as LaTeX delimiters. See _md.
    for note in _approval_notes(values):
        st.warning(_md(note))

    st.subheader("Why this supplier")
    st.markdown(_md(p.cost_vs_speed_trade_off or "—"))
    if p.other_options_summary:
        st.caption(f"**Other options considered:** {_md(p.other_options_summary)}")

    left, right = st.columns(2)
    with left:
        st.subheader("How demand was judged")
        if assessment is not None:
            st.markdown(
                f"Used the **{assessment.chosen_window_days}-day** sales trend. "
                f"{_md(assessment.rationale)}"
            )
        else:
            st.write("—")
    with right:
        st.subheader("Policy check")
        if review is not None:
            verdict = review.verdict.value if hasattr(review.verdict, "value") else str(review.verdict)
            {"PASS": st.success, "EXCEPTION": st.warning, "BLOCKED": st.error}.get(verdict, st.info)(
                {
                    "PASS": "Passed the policy check.",
                    "EXCEPTION": "Passed, but flagged as an exception.",
                    "BLOCKED": "Failed the policy check.",
                }.get(verdict, verdict)
            )
            st.markdown(_md(review.rationale))
            for concern in review.concerns or []:
                st.markdown(f"- {_md(concern)}")
        else:
            st.write("—")

    _render_policy_checklist(review)

    with st.expander("Reference details (for audit)"):
        st.markdown(
            f"""
| | |
|---|---|
| Case | `{case_id}` |
| Proposal | `{p.proposal_id}` |
| Version fingerprint | `{p.proposal_hash}` |
| Stock evidence | `{p.stock_evidence_id}` |
| Sales evidence | `{p.sales_evidence_id}` |
| Supplier evidence | `{', '.join(p.vendor_evidence_ids) or '—'}` |
| Budget evidence | `{p.budget_evidence_id}` |
| Units available | {p.available_units} |
| Sales per day used | {p.daily_velocity} |
| Target days of cover | {p.target_cover_days} |
"""
        )
        st.caption(
            "Your approval is tied to the version fingerprint above. If stock, price or budget "
            "change before the order is written, the approval is cancelled and the case comes back."
        )

    st.divider()
    st.subheader("Your decision")

    with st.expander("What each choice does", expanded=False):
        st.markdown(
            """
- **Approve and order** — the system re-checks stock, the supplier's price, the offer's validity
  and the budget one final time against live data. If anything has moved since this page was
  built, your approval is cancelled and the case comes back to you rebuilt. If everything still
  holds, the purchase request is created once and only once.
- **Ask for changes** — needs a comment. The proposal is thrown away, current stock and sales are
  re-read, and a new recommendation is prepared that has to address your comment directly. You
  get one round of this; asking twice closes the case.
- **Reject** — requires a reason; nothing is ordered and the case is closed with your name and comment on record.
            """
        )

    approver = st.text_input(
        "Your name",
        key="approver_name",
        placeholder="e.g. Yuvraj Singh",
        help="Required. Approvals are recorded against a named person.",
    )
    comment = st.text_area(
        "Comment / reason (required if asking for changes, rejecting, or choosing another supplier)",
        key="approver_comment",
        placeholder="e.g. go with the cheaper supplier, the extra buffer isn't worth it",
        height=80,
        max_chars=500,
    )

    ready = bool(approver.strip())
    if not ready:
        st.caption("Enter your name to enable the buttons below.")

    a, b, c = st.columns(3)
    decision = None
    with a:
        if st.button("Approve and order", type="primary", disabled=not ready, use_container_width=True):
            decision = "APPROVED"
    with b:
        if st.button("Ask for changes", disabled=not (ready and comment.strip()), use_container_width=True):
            decision = "REVISE"
    with c:
        if st.button("Reject", disabled=not (ready and comment.strip()), use_container_width=True):
            decision = "REJECTED"

    # The planner may select only from the evidence-backed, policy-eligible
    # supplier options displayed below.  They cannot edit supplier records,
    # quotes, or policy; a selection is fully recalculated and re-reviewed.
    edited_offer_id = _render_edit_form(case_id, values, approver, comment)
    if edited_offer_id is not None:
        decision = "EDIT"
    chosen_target_basis = None
    if p.policy_floor_units is not None and p.statistical_target_units is not None and p.policy_floor_units != p.statistical_target_units:
        selected_basis = st.selectbox(
            "Change computed target basis",
            ["POLICY_FLOOR", "STATISTICAL"],
            index=0 if p.target_basis == "POLICY_FLOOR" else 1,
            help="This recalculates supplier quantities; it never accepts a hand-entered quantity.",
        )
        if selected_basis != p.target_basis and st.button("Re-price this target", disabled=not ready, use_container_width=True):
            decision, chosen_target_basis = "EDIT", selected_basis

    if decision:
        label = {
            "APPROVED": "Placing the order…",
            "REVISE": "Reworking the recommendation…",
            "REJECTED": "Recording your rejection…",
            "EDIT": "Switching supplier and re-checking…",
        }[decision]
        with st.spinner(label):
            try:
                resume_case(
                    case_id,
                    decision,
                    approver.strip(),
                    comment.strip() or None,
                    thread_id=st.session_state.get("thread_id"),
                    edited_offer_id=edited_offer_id,
                    chosen_target_basis=chosen_target_basis,
                )
            except Exception as exc:
                st.error("The decision could not be applied.")
                st.exception(exc)
                return
        st.session_state.pop("approver_comment", None)
        _goto("case", case_id=case_id)


def _render_vendor_send_approval(case_id: str, values: dict) -> None:
    """The deliberately narrower second gate: send or cancel, never edit."""
    from submission.notifications.vendor_email import build_purchase_order_email_preview

    proposal, request = values["proposal"], values["purchase_result"]
    preview = build_purchase_order_email_preview(proposal, request)
    st.subheader("Approve sending the purchase order")
    st.info("The purchase request is reserved internally. It has not yet been sent to the supplier. Review the exact purchase-order email below before authorising it.")

    st.subheader("Purchase order email to be sent")
    with st.container(border=True):
        left, right = st.columns(2)
        left.markdown(f"**From:** {config.gmail_address or 'Not configured'}")
        right.markdown(f"**To:** {preview.recipient or 'No supplier email address on file'}")
        st.markdown(f"**Subject:** {preview.subject}")
        st.caption(
            f"PO reference {request.request_id} · {preview.product_name} · "
            f"delivery to {preview.warehouse_label}"
        )
        components.html(preview.html_document, height=620, scrolling=True)

    with st.expander("Plain-text email version", expanded=False):
        st.code(preview.plain_text, language=None)

    has_sender_credentials = bool(config.gmail_address and config.gmail_app_password)
    can_send = bool(preview.recipient and has_sender_credentials)
    if not preview.recipient:
        st.error("This purchase order cannot be sent: the chosen supplier has no contact email address on file.")
    elif not has_sender_credentials:
        st.error("This purchase order cannot be sent: the sender email account is not fully configured.")
    else:
        st.success("The recipient, subject, order contents, and formatted email above are exactly what will be sent if you approve.")

    approver = st.text_input("Your name", key="vendor_send_approver")
    reason = st.text_area("Reason (required only when rejecting)", key="vendor_send_reason", height=80, max_chars=500)
    left, right = st.columns(2)
    decision = None
    with left:
        if st.button("Approve and send", type="primary", disabled=not (approver.strip() and can_send), use_container_width=True):
            decision = "APPROVED"
    with right:
        if st.button("Reject and cancel request", disabled=not (approver.strip() and reason.strip()), use_container_width=True):
            decision = "REJECTED"
    if decision:
        try:
            resume_vendor_send(case_id, decision, approver.strip(), reason.strip() or None, st.session_state.get("thread_id"))
        except Exception as exc:
            st.error("The vendor-send decision could not be applied.")
            st.exception(exc)
            return
        _goto("case", case_id=case_id)


def _render_edit_form(case_id: str, values: dict, approver: str, comment: str) -> str | None:
    """Pick a different supplier directly (B8). Returns the chosen offer_id
    when the operator submits, otherwise None.

    Distinct from "Ask for changes", which hands a comment to the strategist
    and lets it re-reason. This is for the case where the approver already
    knows which of the quoted suppliers they want and should not have to
    persuade a model to agree.

    Only eligible options are offered -- the same list the strategist chose
    from, all of which already passed the reliability, arrival-before-stockout
    and offer-validity gates. Quantity is deliberately not editable: it is
    sized per supplier from that supplier's lead time, so switching supplier
    re-sizes the order automatically and correctly.
    """
    options = values.get("vendor_options")
    eligible = list(options.eligible_options) if options else []
    proposal = values.get("proposal")
    economics = values.get("economics")
    current_offer_id = getattr(proposal, "recommended_vendor_id", None)

    alternatives = [
        o for o in eligible
        if o.offer_id != getattr(_current_option(values), "offer_id", None)
    ]
    if not alternatives:
        return None

    used = values.get("retry_counts", {}).get("human_edit", 0)
    remaining = config.max_human_edit_cycles - used

    with st.expander(f"Choose a different supplier ({len(alternatives)} other option(s))"):
        if remaining <= 0:
            st.info(
                f"You have already changed the supplier {used} time(s), which is the limit. "
                "Approve or reject this one, or ask for changes."
            )
            return None

        st.caption(
            "Every supplier below can deliver before this product runs out and meets the "
            "reliability bar — the strategist chose between these same options. Picking one "
            "re-checks it against policy and the budget, then brings it back for your approval."
        )

        labels = {}
        for o in alternatives:
            note = ""
            if economics is not None:
                econ = economics.by_offer(o.offer_id)
                if econ is not None and econ.all_in_cost_per_day_of_cover is not None:
                    # Cost per day of cover, not total cost: the totals differ
                    # because the quantities differ, so putting the totals
                    # side by side invites exactly the wrong comparison.
                    note = (
                        f" · {_md(_money(econ.all_in_cost_per_day_of_cover))} per day of stock"
                    )
                    if econ.offer_id == economics.best_value_offer_id:
                        note += " (best value)"
            # Radio labels go through markdown too, and each one quotes three
            # amounts -- so they need the same dollar-sign escaping. See _md.
            labels[o.offer_id] = (
                f"{o.vendor_name} — {o.quantity} units at {_md(_money(o.unit_price))} "
                f"= {_md(_money(o.total_cost))}, arrives {_day(o.expected_arrival)}{note}"
            )

        picked = st.radio(
            "Use this supplier instead",
            options=[o.offer_id for o in alternatives],
            format_func=lambda oid: labels[oid],
            key=f"edit_pick_{case_id}",
        )
        selected_economics = economics.by_offer(picked) if economics is not None else None
        if selected_economics is not None:
            st.info(f"Why this is not the first recommendation: {selected_economics.verdict_explanation}")
        st.caption(
            "Quantity differs between suppliers because a slower delivery needs more stock "
            "ordered to cover the extra days in transit. It is calculated, not chosen — which is "
            "why the suppliers are compared on cost per day of stock rather than on the total, "
            "and why the largest total is not necessarily the dearest supplier."
        )
        if not approver.strip() or not comment.strip():
            st.caption("Enter your name and a reason above to enable this choice. Your reason is recorded in the audit trail and shown with the rebuilt proposal.")
        if st.button(
            "Use this supplier and re-check",
            disabled=not (approver.strip() and comment.strip()),
            key=f"edit_submit_{case_id}",
        ):
            return picked
    return None


def _current_option(values: dict):
    """The eligible VendorOption the current proposal was built from."""
    proposal = values.get("proposal")
    options = values.get("vendor_options")
    if proposal is None or options is None:
        return None
    return next(
        (o for o in options.eligible_options if o.vendor_id == proposal.recommended_vendor_id),
        None,
    )


def _render_timeline(case_id: str, trace_id: str | None = None) -> None:
    """This run's steps by default. A case_id covers every time this product
    was looked at, which is what an auditor wants and what makes a planner's
    screen unreadable, so the wider view is opt-in."""
    events = read_case_history(case_id, trace_id)
    if not events:
        events, trace_id = read_case_history(case_id), None
    if not events:
        return

    label = "What the system did, step by step" if trace_id else "Everything ever done on this product"
    with st.expander(f"{label} ({len(events)} steps)", expanded=False):
        if trace_id and st.checkbox("Include earlier investigations of this product", key=f"allruns-{case_id}"):
            events = read_case_history(case_id)
        lines = []
        for ev in events:
            detail = f" — {ev.detail}" if ev.detail else ""
            lines.append(f"- `{_when(ev.at)}` &nbsp; **{ev.who}** — {ev.what}{detail}")
        st.markdown("\n".join(lines))
        st.caption(
            "This is the recorded audit trail. It stores what each step decided, "
            "never the models' private reasoning."
        )


# ---------------------------------------------------------------------------
# screen: needs my decision (B1/B2: the operator's actual to-do list)
# ---------------------------------------------------------------------------

def screen_pending() -> None:
    st.title("Needs my decision")
    st.caption(
        "Every case currently waiting on a person — approving a proposal or supplying "
        "missing information. Nothing here is finished yet."
    )
    pending = list_pending_cases()
    if not pending:
        st.success("Nothing is waiting on you right now.")
        return

    status_label = {
        "AWAITING_APPROVAL": "Waiting for approval (gate 1)",
        "AWAITING_VENDOR_APPROVAL": "Waiting for vendor-send approval (gate 2)",
        "NEEDS_INFORMATION": "Needs more information",
    }
    for c in pending:
        # DG8: a manual-cover pause and a missing-fields pause share the
        # same NEEDS_INFORMATION status string -- branch on target_mode so
        # the queue itself says which form the case actually needs, not
        # just that "something" is needed.
        if c["status"] == "NEEDS_INFORMATION" and c.get("target_mode") == "MANUAL_COVER_REQUIRED":
            label = "Needs days-of-stock (immature policy)"
        else:
            label = status_label.get(c["status"], c["status"])
        with st.container(border=True):
            left, mid, right = st.columns([4, 3, 2], vertical_alignment="center")
            with left:
                st.markdown(f"**{c.get('sku') or c['case_id']}** · {c.get('warehouse_id') or '—'}")
                st.caption(label)
            with mid:
                st.caption(f"waiting since {_when(c['last_at'])}")
                if c.get("likely_stale"):
                    st.warning(
                        f"Waiting over {config.data_freshness_hours:.0f}h — stock/price may have "
                        "moved, so acting on this now will likely bounce back for a fresh check.",
                        icon="⏳",
                    )
            with right:
                if st.button("Open", key=f"open-pending-{c['case_id']}", use_container_width=True, type="primary"):
                    _goto("case", case_id=c["case_id"], thread_id=c.get("thread_id"))


# ---------------------------------------------------------------------------
# screen: continuous autonomous monitor -- persistent worker, history, park queue
# ---------------------------------------------------------------------------

def screen_monitor() -> None:
    from submission.config import config
    from submission.monitor.service import get_monitor_status, restart_monitor, start_monitor, stop_monitor
    from tools.parking import get_open_parked_items
    from tools.sweep_runs import get_sweep_history

    st.title("Autonomous monitor")
    st.caption(
        "Start this once and it keeps checking stock in a separate local process. "
        "It can open cases and park missing data, but it never places an order without human approval."
    )

    status = get_monitor_status()
    scope = status.get("warehouse_id") or "All warehouses"
    interval = int(status.get("interval_seconds") or config.monitor_interval_seconds)
    if status.get("desired_running"):
        if status.get("running"):
            started_since = _monitor_when(status.get("monitor_started_at") or status.get("started_at"))
            st.success(
                f"Monitoring is ON — {scope} every {interval // 60 if interval % 60 == 0 else interval} "
                f"{'minutes' if interval % 60 == 0 else 'seconds'}, since {started_since}."
            )
        elif status.get("pid"):
            st.info("Monitoring is starting — the first scan will run now.")
        else:
            st.warning("Stop requested — the current scan will finish safely, then monitoring will stop.")
        started_col, last_col, next_col, cases_col = st.columns(4)
        started_col.metric("Monitoring since", _monitor_when(status.get("monitor_started_at") or status.get("started_at")))
        last_col.metric("Last scan", _monitor_when(status.get("last_completed_at")))
        next_col.metric("Next scan", _monitor_when(status.get("next_run_at")))
        result = status.get("last_result") or {}
        cases_col.metric("Cases opened", result.get("cases_opened", 0))
        if result:
            st.caption(
                f"Latest sweep {result.get('sweep_id', '—')}: examined {result.get('pairs_examined', 0)} · "
                f"candidates {result.get('candidates_found', 0)} · parked {result.get('parked_count', 0)} · "
                f"deferred {result.get('deferred_for_budget_count', 0)} · reminders {result.get('reminders_sent', 0)}"
            )
        if status.get("last_error"):
            st.error(f"Latest monitor error: {status['last_error']}")
        stop_col, restart_col = st.columns(2)
        if stop_col.button("Stop monitoring", type="secondary", use_container_width=True):
            stop_monitor()
            st.rerun()
        if restart_col.button("Restart monitor (apply update)", use_container_width=True, help="Stops only this recorded local monitor worker, then starts a fresh worker using the current code."):
            try:
                _state, started = restart_monitor(status.get("warehouse_id"), interval)
            except RuntimeError as exc:
                st.error(str(exc))
            else:
                if started:
                    st.success("Monitor restarted with the current code. The next scan is starting now.")
                    st.rerun()
    else:
        requested_interval = st.number_input(
            "Check every (seconds)", min_value=30, max_value=3600,
            value=max(30, interval), step=30,
            help="Five minutes is the normal setting. Each scan can open approval cases, so do not set this aggressively.",
        )
        selected_scope = warehouse_filter or "all warehouses"
        st.caption(f"The monitor will start immediately, then check {selected_scope} every {int(requested_interval)} seconds.")
        if status.get("last_error"):
            st.warning(f"Previous monitor error: {status['last_error']}")
        if st.button("Start monitoring", type="primary", use_container_width=True):
            _state, started = start_monitor(warehouse_filter, int(requested_interval))
            if started:
                st.success("Monitoring started. The first scan is running now; it will continue if you leave this page or refresh the browser.")
            else:
                st.info("Monitoring is already running.")
            st.rerun()

    st.subheader("Sweep history")
    history = get_sweep_history()
    if not history:
        st.info("No sweep has run yet.")
    for run in history:
        with st.container(border=True):
            st.markdown(f"**{run.sweep_id}** — {_monitor_when(run.started_at)}")
            st.caption(
                f"examined {run.pairs_examined} · candidates {run.candidates_found} · "
                f"parked {run.parked_count} · deferred {run.deferred_for_budget_count} · "
                f"opened {run.cases_opened} · reminders {run.reminders_sent} · "
                f"~{run.total_model_calls_estimate} model call(s)"
            )
            if run.detail:
                with st.expander("Per-candidate detail"):
                    st.json(run.detail)

    st.subheader("Park queue")
    st.caption("A parked SKU never blocks the sweep. Each row deep-links into the data console's missing-sales screen.")
    parked = get_open_parked_items(warehouse_filter)
    if not parked:
        st.success("Nothing parked.")
    for item in parked:
        with st.container(border=True):
            st.markdown(f"**{item.sku}** · {item.warehouse_id}")
            st.caption(item.reason)
            if item.note:
                st.caption(item.note)
            deep_link = f"http://127.0.0.1:8502/?sku={item.sku}&warehouse_id={item.warehouse_id}"
            st.markdown(f"[Open in data console →]({deep_link})")


# ---------------------------------------------------------------------------
# screen: past cases
# ---------------------------------------------------------------------------

def screen_history() -> None:
    st.title("Past cases")
    st.caption("Everything the system has looked at, most recent first.")
    cases = list_cases()
    if not cases:
        st.info("No cases yet. Start from the stock watchlist.")
        return
    for c in cases:
        with st.container(border=True):
            left, mid, right = st.columns([4, 3, 2], vertical_alignment="center")
            with left:
                st.markdown(f"**{c['case_id']}**")
                st.caption(f"{c['event_count']} steps recorded")
            with mid:
                st.markdown(f"Outcome: **{c['outcome']}**")
                st.caption(f"last activity {_when(c['last_at'])}")
            with right:
                if st.button("Open", key=f"open-{c['case_id']}", use_container_width=True):
                    _goto("case", case_id=c["case_id"], thread_id=None)


# ---------------------------------------------------------------------------

VIEWS = {
    "watchlist": screen_watchlist,
    "investigate": screen_investigate,
    "case": screen_case,
    "pending": screen_pending,
    "history": screen_history,
    "monitor": screen_monitor,
}
VIEWS.get(st.session_state.view, screen_watchlist)()
