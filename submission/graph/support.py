"""
Small helpers shared by graph nodes: structured audit logging and the
validate/retry-once/fail-closed loop for agent nodes (brief: max two model
attempts, scenario 6). Kept out of LangGraph's node RetryPolicy deliberately
-- it does not reliably catch pydantic.ValidationError (see PLAN.md research
finding, langchain-ai/langgraph#6027), so this is a plain conditional loop.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, TypeVar

from pydantic import BaseModel

from tools.execution import append_audit_event
from submission.config import config
from submission.state.state import CaseState


@dataclass(frozen=True)
class TargetReconciliation:
    active_target_units: float
    basis: str
    excess_or_shortfall_units: float
    explanation: str


def reconcile_target(statistical: float, floor, mean_daily_demand: float) -> TargetReconciliation:
    """Resolve the deterministic policy-floor/statistics relationship.

    Positive excess means the floor makes the active target larger; negative
    means the statistical calculation protects more stock than the floor.
    """
    statistical = float(statistical or 0)
    floor_units = max(float(getattr(floor, "min_units", None) or 0),
                      float(getattr(floor, "min_cover_days", None) or 0) * float(mean_daily_demand or 0)) if floor else 0.0
    delta = floor_units - statistical
    if floor is None or statistical >= floor_units:
        return TargetReconciliation(statistical, "STATISTICAL", delta,
            f"The policy floor is insufficient: statistics require {statistical:.1f} units versus floor {floor_units:.1f}; at {mean_daily_demand:.1f} units/day the floor would cover only {floor_units / mean_daily_demand if mean_daily_demand else 0:.1f} days.")
    return TargetReconciliation(floor_units, "POLICY_FLOOR", delta,
        f"The policy floor requires {floor_units:.1f} units, an excess of {delta:.1f} above the statistical target of {statistical:.1f}; this is a named policy cost for human review.")

M = TypeVar("M", bound=BaseModel)


def emit_audit(state: CaseState, actor: str, event_type: str, payload: dict) -> None:
    """Structured summary only -- never chain-of-thought. Best-effort: an
    audit write failure must not crash the case; it's logged into state's
    error_detail as a breadcrumb instead."""
    try:
        append_audit_event(
            case_id=state["case_id"],
            trace_id=state["trace_id"],
            actor=actor,
            event_type=event_type,
            payload=payload,
        )
    except Exception as e:  # pragma: no cover - defensive, audit must never block the case
        state["error_detail"] = f"audit_write_failed:{event_type}:{e}"


def invoke_agent_with_retry(
    state: CaseState,
    node_name: str,
    agent_fn: Callable[[CaseState, str | None], M | dict],
    model_cls: type[M],
    validate: Callable[[M], str | None] | None = None,
) -> tuple[M | None, str | None]:
    """Call agent_fn up to config.max_model_attempts_per_agent times.
    agent_fn receives (state, last_error) so a repair attempt can see what
    went wrong. Returns (validated_output, None) on success or
    (None, last_error) once attempts are exhausted -- caller must route to
    a blocked/failed terminal, never retry a third time.

    validate is an optional second check beyond Pydantic's own type
    validation -- for output that's schema-valid but semantically wrong
    (e.g. an offer_id the agent invented instead of picking one from the
    eligible list it was given). Return an error string to trigger a
    repair attempt, same as a schema failure; return None to accept.

    Catches Exception broadly, not just pydantic.ValidationError -- a real
    LLM call can also fail with a provider timeout, a rate limit, or a
    structured-output parsing error that isn't a ValidationError subclass.
    The brief lists "tool timeout" and "invalid model output" side by side
    as failure modes needing the same bounded-retry-then-fail-closed
    handling (design.md §7), so treating them identically here is
    deliberate, not a catch-all mistake. The exception type is still
    captured in the audit trail for debugging.

    The attempt cap is per node *visit*, tracked locally -- not carried
    over in state.retry_counts, which is audit-only (how many attempts the
    most recent visit used). A node revisited later in the same case
    (e.g. after the bounded revalidation-retry bounce) gets a fresh budget;
    otherwise a node hit 3 times across a case's life would wrongly fail
    closed on attempt 3 even though every individual call had succeeded."""
    retry_counts = state.setdefault("retry_counts", {})
    attempts = 0
    last_error: str | None = None

    while attempts < config.max_model_attempts_per_agent:
        attempts += 1
        retry_counts[node_name] = attempts
        try:
            raw = agent_fn(state, last_error)
            validated = raw if isinstance(raw, model_cls) else model_cls.model_validate(raw)
            if validate is not None:
                problem = validate(validated)
                if problem is not None:
                    raise ValueError(problem)  # caught by the broad except below, same as a schema failure
            emit_audit(
                state,
                actor=f"agent:{node_name}",
                event_type=f"{node_name}_succeeded",
                payload={"attempt": attempts},
            )
            return validated, None
        except Exception as e:
            last_error = str(e)
            emit_audit(
                state,
                actor=f"agent:{node_name}",
                event_type=f"{node_name}_call_failed",
                payload={"attempt": attempts, "error_type": type(e).__name__, "error": last_error},
            )

    return None, last_error
