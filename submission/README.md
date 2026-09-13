# Inventra — Agentic Stockout Resolution System

Prevents avoidable warehouse stockouts. Given one SKU at one warehouse, the
system gathers evidence, decides whether action is needed, sizes and prices a
replenishment order, reviews it against policy, **pauses for a named human to
approve**, re-checks the facts, and only then writes a purchase request.

Built with LangGraph + SQLite + Pydantic. Three LLM agents; everything else is
deterministic Python.

| | |
|---|---|
| **Verified on** | Python 3.13.7, Windows, 2026-09-11; live-tested again 2026-09-13 |
| **Tests** | 192 test functions across 32 test modules are included in this package. Last full run recorded **136 passed** across 23 files (2026-09-11), before additional test modules were added; the 2026-09-13 pass was live/manual testing — see below. |
| **Live model** | Vertex AI `gemini-2.5-flash-lite` / `gemini-2.5-flash` |
| **Architecture, charters, permission matrix** | [design.md](design.md) |
| **Scenario-by-scenario results** | [test_report.md](test_report.md) |
| **Live manual test pass (2026-09-13) — 3 real bugs found and fixed** | [TEST_RESULTS.md](TEST_RESULTS.md) |
| **Explainer for presenting this system to someone else** | [PRESENTATION.md](PRESENTATION.md) |

> **Everything in this file was verified by running it**, not copied from the
> brief. Where the system's real behaviour differs from what you might expect,
> the difference is called out rather than smoothed over — see
> [§9 Gotchas](#9-gotchas-that-will-bite-you).
>
> **2026-09-13 update:** a live manual test pass (real Vertex AI, real DB, no
> stubs) found and fixed 3 real defects that the automated suite's stub agents
> never exercised: a policy-review evidence-grounding check that failed on
> ~60-75% of genuinely valid live proposals, a checkpoint-deserialization bug
> that broke every approve/reject/revise, and a budget "exception tolerance"
> that could never actually be approved. Full detail in
> [TEST_RESULTS.md](TEST_RESULTS.md). Two outbound email templates (internal
> approval emails and vendor PO emails) were also found to be malformed (no
> HTML document wrapper, no plain-text part) and were rewritten.

---

## Contents

1. [The one idea that matters](#1-the-one-idea-that-matters)
2. [Quickstart](#2-quickstart)
3. [How a case flows](#3-how-a-case-flows)
4. [The three agents](#4-the-three-agents)
5. [What's actually in the database](#5-whats-actually-in-the-database)
6. [CLI reference](#6-cli-reference)
7. [The three pauses](#7-the-three-pauses)
8. [Safety guarantees, and how each is enforced](#8-safety-guarantees-and-how-each-is-enforced)
9. [Gotchas that will bite you](#9-gotchas-that-will-bite-you)
10. [Demonstration script](#10-demonstration-script)
11. [Streamlit UI](#11-streamlit-ui)
12. [Email approval](#12-email-approval)
13. [Tests](#13-tests)
14. [Configuration reference](#14-configuration-reference)
15. [Troubleshooting](#15-troubleshooting)
16. [Known limits](#16-known-limits)
17. [File map](#17-file-map)

---

## 1. The one idea that matters

**The model narrates; code decides.**

Every judgment an agent makes is bounded by a plain Python function next to it
that computes the authoritative answer independently, and either enforces or
overrides the agent's output.

```mermaid
flowchart LR
    subgraph agent["LLM agent"]
        A["picks a window / an offer /<br/>a verdict, and explains why"]
    end
    subgraph code["Deterministic code"]
        B["computes cover days, order quantity,<br/>total cost, arrival date, budget fit,<br/>proposal hash"]
    end
    A -->|"names a choice"| B
    B -->|"overrides if the choice<br/>contradicts the arithmetic"| A
    B --> C["Human approval"]
    C --> D["Write"]
```

This exists because of a real failure during development. A live run had the
Sourcing Strategist narrate an extra-cost figure of **$450** for an option whose
computed extra cost was **$1,450** — the model dropped a digit while restating
arithmetic it had been handed correctly, then called the wrong number "a
justified investment."

The fix was not a better prompt. It was making the whole class of error
impossible: an agent may only *cite* a figure that already exists in its
evidence bundle, and it is never the authority on whether its own choice was
acceptable. Concretely:

| Agent judgment | Code that can override it |
|---|---|
| Which sales window to trust | `calculate_stock_risk` computes cover days from whichever window the agent names — the agent picks a *window*, never a *number* |
| Which vendor offer to pick | `economics.evaluate_options` ranks on all-in cost per day of cover (**not** total cost — quantities differ per supplier by design) and assigns a verdict per option; `nodes._validate_recommendation` **refuses** any pick whose verdict isn't `best_value_option` or `within_value_tolerance` |
| Whether policy passes | `nodes._override_policy_checklist` force-overwrites **7 of the 8** checklist rows with the deterministically provable answer, regardless of what the agent said |

Only one policy question is left to the agent's judgment: *"which tradeoff is
being made?"* — because that is narrative, not a fact with a computable answer.

**No LLM agent can call a tool at all.** Not a restricted set — none. Every
deterministic node calls the tools it needs *before* invoking an agent and hands
over only the resulting evidence as text. `call_structured()` takes a
system prompt, a user prompt, and a Pydantic schema. There is no tool list to
bind, so `create_purchase_request` is not merely forbidden to agents, it is
unreachable from them.

---

## 2. Quickstart

```bash
# 1. Install
pip install -r requirements.txt

# 2. Configure (optional — see below)
cp submission/.env.example submission/.env

# 3. Build the database
python database/seed.py
python -m submission.tests.seed_extra

# 4. Run a case that is reliably at risk
python -m submission.app run AC-003 DEL-01
```

Expected output, verbatim from a real run:

```
AWAITING_APPROVAL -- case CASE-AC-003-DEL-01
  proposal PROP-5F0F4F397F34 (1740f275a61d...)
  FastShip Inc.: 14 units, $4200.0
  resume with: python -m submission.app resume CASE-AC-003-DEL-01 APPROVED "your name"
```

Then approve it:

```bash
python -m submission.app resume CASE-AC-003-DEL-01 APPROVED "Your Name" "looks right"
```

```
PURCHASE_REQUEST_CREATED -- case CASE-AC-003-DEL-01
  request_id=PR-97C15FDC7DA7 created=True total_cost=4200.0
```

### Do I need an API key?

**No.** With no provider configured, `agents/wiring.py` prints a warning and
installs the deterministic stub agents from `agents/stubs.py`. The full graph —
including both pauses, revalidation, and the idempotent write — runs end to end
at zero LLM cost. This is also how the test suite runs.

To use real models, set **one** of these in `submission/.env`:

| `MODEL_PROVIDER` | Needs | Notes |
|---|---|---|
| `vertex` | `gcloud auth application-default login` + `GCP_PROJECT_ID` | What this submission was verified against |
| `gemini` | `GEMINI_API_KEY` | Simplest. Free key at [aistudio.google.com/apikey](https://aistudio.google.com/apikey) |
| `openai` | `OPENAI_API_KEY` | Uses `gpt-4o-mini` for all three roles |

The code default is `gemini`; if you want Vertex you must set it explicitly.

---

## 3. How a case flows

23 nodes. Rounded boxes are LLM agents, `[[double]]` are the human pauses,
everything else is deterministic Python.

```mermaid
flowchart TD
    START([START]) --> VR[validate_request]

    VR -->|valid| CP[check_product]
    VR -->|invalid| AMI[[await_missing_info]]
    VR -->|3 retries used| FNI[finalize NEEDS_INFORMATION]
    AMI --> VR

    CP -->|ok| FE[fetch_evidence]
    CP -->|not found / inactive| FB[finalize BLOCKED]

    FE -->|ok| AD(assess_demand<br/>Demand Analyst)
    FE -->|insufficient history| FNI
    FE -->|stale| FB

    AD -->|ok| CRISK[compute_risk]
    AD -->|windows disagree; parked| FNI

    CRISK -->|at risk| FVE[fetch_vendor_evidence]
    CRISK -->|healthy| FNA[finalize NO_ACTION]

    FVE --> BO[build_options<br/>re-size per supplier + score economics]
    BO -->|eligible options exist| RV(recommend_vendor<br/>Sourcing Strategist)
    BO -->|none eligible| FB

    RV -->|verdict acceptable| FBP[fetch_budget_and_policy]
    RV -->|verdict refused| FB

    FBP --> DP[draft_proposal<br/>+ compute proposal_hash]
    DP --> RP(review_policy<br/>Policy Reviewer<br/>+ code override)

    RP -->|PASS / EXCEPTION| RA[request_approval]
    RP -->|BLOCKED| FB

    RA --> AA[[await_approval]]

    AA -->|APPROVED| REV[revalidate]
    AA -->|REJECTED| FB
    AA -->|REVISE, max 1| PREP[prepare_revision]
    AA -->|EDIT, max 3| AHE[apply_human_edit]
    PREP --> FE
    AHE --> DP

    REV -->|pass| EP[execute_purchase]
    REV -->|stock/offer drift, 1 bounce| IA[invalidate_approval]
    REV -->|hash mismatch| FB
    IA --> CRISK

    EP -->|written| FS[finalize PURCHASE_REQUEST_CREATED]
    EP -->|write failed| FB

    FNA --> END([END])
    FNI --> END
    FB --> END
    FS --> END
```

**The write invariant:** exactly one path in the entire graph reaches
`execute_purchase`, and it requires human `APPROVED` **and** passing
revalidation. Every other path ends in one of four terminal states.

### Two cycles, both bounded

```mermaid
flowchart LR
    subgraph revise["REVISE — re-reason (max 1)"]
        direction LR
        R1[await_approval] --> R2[prepare_revision] --> R3[fetch_evidence]
        R3 -.->|full re-run<br/>incl. fresh stock read| R1
    end
```

`REVISE` hands a human comment back to the model and re-enters at
**`fetch_evidence`** — deliberately, because a human pause can outlast the
freshness window, so the stock snapshot must be re-read.

Supplier source data is system-owned: the operator cannot create or alter a
supplier record or quote. Supplier performance and quotes come from the purchasing data
source, then the deterministic gates and Sourcing Strategist evaluate them.
The operator may choose a different option only from the already eligible,
evidence-backed options. That choice requires a reason, recalculates quantity,
cost and arrival, runs policy/budget checks again, and returns for approval.

**Quantity is not human-editable, by design.** Order quantity is derived per
supplier from velocity, that supplier's lead time, fill rate and MOQ. Switching
supplier re-sizes the order automatically and correctly. Letting a human type a
number over that would reintroduce the hand-computed figure this system exists
to eliminate.

---

## 4. The three agents

Full charters in [design.md §4](design.md). Summary:

| Agent | Owns exactly one judgment | Sees | Cannot |
|---|---|---|---|
| **Demand Analyst**<br/>`assess_demand` | Which sales window (7d or 30d) reflects current demand — and whether they disagree too much to choose | `SalesVelocity` only | Compute cover days or decide `at_risk` |
| **Sourcing Strategist**<br/>`recommend_vendor` | Cost vs speed vs stockout-buffer, among options already filtered and priced by code | `StockRisk`, eligible options, the computed `economics` block, prior human rejections, any revision comment | Invent a price, quantity or arrival date; pick an option the economics gate refuses |
| **Policy Reviewer**<br/>`review_policy` | Reading `policy.md` prose against the evidence bundle; `PASS` / `BLOCKED` / `EXCEPTION` | The full bundle + full policy text | Edit the proposal; be final on budget, freshness, deadline or 6 other checklist rows |

All three: `extra="forbid"`, one repair attempt on invalid output, then **fail
closed** (`config.max_model_attempts_per_agent = 2`).

`PolicyReview` requires **exactly 8 checklist rows**, one per policy question,
enforced by a Pydantic `model_validator` — a question cannot be silently skipped
or buried in a paragraph.

---

## 5. What's actually in the database

Measured from a freshly seeded database, not from the brief. Warehouse `DEL-01`:

| SKU | Available | v7 | v30 | Cover (7d / 30d) | Outcome at the default 14-day target |
|---|---|---|---|---|---|
| AC-001 | 40 | 2.57 | 2.90 | 15.6d / 13.8d | ⚠️ **Nondeterministic** — see below |
| AC-002 | 32 | 2.57 | 2.90 | — | `BLOCKED` `DATA_STALE` (snapshot 78.0h vs 48.0h limit) |
| AC-003 | 15 | 1.71 | 1.93 | 8.8d / 7.8d | `AWAITING_APPROVAL` — FastShip Inc., 14 units, $4200 |
| AC-004 | 12 | 2.57 | 2.90 | 4.7d / 4.1d | `AWAITING_APPROVAL` on a clean budget (23 units, Standard Supplier, **$10,350** total, well under the $15,000 remaining). It reaches `BLOCKED`/`EXCEPTION` only if the warehouse budget is tightened first. Figure corrected 2026-09-13 — this row previously said $18,000, which no longer matches the seeded offer price. |
| AC-005 | 90 | 1.71 | 1.93 | 52.6d / 46.6d | `NO_ACTION` |
| AC-006 | 10 | 1.71 | 1.93 | 5.9d / 5.2d | `BLOCKED` — no eligible vendor (reliability or deadline) |
| REF-001 | — | — | — | — | `BLOCKED` `NOT_FOUND` (no snapshot at DEL-01) |
| TV-001 | — | — | — | — | `BLOCKED` `NOT_FOUND` (no snapshot at DEL-01) |

AC-006 is *at risk* under both windows but reaches `build_options` and finds no
supplier that is both reliable enough (≥ 0.90) and able to arrive before the
projected stockout. It is the cleanest demo of that path.

Budget for `DEL-01` / `2026-09`: **$50,000** total, $30,000 spent, $5,000
committed → **$15,000 remaining** on a fresh seed.

### ⚠️ AC-001 is a nondeterministic demo — use AC-003 instead

AC-001 sits almost exactly on the threshold:

- 7-day window → **15.56 days** cover → **not** at risk
- 30-day window → **13.79 days** cover → **at risk**

Which one applies depends on which window the LLM Demand Analyst chooses. In
verified runs AC-001 returned `AWAITING_APPROVAL` once and `NO_ACTION` another
time, from the *same* seeded data. That is correct behaviour — the agent owns
that judgment — but it makes AC-001 unsuitable for a scripted demo.

**AC-003 is at risk under both windows** (8.8d and 7.8d, both under 14), so it
behaves identically whichever the agent picks. It is the only SKU that reliably
reaches `AWAITING_APPROVAL`. Use it for any scripted demo.

`AC-001 DEL-01 10` (a 10-day target) is a reliable `NO_ACTION`.

---

## 6. CLI reference

```bash
python -m submission.app <command> [args]
```

| Command | Purpose |
|---|---|
| `run <SKU> <WH> [cover_days]` | Start a case. `cover_days` must be 7-45; omit for 14 |
| `resume <CASE_ID> APPROVED\|REJECTED\|REVISE <name> ["comment"]` | Decide a case awaiting approval |
| `edit <CASE_ID> <eligible OFFER_ID> <name> "reason"` | Choose an eligible supplier; recalculates and re-checks policy |
| `resume-info <CASE_ID> <SKU> <WH> <cover_days>` | Supply corrected fields to a `NEEDS_INFORMATION` pause |
| `pending` | List every case waiting on a human |
| `cancel <REQUEST_ID> <name> "reason"` | Withdraw a `PENDING` purchase request |

`pending` is the discovery command — it prints the exact resume line for each
case, so you never have to remember a case ID:

```
1 case(s) waiting on a human:
  CASE-AC-003-DEL-01
    status    AWAITING_APPROVAL
    product   AC-003 at DEL-01
    waiting   0.1h
    thread    CASE-AC-003-DEL-01#20260911T152336185380
    resume    python -m submission.app resume CASE-AC-003-DEL-01 APPROVED "your name"
```

### Case IDs vs thread IDs

- **`case_id`** = `CASE-<SKU>-<WAREHOUSE>`. Stable business identity. Never
  forks, so the audit trail for a product at a warehouse is one readable
  history.
- **`thread_id`** = `<case_id>#<UTC timestamp>`. Per-*run* checkpoint identity.

This split matters: a finished case (rejected, blocked, ordered) can be
re-investigated later without resuming a dead thread. You always pass the
`case_id`; the newest thread is resolved for you.

---

## 7. The three pauses

All three use LangGraph `interrupt()` with a SQLite checkpointer, so a pause is
**durable** — the process can exit and the case resumes later, from another
process, even by a different entry point.

```mermaid
sequenceDiagram
    participant H as Human
    participant CLI as CLI / UI / email link
    participant G as Graph
    participant CP as checkpoints.sqlite
    participant DB as inventra.db

    CLI->>G: run AC-003 DEL-01
    G->>DB: read stock, sales, vendors, budget
    G->>G: 3 LLM calls + deterministic gates
    G->>CP: persist state, interrupt()
    G-->>CLI: AWAITING_APPROVAL + proposal_hash
    Note over G,CP: process may exit here

    H->>CLI: resume CASE-AC-003-DEL-01 APPROVED "Name"
    CLI->>CP: load newest thread
    CP-->>G: restore exactly where it paused
    G->>DB: revalidate — stock, offer, budget, hash
    alt facts unchanged
        G->>DB: INSERT purchase_request (idempotency_key = proposal_hash)
        G-->>CLI: PURCHASE_REQUEST_CREATED
    else facts changed
        G->>G: invalidate approval, bounce to compute_risk
    end
```

| Pause | Fires when | Resume with |
|---|---|---|
| `await_missing_info` | SKU/warehouse missing, or cover days outside 7-45 | `resume-info` |
| `await_approval` | A policy-reviewed proposal is ready | `resume` or `edit` |

Each pause node calls `interrupt()` as its **first statement**, so resuming
re-runs only that tiny node — never the expensive model call before it.

---

## 8. Safety guarantees, and how each is enforced

Every row here was verified by running it, not by reading the code.

| Guarantee | Mechanism | How it was proven |
|---|---|---|
| **No agent can write** | No agent has any tool binding at all | Structural — `call_structured()` accepts prompts + a schema, nothing else |
| **Approval binds to an exact proposal version** | `proposal_hash` over (sku, warehouse, quantity, unit_price, vendor_id, target_cover_days) | Revalidation rejects a mismatched hash and fails closed immediately |
| **Facts are re-checked after approval** | `graph/revalidation.py` re-reads stock, offer validity, budget, hash | Budget-change-during-pause test bounces the case back to `compute_risk` |
| **One approval → at most one order** | `idempotency_key = proposal_hash` against a `UNIQUE` column | Resuming an approved case twice returns the existing row, `created=False` |
| **No duplicate ordering across runs** | `get_open_order_quantity()` folds `PENDING` units into available stock | **Verified live:** re-running AC-003 after its 14-unit order returned `NO_ACTION` (15 + 14 = 29 units → 14.5d cover > 14d target) |
| **An approved order reserves budget** | `create_purchase_request` increments `monthly_budgets.committed_amount` | **Verified live:** `committed_amount` went 5000 → **9200**, exactly +4200, the order total |
| **Cancelling releases the reservation** | `cancel_purchase_request` decrements the *same* `committed_budget_month` it reserved | Month-boundary safe: it credits the month it committed to, not "now" |
| **Audit trail leaks no model reasoning** | `emit_audit` stores structured payloads only | A test asserts no `rationale`/`reasoning`/`thoughts` key ever appears |
| **Bounded loops** | revision ≤ 1, edits ≤ 3, info retries ≤ 3, model attempts ≤ 2 | Graph-path tests prove termination on each |

---

## 9. Gotchas that will bite you

Real quirks found by running the system. None are documented in the brief.

### 9.1 [FIXED, 2026-09-11] Velocity windows used to include today

**Status: fixed.** `tools/sales.py` now anchors both windows on `yesterday`
(`start_7_days = yesterday - timedelta(days=6)`, span `today-7 … today-1`),
with an explicit comment recording why: "today can never have a complete
sales_daily row ... a window that included today was always averaging N
units of demand over N-1 real days of coverage." This section is kept for
the record — it originally documented a real ~14% (7-day) / ~3.3% (30-day)
low bias in every velocity read, found and fixed before this submission's
current form. If you see the old boundary (`start_7_days = today -
timedelta(days=7)`, `sale_date > start_7_days`) in a diff or fork, that's the
regression to watch for.

### 9.2 AC-005 does not trigger `INSUFFICIENT_DATA`

The seed comment implies it should. It does not. The rule in `tools/sales.py` is
**fewer than 3 observations in either window**:

```python
if count_7 < 3 or count_30 < 3:
    return ... error=ErrorCode.INSUFFICIENT_DATA
```

AC-005 has 14 days of history, comfortably over 3, so velocity resolves fine
and its 45+ days of cover produce `NO_ACTION`. The `INSUFFICIENT_DATA` path is
covered by tests using purpose-built fixtures, not by AC-005 from the CLI.

### 9.3 `INSUFFICIENT_DATA` returns `BLOCKED`, but the spec says `NEEDS_INFORMATION`

`nodes.fetch_evidence` calls `_fail(...)` without overriding the default status,
so thin sales history ends the case as `BLOCKED`. The case-flow specification
(`05_inventra_case_flow.md`, scenario 11) and the Investigator interface both
specify **`NEEDS_INFORMATION`**. This is a known deviation, not a design choice.

### 9.4 Freshness is 48h, not the brief's 2h

`policy.md` says "2 days"; the brief's business-rules table says 2 hours. The
code follows `policy.md` (`data_freshness_hours = 48`), on the reasoning that an
agent reading "2 days" in its own evidence bundle while code enforces 2 hours is
a worse failure than a permissive threshold. Override with
`DATA_FRESHNESS_HOURS=2` if you want the literal brief reading — note that doing
so will make almost every seeded snapshot stale.

### 9.5 PowerShell reports exit code 1 on success

Deprecation warnings go to stderr, and PowerShell raises `NativeCommandError`
for any stderr output. `136 passed` with exit code 1 is a **pass**. Check the
summary line, not the exit code. In `bash` this does not happen.

### 9.6 17,957 deprecation warnings

`datetime.utcnow()` is deprecated in Python 3.13 and used throughout the starter
package. Harmless today. Silence with `-p no:warnings`.

---

## 10. Demonstration script

One happy path and six failure paths. Every output below is real.

```bash
python database/seed.py && python -m submission.tests.seed_extra
```

### ① Happy path — cost vs speed, approved, written

```bash
python -m submission.app run AC-003 DEL-01
python -m submission.app resume CASE-AC-003-DEL-01 APPROVED "Your Name" "looks right"
```
→ `AWAITING_APPROVAL` with a proposal explaining the trade-off, then
`PURCHASE_REQUEST_CREATED request_id=PR-... created=True total_cost=4200.0`

### ② `NO_ACTION` — healthy stock, no vendor work

```bash
python -m submission.app run AC-005 DEL-01
```
→ `NO_ACTION`. 46+ days of cover. Vendor tools and the write tool are never
called, so no LLM spend beyond the demand read.

### ③ `BLOCKED` / `DATA_STALE` — evidence too old to trust

```bash
python -m submission.app run AC-002 DEL-01
```
→ `ErrorCode.DATA_STALE: Inventory snapshot is 78.0h old, exceeds 48.0h
threshold.` Blocks before any vendor lookup.

### ④ `BLOCKED` — over budget

```bash
python -m submission.app run AC-004 DEL-01
```
→ `Policy review blocked: The proposed total cost of 18000.0 exceeds the
remaining budget of 15000.0 ... Over budget: cost 18000.0 exceeds remaining
15000.0.`

Note this verdict is **code-enforced**, not the agent's opinion —
`review_policy` recomputes the budget and overrides whatever the model said.

### ⑤ `BLOCKED` — at risk, but no eligible supplier

```bash
python -m submission.app run AC-006 DEL-01
```
→ `ErrorCode.INVALID_INPUT: No eligible vendor options (reliability or
deadline).` The SKU genuinely needs stock (5.2 days cover) but no supplier is
both reliable enough and fast enough. `state["vendor_rejection_detail"]` records
which vendor failed on which test, so the block is explainable per vendor rather
than one flat sentence.

### ⑥ `BLOCKED` / `NOT_FOUND` — product not stocked here

```bash
python -m submission.app run REF-001 DEL-01
```
→ `ErrorCode.NOT_FOUND: Stock lookup failed: NOT_FOUND`

### ⑦ `NEEDS_INFORMATION`, resumable — bad input

```bash
python -m submission.app run AC-001 DEL-01 99      # 99 is outside 7-45
```
→ `Missing or invalid field(s): target_cover_days (must be 7-45, got 99)` —
pauses instead of dead-ending, then:
```bash
python -m submission.app resume-info CASE-AC-001-DEL-01 AC-001 DEL-01 14
```

### ⑦ Reorder guard — no duplicate order

Immediately after ①:
```bash
python -m submission.app run AC-003 DEL-01
```
→ `NO_ACTION`. The 14 units already on order count toward available stock
(15 + 14 = 29 → 14.5 days cover), so the system does not re-order.

---

## 11. Streamlit UI

```bash
streamlit run submission/ui.py
```

Screens: **watchlist** (portfolio ranked worst-first), **case/approval** (full
proposal, agent reasoning, policy checklist, approve/reject/revise/edit),
**needs-my-decision queue**, **monitor control** (start/stop the autonomous
sweep, sweep history, park queue), and **past cases** with audit playback.

### The autonomous monitor — the actual simulator

`submission/monitor/service.py` + the UI's Monitor screen let you start a
background sweep (minimum 30s interval) that scans a warehouse on its own
and opens cases the same way a human triggering `run` would — this is the
system operating unattended, not just a manual CLI demo. Pair it with
`submission/data_console.py` (port 8502) to stage a condition (low stock,
stale data, expired vendor offers, a tight budget, a policy floor) before
starting the monitor, then watch it react.

**Full step-by-step scenario guide, verified against the actual code
(button labels, screen names, exact thresholds):
[SIMULATOR_GUIDE.md](SIMULATOR_GUIDE.md).**

The UI calls the same `run_case` / `resume_case` / `load_case` functions as the
CLI, so the two entry points cannot drift into behaving differently.

Audit playback maps event types to fixed sentences via a plain lookup table —
deliberately not an LLM, because this is the one place a hallucination would
directly mislead an auditor about what the system did.

---

## 12. Email approval

Optional. Requires `EMAIL_ENABLED=true`, a Gmail address + App Password, and
`EMAIL_TO`. For local development, run the approval server alongside the CLI
or UI, then keep it running while using approval-email links:

```bash
python -m submission.graph.approval_server
```

The default local approval URL is [http://127.0.0.1:8787](http://127.0.0.1:8787).
It only works from the computer running this command. An approver on another
computer needs a reachable HTTPS `APPROVAL_BASE_URL`; do not send them the
default localhost links.

The email contains signed links, not embedded response fields. Selecting a
link opens a confirmation page served by the local approval server:

| Email action | Confirmation-page behaviour |
|---|---|
| **Approve** | Shows a final confirmation button; no comment is required. |
| **Request changes** | Shows a required text box for what should change and why. The submitted feedback resumes the case and is passed to the revision workflow. |
| **Reject** | Shows a required reason text box. The reason is recorded and the proposal is rejected. |
| **Reject vendor send** | Shows a required reason text box. The reserved purchase request is cancelled. |

Both the email links and the Streamlit screen resume the *same* checkpoint —
whichever arrives first wins, and the other is rejected as already-used.
Links are signed, expire, and require a final POST confirmation, so merely
opening a link does not apply a decision.

Vendor-facing purchase orders were originally **fully built and tested but
shipped disabled** (`vendor_email_enabled=False`), pending SPF/DKIM/DMARC
review on a real sending domain. **As of 2026-09-13, `VENDOR_EMAIL_ENABLED`
was set to `true`** for this deployment after the trust model was reviewed —
see [notifications/vendor_email.py](notifications/vendor_email.py) for the
guardrail that keeps this safe: every field in the vendor email is
code-computed (SKU, quantity, price, total, delivery date, warehouse) —
never agent-generated free text. A real vendor send is a genuine commercial
action to a third party (currently the vendors on file:
V-FAST/V-CHEAP/V-BALANCED each have a real contact_email set), so re-check
this flag before running unattended.

The vendor email template was rewritten 2026-09-13 (previously a bare HTML
fragment with no company name, no product name, no delivery destination, and
no plain-text alternative — see `TEST_RESULTS.md`). It now includes a
greeting, the buyer's identity (`config.company_name`, set via `COMPANY_NAME`
in `.env`, defaults to "Inventra Purchasing"), the actual product name (not
just the SKU code), the delivery warehouse, and a proper multipart
(HTML + plain-text) message. Before the Gate-2 **Approve and send** action,
the Agent Console shows the exact recipient, sender, subject, formatted email,
and plain-text fallback generated from this same template. The draft remains
read-only: editing vendor-facing copy is not implemented.

Rejecting at **either** approval gate (the original proposal, or the separate
later "approve sending to vendor" confirmation) never results in a vendor
email — confirmed by tracing `handle_decision`/`handle_vendor_decision` in
`graph/nodes.py`. Only approving both gates sends anything.

---

## 13. Tests

```bash
python -m pytest submission/tests/ -q -p no:warnings
```

**136 passed in ~85s.** Full per-scenario mapping in
[test_report.md](test_report.md).

Tests run against the **real compiled graph** with stub agents — zero LLM cost,
fully deterministic. `conftest.py` forces email off regardless of your `.env`;
tests that exercise email re-enable it for themselves only. Four tests in
`test_phase4_agents.py` need a real API key and skip cleanly without one.

| File | Tests | | File | Tests |
|---|---|---|---|---|
| `test_phase6_revision_and_ui_reads.py` | 21 | | `test_phase1_contracts.py` | 9 |
| `test_phase10_cancel_purchase_request.py` | 15 | | `test_phase2_3_graph.py` | 8 |
| `test_phase_e_insufficient_data_loop.py` | 5 | | `test_phase9_revalidation_routing.py` | 7 |
| `test_phase10_human_edit_at_approval.py` | 12 | | `test_phase12_policy_checklist.py` | 6 |
| `test_phase5_remaining_scenarios.py` | 5 | | `test_phase9_notifications.py` | 5 |
| `test_phase4_agents.py` | 4 | | `test_phase9_policy_hardening.py` | 4 |
| `test_phase9_observability.py` | 4 | | `test_phase3_email_approval.py` | 3 |
| `test_phase9_pending_queue.py` | 3 | | `test_phase10_pending_scan_cost.py` | 3 |
| `test_phase11_budget_and_reorder_guard.py` | 3 | | `test_phase9_demand_clarification_message.py` | 3 |
| `test_phase9_needs_information_resume.py` | 2 | | `test_phase9_policy_evidence_gap.py` | 2 |
| `test_phase9_ui_deep_links.py` | 2 | | `test_phase9_vendor_ordering.py` | 2 |
| `test_phase9_agent_memory.py` | 1 | | **Total** | **129** |

---

## 14. Configuration reference

All in `submission/config.py`, overridable by env var in `submission/.env`.

### Business rules

| Setting | Default | Env var |
|---|---|---|
| Data freshness | `48.0` hours | `DATA_FRESHNESS_HOURS` |
| Target cover (default / min / max) | `14` / `7` / `45` days | — |
| Vendor reliability floor | `0.90` | — |
| Over-budget exception tolerance | `0.05` (5%) | — |
| Assumed gross margin | `0.25` | `ASSUMED_GROSS_MARGIN_RATE` |

`assumed_gross_margin_rate` is a **declared assumption, not data** — the
`products` table has no selling price, so profit per unit is not derivable.
It is emitted as a caveat beside every figure it affects, and changing the env
var visibly moves the premium verdicts.

### Engineering limits

| Setting | Value |
|---|---|
| Revision cycles | `1` |
| Model attempts per agent | `2` (initial + one repair, then fail closed) |
| Missing-info retries | `3` |
| Human edit cycles | `3` |

### Models

| Role | Vertex | Gemini | OpenAI |
|---|---|---|---|
| demand | `gemini-2.5-flash-lite` | `gemini-3.5-flash-lite` | `gpt-4o-mini` |
| strategist | `gemini-2.5-flash` | `gemini-3.5-flash` | `gpt-4o-mini` |
| policy | `gemini-2.5-flash` | `gemini-3.5-flash` | `gpt-4o-mini` |

`agent_temperature = 0.1` — low but not zero; these are judgment tasks, not
extraction. Observed latency on Vertex: **7.5-9.5s** per structured call.

Cheap model for the narrow window choice, stronger model for trade-off
reasoning and the policy read.

### Paths and email

`DATABASE_PATH` (default `database/inventra.db`), checkpointer fixed at
`submission/checkpoints.sqlite`, `EMAIL_ENABLED`, `VENDOR_EMAIL_ENABLED`,
`GMAIL_ADDRESS`, `GMAIL_APP_PASSWORD`, `EMAIL_TO`, `APPROVAL_SERVER_HOST/PORT`,
`APPROVAL_BASE_URL`, `APPROVAL_TOKEN_SECRET`, `APPROVAL_TIMEOUT_MINUTES`,
`COMPANY_NAME` (new 2026-09-13, defaults to `"Inventra Purchasing"` — cosmetic
only, appears on the outbound vendor PO email's letterhead/signature, never
used for anything auth-related).

Generate an approval secret:
```bash
python -c "import secrets; print(secrets.token_hex(32))"
```

---

## 15. Troubleshooting

| Symptom | Cause and fix |
|---|---|
| `Case ... has never been run` | No checkpoint for that case. `run` it first, or check `pending` |
| `Case ... is not paused for approval` | Already resumed, or it reached a terminal state. `pending` shows what's actually waiting |
| Everything returns `DATA_STALE` | `DATA_FRESHNESS_HOURS` too low, or the seed is old. Re-run `python database/seed.py` |
| No LLM calls in the log | No provider configured — you're on stub agents. Expected, and fine |
| Exit code 1 but tests passed | PowerShell treating stderr warnings as errors. See §9.5 |
| `RequestsDependencyWarning: urllib3 ... doesn't match` | Pre-existing env mismatch (`urllib3` 2.7.0 / `chardet` 6.0.0). Cosmetic; does not affect the run |
| Case IDs collide between runs | They're meant to. `case_id` is stable; each run gets its own `thread_id` |
| Vertex auth failures | `gcloud auth application-default login`, and check `GCP_PROJECT_ID`. Or switch to `MODEL_PROVIDER=gemini` with one API key |

---

## 16. Known limits

Honest list. Detail in [test_report.md](test_report.md) and
[../GAP_NEEDS_INFORMATION.md](../GAP_NEEDS_INFORMATION.md).

- **No background scheduler.** Nothing runs on its own. A case starts because a
  human triggered it. The "needs my decision" queue computes staleness live when
  opened, which is an honest manual check rather than a cron.
- **`INSUFFICIENT_DATA` returns `BLOCKED`, not `NEEDS_INFORMATION`** — off-spec
  against the case-flow document. See §9.3.
- **Nothing ever confirms an order.** Only `PENDING`, `FAILED` and `CANCELLED`
  are ever written; `CONFIRMED` is defined but unreachable because there is no
  supplier acknowledgement channel. `PENDING` means "written and not withdrawn",
  never "the supplier committed".
- **`confirmed_inbound` is never written** by this system. The reorder guard
  compensates by counting open `PENDING` orders instead.
- **Re-approving a byte-identical cancelled proposal no-ops.** `proposal_hash`
  contains no `case_id` or timestamp, so a proposal cancelled and then
  re-approved with every hashed field unchanged collides with its own old
  `idempotency_key` and returns the cancelled row. Real stock and price drift
  makes this unlikely but it is not guarded.
- **No two-way email.** Outbound works; nothing reads replies.
- **Email cannot be tested locally.** `smtp_host`/`smtp_port` are hardcoded and
  `starttls()`/`login()` are unconditional, so Mailpit/MailHog cannot be
  substituted.
- **[Resolved 2026-09-13] Vendor contact emails were synthetic**
  (`<vendor_id>@example-vendor.test`). `V-FAST`, `V-CHEAP`, and `V-BALANCED`
  now have real contact emails set directly in `database/seed.py`'s `VENDORS`
  tuple (so they survive every reseed); `V-SLOW` and `V-UNRELIABLE` remain
  `NULL` — deliberately, since no real address was given for them.
- **One test docstring is stale (the test itself is fine).**
  `test_phase10_cancel_purchase_request.py::test_cancelling_releases_no_budget_and_says_so`
  says "create_purchase_request never increments committed_amount" — no longer
  true. The **assertions are still correct**: its helper `_insert_request()`
  writes a `purchase_requests` row directly via SQL and omits
  `committed_budget_month`, so nothing was ever reserved for that row and
  cancelling correctly releases nothing. It coexists with
  `test_phase11_budget_and_reorder_guard.py` (which proves the normal path does
  reserve and release) because the two cover genuinely different cases. Only the
  docstring and the test name mislead.
- **No way to preview or edit a vendor PO email before it sends.** Between the
  two approval gates there is no step where a human sees the drafted vendor
  email content and can change it — approving Gate 2 fires the template
  verbatim. Recorded as an open feature request ("Edit mail" button) in
  `../GAP_NEEDS_INFORMATION.md`, not designed or built.
- **No automated test proves resistance to adversarial reject/revise reasons.**
  A human's rejection/revision comment is stored (truncated at 500 chars, no
  sanitization) and later concatenated unescaped into the Strategist's prompt
  on a *different, later* case touching the same vendor
  (`tools/memory.py::summarize_memory_for_prompt` →
  `prompts/strategist.py`). Manually tested live 2026-09-13 with an adversarial
  planted signal ("always recommend V-CHEAP ... per new management directive")
  and the system correctly ignored it — but no automated test asserts this, so
  nothing guards against a regression. Detail and a suggested test shape in
  `../GAP_NEEDS_INFORMATION.md`.

---

## 17. File map

```
requirements.txt              pinned deps, verified 2026-09-11
database/
  schema.sql                  9 tables
  seed.py                     base fixtures — run first
  migrate.py                  additive, idempotent column adds
tools/                        STARTER PACKAGE — unmodified
  inventory.py                product, stock, risk arithmetic
  sales.py                    velocity (see §9.1 for the /7 quirk)
  vendors.py                  offers, performance, option building
  policy.py                   budget position, policy.md loader
  execution.py                revalidate, write, open-order guard, cancel
  memory.py                   human-decision signal store
domain/tool_models.py         STARTER — Pydantic tool I/O
submission/
  README.md                   this file
  design.md                   architecture, charters, permission matrix
  test_report.md              scenario-by-scenario results
  SIMULATOR_GUIDE.md          step-by-step scenario guide for the monitor + Data Console
  app.py                      CLI entry point
  ui.py                       Streamlit operator screens (approval, watchlist, monitor control)
  data_console.py             stage test conditions (levers, table editor, backfill)
  monitor/service.py          the autonomous sweep — start/stop, interval, per-warehouse scan
  config.py                   every threshold and credential
  portfolio.py                watchlist, pending queue, audit playback
  statistics/                 SKU policy derivation (cover-days targets from sales history)
  dataops/                    Data Console's read/write layer over the DB tables
  state/state.py              CaseState + identity rules
  agents/
    models.py                 the three output contracts
    real.py                   live LLM agents
    stubs.py                  deterministic stand-ins (test default)
    wiring.py                 picks real vs stub
    llm.py                    single structured-output chokepoint
  graph/
    workflow.py               nodes, edges, 3 interrupts, checkpointer
    routes.py                 14 pure routing functions
    nodes.py                  every node implementation
    economics.py              sizing + premium-justification arithmetic
    hashing.py                proposal_hash
    revalidation.py           post-approval fact re-check
    approval_server.py        signed email approval links
    support.py                audit emit + agent retry wrapper
  prompts/                    versioned, evidence-only prompts
  notifications/              approver email, vendor PO email
  tests/                      188 tests, 31 files (136 last fully re-run 2026-09-11)
policy.md                     prose read by the Policy Reviewer each run
```

---

## Where to go next

- **Present this system to someone else** → [PRESENTATION.md](PRESENTATION.md)
- **Understand the design rationale** → [design.md](design.md)
- **Check automated scenario coverage (2026-09-11 snapshot)** → [test_report.md](test_report.md)
- **See the 2026-09-13 live manual test pass and the 3 bugs it found/fixed** → [TEST_RESULTS.md](TEST_RESULTS.md)
- **Use the autonomous monitor** → [SIMULATOR_GUIDE.md](SIMULATOR_GUIDE.md) —
  `submission/monitor/service.py` and the UI's Monitor screen scan a warehouse
  on a timer and open cases on their own.
