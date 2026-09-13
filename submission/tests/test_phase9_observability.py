"""
A7 proof: agents/llm.call_structured is the one chokepoint every agent call
goes through regardless of provider (vertex/gemini/openai), so instrumenting
it once gives trajectory/dependency/outcome observability everywhere --
including the vertex path, which calls the raw google-genai SDK directly
and would otherwise be invisible to LangChain's own auto-tracing.

Verifies: (1) every call logs a structured summary with no prompt content,
(2) LangSmith tracing stays a true no-op unless LANGCHAIN_TRACING_V2 is set,
(3) a missing `langsmith` package degrades to a plain function, never a
crash -- nobody should need a LangSmith account to run this suite.
"""

from __future__ import annotations

import logging

import pytest
from pydantic import BaseModel

import submission.agents.llm as llm_module


class _Echo(BaseModel):
    value: str


def test_call_structured_logs_a_structured_summary_without_prompt_content(monkeypatch, caplog):
    monkeypatch.setattr(llm_module, "_traced_dispatch", lambda role, system, user, model_cls: _Echo(value="ok"))

    with caplog.at_level(logging.INFO, logger="inventra.llm"):
        result = llm_module.call_structured("demand", "SECRET SYSTEM PROMPT", "SECRET USER EVIDENCE", _Echo)

    assert result.value == "ok"
    messages = [r.message for r in caplog.records]
    assert any("llm_call" in m and "role=demand" in m for m in messages)
    assert not any("SECRET" in m for m in messages), "prompt/evidence content must never reach the log"


def test_call_structured_logs_failure_and_reraises(monkeypatch, caplog):
    def _boom(role, system, user, model_cls):
        raise ValueError("simulated provider timeout")

    monkeypatch.setattr(llm_module, "_traced_dispatch", _boom)

    with caplog.at_level(logging.INFO, logger="inventra.llm"):
        with pytest.raises(ValueError):
            llm_module.call_structured("policy", "sys", "usr", _Echo)

    messages = [r.message for r in caplog.records]
    assert any("ok=False" in m and "simulated provider timeout" in m for m in messages)


def test_tracing_wrapper_is_a_no_op_without_the_env_var(monkeypatch):
    monkeypatch.delenv("LANGCHAIN_TRACING_V2", raising=False)

    def _plain(x):
        return x * 2

    wrapped = llm_module._maybe_traceable(_plain)
    assert wrapped is _plain, "must not wrap at all when tracing is off -- zero overhead, zero surprise imports"


def test_tracing_wrapper_degrades_gracefully_without_langsmith_installed(monkeypatch):
    import builtins

    monkeypatch.setenv("LANGCHAIN_TRACING_V2", "true")
    real_import = builtins.__import__

    def _no_langsmith(name, *args, **kwargs):
        if name == "langsmith":
            raise ImportError("simulated: langsmith not installed")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", _no_langsmith)

    def _plain(x):
        return x + 1

    wrapped = llm_module._maybe_traceable(_plain)
    assert wrapped(1) == 2, "must fall back to the plain function, never crash, when langsmith is unavailable"
