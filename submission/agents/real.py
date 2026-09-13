"""
Real LLM-backed agents. Same (state, last_error) -> <output model> shape
as submission/agents/stubs.py, so nodes.set_agents() can swap either in
without touching graph/nodes.py or graph/workflow.py.

Each function builds the versioned system prompt + evidence-only user
message and calls llm.call_structured(), which handles provider dispatch
(Vertex / Gemini API key / OpenAI) and returns an already-validated
instance of the given Pydantic model. Anything that comes back wrong --
malformed JSON, a provider timeout, whatever -- surfaces as an exception
for graph/support.py's retry-once-then-fail-closed loop to catch; see
that module's docstring for why the except there is broad.
"""

from __future__ import annotations

from submission.agents.llm import call_structured
from submission.agents.models import DemandAssessment, PolicyReview, ReplenishmentRecommendation
from submission.prompts import demand, policy, strategist
from submission.state.state import CaseState


def assess_demand_llm(state: CaseState, last_error: str | None) -> DemandAssessment:
    return call_structured("demand", demand.SYSTEM, demand.build_user_message(state, last_error), DemandAssessment)


def recommend_vendor_llm(state: CaseState, last_error: str | None) -> ReplenishmentRecommendation:
    return call_structured(
        "strategist", strategist.SYSTEM, strategist.build_user_message(state, last_error), ReplenishmentRecommendation
    )


def review_policy_llm(state: CaseState, last_error: str | None) -> PolicyReview:
    return call_structured("policy", policy.SYSTEM, policy.build_user_message(state, last_error), PolicyReview)


REAL_AGENTS = {
    "assess_demand": assess_demand_llm,
    "recommend_vendor": recommend_vendor_llm,
    "review_policy": review_policy_llm,
}
