"""
Policy Tools
Read-only budget lookup plus policy-document access.
"""

import logging
import sqlite3
from pathlib import Path
from datetime import datetime
from typing import Optional
from domain.tool_models import (
    BudgetPosition,
    PolicyGuidance,
    PolicyGuidanceInput,
    ErrorCode,
)

logger = logging.getLogger(__name__)

# Tripwire, not a fix: policy.md is read whole into one prompt (no chunking,
# no retrieval). That's the right-sized approach while the doc is short, but
# it degrades silently if the doc grows -- this just makes that growth
# visible. If it ever fires, chunking/retrieval becomes a real follow-up
# task, not something built speculatively now. ~20k chars is a generous
# multiple of policy.md's current size (~3.5KB), chosen to warn well before
# a single prompt could plausibly start dropping rules.
_POLICY_LENGTH_WARNING_CHARS = 20_000


def _get_db_connection(db_path: str | None = None):
    """Get database connection."""
    if db_path is None:
        from submission.config import config
        db_path = config.database_path
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def get_budget_position(
    warehouse_id: str,
    budget_month: str  # YYYY-MM format
) -> BudgetPosition:
    """
    Get the latest budget position for a warehouse and month.
    
    Calculates remaining = budget - spent - committed.
    
    Args:
        warehouse_id: Warehouse identifier
        budget_month: Month in YYYY-MM format
    
    Returns:
        BudgetPosition with current spending and available budget
    """
    try:
        conn = _get_db_connection()
        cursor = conn.cursor()
        
        cursor.execute(
            """
            SELECT budget_id, warehouse_id, month, budget_amount, 
                   spent_amount, committed_amount
            FROM monthly_budgets
            WHERE warehouse_id = ? AND month = ?
            """,
            (warehouse_id, budget_month)
        )
        row = cursor.fetchone()
        conn.close()
        
        if not row:
            return BudgetPosition(
                warehouse_id=warehouse_id,
                month=budget_month,
                budget_amount=0,
                spent_amount=0,
                committed_amount=0,
                remaining=0,
                retrieved_at=datetime.utcnow(),
                evidence_id="",
                error=ErrorCode.NOT_FOUND,
            )
        
        remaining = (
            row["budget_amount"] - 
            row["spent_amount"] - 
            row["committed_amount"]
        )
        
        return BudgetPosition(
            warehouse_id=row["warehouse_id"],
            month=row["month"],
            budget_amount=row["budget_amount"],
            spent_amount=row["spent_amount"],
            committed_amount=row["committed_amount"],
            remaining=remaining,
            retrieved_at=datetime.utcnow(),
            evidence_id=f"budget:{warehouse_id}:{budget_month}",
        )
    except Exception as e:
        return BudgetPosition(
            warehouse_id=warehouse_id,
            month=budget_month,
            budget_amount=0,
            spent_amount=0,
            committed_amount=0,
            remaining=0,
            retrieved_at=datetime.utcnow(),
            evidence_id="",
            error=ErrorCode.UNKNOWN_ERROR,
        )


def get_policy_guidance(
    sku: str,
    warehouse_id: str,
    target_cover_days: int,
    policy_path: str = "policy.md",
) -> PolicyGuidance:
    """Load the narrative policy guidance that the agent should use for review."""
    path = Path(policy_path)
    text = path.read_text()
    if len(text) > _POLICY_LENGTH_WARNING_CHARS:
        logger.warning(
            "%s is %d characters, over the %d-character tripwire -- a single flat prompt read "
            "may start silently missing rules; consider chunking/retrieval instead of growing "
            "this further.",
            path, len(text), _POLICY_LENGTH_WARNING_CHARS,
        )
    summary = (
        f"Use this policy to review SKU {sku} at warehouse {warehouse_id} "
        f"for target cover {target_cover_days} days. Treat tool outputs as authoritative evidence."
    )
    return PolicyGuidance(
        policy_version="2026-08-30",
        source_path=str(path),
        summary=summary,
        policy_text=text,
        retrieved_at=datetime.utcnow(),
    )
