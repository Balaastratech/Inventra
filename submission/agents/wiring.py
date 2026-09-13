"""One-time agent wiring shared by every entry point (CLI, approval_server)
that can invoke the graph. Real LLM agents if a key is configured for
config.model_provider, otherwise the Phase 2/3 stubs -- so any entry point
runs out of the box instead of crashing on a missing key."""

from __future__ import annotations

import sys

_WIRED = False


def wire_agents() -> None:
    global _WIRED
    if _WIRED:
        return
    from submission.agents.llm import is_configured
    from submission.graph import nodes

    if is_configured():
        from submission.agents.real import REAL_AGENTS

        nodes.set_agents(**REAL_AGENTS)
    else:
        from submission.config import config

        print(
            f"[warn] no API key set for MODEL_PROVIDER={config.model_provider!r} "
            f"(submission/.env) -- running with Phase 2/3 stub agents, not real judgment.",
            file=sys.stderr,
        )
    _WIRED = True
