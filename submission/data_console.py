"""
G1 — data console. Run with: streamlit run submission/data_console.py

Full, validated create/edit/delete on every *input* table (R11/G1.1), the
missing-sales-data screen that makes R11 workable (G1.2), per-SKU levers,
scenario picker and a live statistics panel (G1.5), and a persisted change
log (G1.2/DG5). Derived tables are shown read-only (DG3).

No SQL box anywhere here (DG2): every write goes through
submission/dataops/write.py, which validates against submission/dataops/spec.py
and logs to data_change_log.

DG10 -- security: this console can write every input table, including
prices, budgets and stock levels, and it has no authentication. Bind it to
localhost only:

    streamlit run submission/data_console.py --server.port 8502 --server.address 127.0.0.1
"""

from __future__ import annotations

import sys
from datetime import date, timedelta
from pathlib import Path

import streamlit as st
import pandas as pd
from st_aggrid import AgGrid, GridOptionsBuilder, JsCode

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from submission.dataops.read import all_table_names, count_table_rows, read_change_log, read_table, read_table_row  # noqa: E402
from submission.dataops.scenarios import load_scenarios  # noqa: E402
from submission.dataops.spec import DERIVED_TABLES, SYSTEM_MANAGED_TABLES, TABLE_SPECS  # noqa: E402
from submission.dataops.stats_panel import get_live_stats, recompute  # noqa: E402
from submission.dataops.write import WriteRejected, create_row, delete_row, update_row  # noqa: E402
from submission.portfolio import list_warehouses  # noqa: E402

st.set_page_config(page_title="Inventra — data console", page_icon="🛠️", layout="wide")

st.markdown(
    """
    <style>
      .block-container { max-width: 1560px; padding-top: 2rem; }
      .dc-toolbar { display:flex; align-items:center; justify-content:space-between; gap:1rem; margin:0 0 .8rem; }
      .dc-toolbar h1 { margin:0; font-size:2rem; letter-spacing:-.035em; line-height:1.1; }
      .st-key-dc_table_tabs {
        width:100%; overflow-x:scroll; overflow-y:hidden; flex-wrap:nowrap;
        gap:.55rem; padding:0 0 .7rem; margin:0 0 1rem;
        border-bottom:1px solid rgba(151, 165, 190, .24); scrollbar-gutter:stable;
      }
      .st-key-dc_table_tabs [data-testid="stButton"] { flex:0 0 auto; }
      .st-key-dc_table_tabs [data-testid="stButton"] button { white-space:nowrap; }
      .dc-table-wrap { overflow-x:auto; border:1px solid rgba(151, 165, 190, .24); border-radius:10px; }
      .dc-table { border-collapse:collapse; width:100%; min-width:980px; font-size:.86rem; }
      .dc-table th { color:#aab5c7; background:rgba(151, 165, 190, .08); font-weight:600; text-align:left; white-space:nowrap; }
      .dc-table th, .dc-table td { padding:.62rem .7rem; border-bottom:1px solid rgba(151, 165, 190, .16); vertical-align:middle; }
      .dc-table tbody tr:last-child td { border-bottom:0; }
      .dc-table tbody tr:hover { background:rgba(80, 135, 240, .06); }
      .dc-table .dc-number { font-variant-numeric:tabular-nums; text-align:right; }
      .dc-table .dc-actions { white-space:nowrap; width:1%; }
      .dc-action { display:inline-flex; align-items:center; justify-content:center; width:1.85rem; height:1.85rem; margin-left:.35rem; border-radius:6px; text-decoration:none; font-size:.9rem; font-weight:700; }
      .dc-edit { color:#fff; background:#146ee8; }
      .dc-delete { color:#fff; background:#d83b46; }
      .dc-boolean { display:inline-block; padding:.14rem .42rem; border-radius:5px; font-size:.75rem; font-weight:600; }
      .dc-boolean-yes { color:#71e6ab; background:rgba(34, 130, 79, .28); }
      .dc-boolean-no { color:#bac2d0; background:rgba(135, 145, 163, .16); }
      [data-testid="stNumberInput"] button { min-width:1.5rem; padding:0; }
    </style>
    """,
    unsafe_allow_html=True,
)

st.warning(
    "**Local demo tool -- no access control.** This screen can write operational "
    "inputs (prices, budgets, stock levels). Supplier records and quotes are read-only. Run bound to 127.0.0.1 only; do not "
    "expose it on a non-loopback address (DG10)."
)

with st.sidebar:
    st.markdown("### 🛠️ Data console")
    st.caption("R11: humans supply data, never answers")
    operator = st.text_input("Your name (required before any write)", key="operator_name")
    view = st.radio(
        "Screen",
        ["Table editor", "Missing sales data", "Levers & scenarios", "Change log"],
        key="dc_view",
    )
    st.divider()
    st.caption(
        "Derived tables (sku_policy, parked_items, sweep_runs, purchase_requests, "
        "audit_events, agent_memory_signals) are read-only here. Edit their inputs "
        "and recompute -- see DG3."
    )

can_write = bool(operator.strip())


def _write_error(exc: WriteRejected) -> None:
    for message in exc.errors:
        st.error(message)


# ---------------------------------------------------------------------------
# Screen: generic table editor (G1-3)
# ---------------------------------------------------------------------------

def screen_table_editor() -> None:
    title, create = st.columns([8, 2], vertical_alignment="center")
    title.markdown('<div class="dc-toolbar"><h1>Table editor</h1></div>', unsafe_allow_html=True)
    table = _table_tabs()

    if table in TABLE_SPECS and table not in SYSTEM_MANAGED_TABLES and can_write and create.button(f"+ Create {TABLE_SPECS[table].label.rstrip('s')}", type="primary", width="stretch"):
        _show_create_dialog(table, TABLE_SPECS[table])

    if table in DERIVED_TABLES:
        st.info("**Computed — edit the inputs and recompute.** This table has no write control (DG3).")
        rows = read_table(table)
        st.dataframe(rows, width="stretch")
        return

    if table in SYSTEM_MANAGED_TABLES:
        st.info("**Supplier-source data — read only.** Supplier eligibility, reliability, and quotes are supplied by the purchasing data source; an operator cannot create, edit, delete, or select them here.")
        st.dataframe(_paged_rows(table), width="stretch", hide_index=True)
        _render_pagination(table)
        return

    spec = TABLE_SPECS[table]
    rows = _paged_rows(table)
    _render_rows_with_actions(table, spec, rows)

    if not can_write:
        st.info("Enter your name in the sidebar to enable Create, Edit, and Delete.")
    _show_pending_row_dialog()


def _table_tabs() -> str:
    """Browser-like table buttons, rather than a selector hidden in a dropdown."""
    tables = all_table_names()
    active = st.session_state.get("dc_active_table", tables[0])
    if active not in tables:
        active = tables[0]

    # Keep every table discoverable. The row scrolls horizontally rather than
    # hiding lesser-used tables behind a separate menu.
    with st.container(horizontal=True, horizontal_alignment="left", key="dc_table_tabs"):
        for name in tables:
            label = TABLE_SPECS[name].label if name in TABLE_SPECS else name.replace("_", " ").title()
            if st.button(label, key=f"dc_table_tab_{name}", type="primary" if name == active else "secondary"):
                st.session_state["dc_active_table"] = name
                st.rerun()
    return active


def _paged_rows(table: str) -> list[dict]:
    total = count_table_rows(table)
    # The compact control is rendered below the table, so pagination never
    # pushes the data away from the top of the screen.
    page_size = int(st.session_state.get(f"dc_page_size_{table}", 10))
    total_pages = max(1, (total + page_size - 1) // page_size)
    page_key = f"dc_page_{table}"
    page = int(st.session_state.get(page_key, 1))
    page = min(max(1, page), total_pages)
    st.session_state[page_key] = page

    start = (page - 1) * page_size
    return read_table(table, limit=page_size, offset=start)


def _render_rows_with_actions(table: str, spec, rows: list[dict]) -> None:
    headers = list(rows[0].keys()) if rows else [column.name for column in spec.columns]
    if not can_write:
        st.dataframe(rows, width="stretch", hide_index=True)
        _render_pagination(table)
        return

    # AgGrid provides real button cells while preserving Streamlit's in-page
    # interaction model; unlike link-based HTML controls, it never navigates.
    action_field = "__row_action"
    grid_data = pd.DataFrame([{**row, action_field: ""} for row in rows])
    grid_builder = GridOptionsBuilder.from_dataframe(grid_data)
    grid_builder.configure_default_column(editable=False, resizable=True, sortable=False)
    grid_options = grid_builder.build()
    grid_options["columnDefs"] = [
        column for column in grid_options["columnDefs"] if column["field"] != action_field
    ]
    grid_options["columnDefs"].append({
        "field": action_field,
        "headerName": "Actions",
        "editable": True,
        "sortable": False,
        "filter": False,
        "width": 165,
        "pinned": "right",
        "cellRenderer": _ACTION_BUTTON_RENDERER,
    })
    revision = st.session_state.get(f"dc_grid_revision_{table}", 0)
    response = AgGrid(
        grid_data,
        gridOptions=grid_options,
        height=max(105, min(430, 42 + len(rows) * 38)),
        update_on=["cellValueChanged"],
        allow_unsafe_jscode=True,
        theme="streamlit",
        key=f"dc_grid_{table}_{revision}",
        show_toolbar=False,
        show_search=False,
        show_download_button=False,
    )
    _queue_grid_action(table, spec, response.data, action_field)
    _render_pagination(table)


def _render_pagination(table: str) -> None:
    total = count_table_rows(table)
    page_size = int(st.session_state.get(f"dc_page_size_{table}", 10))
    total_pages = max(1, (total + page_size - 1) // page_size)
    page_key = f"dc_page_{table}"
    page = min(max(1, int(st.session_state.get(page_key, 1))), total_pages)
    start = (page - 1) * page_size
    end = min(start + page_size, total)
    spacer, rows_label, rows_input, count, previous, current, next_page = st.columns([5, .55, .75, 1.35, .55, .4, .55], vertical_alignment="center")
    rows_label.caption("Rows")
    new_size = rows_input.number_input("Records per page", min_value=1, max_value=1_000, value=page_size, step=1, key=f"dc_page_size_compact_{table}", label_visibility="collapsed")
    if int(new_size) != page_size:
        st.session_state[f"dc_page_size_{table}"] = int(new_size)
        st.session_state[page_key] = 1
        st.rerun()
    count.caption(f"{start + 1 if total else 0}–{end} of {total}")
    if previous.button("‹", key=f"dc_previous_{table}", disabled=page == 1, help="Previous page"):
        st.session_state[page_key] = page - 1
        st.rerun()
    current.markdown(f"<div style='text-align:center; font-weight:600'>{page}</div>", unsafe_allow_html=True)
    if next_page.button("›", key=f"dc_next_{table}", disabled=page == total_pages, help="Next page"):
        st.session_state[page_key] = page + 1
        st.rerun()


_ACTION_BUTTON_RENDERER = JsCode(
    """
    class ActionButtonsRenderer {
      init(params) {
        this.eGui = document.createElement('div');
        this.eGui.style.cssText = 'display:flex; gap:6px; align-items:center; height:100%;';
        const makeButton = (label, color, action, title) => {
          const button = document.createElement('button');
          button.innerText = label;
          button.title = title;
          button.style.cssText = `border:0; border-radius:5px; padding:4px 10px; color:#fff; background:${color}; cursor:pointer; font-size:12px; font-weight:600;`;
          button.addEventListener('click', (event) => {
            event.stopPropagation();
            params.setValue(action);
          });
          return button;
        };
        this.eGui.appendChild(makeButton('Edit', '#146ee8', 'edit', 'Edit this row'));
        this.eGui.appendChild(makeButton('Delete', '#c83b45', 'delete', 'Delete this row'));
      }
      getGui() { return this.eGui; }
      refresh() { return true; }
    }
    """
)


def _queue_grid_action(table: str, spec, grid_data, action_field: str) -> None:
    """Open one modal for the row whose visible action button was clicked."""
    for _, row in grid_data.iterrows():
        action = row.get(action_field)
        if action not in {"edit", "delete"}:
            continue
        st.session_state["dc_pending_row_action"] = {
            "action": action,
            "table": table,
            "pk_value": row[spec.primary_key],
        }
        # A fresh component key clears the clicked action after the modal
        # closes, so Cancel takes exactly one click.
        st.session_state[f"dc_grid_revision_{table}"] = st.session_state.get(f"dc_grid_revision_{table}", 0) + 1
        st.rerun()


def _show_pending_row_dialog() -> None:
    pending = st.session_state.get("dc_pending_row_action")
    if not pending:
        return
    table = pending["table"]
    spec = TABLE_SPECS[table]
    current = read_table_row(table, pending["pk_value"])
    if current is None:
        st.session_state.pop("dc_pending_row_action", None)
        st.error("That record no longer exists.")
        return
    if pending["action"] == "edit":
        _show_edit_dialog(table, spec, current)
    else:
        _show_delete_dialog(table, spec, current)


def _show_create_dialog(table: str, spec) -> None:
    @st.dialog(f"Create {spec.label.rstrip('s')}")
    def dialog():
        with st.form(f"create_{table}"):
            values = {}
            for col in spec.columns:
                if not col.auto:
                    values[col.name] = _field_input(col, key=f"create_{table}_{col.name}")
            submitted = st.form_submit_button("Create row", type="primary")
        if submitted:
            try:
                create_row(table, values, changed_by=operator)
                st.rerun()
            except WriteRejected as exc:
                _write_error(exc)
    dialog()


def _show_edit_dialog(table: str, spec, current: dict) -> None:
    pk_value = current[spec.primary_key]

    @st.dialog(f"Edit {spec.primary_key}: {pk_value}", dismissible=False)
    def dialog():
        with st.form(f"edit_{table}_{pk_value}"):
            values = {}
            for col in spec.columns:
                if not col.auto and col.name != spec.primary_key:
                    values[col.name] = _field_input(col, key=f"edit_{table}_{pk_value}_{col.name}", default=current.get(col.name))
            save, cancel = st.columns(2)
            submitted = save.form_submit_button("Save changes", type="primary")
            cancelled = cancel.form_submit_button("Cancel")
        if cancelled:
            st.session_state.pop("dc_pending_row_action", None)
            st.rerun()
        if submitted:
            try:
                update_row(table, pk_value, values, changed_by=operator)
                st.session_state.pop("dc_pending_row_action", None)
                st.rerun()
            except WriteRejected as exc:
                _write_error(exc)
    dialog()


def _show_delete_dialog(table: str, spec, current: dict) -> None:
    pk_value = current[spec.primary_key]

    @st.dialog("Delete record", dismissible=False)
    def dialog():
        st.warning(f"Delete {spec.primary_key}={pk_value}? This cannot be undone.")
        confirm, cancel = st.columns(2)
        if confirm.button("Delete", type="primary", key=f"dc_confirm_delete_{table}_{pk_value}"):
            try:
                delete_row(table, pk_value, changed_by=operator)
                st.session_state.pop("dc_pending_row_action", None)
                st.rerun()
            except WriteRejected as exc:
                _write_error(exc)
        if cancel.button("Cancel", key=f"dc_cancel_delete_{table}_{pk_value}"):
            st.session_state.pop("dc_pending_row_action", None)
            st.rerun()
    dialog()


def _field_input(col, *, key: str, default=None):
    from datetime import date as _date

    # Optional numeric fields need a way to mean "leave this unset" --
    # st.number_input always returns a number, so 0 would otherwise be
    # indistinguishable from "not provided" and would fail a min_value>0
    # check on every row that didn't set it.
    if not col.required and col.type in (int, float):
        has_value = st.checkbox(f"Set {col.display_label()}", value=default not in (None, ""), key=f"{key}_has")
        if not has_value:
            return None

    if col.enum:
        options = list(col.enum) + ([""] if not col.required else [])
        idx = options.index(default) if default in options else 0
        return st.selectbox(col.display_label(), options, index=idx, key=key) or None
    if col.type is bool:
        return st.checkbox(col.display_label(), value=bool(default) if default is not None else False, key=key)
    if col.type is int:
        return st.number_input(col.display_label(), value=int(default) if default not in (None, "") else 0, step=1, key=key)
    if col.type is float:
        return st.number_input(col.display_label(), value=float(default) if default not in (None, "") else 0.0, key=key)
    if col.type is _date:
        value = default
        if isinstance(value, str) and value:
            value = _date.fromisoformat(value)
        return st.date_input(col.display_label(), value=value or _date.today(), key=key)
    return st.text_input(col.display_label(), value=str(default) if default is not None else "", key=key)


# ---------------------------------------------------------------------------
# Screen: missing sales data (G1-4, the R11-critical one)
# ---------------------------------------------------------------------------

def screen_missing_sales() -> None:
    st.header("Missing sales data")
    st.caption(
        "The R11 loop: a thin-data SKU parks in G2's queue → this screen shows the "
        "exact missing range day by day → real rows are entered → re-run from here."
    )

    query = st.query_params
    sku = st.text_input("Product code (SKU)", value=query.get("sku", ""), key="ms_sku")
    warehouse_id = st.text_input("Warehouse", value=query.get("warehouse_id", ""), key="ms_warehouse")
    default_start = date.today() - timedelta(days=30)
    start = st.date_input("Range start", value=date.fromisoformat(query["start_date"]) if "start_date" in query else default_start, key="ms_start")
    end = st.date_input("Range end", value=date.fromisoformat(query["end_date"]) if "end_date" in query else date.today() - timedelta(days=1), key="ms_end")

    if not sku or not warehouse_id:
        st.info("Enter a SKU and warehouse (or arrive here via a park-queue deep link) to see the range.")
        return

    from tools.sales import get_daily_sales_series

    history = get_daily_sales_series(sku, warehouse_id, start, end)
    st.subheader("Day by day")
    day_rows = []
    for offset, units in enumerate(history.daily_units):
        d = start + timedelta(days=offset)
        day_rows.append({"date": d.isoformat(), "units_sold": units if units else "— missing —"})
    st.dataframe(day_rows, width="stretch", height=300)

    observed_7d = sum(1 for u in history.daily_units[-7:] if u > 0)
    observed_30d = sum(1 for u in history.daily_units if u > 0)
    st.caption(f"Non-zero observations: {observed_7d}/7 in the last 7 days, {observed_30d}/30 in the last 30 (threshold >= 3 each).")

    if not can_write:
        st.info("Enter your name in the sidebar to enter data.")
        return

    st.subheader("Bulk fill")
    bulk_units = st.number_input("Units per day for the whole range above", min_value=0, value=0, step=1, key="ms_bulk_units")
    if st.button("Backfill this range", type="primary"):
        from submission.dataops.write import create_row

        added = 0
        for offset in range((end - start).days + 1):
            d = start + timedelta(days=offset)
            try:
                create_row("sales_daily", {"sale_date": d, "sku": sku, "warehouse_id": warehouse_id, "units_sold": bulk_units}, changed_by=operator)
                added += 1
            except WriteRejected:
                pass  # already exists -- additive-safe, matches backfill_missing_sales semantics
        st.success(f"Backfilled {added} day(s).")
        st.rerun()

    st.subheader("Re-run this case")
    if st.button("Data is in — re-run this case", type="primary"):
        from submission.app import run_case

        result = run_case(sku, warehouse_id)
        st.success(f"Ran a fresh case. Status: {result.get('status')}. Open it in the agent console (port 8501).")

    st.subheader("Resolve the park record")
    resolved_by = st.text_input("Resolved by", value=operator, key="ms_resolved_by")
    resolution = st.text_input("Resolution note", key="ms_resolution")
    if st.button("Resolve this park"):
        from tools.parking import get_open_parked_items, resolve_park

        open_items = [p for p in get_open_parked_items(warehouse_id) if p.sku == sku]
        if not open_items:
            st.warning("No open park record for this SKU/warehouse.")
        else:
            resolve_park(open_items[0].park_id, resolved_by.strip() or operator, resolution.strip() or "Backfilled from data console")
            st.success("Park resolved.")


# ---------------------------------------------------------------------------
# Screen: levers, scenario picker, live statistics (G1-5)
# ---------------------------------------------------------------------------

def screen_levers() -> None:
    st.header("Levers, scenarios and live statistics")

    with st.expander("Scenario catalogue (jump to a sku/warehouse pair)"):
        for scenario in load_scenarios():
            info = scenario.get("input", {})
            st.markdown(
                f"**{scenario.get('name', scenario.get('scenario_id'))}** — "
                f"{info.get('sku', '?')} / {info.get('warehouse_id', '?')} — "
                f"expects `{scenario.get('expected_outcome', '?')}`"
            )
            st.caption(scenario.get("description", ""))

    st.subheader("Per-SKU levers")
    col1, col2 = st.columns(2)
    sku = col1.text_input("SKU", key="lev_sku")
    warehouse_id = col2.text_input("Warehouse", key="lev_wh")

    if sku and warehouse_id:
        stats = get_live_stats(sku, warehouse_id)
        st.subheader("Live statistics")
        policy = stats["policy"]
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Current position", stats["current_position"] if stats["current_position"] is not None else "—")
        if policy:
            c2.metric("Maturity", policy.maturity)
            c3.metric("Derived cover days", f"{policy.derived_cover_days:.1f}" if policy.derived_cover_days else "—")
            c4.metric("ABC / XYZ", f"{policy.abc_class or '—'}/{policy.xyz_class or '—'}")
            st.caption(
                f"μ={policy.mean_daily_demand}, σ={policy.std_daily_demand}, CV={policy.cv}, ADI={policy.adi}, "
                f"quadrant={policy.demand_quadrant}, service_level={policy.service_level}, "
                f"safety_stock={policy.safety_stock_units}, reorder_point={policy.reorder_point_units}, "
                f"confidence={policy.confidence}"
            )
        else:
            st.info("No sku_policy row yet for this pair. Recompute below once sales/stock data exists.")

        if can_write:
            st.subheader("Fabricator levers")
            from fixtures import fabricator

            lc1, lc2, lc3 = st.columns(3)
            with lc1:
                on_hand = st.number_input("Set on-hand position", min_value=0, value=0, step=1, key="lev_on_hand")
                if st.button("Apply position"):
                    fabricator.set_position(sku, warehouse_id, on_hand)
                    st.success("Position set.")
            with lc2:
                cover_days = st.number_input("Set cover days (recomputes position)", min_value=0.0, value=14.0, key="lev_cover_days")
                if st.button("Apply cover days"):
                    fabricator.set_cover_days(sku, warehouse_id, cover_days)
                    st.success("Cover days set.")
            with lc3:
                age_hours = st.number_input("Age snapshot by (hours)", min_value=0.0, value=0.0, key="lev_age")
                if st.button("Apply staleness"):
                    fabricator.age_snapshot(sku, warehouse_id, age_hours)
                    st.success("Snapshot aged.")

            if st.button("Recompute classification for this warehouse"):
                n = recompute(warehouse_id)
                st.success(f"Recomputed {n} SKU(s) for {warehouse_id}.")
                st.rerun()

    st.subheader("Policy floor")
    if can_write:
        with st.form("policy_floor_form"):
            pf_sku = st.text_input("SKU", key="pf_sku")
            pf_wh = st.text_input("Warehouse", key="pf_wh")
            pf_units = st.number_input("Minimum units (optional)", min_value=0, value=0, key="pf_units")
            pf_days = st.number_input("Minimum cover days (optional)", min_value=0.0, value=0.0, key="pf_days")
            pf_reason = st.text_area("Business reason (required)", key="pf_reason")
            submitted = st.form_submit_button("Set policy floor", type="primary")
        if submitted:
            from tools.policy_floors import set_policy_floor

            try:
                set_policy_floor(
                    pf_sku, pf_wh, min_units=pf_units or None, min_cover_days=pf_days or None,
                    reason=pf_reason, source="data_console", set_by=operator,
                )
                st.success("Policy floor set.")
            except ValueError as exc:
                st.error(str(exc))
    else:
        st.info("Enter your name in the sidebar to set a policy floor (it is an audited exception -- A4/D15).")


# ---------------------------------------------------------------------------
# Screen: change log (G1-5)
# ---------------------------------------------------------------------------

def screen_change_log() -> None:
    st.header("Change log")
    table_filter = st.selectbox("Filter by table", ["All"] + list(TABLE_SPECS.keys()), key="cl_table")
    rows = read_change_log(table=None if table_filter == "All" else table_filter)
    st.dataframe(rows, width="stretch", height=500)
    if rows:
        import json as _json

        st.download_button("Export as JSON", data=_json.dumps(rows, indent=2, default=str), file_name="data_change_log.json")


{
    "Table editor": screen_table_editor,
    "Missing sales data": screen_missing_sales,
    "Levers & scenarios": screen_levers,
    "Change log": screen_change_log,
}[view]()
