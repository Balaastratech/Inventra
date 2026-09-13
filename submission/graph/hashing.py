"""Shared proposal-hash computation, used by both draft_proposal (nodes.py)
and revalidate_proposal (revalidation.py) so they can never drift apart.
Mirrors tools/execution.py's _hash_proposal field set (content only, no
IDs/timestamps) but is submission-owned since tools/execution.py's version
is unused (see revalidation.py docstring)."""

from __future__ import annotations

import hashlib


def compute_proposal_hash(fields: dict) -> str:
    key_parts = [
        str(fields["sku"]),
        str(fields["warehouse_id"]),
        str(fields["quantity"]),
        str(fields["unit_price"]),
        str(fields["recommended_vendor_id"]),
        str(fields["target_cover_days"]),
    ]
    return hashlib.sha256("|".join(key_parts).encode()).hexdigest()


def hash_fields_from_proposal(proposal) -> dict:
    return {
        "sku": proposal.sku,
        "warehouse_id": proposal.warehouse_id,
        "quantity": proposal.quantity,
        "unit_price": proposal.unit_price,
        "recommended_vendor_id": proposal.recommended_vendor_id,
        "target_cover_days": proposal.target_cover_days,
    }
