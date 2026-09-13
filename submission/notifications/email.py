"""
Gmail SMTP notifications (stdlib smtplib + App Password, no OAuth). Called
only from deterministic graph nodes -- never an LLM-callable tool, same
boundary as append_audit_event / create_purchase_request.

If EMAIL_ENABLED is false (default) every function here is a no-op, so
Phase 2/3 tests don't need real credentials.
"""

from __future__ import annotations

import html
import hashlib
import json
import logging
import re
import sqlite3
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from submission.config import config
from submission.notifications.tokens import make_token
from submission.state.state import CaseState

_logger = logging.getLogger("inventra.email")


def _notification_fingerprint(context: dict) -> str:
    payload = json.dumps(context, sort_keys=True, default=str, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _claim_lifecycle_notification(state: CaseState, event_type: str, context: dict) -> bool:
    """Reserve one operator email for one unchanged lifecycle event.

    A monitor sweep is deliberately repetitive; an operator notification is
    not.  This small durable ledger suppresses an identical BLOCKED (or
    NEEDS_INFORMATION) email for the same business case, even after the
    monitor process or Streamlit page is restarted.  A materially different
    blocker has a different fingerprint and is allowed through.
    """
    fingerprint = _notification_fingerprint(context)
    try:
        conn = sqlite3.connect(config.database_path, timeout=10)
        try:
            conn.execute(
                """CREATE TABLE IF NOT EXISTS notification_deliveries (
                    case_id TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    fingerprint TEXT NOT NULL,
                    sent_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (case_id, event_type, fingerprint)
                )"""
            )
            conn.execute("BEGIN IMMEDIATE")
            try:
                conn.execute(
                    "INSERT INTO notification_deliveries (case_id, event_type, fingerprint) VALUES (?, ?, ?)",
                    (state["case_id"], event_type, fingerprint),
                )
            except sqlite3.IntegrityError:
                conn.rollback()
                return False
            conn.commit()
            return True
        finally:
            conn.close()
    except sqlite3.Error as exc:  # email must never make the workflow fail
        _logger.warning("Could not record notification delivery; suppressing duplicate-prone email: %s", exc)
        return False


def _release_lifecycle_notification(state: CaseState, event_type: str, context: dict) -> None:
    """Allow the next monitor cycle to retry if SMTP did not accept the email."""
    try:
        with sqlite3.connect(config.database_path, timeout=10) as conn:
            conn.execute(
                "DELETE FROM notification_deliveries WHERE case_id=? AND event_type=? AND fingerprint=?",
                (state["case_id"], event_type, _notification_fingerprint(context)),
            )
    except sqlite3.Error as exc:  # no notification bookkeeping may fail a case
        _logger.warning("Could not release failed notification reservation: %s", exc)


def _esc(value) -> str:
    return html.escape(str(value))


def _money(value) -> str:
    try:
        return f"${float(value):,.2f}"
    except (TypeError, ValueError):
        return "-"


def _date(value) -> str:
    try:
        return value.strftime("%d %b %Y, %H:%M UTC")
    except AttributeError:
        return "-" if value is None else str(value)


# Every notify_* function below hands send_email an HTML *fragment* (a
# couple of tags, no <html>/<head>/<body>). Sending that fragment as the
# entire message -- no wrapper, no charset, no plain-text alternative --
# is what actually broke readability in practice: a client that can't or
# won't render a bare, doctype-less text/html part (several corporate
# scanners and some mobile mail apps) falls back to showing the raw tags
# as literal text. Fixed by (1) wrapping every fragment in one real,
# consistently-branded HTML document with an explicit charset, and (2)
# always sending multipart/alternative with a real plain-text part
# alongside it, so a client that skips HTML entirely still shows readable
# text instead of markup soup.
def _wrap_html(inner: str) -> str:
    return f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Inventra</title>
</head>
<body style="margin:0;padding:0;background:#f4f5f7;font-family:-apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif;color:#1a1a1a">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="padding:24px 12px">
<tr><td align="center">
<table role="presentation" width="100%" style="max-width:600px;background:#ffffff;border-radius:8px;overflow:hidden;border:1px solid #e5e7eb">
<tr><td style="background:#111827;padding:16px 24px">
<span style="color:#ffffff;font-size:14px;font-weight:600;letter-spacing:0.3px">INVENTRA &middot; Automated Replenishment</span>
</td></tr>
<tr><td style="padding:24px 24px 8px 24px;font-size:14px;line-height:1.5">
{inner}
</td></tr>
<tr><td style="padding:16px 24px;background:#f9fafb;border-top:1px solid #e5e7eb">
<p style="margin:0;color:#9ca3af;font-size:11px">Automated message from the Inventra replenishment agent. Do not reply to this address.</p>
</td></tr>
</table>
</td></tr>
</table>
</body>
</html>"""


_TAG_BREAK = re.compile(r"</(p|tr|h[1-6]|div|table)>", re.IGNORECASE)
_BR = re.compile(r"<br\s*/?>", re.IGNORECASE)
_TAG = re.compile(r"<[^>]+>")
_BLANK_RUN = re.compile(r"\n{3,}")


def _html_to_text(fragment: str) -> str:
    """Best-effort plain-text rendering of the same fragment, for the
    multipart/alternative text/plain part -- never the only thing we send,
    but required so a client that ignores the HTML part still shows
    something a human can read instead of nothing or raw tags."""
    text = _BR.sub("\n", fragment)
    text = _TAG_BREAK.sub("\n", text)
    text = _TAG.sub("", text)
    text = html.unescape(text)
    text = re.sub(r"[ \t]+", " ", text)
    text = _BLANK_RUN.sub("\n\n", text)
    return text.strip()


def send_email(subject: str, html_fragment: str) -> bool:
    """Best-effort: a notification failure must never crash the case it's
    reporting on, any more than an audit-write failure does (see
    graph/support.emit_audit's docstring for the same discipline). This is
    not hypothetical -- a live run hit Gmail's daily sending limit
    (SMTPDataError 550) mid-case, and because this function used to let
    that exception propagate, it took the entire graph.invoke() down with
    it: a BLOCKED case never even finished writing its own audit record
    because the notification about it failed to send. Every caller here
    already treats email as fire-and-forget (none check the return value
    for control flow), so logging and returning False is the correct
    failure mode, not a workaround."""
    if not config.email_enabled:
        return False
    if not (config.gmail_address and config.gmail_app_password and config.email_to):
        _logger.warning(
            "EMAIL_ENABLED=true but GMAIL_ADDRESS/GMAIL_APP_PASSWORD/EMAIL_TO not fully set -- skipping send: %s",
            subject,
        )
        return False

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = config.gmail_address
    msg["To"] = config.email_to
    # Plain-text part first, HTML second: RFC 2046 says the LAST part in a
    # multipart/alternative is the preferred one a capable client renders,
    # with earlier parts as fallback for clients that can't.
    msg.attach(MIMEText(_html_to_text(html_fragment), "plain", "utf-8"))
    msg.attach(MIMEText(_wrap_html(html_fragment), "html", "utf-8"))

    try:
        with smtplib.SMTP(config.smtp_host, config.smtp_port) as server:
            server.starttls()
            server.login(config.gmail_address, config.gmail_app_password)
            server.sendmail(config.gmail_address, [config.email_to], msg.as_string())
        return True
    except Exception as e:
        _logger.warning("Email send failed, continuing without notifying (%s): %s", subject, e)
        return False


def notify_awaiting_approval(state: CaseState) -> None:
    if not config.email_enabled:
        return
    proposal = state["proposal"]
    approver = config.email_to or "unspecified-approver"
    approve_url = f"{config.approval_base_url}/decide?token=" + make_token(
        state["case_id"], proposal.proposal_hash, "APPROVED", approver
    )
    revise_url = f"{config.approval_base_url}/decide?token=" + make_token(
        state["case_id"], proposal.proposal_hash, "REVISE", approver
    )
    reject_url = f"{config.approval_base_url}/decide?token=" + make_token(
        state["case_id"], proposal.proposal_hash, "REJECTED", approver
    )
    concerns = ", ".join(proposal.policy_violations) or "none"
    rows = [
        ("SKU", f"{_esc(proposal.sku)} @ {_esc(proposal.warehouse_id)}"),
        ("Vendor", _esc(proposal.recommended_vendor_name)),
        ("Quantity", f"{_esc(proposal.quantity)} units"),
        ("Unit price", _esc(_money(proposal.unit_price))),
        ("Total cost", _esc(_money(proposal.total_cost))),
        ("Expected arrival", _esc(_date(proposal.expected_arrival))),
        ("Projected stockout", _esc(_date(proposal.projected_stockout_date))),
        ("Trade-off", _esc(proposal.cost_vs_speed_trade_off or "-")),
        ("Policy concerns", _esc(concerns)),
        ("Proposal hash", f"<code>{_esc(proposal.proposal_hash)}</code>"),
    ]
    table_rows = "".join(
        f'<tr><td style="padding:6px 16px 6px 0;color:#666;white-space:nowrap;border-bottom:1px solid #f0f0f0">{label}</td>'
        f'<td style="padding:6px 0;border-bottom:1px solid #f0f0f0">{value}</td></tr>'
        for label, value in rows
    )
    body = f"""
    <h2 style="margin:0 0 16px 0;font-size:18px">Approval needed &mdash; {_esc(state['case_id'])}</h2>
    <table role="presentation" width="100%" style="border-collapse:collapse;font-size:14px">{table_rows}</table>
    <p style="margin:20px 0 0 0">
      <a href="{approve_url}" style="display:inline-block;padding:10px 18px;background:#1a7f37;color:#fff;text-decoration:none;border-radius:4px;font-weight:600">APPROVE</a>
      &nbsp;&nbsp;
      <a href="{revise_url}" style="display:inline-block;padding:10px 18px;background:#a15c00;color:#fff;text-decoration:none;border-radius:4px;font-weight:600">REQUEST CHANGES</a>
      &nbsp;&nbsp;
      <a href="{reject_url}" style="display:inline-block;padding:10px 18px;background:#b91c1c;color:#fff;text-decoration:none;border-radius:4px;font-weight:600">REJECT</a>
    </p>
    <p style="color:#888;font-size:12px;margin-top:16px">
      Links expire in {config.approval_token_ttl_minutes} minutes and work once each.
      Clicking opens a confirmation page &mdash; nothing is decided until you confirm there.
      You can also decide from the CLI or Streamlit screen; whichever happens first wins.
    </p>
    """
    subject = (
        f"[Inventra] Approval needed: {proposal.sku}/{proposal.warehouse_id} "
        f"— {proposal.recommended_vendor_name}, {_money(proposal.total_cost)}"
    )
    send_email(subject, body)


def notify_vendor_approval_needed(state: CaseState) -> None:
    """Ask the internal approver to authorize sending an already-created PO."""
    if not config.email_enabled:
        return
    proposal, result = state["proposal"], state["purchase_result"]
    approver = config.email_to or "unspecified-approver"
    approve_url = f"{config.approval_base_url}/decide?token=" + make_token(
        state["case_id"], proposal.proposal_hash, "VENDOR_APPROVED", approver
    )
    reject_url = f"{config.approval_base_url}/decide?token=" + make_token(
        state["case_id"], proposal.proposal_hash, "VENDOR_REJECTED", approver
    )
    body = f"""
    <h2 style="margin:0 0 16px 0;font-size:18px">Approve sending purchase order &mdash; {_esc(state['case_id'])}</h2>
    <p>Purchase request <b>{_esc(result.request_id)}</b> is reserved internally but has not been sent to the vendor.</p>
    <table role="presentation" style="border-collapse:collapse;font-size:14px">
      <tr><td style="padding:6px 16px 6px 0;color:#666">Vendor</td><td style="padding:6px 0">{_esc(proposal.recommended_vendor_name)}</td></tr>
      <tr><td style="padding:6px 16px 6px 0;color:#666">Quantity</td><td style="padding:6px 0">{_esc(proposal.quantity)} units</td></tr>
      <tr><td style="padding:6px 16px 6px 0;color:#666">Total</td><td style="padding:6px 0">{_esc(_money(proposal.total_cost))}</td></tr>
    </table>
    <p style="margin-top:20px">
      <a href="{approve_url}" style="display:inline-block;padding:10px 18px;background:#1a7f37;color:#fff;text-decoration:none;border-radius:4px;font-weight:600">APPROVE SEND</a>
      &nbsp;&nbsp;
      <a href="{reject_url}" style="display:inline-block;padding:10px 18px;background:#b91c1c;color:#fff;text-decoration:none;border-radius:4px;font-weight:600">REJECT SEND</a>
    </p>
    """
    subject = (
        f"[Inventra] Vendor-send approval needed: {proposal.sku}/{proposal.warehouse_id} "
        f"— {proposal.recommended_vendor_name}, {_money(proposal.total_cost)}"
    )
    send_email(subject, body)


def notify_vendor_approval_reminder(state: CaseState, reminder_count: int) -> None:
    if not config.email_enabled:
        return
    result = state["purchase_result"]
    body = (
        f'<h2 style="margin:0 0 16px 0;font-size:18px">Vendor-send approval reminder #{reminder_count}</h2>'
        f"<p>Purchase request <b>{_esc(result.request_id)}</b> is still waiting for approval to send to the vendor.</p>"
    )
    send_email(f"[Inventra] Reminder #{reminder_count}: vendor-send approval needed — {result.request_id}", body)


def _revalidation_failure_reason(revalidation) -> str:
    """Gap 7: the approver acted in good faith; tell them specifically what
    changed since they approved, not a generic blocked notice. Checked in
    the same priority order route_after_revalidation uses (structural /
    budget first, since those are the unrecoverable ones)."""
    if not revalidation.hash_matches:
        return "The proposal no longer matches what you approved -- it was revised or superseded."
    if not revalidation.budget_valid:
        return "The remaining budget dropped below the approved cost after you approved this."
    if not revalidation.stock_valid:
        return "The stock snapshot is no longer fresh enough to trust."
    if not revalidation.offer_valid:
        return "The supplier's offer changed price, or is no longer valid."
    return revalidation.error_details or "The underlying facts changed after you approved this."


def notify_blocked(state: CaseState) -> None:
    if not config.email_enabled:
        return
    context = {
        "error_code": str(state.get("error_code") or ""),
        "error_detail": state.get("error_detail") or "",
        "vendor_rejection_detail": state.get("vendor_rejection_detail") or {},
        "revalidation": str(state.get("revalidation") or ""),
    }
    if not _claim_lifecycle_notification(state, "BLOCKED", context):
        return
    approval_note = ""
    revalidation = state.get("revalidation")
    if revalidation is not None and not revalidation.all_checks_pass:
        approval_note = (
            "<p><b>Your approval could not be honored.</b> "
            f"{_esc(_revalidation_failure_reason(revalidation))}</p>"
        )
    detail_html = approval_note
    rejection = state.get("vendor_rejection_detail")
    if rejection:
        rows = "".join(
            f"<tr><td style=\"padding:4px 12px 4px 0\">{_esc(o['vendor_name'])}</td><td style=\"padding:4px 12px 4px 0\">{_esc(o['offer_id'])}</td>"
            f"<td style=\"padding:4px 12px 4px 0\">{'yes' if o['meets_deadline'] else 'no'}</td>"
            f"<td style=\"padding:4px 12px 4px 0\">{'yes' if o['reliable'] else 'no'}</td>"
            f"<td style=\"padding:4px 0\">{_esc('; '.join(o['reasons']) or '-')}</td></tr>"
            for o in rejection["considered"]
        )
        detail_html += (
            '<table role="presentation" border="1" cellpadding="4" style="border-collapse:collapse;font-size:13px;margin-top:8px">'
            "<tr><th>Vendor</th><th>Offer</th><th>Meets deadline</th><th>Reliable</th>"
            "<th>Why rejected</th></tr>"
            f"{rows}</table>"
            f"<p style=\"font-size:13px;color:#666\">Also excluded: {_esc(rejection['expired_count'])} expired offer(s), "
            f"{_esc(rejection['inactive_count'])} from inactive vendor(s).</p>"
        )
    body = (
        f'<h2 style="margin:0 0 16px 0;font-size:18px;color:#b91c1c">Case blocked &mdash; {_esc(state["case_id"])}</h2>'
        f"<p><b>{_esc(state.get('error_code'))}</b>: {_esc(state.get('error_detail'))}</p>"
        f"{detail_html}"
    )
    sku = state.get("sku")
    warehouse_id = state.get("warehouse_id")
    subject_suffix = f": {sku}/{warehouse_id}" if sku and warehouse_id else f": {state['case_id']}"
    if not send_email(f"[Inventra] Blocked{subject_suffix}", body):
        _release_lifecycle_notification(state, "BLOCKED", context)


def notify_needs_information(state: CaseState) -> None:
    if not config.email_enabled:
        return
    context = {"detail": state.get("error_detail") or ""}
    if not _claim_lifecycle_notification(state, "NEEDS_INFORMATION", context):
        return
    body = (
        f'<h2 style="margin:0 0 16px 0;font-size:18px;color:#a15c00">More information needed &mdash; {_esc(state["case_id"])}</h2>'
        f"<p>{_esc(state.get('error_detail'))}</p>"
        f'<p style="color:#888;font-size:12px">Provide the corrected details from the CLI or '
        f"Streamlit screen to continue this exact case &mdash; nothing has been lost.</p>"
    )
    if not send_email(f"[Inventra] More information needed: {state['case_id']}", body):
        _release_lifecycle_notification(state, "NEEDS_INFORMATION", context)


def notify_no_action(state: CaseState) -> None:
    """Healthy scans are sweep history, never interrupting email alerts.

    The monitor can run indefinitely.  Sending an email for every healthy
    scan trains an operator to ignore the inbox and hides the approvals that
    actually need attention.
    """
    return


def notify_outcome(state: CaseState) -> None:
    if not config.email_enabled:
        return
    result = state.get("purchase_result")
    if result is None:
        return
    if result.error is None:
        body = (
            f'<h2 style="margin:0 0 16px 0;font-size:18px;color:#1a7f37">Purchase request created &mdash; {_esc(state["case_id"])}</h2>'
            f"<p><b>{_esc(result.request_id)}</b>, total {_esc(_money(result.total_cost))}</p>"
        )
        send_email(f"[Inventra] Purchase request created: {result.request_id} — {_money(result.total_cost)}", body)
    else:
        body = (
            f'<h2 style="margin:0 0 16px 0;font-size:18px;color:#b91c1c">Write failed &mdash; {_esc(state["case_id"])}</h2>'
            f"<p>{_esc(result.error)} {_esc(result.error_details or '')}</p>"
        )
        send_email(f"[Inventra] Write failed: {state['case_id']}", body)
