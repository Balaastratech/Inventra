"""
Local HTTP server backing the Approve/Reject links in approval emails
(D11). Uses FastAPI + uvicorn -- both already installed in this environment
(ladder rung 5: use what's already there instead of adding a new
dependency for it).

Security shape, on purpose:
  GET  /decide  -> renders a confirmation page only. Never mutates state.
                   Safe for email clients/security scanners that prefetch
                   links -- verify_token() does not consume the token.
  POST /decide  -> the only state-changing path. Consumes the token
                   (single-use), re-checks the token's proposal_hash against
                   the graph's CURRENT proposal for that case (catches a
                   stale link from a since-revised proposal), then resumes
                   the paused thread via Command(resume=...).

Runs against the same config.checkpointer_path SqliteSaver file as the CLI,
so it can resume a thread the CLI's `run` command paused -- see
graph/workflow.py's compile_graph() docstring.
"""

from __future__ import annotations

import html
from datetime import datetime, timezone

from fastapi import FastAPI, Form
from fastapi.responses import HTMLResponse
from langgraph.types import Command

from submission.agents.wiring import wire_agents
from submission.config import config
from submission.graph.workflow import compile_graph, latest_thread_id
from submission.notifications.tokens import consume_token, verify_token

app = FastAPI(title="Inventra Approval Links")


def _thread_config(case_id: str) -> dict | None:
    """Approval tokens carry the business case_id; the checkpointer is keyed
    by per-run thread_id. Resolve to the latest run, or None if the case has
    never been run."""
    thread = latest_thread_id(case_id)
    return None if thread is None else {"configurable": {"thread_id": thread}}


def _esc(value) -> str:
    return html.escape(str(value))


def _page(title: str, body: str) -> HTMLResponse:
    return HTMLResponse(
        f"<html><head><title>{_esc(title)}</title></head>"
        f"<body style='font-family:system-ui;max-width:560px;margin:40px auto;line-height:1.5'>"
        f"<h2>{_esc(title)}</h2>{body}</body></html>"
    )


@app.get("/decide")
def confirm(token: str) -> HTMLResponse:
    result = verify_token(token)
    if not result.ok:
        return _page("Link invalid", f"<p>{_esc(result.error)}.</p>")

    payload = result.payload
    thread_config = _thread_config(payload["case_id"])
    if thread_config is None:
        return _page("Nothing to decide", "<p>This case is no longer waiting for approval.</p>")

    graph, conn = compile_graph()
    try:
        snapshot = graph.get_state(thread_config)
    finally:
        conn.close()

    if not snapshot.next:
        return _page("Nothing to decide", "<p>This case is no longer waiting for approval.</p>")

    current_proposal = snapshot.values.get("proposal")
    if current_proposal is None or current_proposal.proposal_hash != payload["proposal_hash"]:
        return _page(
            "This proposal has changed",
            "<p>The proposal was revised or facts changed since this email was sent. "
            "Open the CLI/Streamlit screen to review the current version.</p>",
        )

    is_vendor_gate = payload["decision"] in {"VENDOR_APPROVED", "VENDOR_REJECTED"}
    status = snapshot.values.get("status")
    status = status.value if hasattr(status, "value") else str(status or "")
    if is_vendor_gate != (status == "AWAITING_VENDOR_APPROVAL"):
        return _page("Nothing to decide", "<p>This approval link does not match the case's current gate.</p>")

    needs_reason = payload["decision"] in {"REVISE", "REJECTED", "VENDOR_REJECTED"}
    if needs_reason:
        action = "Request changes" if payload["decision"] == "REVISE" else "Reject vendor send" if payload["decision"] == "VENDOR_REJECTED" else "Reject"
        return _page(
            f"{action}: {payload['case_id']}",
            f"""
            <p><b>Vendor</b> {_esc(current_proposal.recommended_vendor_name)} &mdash;
               {_esc(current_proposal.quantity)} units, ${_esc(current_proposal.total_cost)}</p>
            <p>Provide a reason for this decision.</p>
            <form method="post" action="/decide">
              <input type="hidden" name="token" value="{_esc(token)}" />
              <textarea name="comments" rows="4" style="width:100%;font-family:inherit" required
                        placeholder="e.g. go with the cheaper supplier, the extra buffer isn't worth it"></textarea>
              <p><button type="submit" style="padding:8px 16px">Confirm {action}</button></p>
            </form>
            """,
        )

    return _page(
        f"Confirm: {payload['decision'].replace('VENDOR_', '')}",
        f"""
        <p><b>Case</b> {_esc(payload['case_id'])}</p>
        <p><b>Vendor</b> {_esc(current_proposal.recommended_vendor_name)} &mdash;
           {_esc(current_proposal.quantity)} units, ${_esc(current_proposal.total_cost)}</p>
        <p>Confirm <b>{_esc(payload['decision'])}</b> for approver
           <b>{_esc(payload['approver'])}</b>?</p>
        <form method="post" action="/decide">
          <input type="hidden" name="token" value="{_esc(token)}" />
          <button type="submit" style="padding:8px 16px">Confirm {_esc(payload['decision'])}</button>
        </form>
        """,
    )


@app.post("/decide")
def execute(token: str = Form(...), comments: str | None = Form(None)) -> HTMLResponse:
    wire_agents()
    result = verify_token(token)
    if not result.ok:
        return _page("Link invalid", f"<p>{_esc(result.error)}.</p>")

    payload = result.payload
    if comments is not None and len(comments) > 500:
        return _page("Reason too long", "<p>Comments must be at most 500 characters.</p>")
    if payload["decision"] in {"REJECTED", "VENDOR_REJECTED"} and not (comments or "").strip():
        return _page("Reason required", "<p>A rejection requires a reason. Use the original link and provide one.</p>")
    if not consume_token(payload["jti"]):
        return _page("Already decided", "<p>This link was already used.</p>")

    thread_config = _thread_config(payload["case_id"])
    if thread_config is None:
        return _page("Nothing to decide", "<p>This case is no longer waiting for approval.</p>")

    graph, conn = compile_graph()
    try:
        snapshot = graph.get_state(thread_config)
        if not snapshot.next:
            return _page("Nothing to decide", "<p>This case is no longer waiting for approval.</p>")

        current_proposal = snapshot.values.get("proposal")
        if current_proposal is None or current_proposal.proposal_hash != payload["proposal_hash"]:
            return _page(
                "This proposal has changed",
                "<p>The proposal was revised since this email was sent; this decision was not applied.</p>",
            )

        is_vendor_gate = payload["decision"] in {"VENDOR_APPROVED", "VENDOR_REJECTED"}
        status = snapshot.values.get("status")
        status = status.value if hasattr(status, "value") else str(status or "")
        if is_vendor_gate != (status == "AWAITING_VENDOR_APPROVAL"):
            return _page("Nothing to decide", "<p>This approval link does not match the case's current gate.</p>")
        supplied_reason = (comments or "").strip()
        if payload["decision"] in {"REJECTED", "VENDOR_REJECTED"} and not supplied_reason:
            return _page("Reason required", "<p>A rejection requires a reason. Use the original link and provide one.</p>")
        if is_vendor_gate:
            purchase_result = snapshot.values.get("purchase_result")
            if purchase_result is None:
                return _page("Nothing to decide", "<p>The purchase request is no longer available.</p>")
            decision_payload = {
                "request_id": purchase_result.request_id, "case_id": payload["case_id"],
                "decision": payload["decision"].replace("VENDOR_", ""), "approver": payload["approver"],
                "reason": supplied_reason or None, "approved_at": datetime.now(timezone.utc).isoformat(),
            }
        else:
            decision_payload = {
                "case_id": payload["case_id"], "proposal_id": current_proposal.proposal_id,
                "proposal_hash": payload["proposal_hash"], "decision": payload["decision"],
                "approver": payload["approver"],
                "comments": supplied_reason or "via email link", "approved_at": datetime.now(timezone.utc).isoformat(),
            }
        final = graph.invoke(Command(resume=decision_payload), config=thread_config)
    finally:
        conn.close()

    if "__interrupt__" in final:
        return _page("Recorded", "<p>Decision recorded. The case needs a further look -- check the CLI/Streamlit screen.</p>")

    status = final.get("status")
    return _page("Recorded", f"<p>Decision recorded. Case status: <b>{_esc(status.value if status else 'UNKNOWN')}</b>.</p>")


def main() -> None:
    import uvicorn

    uvicorn.run(app, host=config.approval_server_host, port=config.approval_server_port)


if __name__ == "__main__":
    main()
