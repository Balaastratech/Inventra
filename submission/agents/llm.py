"""
Structured-output LLM call, one function all three agents go through
regardless of provider. Provider is config.model_provider ("vertex"
default for this deployment, "gemini" AI-Studio-key and "openai" both
fully wired as fallbacks -- PLAN.md D3, no Anthropic).

Vertex uses the `google-genai` unified SDK directly (Client(vertexai=True,
...)), not langchain-google-vertexai / the legacy google-cloud-aiplatform
package -- that package imports its entire generated API surface (Vizier,
Tensorboard, Feature Store, RAG, ...) and its default gRPC transport
reliably hung for minutes in this dev sandbox even though plain
google.auth (ADC token refresh, same credentials) and gcloud both worked
fine and fast. google-genai's HTTP-based Vertex mode reached the same
project/location/credentials successfully in ~10-25s cold, confirmed by a
live call during development -- see PLAN.md D3 for the full story. If a
future langchain-google-vertexai release fixes this, swapping back is a
localized change to _call_vertex() only; nothing else in submission/
depends on how a provider is implemented internally.
"""

from __future__ import annotations

import json
import logging
import os
import time
from typing import TypeVar

from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel

from submission.config import config

M = TypeVar("M", bound=BaseModel)

# Observability (brief §5.8: capture trajectory/dependency/outcome events).
# Reads the starter's own .env.example names (LOG_LEVEL, LOG_FORMAT) rather
# than inventing new ones. Deliberately plain stdlib logging, not routed
# through config.py: this is a process-wide logging concern, not a
# business-rule value, and it needs to be configurable before config even
# loads in some setups (e.g. -c invocations).
_logger = logging.getLogger("inventra.llm")
if not _logger.handlers:
    _logger.addHandler(logging.StreamHandler())
_logger.setLevel(os.getenv("LOG_LEVEL", "INFO").upper())
_LOG_JSON = os.getenv("LOG_FORMAT", "plain").strip().lower() == "json"


def _log_call(role: str, provider: str, model_name: str, duration_s: float, ok: bool, error: str | None) -> None:
    """Structured summary only -- model name, provider, timing, success --
    never the prompt or the model's own text, matching the same
    no-private-reasoning discipline graph/support.emit_audit already
    applies to audit_events."""
    if _LOG_JSON:
        _logger.info(json.dumps({
            "event": "llm_call", "role": role, "provider": provider, "model": model_name,
            "duration_s": round(duration_s, 3), "ok": ok, "error": error,
        }))
    else:
        _logger.info(
            "llm_call role=%s provider=%s model=%s duration_s=%.3f ok=%s%s",
            role, provider, model_name, duration_s, ok, f" error={error}" if error else "",
        )


def _maybe_traceable(fn):
    """Opt-in LangSmith tracing (the starter's .env.example already ships
    LANGCHAIN_TRACING_V2 / LANGCHAIN_API_KEY / LANGCHAIN_PROJECT, unused
    until now). Only activates if both the env var is set AND the
    `langsmith` package is installed -- otherwise this is a no-op wrapper,
    so nothing here requires a LangSmith account to run the suite.

    Wrapping at this one chokepoint matters because MODEL_PROVIDER=vertex
    calls the raw google-genai SDK directly (see module docstring above),
    which LangChain's own auto-instrumentation never sees -- tracing has to
    be explicit here to cover the provider actually configured for this
    deployment, not just the langchain_openai / langchain_google_genai
    fallback paths.
    """
    if os.getenv("LANGCHAIN_TRACING_V2", "").strip().lower() not in ("1", "true", "yes"):
        return fn
    try:
        from langsmith import traceable
    except ImportError:
        _logger.warning("LANGCHAIN_TRACING_V2 is set but the `langsmith` package is not installed -- tracing skipped")
        return fn
    return traceable(name="inventra_llm_call", run_type="llm")(fn)


def _dispatch(role: str, system: str, user: str, model_cls: type[M]) -> M:
    model_name = config.active_models()[role]
    if config.model_provider == "vertex":
        return _call_vertex(model_name, system, user, model_cls)
    if config.model_provider == "openai":
        return _call_langchain("openai", model_name, system, user, model_cls)
    return _call_langchain("gemini", model_name, system, user, model_cls)


_traced_dispatch = _maybe_traceable(_dispatch)


def call_structured(role: str, system: str, user: str, model_cls: type[M]) -> M:
    model_name = config.active_models()[role]
    start = time.monotonic()
    try:
        result = _traced_dispatch(role, system, user, model_cls)
        _log_call(role, config.model_provider, model_name, time.monotonic() - start, ok=True, error=None)
        return result
    except Exception as e:
        _log_call(role, config.model_provider, model_name, time.monotonic() - start, ok=False, error=str(e))
        raise


def _call_vertex(model_name: str, system: str, user: str, model_cls: type[M]) -> M:
    from google import genai
    from google.genai import types

    if not config.gcp_project_id:
        raise RuntimeError("MODEL_PROVIDER=vertex but GCP_PROJECT_ID is not set (submission/.env)")

    # No API key: auth is Application Default Credentials (gcloud auth
    # application-default login, or GOOGLE_APPLICATION_CREDENTIALS pointing
    # at a service-account file outside this repo).
    client = genai.Client(vertexai=True, project=config.gcp_project_id, location=config.gcp_location)
    response = client.models.generate_content(
        model=model_name,
        contents=user,
        config=types.GenerateContentConfig(
            system_instruction=system,
            temperature=config.agent_temperature,
            response_mime_type="application/json",
            response_schema=model_cls,
        ),
    )
    if response.parsed is None:
        raise ValueError(f"Vertex response did not parse into {model_cls.__name__}: {response.text!r}")
    return response.parsed


def _call_langchain(provider: str, model_name: str, system: str, user: str, model_cls: type[M]) -> M:
    if provider == "openai":
        from langchain_openai import ChatOpenAI

        if not config.openai_api_key:
            raise RuntimeError("MODEL_PROVIDER=openai but OPENAI_API_KEY is not set (submission/.env)")
        model = ChatOpenAI(model=model_name, temperature=config.agent_temperature, api_key=config.openai_api_key)
    else:
        from langchain_google_genai import ChatGoogleGenerativeAI

        if not config.gemini_api_key:
            raise RuntimeError("MODEL_PROVIDER=gemini but GEMINI_API_KEY is not set (submission/.env)")
        model = ChatGoogleGenerativeAI(
            model=model_name, temperature=config.agent_temperature, google_api_key=config.gemini_api_key
        )

    structured = model.with_structured_output(model_cls)
    return structured.invoke([SystemMessage(content=system), HumanMessage(content=user)])


def is_configured() -> bool:
    """True once whichever provider is selected can actually be called --
    used by app.py to decide real agents vs. Phase 2/3 stubs without
    crashing a run that hasn't set one up yet."""
    if config.model_provider == "openai":
        return bool(config.openai_api_key)
    if config.model_provider == "vertex":
        return bool(config.gcp_project_id)  # auth is ADC, not a key -- project id is the only required setting
    return bool(config.gemini_api_key)
