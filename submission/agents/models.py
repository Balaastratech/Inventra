"""
Structured output contracts for the three LLM agents.

Each model is deliberately narrow: an agent returns its judgment call plus
the evidence IDs it relied on, never a number it invented. All authoritative
arithmetic (cost, arrival dates, the proposal hash) is computed by
deterministic code in graph/workflow.py and assembled into the existing
domain.tool_models.ReplenishmentProposal — agents never emit that model
directly, so an LLM can't hand-roll its own hash or totals.

extra="forbid" so an agent can't smuggle an untyped field past validation —
consistent with the brief's "critical outputs are Pydantic-validated" /
fail-closed requirement (scenario 6).
"""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, ConfigDict, Field, model_validator


class DemandAssessment(BaseModel):
    """Intake & Demand Interpreter's output.

    Judgment owned: which sales-velocity window (7-day vs 30-day) to trust
    when they disagree, and whether the request itself is ambiguous or
    incomplete. Never computes cover days or risk — that's calculate_stock_risk.
    """

    model_config = ConfigDict(extra="forbid")

    case_id: str
    chosen_window_days: int = Field(..., description="7 or 30 - which velocity window is trusted")
    rationale: str = Field(..., min_length=1, description="Why this window was chosen over the other")
    ambiguous: bool = Field(..., description="True if the request needs a clarifying question before proceeding")
    clarification_needed: str | None = Field(None, description="The single precise question, if ambiguous")
    evidence_ids: list[str] = Field(default_factory=list)


class SourcingStrategy(str, Enum):
    CHEAPEST = "cheapest"
    FASTEST = "fastest"
    BALANCED = "balanced"


class ReplenishmentRecommendation(BaseModel):
    """Replenishment Strategist's output.

    Judgment owned: cost vs speed vs risk-buffer trade-off among the
    deterministic, already-eligible options from build_vendor_options().
    Picks an offer_id; does not invent price, quantity, or arrival date.
    """

    model_config = ConfigDict(extra="forbid")

    case_id: str
    recommended_offer_id: str = Field(..., description="offer_id of the chosen eligible VendorOption")
    strategy: SourcingStrategy
    rationale: str = Field(..., min_length=1, description="Explains the trade-off in terms a planner can challenge")
    other_options_summary: str | None = Field(None, description="One-line summary of alternatives considered")
    evidence_ids: list[str] = Field(
        default_factory=list,
        description=(
            "The offer_id value(s) from eligible_options that this recommendation relies on -- "
            "always include recommended_offer_id, and optionally the offer_id of any alternative "
            "you compared it against. Copy these verbatim from the offer_id field in the evidence; "
            "never invent an id, and never use a sku, case_id, or made-up string here."
        ),
    )


class PolicyVerdict(str, Enum):
    PASS = "PASS"
    BLOCKED = "BLOCKED"
    EXCEPTION = "EXCEPTION"  # bounded, human still decides - see config.over_budget_exception_tolerance


class PolicyQuestion(str, Enum):
    """The 8 numbered review questions in policy.md's "Review questions"
    section, made addressable one at a time instead of folded into a single
    free-text verdict. See POLICY_QUESTION_TEXT for the question wording and
    graph/nodes.py::review_policy for which of these get a code-computed
    override regardless of what the agent answers."""

    FRESHNESS = "freshness"
    AT_RISK = "at_risk"
    SALES_SUFFICIENCY = "sales_sufficiency"
    VENDOR_VALIDITY = "vendor_validity"
    TRADEOFF_EXPLAINED = "tradeoff_explained"
    ARRIVAL_BEATS_STOCKOUT = "arrival_beats_stockout"
    BUDGET_FIT = "budget_fit"
    EVIDENCE_TRACEABLE = "evidence_traceable"
    POLICY_FLOOR = "policy_floor"


# policy.md's exact question wording, so the agent, the node's override
# rationale, and the UI all cite the same source rather than three
# paraphrases drifting apart over time.
POLICY_QUESTION_TEXT: dict[PolicyQuestion, str] = {
    PolicyQuestion.FRESHNESS: "Is the inventory snapshot still fresh enough to trust?",
    PolicyQuestion.AT_RISK: "Is the SKU actually at risk?",
    PolicyQuestion.SALES_SUFFICIENCY: "Is the sales evidence sufficient?",
    PolicyQuestion.VENDOR_VALIDITY: "Are there any valid vendor options?",
    PolicyQuestion.TRADEOFF_EXPLAINED: "Which tradeoff is being made?",
    PolicyQuestion.ARRIVAL_BEATS_STOCKOUT: "Does the proposed arrival beat the projected stockout date?",
    PolicyQuestion.BUDGET_FIT: "Does the proposed cost fit the remaining monthly budget?",
    PolicyQuestion.EVIDENCE_TRACEABLE: "Is the proposal grounded in evidence IDs?",
    PolicyQuestion.POLICY_FLOOR: "Does the proposal respect the active policy floor?",
}


class ChecklistVerdict(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"
    NA = "NA"  # question does not apply to this proposal


class PolicyChecklistItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    question: PolicyQuestion
    verdict: ChecklistVerdict
    rationale: str = Field(..., min_length=1, description="Why this specific question got this verdict")


class PolicyReview(BaseModel):
    """Policy Reviewer's output.

    Judgment owned: reading policy.md guidance alongside the evidence bundle
    and deciding whether a concern is a hard block or a labelled exception.
    Independent second opinion on the Strategist's proposal — cannot edit it,
    only verdict + concerns.

    checklist replaces a single blended verdict with one row per policy.md
    review question (schema-enforced: exactly the 8 PolicyQuestion members,
    no duplicates, none omitted -- see the model_validator below), so a
    question can no longer be silently skipped by the model or hidden inside
    a paragraph. graph/nodes.py::review_policy then code-overrides every row
    that's mechanically checkable (freshness, at-risk, sales sufficiency,
    vendor validity, arrival-vs-stockout, budget fit, evidence traceability)
    regardless of what the agent answered -- only tradeoff_explained is left
    as the agent's own judgment, because "which tradeoff is being made" is a
    narrative call, not a fact with a deterministic right answer.
    """

    model_config = ConfigDict(extra="forbid")

    case_id: str
    proposal_id: str
    verdict: PolicyVerdict
    checklist: list[PolicyChecklistItem] = Field(
        ..., min_length=9, max_length=9, description="One entry per PolicyQuestion, in any order"
    )
    concerns: list[str] = Field(default_factory=list)
    rationale: str = Field(..., min_length=1)
    evidence_ids: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _checklist_covers_every_question_exactly_once(self) -> "PolicyReview":
        seen = [item.question for item in self.checklist]
        if set(seen) != set(PolicyQuestion) or len(seen) != len(set(seen)):
            missing = set(PolicyQuestion) - set(seen)
            duplicated = {q for q in seen if seen.count(q) > 1}
            problems = []
            if missing:
                problems.append(f"missing {sorted(q.value for q in missing)}")
            if duplicated:
                problems.append(f"duplicated {sorted(q.value for q in duplicated)}")
            raise ValueError(f"checklist must cover every policy question exactly once: {'; '.join(problems)}")
        return self
