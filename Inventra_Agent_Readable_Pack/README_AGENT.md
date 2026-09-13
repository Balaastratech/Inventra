# Inventra Agent-Readable Pack

This folder converts the 8 supplied Inventra files into formats that are easier for LLM agents, coding agents, RAG pipelines, and automation workflows to read reliably.

## Recommended format strategy

- **Markdown (`.md`) is the primary format.** It preserves headings, tables, code, rules, and narrative while remaining token-efficient and easy for agents to quote/search.
- **JSON is used as an index/knowledge manifest**, not as a replacement for long prose. Large prose-only JSON is harder to read and wastes tokens with repeated keys/escaping.
- Mermaid blocks are used for graph/flow documents so an agent can understand topology as text instead of depending on an image.

## Files

1. `01_the_reorder_journey.md` - plain-English stakeholder view.
2. `02_investigator_agent_interface.md` - Investigator input/output and guardrail contract.
3. `03_sourcing_agent_interface.md` - Sourcing tool chain, output states, and handoff.
4. `04_policy_proposal_agent_interface.md` - Policy/Proposal budget guardrail and approval handoff.
5. `05_inventra_case_flow.md` - architecture overview and end-to-end workflow.
6. `06_inventra_case_graph.md` - deterministic graph, nodes, write boundary, state.
7. `07_inventra_student_design_challenge.md` - converted original requirements brief.
8. `08_inventra_technical_review.md` - converted implementation/review slide deck.
9. `INVENTRA_AGENT_CONTEXT.md` - compact cross-document context for loading into an agent.
10. `inventra_knowledge_manifest.json` - machine-readable index, rules, tools, statuses, and source priority.

## Source priority for an agent

When documents disagree, use this order depending on the question:

### Requirements / what the challenge requires
1. `07_inventra_student_design_challenge.md`

### What was implemented / latest supplied implementation snapshot
1. `08_inventra_technical_review.md`
2. `06_inventra_case_graph.md`
3. `02_investigator_agent_interface.md`
4. `03_sourcing_agent_interface.md`
5. `04_policy_proposal_agent_interface.md`

### Architecture explanation
1. `06_inventra_case_graph.md`
2. `05_inventra_case_flow.md`

### Non-technical explanation
1. `01_the_reorder_journey.md`

## Known source inconsistencies / chronology

- `05_inventra_case_flow.md` labels Sourcing and Policy/Proposal as **PLANNED**. The later dedicated interface documents label them **Built & tested**.
- The Case Flow snapshot says the invalid-output repair/fail-closed scenario is "not yet implemented." The Technical Review says all three agents are wired with retry-once-then-fail-closed, but its Next Steps slide still says Scenario 6 is not yet wired. Treat this as an implementation-status ambiguity that should be verified against code/tests if code is available.
- The Technical Review says cases end in four terminal states, while other material discusses `AWAITING_APPROVAL`. Best interpretation from the graph: `AWAITING_APPROVAL` is a paused workflow status, not a terminal outcome.
- Some PDF pages were exported from horizontally scrollable browser artifacts. Their far-right table cells are physically clipped in the PDFs. The conversions explicitly flag those limitations rather than inventing hidden text.

## Suggested agent prompt

You can load `INVENTRA_AGENT_CONTEXT.md` first and tell an agent:

> Use the Inventra Agent-Readable Pack as the source of truth. For requirements, prioritize the Student Design Challenge. For implementation status, prioritize the Technical Review and dedicated agent/graph interface files. Do not infer missing fields from clipped PDF exports. Distinguish deterministic tool outputs from LLM narrative, and preserve the human-approval + revalidation + idempotent-write safety boundary.

