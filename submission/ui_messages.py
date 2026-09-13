"""Small, dependency-free messages shared by the operator UI and its tests."""

from __future__ import annotations


def manual_cover_warning(values: dict) -> str | None:
    """Describe the provenance of the sole legal manual numeric input."""
    if values.get("target_mode") != "MANUAL_COVER_CONFIRMED":
        return None
    provenance = str(values.get("target_provenance") or "")
    if not provenance.startswith("human:"):
        return None
    requested_by = provenance.removeprefix("human:").strip()
    if not requested_by:
        return None
    return (
        "There is not enough sales history for this product; the cover target "
        f"was set by {requested_by}, not derived from data."
    )
