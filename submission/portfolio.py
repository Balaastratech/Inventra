"""
Operator-facing read models. Two things the CLI never needed and the UI
cannot work without:

  scan_portfolio()    -- the worklist. Every product/warehouse pair the
                         warehouse actually holds, ranked worst-first by
                         days of stock remaining, in plain language.
  read_case_history() -- the audit trail played back as a readable
                         timeline instead of raw JSON rows.

Why this exists (brief §4 requires justifying any added tool):

  Business need. The brief's premise is a planner responsible for hundreds
  of products who cannot notice a stockout in time. Every other tool in
  the package answers "how bad is THIS product at THIS warehouse" -- none
  answers "which ones should I be looking at". Without that step the
  operator has to already know the answer before the system can help,
  which is the manual process the brief asks us to replace.

  Contract. scan_portfolio(target_cover_days, warehouse_id=None) ->
  list[WorklistRow], sorted most-urgent-first. read_case_history(case_id)
  -> list[CaseEvent], oldest-first. Both are pure reads and both return
  partial results with a per-row reason string rather than raising, so one
  bad product cannot blank the whole screen.

  Permission level. Deterministic, operator-facing, read-only. NOT an
  agent tool and deliberately not registered in nodes._AGENTS or any
  prompt -- no agent needs a portfolio-wide view to judge one case, and
  handing a model a whole-database read is exactly the generic-SQL
  surface the brief forbids. The one SQL statement here (discovering which
  sku/warehouse pairs exist) is the only query in the submission that
  isn't a provided tool call; every number after that comes from
  get_stock_position / get_sales_velocity / calculate_stock_risk
  unmodified, so the risk arithmetic on the worklist is the same
  arithmetic the graph will use when the operator opens the case.

  Failure behaviour. A row that cannot be assessed still appears, with
  status set to the reason (stale snapshot, no sales history, inactive
  product). Hiding an unassessable product is the one outcome that could
  cause a real stockout, so nothing is ever silently dropped.
"""

from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

from domain.tool_models import ErrorCode
from tools.inventory import calculate_stock_risk, get_product, get_stock_position
from tools.sales import get_sales_velocity

from submission.config import config

# --- Worklist statuses, ordered by how urgently a human should look ---
STATUS_CRITICAL = "Critical"
STATUS_AT_RISK = "At risk"
STATUS_BORDERLINE = "Borderline"
STATUS_HEALTHY = "Healthy"
STATUS_NEEDS_ATTENTION = "Needs attention"  # data problem: stale, no history, inactive

_STATUS_ORDER = {
    STATUS_CRITICAL: 0,
    STATUS_AT_RISK: 1,
    STATUS_BORDERLINE: 2,
    STATUS_NEEDS_ATTENTION: 3,
    STATUS_HEALTHY: 4,
}


@dataclass
class WorklistRow:
    sku: str
    product_name: str
    warehouse_id: str
    status: str
    headline: str  # one plain-language sentence, safe to show a non-technical user
    units_available: Optional[int] = None
    daily_sales_7d: Optional[float] = None
    daily_sales_30d: Optional[float] = None
    days_of_stock: Optional[float] = None  # worst case of the two windows
    days_of_stock_best: Optional[float] = None
    runs_out_on: Optional[datetime] = None
    data_age_hours: Optional[float] = None
    windows_disagree: bool = False  # 7-day and 30-day trends give different verdicts
    can_investigate: bool = True
    target_basis_label: str = ""  # which cover target this row was judged against, and why (R11)

    @property
    def sort_key(self):
        return (
            _STATUS_ORDER.get(self.status, 9),
            self.days_of_stock if self.days_of_stock is not None else 9_999,
        )


@dataclass
class CaseEvent:
    at: datetime
    actor: str  # "system" | "agent:<node>" | "human:<name>"
    who: str  # plain-language actor
    what: str  # plain-language description
    detail: str = ""
    raw: dict = field(default_factory=dict)


@contextmanager
def _connect(db_path: str | None = None):
    """A plain `with sqlite3.connect(...) as conn:` only commits/rolls back
    on exit -- it does NOT close the connection, so every caller below was
    leaking a file handle. Harmless on its own, but on Windows a leaked
    handle keeps database/inventra.db locked until garbage collection gets
    to it, which made database/seed.py's os.remove() intermittently fail
    with PermissionError right after a test module that had called one of
    these reads (surfaced by the Phase 2 test suite, not specific to it)."""
    conn = sqlite3.connect(db_path or config.database_path)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
    finally:
        conn.close()


def list_warehouses() -> list[str]:
    """Every configured warehouse, including newly created empty ones."""
    from tools.warehouses import list_warehouses as _list_warehouses

    return [warehouse.warehouse_id for warehouse in _list_warehouses()]


def _stocked_pairs(warehouse_id: str | None) -> list[sqlite3.Row]:
    sql = """
        SELECT DISTINCT s.sku, s.warehouse_id, p.name AS product_name, p.active
        FROM inventory_snapshots s
        JOIN products p ON p.sku = s.sku
    """
    params: tuple = ()
    if warehouse_id:
        sql += " WHERE s.warehouse_id = ?"
        params = (warehouse_id,)
    sql += " ORDER BY s.sku, s.warehouse_id"
    with _connect() as conn:
        return conn.execute(sql, params).fetchall()


def _days(value: float | None) -> str:
    if value is None:
        return "unknown"
    if value < 1:
        return "less than a day"
    return f"{value:.0f} day" + ("" if 0.5 <= value < 1.5 else "s")


def scan_portfolio(
    target_cover_days: int | None = None,
    warehouse_id: str | None = None,
) -> list[WorklistRow]:
    """Assess every stocked product/warehouse pair. Most urgent first.

    Ranking uses the *worse* of the 7-day and 30-day sales trends, so the
    worklist errs toward showing a product rather than hiding it. Which
    window to actually trust is a judgment the Demand agent makes once the
    operator opens the case -- this function never makes that call, it
    just refuses to let the optimistic window bury a product.

    target_cover_days is a **test-only override**. In normal operation each
    row is judged against its own sku_policy.derived_cover_days (Phase B) --
    never a flat number for every product (see AUTONOMOUS_PLAN.md problem
    §0.2 / rule R11). A pair with no policy row yet, or one that has not
    reached ESTABLISHED maturity, is labelled as such rather than silently
    falling back to config.target_cover_default_days.
    """
    from tools.classification import get_latest_sku_policy

    rows: list[WorklistRow] = []

    for pair in _stocked_pairs(warehouse_id):
        sku, wh, name = pair["sku"], pair["warehouse_id"], pair["product_name"]

        policy = None if target_cover_days is not None else get_latest_sku_policy(sku, wh)
        if target_cover_days is not None:
            target = target_cover_days
            target_label = f"{target}-day (test override)"
        elif policy is None:
            target = config.target_cover_default_days
            target_label = "not yet derived — needs classification"
        elif policy.maturity != "ESTABLISHED" or policy.derived_cover_days is None:
            target = config.target_cover_default_days
            target_label = f"provisional maturity — using {target}-day placeholder until established"
        else:
            target = round(policy.derived_cover_days)
            target_label = f"{target}-day (derived from this SKU's own policy)"

        if not pair["active"]:
            rows.append(
                WorklistRow(
                    sku=sku, product_name=name, warehouse_id=wh,
                    status=STATUS_NEEDS_ATTENTION,
                    headline="This product is discontinued, so it is not being restocked.",
                    can_investigate=False,
                )
            )
            continue

        stock = get_stock_position(sku, wh)
        if stock.error is not None:
            rows.append(
                WorklistRow(
                    sku=sku, product_name=name, warehouse_id=wh,
                    status=STATUS_NEEDS_ATTENTION,
                    headline="No usable stock record for this warehouse, so stock level is unknown.",
                    can_investigate=False,
                )
            )
            continue

        available = stock.on_hand - stock.reserved + stock.confirmed_inbound
        age_hours = (datetime.utcnow() - stock.captured_at).total_seconds() / 3600

        sales = get_sales_velocity(sku, wh)
        if sales.error is not None:
            reason = (
                "Too few recent sales to predict demand, so no restock can be justified yet."
                if sales.error == ErrorCode.INSUFFICIENT_DATA
                else "Sales history could not be read, so demand is unknown."
            )
            rows.append(
                WorklistRow(
                    sku=sku, product_name=name, warehouse_id=wh,
                    status=STATUS_NEEDS_ATTENTION, headline=reason,
                    units_available=available, data_age_hours=round(age_hours, 1),
                    can_investigate=True,  # the graph will explain and close it properly
                )
            )
            continue

        # Both windows, so the worklist can flag when they disagree -- that
        # disagreement is exactly what decides buy-vs-do-nothing on
        # borderline products, and it is invisible in a single number.
        risks = {}
        for label, velocity in (("7d", sales.window_7_days), ("30d", sales.window_30_days)):
            if velocity and velocity > 0:
                risks[label] = calculate_stock_risk(
                    available_units=available,
                    daily_velocity=velocity,
                    target_cover_days=target,
                    snapshot_captured_at=stock.captured_at,
                    stale_threshold_hours=config.data_freshness_hours,
                )

        if not risks:
            rows.append(
                WorklistRow(
                    sku=sku, product_name=name, warehouse_id=wh,
                    status=STATUS_HEALTHY,
                    headline="No sales recorded recently, so stock is not being drawn down.",
                    units_available=available, data_age_hours=round(age_hours, 1),
                )
            )
            continue

        # Undefined cover (zero demand with stock) is deliberately surfaced as
        # attention-worthy rather than compared as infinity or a fake rate.
        worst = min(
            risks.values(),
            key=lambda r: (r.cover_days is not None, r.cover_days if r.cover_days is not None else 0),
        )
        best = max(risks.values(), key=lambda r: (-1 if r.cover_days is None else r.cover_days))
        disagree = len(risks) == 2 and (risks["7d"].at_risk != risks["30d"].at_risk)

        if age_hours > config.data_freshness_hours:
            status = STATUS_NEEDS_ATTENTION
            headline = (
                f"The stock figure is {age_hours:.0f} hours old. Anything older than "
                f"{config.data_freshness_hours:.0f} hours is not trusted for ordering, "
                "so this needs a fresh stock count."
            )
        elif worst.cover_days is None:
            status = STATUS_NEEDS_ATTENTION
            headline = "Demand is currently zero, so days of stock cannot be meaningfully calculated."
        elif worst.cover_days < target / 2:
            status = STATUS_CRITICAL
            headline = (
                f"About {_days(worst.cover_days)} of stock left against a {target}-day target. "
                "Order now or this will run out."
            )
        elif worst.at_risk and disagree:
            status = STATUS_BORDERLINE
            headline = (
                f"Between {_days(worst.cover_days)} and {_days(best.cover_days)} of stock left, "
                f"depending on whether recent sales or the longer trend holds. Worth a look."
            )
        elif worst.at_risk:
            status = STATUS_AT_RISK
            headline = (
                f"About {_days(worst.cover_days)} of stock left against a {target}-day target."
            )
        else:
            status = STATUS_HEALTHY
            headline = f"About {_days(worst.cover_days)} of stock left. Comfortably above the {target}-day target."

        rows.append(
            WorklistRow(
                sku=sku, product_name=name, warehouse_id=wh,
                status=status, headline=headline,
                units_available=available,
                daily_sales_7d=sales.window_7_days,
                daily_sales_30d=sales.window_30_days,
                days_of_stock=round(worst.cover_days, 1) if worst.cover_days is not None else None,
                days_of_stock_best=round(best.cover_days, 1) if best.cover_days is not None else None,
                runs_out_on=worst.projected_stockout_date,
                data_age_hours=round(age_hours, 1),
                windows_disagree=disagree,
                target_basis_label=target_label,
            )
        )

    rows.sort(key=lambda r: r.sort_key)
    return rows


# ---------------------------------------------------------------------------
# Audit trail playback
# ---------------------------------------------------------------------------

# Deliberately a plain lookup, not a model call. Turning a known event_type
# into a known sentence needs no judgment, and an LLM here would be able to
# misdescribe what the system did -- the one place a hallucination would
# directly mislead an auditor.
_EVENT_TEXT: dict[str, tuple[str, str]] = {
    "request_validated": ("System", "Checked the request had a product and a warehouse"),
    "needs_information": ("System", "Paused: the request was missing something it needed"),
    "missing_information_provided": ("System", "Received corrected information and re-checked the request"),
    "product_verified": ("System", "Confirmed the product exists and is still sold"),
    "product_check_failed": ("System", "Stopped: could not confirm the product"),
    "evidence_gathered": ("System", "Read the current stock level and recent sales"),
    "stock_check_failed": ("System", "Stopped: could not read the stock level"),
    "data_stale": ("System", "Stopped: the stock figure was too old to trust"),
    "sales_check_failed": ("System", "Stopped: not enough sales history to predict demand"),
    "assess_demand_succeeded": ("Demand analyst", "Decided which sales trend to trust and why"),
    "demand_ambiguous": ("Demand analyst", "Paused: the sales trends disagreed too much to pick one automatically"),
    "assess_demand_call_failed": ("Demand analyst", "Gave an unusable answer; asked again"),
    "risk_assessed": ("System", "Worked out how many days of stock are left"),
    "vendor_evidence_gathered": ("System", "Looked up supplier offers and delivery track records"),
    "vendor_options_built": ("System", "Priced up each supplier option and checked delivery dates"),
    "no_eligible_vendors": ("System", "Stopped: no supplier was both reliable enough and fast enough"),
    "recommend_vendor_succeeded": ("Sourcing strategist", "Chose a supplier and explained the trade-off"),
    "recommend_vendor_call_failed": ("Sourcing strategist", "Gave an unusable answer; asked again"),
    "budget_and_policy_loaded": ("System", "Checked the warehouse budget and the purchasing policy"),
    "budget_check_failed": ("System", "Stopped: could not read the budget"),
    "proposal_drafted": ("System", "Wrote up the purchase proposal"),
    "policy_reviewed": ("Policy reviewer", "Checked the proposal against policy and the budget"),
    "review_policy_call_failed": ("Policy reviewer", "Gave an unusable answer; asked again"),
    "review_policy_succeeded": ("Policy reviewer", "Completed the policy check"),
    "approval_requested": ("System", "Sent the proposal to a person for approval"),
    "decision_recorded": ("Approver", "Recorded the decision"),
    "revision_requested": ("System", "Reworking the proposal with the approver's feedback"),
    "approval_invalidated": ("System", "Cancelled the approval because the facts changed"),
    "revalidated": ("System", "Re-checked stock, price and budget one last time before ordering"),
    "purchase_request_created": ("System", "Created the purchase request"),
    "purchase_request_cancelled": ("Approver", "Cancelled the order"),
    "write_failed": ("System", "Could not save the purchase request"),
    "case_closed": ("System", "Closed the case"),
}

_STATUS_TEXT = {
    "NO_ACTION": "no order needed",
    "NEEDS_INFORMATION": "more information needed",
    "BLOCKED": "could not proceed",
    "AWAITING_APPROVAL": "waiting for a person to approve",
    "AWAITING_VENDOR_APPROVAL": "waiting for vendor-send approval",
    "PURCHASE_REQUEST_CREATED": "purchase request created",
    "PURCHASE_REQUEST_CANCELLED": "purchase request cancelled",
}


def _describe(event_type: str, payload: dict) -> tuple[str, str, str]:
    who, what = _EVENT_TEXT.get(event_type, ("System", event_type.replace("_", " ")))
    detail = ""
    if event_type == "risk_assessed":
        detail = f"{payload.get('available_units')} units available, about {payload.get('cover_days')} days of stock"
    elif event_type == "vendor_options_built":
        detail = f"{payload.get('eligible_count')} supplier option(s) could actually deliver in time"
    elif event_type == "proposal_drafted":
        detail = f"total cost ${payload.get('total_cost')}"
    elif event_type == "policy_reviewed":
        concerns = payload.get("concerns") or []
        detail = f"verdict: {payload.get('verdict')}" + (f" — {'; '.join(concerns)}" if concerns else "")
    elif event_type == "decision_recorded":
        detail = f"{payload.get('decision')}"
    elif event_type == "revalidated":
        detail = "all checks passed" if payload.get("all_checks_pass") else f"failed: {payload.get('detail')}"
    elif event_type == "purchase_request_created":
        detail = f"request {payload.get('request_id')}"
    elif event_type == "purchase_request_cancelled":
        detail = f"request {payload.get('request_id')} — {payload.get('reason') or 'no reason given'}"
    elif event_type == "case_closed":
        detail = _STATUS_TEXT.get(payload.get("status", ""), payload.get("status", ""))
        if payload.get("detail"):
            detail += f" — {payload['detail']}"
    elif event_type in ("needs_information",):
        detail = f"missing: {', '.join(payload.get('missing', []))}"
    elif event_type.endswith("_call_failed"):
        detail = f"attempt {payload.get('attempt')}: {payload.get('error_type')}"
    return who, what, detail


def read_case_history(case_id: str, trace_id: str | None = None) -> list[CaseEvent]:
    """Play the audit trail back as a readable timeline.

    Pass trace_id to see just one run of the case. A case_id is stable for a
    product at a warehouse, so it deliberately accumulates every run's events
    -- which is right for an auditor and confusing for a planner, who opens a
    case and sees 39 steps spanning three separate investigations. Each run
    gets its own trace_id at intake, so it is the natural filter.

    Only the structured payload each node wrote is used -- there is no
    model reasoning in audit_events to leak, by design (brief §6: audit
    events carry structured summaries, not private reasoning).
    """
    sql = """
        SELECT actor, event_type, payload_json, created_at
        FROM audit_events WHERE case_id = ?
    """
    params: tuple = (case_id,)
    if trace_id:
        sql += " AND trace_id = ?"
        params = (case_id, trace_id)
    sql += " ORDER BY created_at ASC, rowid ASC"
    with _connect() as conn:
        rows = conn.execute(sql, params).fetchall()

    events: list[CaseEvent] = []
    for r in rows:
        try:
            payload = json.loads(r["payload_json"])
        except (ValueError, TypeError):
            payload = {}
        who, what, detail = _describe(r["event_type"], payload)
        if r["actor"].startswith("human:"):
            who = r["actor"].split(":", 1)[1] or "Approver"
        events.append(
            CaseEvent(
                at=r["created_at"],
                actor=r["actor"],
                who=who,
                what=what,
                detail=detail,
                raw=payload,
            )
        )
    return events


def get_purchase_request(case_id: str) -> Optional[dict]:
    """The actual purchase_requests row for a case, read fresh from the
    database -- not the in-memory graph state the approval screen already
    has. Exists so "order placed" is something the UI can prove by querying
    the same table create_purchase_request (tools/execution.py) wrote to,
    rather than the operator having to trust a status label in state that
    could in principle say PURCHASE_REQUEST_CREATED without a row existing.
    Returns None if no request was ever written for this case (the normal
    case for every status other than PURCHASE_REQUEST_CREATED)."""
    with _connect() as conn:
        row = conn.execute(
            """
            SELECT request_id, vendor_id, sku, warehouse_id, quantity, unit_price,
                   total_cost, status, approved_by, approved_at, created_at,
                   vendor_sent_at, vendor_send_status, vendor_reminder_count, vendor_last_reminded_at,
                   cancelled_at, cancelled_by, cancel_reason, committed_budget_month
            FROM purchase_requests
            WHERE case_id = ?
            ORDER BY created_at DESC LIMIT 1
            """,
            (case_id,),
        ).fetchone()
    return dict(row) if row else None


def list_cases() -> list[dict]:
    """Every case the system has ever opened, newest first, with its last
    known event -- so an operator can find yesterday's work instead of
    having to remember a case id."""
    with _connect() as conn:
        rows = conn.execute(
            """
            SELECT a.case_id,
                   MIN(a.created_at) AS started_at,
                   MAX(a.created_at) AS last_at,
                   COUNT(*)          AS event_count
            FROM audit_events a
            GROUP BY a.case_id
            ORDER BY MAX(a.created_at) DESC
            """
        ).fetchall()
        cases = []
        for r in rows:
            closing = conn.execute(
                """
                SELECT payload_json FROM audit_events
                WHERE case_id = ? AND event_type = 'case_closed'
                ORDER BY created_at DESC LIMIT 1
                """,
                (r["case_id"],),
            ).fetchone()
            outcome = "waiting for a person to approve"
            if closing:
                try:
                    status = json.loads(closing["payload_json"]).get("status", "")
                except (ValueError, TypeError):
                    status = ""
                outcome = _STATUS_TEXT.get(status, status or "closed")
            cases.append(
                {
                    "case_id": r["case_id"],
                    "started_at": r["started_at"],
                    "last_at": r["last_at"],
                    "event_count": r["event_count"],
                    "outcome": outcome,
                    "is_pending": closing is None,
                }
            )
    return cases


def list_pending_cases() -> list[dict]:
    """The operator's actual to-do list: cases currently paused for a human
    action (AWAITING_APPROVAL or NEEDS_INFORMATION), distinct from "Past
    cases" which lists everything ever opened, closed or not. Without this
    the only way to find pending work was to already know a case_id or read
    every row in the full history and guess from the prose outcome.

    Resolves each candidate's live checkpoint status rather than trusting
    the audit trail alone, since a pending case has no case_closed event to
    read a status from -- and flags cases that have been waiting longer
    than config.data_freshness_hours, since that pause will fail
    revalidation (stock/offer facts too old to trust) the moment someone
    tries to act on it. The continuous monitor also uses this same live
    calculation when it re-sweeps; the queue remains an immediate read model
    for an operator opening this screen.
    """
    from submission.graph.workflow import compile_graph, latest_thread_ids

    candidates = [c for c in list_cases() if c["is_pending"]]
    if not candidates:
        return []

    # One batched thread-id lookup and ONE compiled graph for the whole scan.
    # Both used to sit inside the loop, which meant every pending case paid
    # for a fresh SQLite connection plus a full build_graph().compile() --
    # on a screen the sidebar re-renders on every Streamlit interaction.
    # Rebuilding identical graph topology per row bought nothing and made
    # concurrent access to the checkpoint file needlessly likely to collide.
    threads = latest_thread_ids(c["case_id"] for c in candidates)
    if not threads:
        return []

    pending: list[dict] = []
    graph, conn = compile_graph()
    try:
        for c in candidates:
            thread = threads.get(c["case_id"])
            if thread is None:
                continue
            snapshot = graph.get_state({"configurable": {"thread_id": thread}})
            if not snapshot.next:
                continue  # resumed/finished since list_cases() read the audit trail
            values = snapshot.values or {}
            status = values.get("status")
            status = status.value if hasattr(status, "value") else str(status or "")
            last_at = c["last_at"]
            if isinstance(last_at, str):
                try:
                    last_at = datetime.fromisoformat(last_at)
                except ValueError:
                    last_at = None
            waiting_hours = (
                (datetime.utcnow() - last_at).total_seconds() / 3600 if last_at is not None else None
            )
            pending.append(
                {
                    **c,
                    "thread_id": thread,
                    "status": status,
                    "target_mode": values.get("target_mode"),
                    "sku": values.get("sku"),
                    "warehouse_id": values.get("warehouse_id"),
                    "waiting_hours": waiting_hours,
                    "likely_stale": waiting_hours is not None and waiting_hours > config.data_freshness_hours,
                }
            )
    finally:
        conn.close()
    return pending
