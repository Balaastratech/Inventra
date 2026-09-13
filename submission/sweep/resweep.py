from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ReminderAction:
    kind: str
    case_id: str
    thread_id: str
    message: str


def check_in_flight_case(sku: str, warehouse_id: str) -> ReminderAction | None:
    """Return a reminder decision; delivery itself remains a Phase D concern."""
    from submission.portfolio import list_pending_cases
    for item in list_pending_cases():
        if item.get("sku") != sku or item.get("warehouse_id") != warehouse_id:
            continue
        status = item.get("status")
        if status not in {"AWAITING_APPROVAL", "AWAITING_VENDOR_APPROVAL"}:
            return None
        if item.get("likely_stale"):
            kind = "VENDOR_SEND_REVALIDATION_NEEDED" if status == "AWAITING_VENDOR_APPROVAL" else "REVALIDATION_NEEDED"
            return ReminderAction(kind, item["case_id"], item["thread_id"], "The paused case needs re-validation before a reminder can be sent.")
        if status == "AWAITING_VENDOR_APPROVAL":
            return ReminderAction("VENDOR_SEND_REMINDER", item["case_id"], item["thread_id"], "A human must approve or reject sending the purchase order to the vendor.")
        return ReminderAction("REMINDER", item["case_id"], item["thread_id"], "A human can approve or reject the existing proposal.")
    return None
