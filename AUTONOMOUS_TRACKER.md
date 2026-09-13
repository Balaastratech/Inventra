# AUTONOMOUS_TRACKER.md

Append-only work log for `AUTONOMOUS_PLAN.md`.

Every agent that reads `AUTONOMOUS_PLAN.md` must read this file first and append
one entry before finishing its session.

---

## RULES — read before writing

1. **APPEND ONLY.** Add new entries at the **bottom**. Never edit, reword,
   reformat, reorder, merge, summarise, compact or delete an existing entry.
   Not even your own from a previous session. Not even to fix a typo.
2. **This file only ever grows.** Two ways to check, in order of preference:
   - **If this workspace is a git repository:** `git diff -- AUTONOMOUS_TRACKER.md`
     must show **only added lines**. A deletion or modification means the rule was
     broken — restore the file and re-append instead.
   - **If it is not a git repository** (it was not, as of Entry 003): compare
     **file size and entry count** before and after your append. Both must
     increase, never decrease. Known baselines: Entry 001 → 8,174 bytes / 1 entry.
     Entry 002 → 13,052 bytes / 2 entries. Record your own figures in your entry
     so the next agent has a fresh baseline.
   - **Use `fs_append`, never `fs_write`.** `fs_write` replaces the entire file
     and will destroy the log in a single call. This is the most likely way to
     break the rule by accident.
3. **Sign every entry with your agent name and model.** "Claude Opus 5 (Kiro)",
   "GPT-5 (Codex CLI)", "Gemini 3 Pro", and so on. If a human wrote the entry by
   hand, sign it `human:<name>`.
4. **Number entries sequentially.** Read the last entry to get the next number.
   If two agents collide on the same number, the later one takes the next free
   integer. **Never renumber an existing entry.**
5. **Be honest about what you did not do.** An entry that overstates progress is
   worse than no entry, because the next agent trusts it and builds on a lie.
   Explicitly separate *verified* from *written but unverified*.
6. **Task status lives in `AUTONOMOUS_PLAN.md`,** not here. Tick the checkboxes
   there. This file records *who did what, when, and what they learned*.
7. **If you changed the plan itself, say so** and say why. If you made a design
   decision, add it to `DECISIONS.md` as a new `D<n>` record and reference it
   here.
8. **The newest entry is the current state.** Because entries are chronological
   and append-only, the last `State after this session` block is authoritative.
   Do not maintain a summary at the top of this file — it would have to be
   rewritten, which rule 1 forbids.

---

## ENTRY TEMPLATE

Copy this, fill it in, append it at the bottom. Leave a field as `none` rather
than deleting it.

```markdown
### Entry NNN — YYYY-MM-DD HH:MM UTC — <agent name and model> — <session type>

**Read:** which files and which sections you actually read this session
**Phase / tasks touched:** e.g. A1, A2, B3 (use the plan's own task IDs)
**Files created:**
**Files modified:**
**Did:** what actually happened, in plain terms
**Verified:** what you checked, how you checked it, and what the result was
**NOT verified:** what you wrote but could not confirm works
**Blocked / open:** anything needing a human decision, with the specific question
**Plan changed?:** no / yes + what and why
**Decisions added to DECISIONS.md:** none / D<n> + one-line summary
**State after this session:** which phases are complete, in progress, not started
**Next recommended step:** one concrete action for the next agent
**Notes for the next agent:** gotchas, dead ends, things not to repeat, surprises
```

Session types: `planning`, `implementation`, `verification`, `debugging`,
`refactor`, `docs`, `review`, `handoff`.

---

## LOG

### Entry 001 — 2026-09-11 — Claude Opus 5 (Kiro) — planning

**Read:** `Inventra_Agent_Readable_Pack/07_inventra_student_design_challenge.md`
(full brief), `05_inventra_case_flow.md` and `02_investigator_agent_interface.md`
(scenario tables), `database/schema.sql` (full), `submission/graph/workflow.py`,
`submission/graph/nodes.py`, `submission/graph/economics.py`,
`submission/portfolio.py`, `submission/state/state.py`, `submission/config.py`
(targeted greps), plus a context-gatherer sweep of `submission/` and `tools/`.

**Phase / tasks touched:** none — no implementation performed

**Files created:**
- `AUTONOMOUS_PLAN.md`
- `DECISIONS.md`
- `AUTONOMOUS_TRACKER.md` (this file)
- `.kiro/steering/autonomous-plan-tracker.md`

**Files modified:**
- `AUTONOMOUS_PLAN.md` — added the mandatory tracker header after initial write

**Did:** Designed the autonomous-monitor architecture across four rounds of
discussion with the user. Produced a 9-phase plan with 247 checkable tasks, 28
decision records, and a 22-scenario catalogue covering all 10 brief acceptance
scenarios plus case-flow scenario 11.

Key architectural conclusions, all recorded in `DECISIONS.md`:
- No simulation clock (D1) — fabricate data dates relative to real `utcnow()`;
  `as_of` is a classifier function argument, not ambient state
- `target_cover_days` becomes a derived output, input removed (D2)
- Reorder point replaces cover-days threshold (D3)
- Two windows, two jobs: ABC on rolling 12 months, forecast on recent level; the
  gap between them is the regime-shift signal (D4)
- Demand quadrant switches the forecasting method, not just the label (D5)
- Monitor is deterministic, not an agent — stays at 3 agents (D9)
- Floor reconciliation reuses the existing `apply_human_edit` cycle; no new graph
  shape and no agent-before-monitor (D19)

**Verified:**
- Both documents exist at workspace root; 247 checkboxes and 28 decision records
  counted programmatically
- Full traceability pass: every user decision from the conversation mapped to a
  location in the plan or decision records, output to the user for review
- Found and fixed a real defect during verification: Phase D task groups were
  numbered D1-D4, colliding with decision records D1-D28. Renamed to descriptive
  headings; confirmed no `### D<digit>` headings remain

**NOT verified:** Nothing was built, so nothing is executable. Three code claims
inside the plan came from earlier reads this session and were not independently
re-confirmed at write time: the ~45 wall-clock call sites, the
`INSUFFICIENT_DATA` returning `BLOCKED` instead of `NEEDS_INFORMATION`, and the
contradictory budget-reservation tests. **A future agent should re-confirm these
three before acting on them.**

**Blocked / open:** Two open decisions, both with provisional defaults recorded
in the plan's Open Decisions section:
- **O1** — when a policy floor exceeds the statistical target, should the agent
  recommend the floor (current default, argued in D16) or the statistical
  figure? Business judgment; needs the user's call.
- **O2** — how many SKUs get policy floors? Provisional: 3-4 of ~35.

**Plan changed?:** n/a — created this session

**Decisions added to DECISIONS.md:** D1 through D28 (initial set)

**State after this session:**
- Phases A-H: **not started.** Nothing has been implemented.
- Planning: **complete** and reviewed by the user
- Estimated remaining effort: 36-50 agent sessions (~70-100 hours) for all
  phases; 18-24 sessions for the reduced-scope cut (A trimmed + B + C + C2 + E +
  one UI)

**Next recommended step:** Get the user's answer on **O1** (it changes the
default on every floor-constrained SKU), then start **Phase A1** — the schema
additions and migration. Do not start at Phase C; A and B carry the substance.

**Notes for the next agent:**
- **Develop Phases C and D against `submission/agents/stubs.py`,** not the real
  LLMs. Deterministic stand-ins for all three agents already exist and are the
  default in `nodes._AGENTS`. A six-candidate sweep with real models costs 1-2
  minutes of latency per iteration; with stubs it is sub-second. Switch to real
  models only for final verification. This is probably worth 3-5 sessions.
- Existing tests **will** break by design. The user has explicitly agreed green
  tests are not a gate right now (D26). Do not spend sessions chasing them.
- `submission/graph/economics.py` is good work — extend it, do not replace it.
  Same for the cyclic `apply_human_edit → draft_proposal → review_policy →
  request_approval` loop, which is the mechanism Phase C2 depends on.
- `PolicyReview.checklist` is currently pinned at **exactly 8** items with a
  validator enforcing one entry per question. Phase C2 makes it 9. Expect that
  to surface in more places than you first find.
- There is no `GRAPH_REPORT.md` in this workspace despite a global rule
  referencing one. Do not go looking for it.
- The rubric awards **zero marks for a dashboard** and explicitly lists "a large
  dashboard" under what does not earn marks. Phase G exists for the user's own
  demonstration needs. Do not let it consume time budgeted for A-E.

---

### Entry 002 — 2026-09-11 — Claude Opus 5 (Kiro) — docs

**Read:** `AUTONOMOUS_PLAN.md` (header region), `.kiro` (absent, created this
session)

**Phase / tasks touched:** none — no implementation performed

**Files created:**
- `AUTONOMOUS_TRACKER.md` (this file, with rules + template + Entry 001)
- `.kiro/steering/autonomous-plan-tracker.md`

**Files modified:**
- `AUTONOMOUS_PLAN.md` — inserted a mandatory agent header above the intro and a
  companion-files table below it. Body content untouched.

**Did:** Built the cross-agent handoff mechanism the user asked for. Three layers,
because no single one covers every tool:

1. **Loud header in `AUTONOMOUS_PLAN.md`** — works for any agent that reads the
   file, regardless of tooling (Claude Code, Codex CLI, Gemini, a human).
2. **Kiro steering rule** at `.kiro/steering/autonomous-plan-tracker.md` with
   `inclusion: fileMatch` and `fileMatchPattern: 'AUTONOMOUS_*'`, so Kiro
   auto-injects the obligation whenever the plan or the tracker enters context.
   This is the layer that actually enforces rather than requests.
3. **Rules + template inside the tracker itself**, so an agent that lands here
   directly still knows the discipline.

Also established the three-file separation of concerns so append-only does not
conflict with progress tracking: status lives in the plan's checkboxes, history
appends here, rationale appends to `DECISIONS.md`. This is why there is
deliberately **no summary block at the top of this file** — it would need
rewriting on every session, which rule 1 forbids. The newest entry is the state.

**Verified:**
- All four files exist with expected sizes (plan 38,773 B; tracker 8,174 B;
  decisions 29,969 B; steering 2,193 B)
- Plan checkbox count still **247** after the header edit — confirms the insert
  did not disturb or drop any task
- Header renders correctly as a blockquote at the top of the plan, above the
  intro, with working relative links to both companion files
- Tracker entry regex finds exactly one entry (001) prior to this one, so
  sequential numbering is intact
- This entry was written with `fs_append`, not `fs_write`

**NOT verified:** The Kiro steering rule's `fileMatchPattern: 'AUTONOMOUS_*'` was
observed activating in this same session immediately after creation, so the glob
matches at least `AUTONOMOUS_PLAN.md`. **Not** confirmed: whether it also fires
for `DECISIONS.md` — it does not match that filename, by design. If a future
session wants `DECISIONS.md` to trigger the same rule, the pattern needs
widening.

Also unverified: whether non-Kiro agents actually comply. The header is a request
to them, not an enforcement. See notes below.

**Blocked / open:** No change. **O1** and **O2** from Entry 001 remain open. O1
still gates nothing structural but changes the default on every floor-constrained
SKU, so it is worth answering before Phase C2.

**Plan changed?:** Yes — header and companion-files table added. No task,
phase, rule or scenario was altered, added or removed. Checkbox count unchanged
at 247, which is the check that proves it.

**Decisions added to DECISIONS.md:** none. The tracker mechanism is process, not
architecture, so it did not warrant a `D<n>` record.

**State after this session:**
- Phases A-H: **not started.** Still zero implementation.
- Planning: complete
- Handoff infrastructure: complete
- Estimated remaining effort unchanged: 36-50 sessions for all phases, 18-24 for
  the reduced-scope cut

**Next recommended step:** Unchanged from Entry 001 — answer **O1**, then begin
**Phase A1** (schema additions + migration). Before acting on the three code
claims flagged as unverified in Entry 001, re-confirm them; the
`INSUFFICIENT_DATA` → `BLOCKED` one in particular is load-bearing for Phase E.

**Notes for the next agent:**
- **Use `fs_append` for this file, never `fs_write`.** `fs_write` overwrites and
  would destroy the log in one call. This is the single easiest way to break the
  rule by accident.
- If you are **not** running in Kiro, the steering file will not fire for you.
  The header in `AUTONOMOUS_PLAN.md` is your instruction. Consider adding a
  pointer to your own tool's convention file (`CLAUDE.md`, `AGENTS.md`) so the
  obligation survives a tool switch — the user works across Claude, ChatGPT and
  Kiro, so tool switches are expected rather than exceptional.
- A `.claude/` directory already exists in this workspace with settings but no
  `CLAUDE.md`. One was deliberately **not** created this session, to avoid adding
  files the user did not ask for. It is a reasonable thing to add if a Claude
  Code session finds it useful.
- Checkbox count is a cheap integrity check on the plan. It was 247 at Entries
  001 and 002. If you legitimately add or complete tasks it will move — just know
  the baseline so an accidental truncation is obvious.

---

### Entry 003 — 2026-09-11 — Claude Opus 5 (Kiro) — verification

Short correcting entry. Appended rather than folded into Entry 002 because rule 1
forbids editing an existing entry — this is the discipline working as intended.

**Read:** `AUTONOMOUS_TRACKER.md` (own Entries 001-002)

**Phase / tasks touched:** none

**Files created:** none

**Files modified:**
- `AUTONOMOUS_TRACKER.md` — **rule 2 rewritten** (the RULES block, not an entry;
  entries remain untouched). Declared transparently here so the change is not
  silent.

**Did:** Ran a git-based integrity check on the tracker and discovered
**this workspace is not a git repository** — `git status` returns "fatal: not a
git repository (or any of the parent directories): .git".

That invalidates the verification mechanism I gave future agents in Entry 002 and
in the original rule 2: `git diff` cannot prove append-only here because there is
no history to diff against. A rule that cannot be checked is not a rule.

Rewrote rule 2 to give a working alternative: **monotonic growth in file size and
entry count**, with recorded baselines so each agent can verify against the
previous session's figures. Kept the git check as the preferred method for
whenever the repo is initialised, and promoted the `fs_append`-not-`fs_write`
warning into rule 2 itself, since that is the actual failure mode the rule guards
against.

**Verified:**
- Not a git repo — confirmed by `git status` and `git diff` both failing with
  "not a git repository"
- Entry sequence intact: 001, 002, 003 present, in order, none renumbered
- No prior entry text altered — only the RULES block above the log
- Growth check passes: 8,174 B / 1 entry (001) → 13,052 B / 2 entries (002) →
  larger still now

**NOT verified:** The new size/entry baseline for this entry was not captured
after the append (chicken-and-egg — the number changes as the entry is written).
The next agent should read the current size, record it, and use it as their
baseline.

**Blocked / open:** One **new** question for the user, in addition to O1 and O2:

- **O3 — should this workspace be initialised as a git repository?** It is not
  one today. That means: no history, no way to recover a file an agent
  overwrites, no diff-based review of agent changes, and the strongest
  append-only guarantee is unavailable. Given the plan spans 36-50 agent sessions
  across multiple tools, working without version control is the single largest
  unmanaged risk in this project — considerably larger than any design question
  still open. Not initialised unilaterally because that is a repo-level action
  the user should choose.

**Plan changed?:** no

**Decisions added to DECISIONS.md:** none

**State after this session:**
- Phases A-H: **not started**
- Planning: complete
- Handoff infrastructure: complete, and now self-consistent (the append-only rule
  is checkable in this workspace as it actually is, not as it was assumed to be)
- **No version control** — see O3

**Next recommended step:** Answer **O3** first; if git is wanted, initialise and
commit the three planning documents before any implementation begins, so Phase A
onward is recoverable. Then **O1**, then **Phase A1**.

**Notes for the next agent:**
- Do not trust `git` commands in this workspace until O3 is resolved. They fail,
  loudly but confusingly — the error text is long and easy to misread as a
  different problem.
- The lesson generalises: when this project's own documents tell you to verify
  something a particular way, confirm the *mechanism* exists before relying on
  it. I wrote a rule referencing a tool that was not present and only caught it
  because I ran the check instead of assuming it would pass.

---

### Entry 004 — 2026-09-11 — Claude Opus 5 (Kiro) — handoff

**Read:** `AUTONOMOUS_TRACKER.md` (Entries 001-003), workspace file inventory

**Phase / tasks touched:** none — no implementation performed

**Files created:**
- `d:\future\Vitrious_BASELINE_2026-09-11\` — full verified snapshot (122 files)
- `d:\future\Vitrious_BASELINE_2026-09-11\BASELINE_MANIFEST.sha256` — 122 hashes
- `d:\future\Vitrious_BASELINE_2026-09-11\RESTORE.md` — restore procedure
- `d:\future\Vitrious_BASELINE_2026-09-11.zip` — 1.88 MB, 123 files

**Files modified:** `AUTONOMOUS_TRACKER.md` (this entry only)

**Did:** Created a pre-implementation baseline backup at the user's request, so
the working submission survives if the autonomous rebuild is not finished.

Placed **outside** the workspace as a sibling directory, deliberately: a backup
inside the folder it protects is worth much less, and a destructive operation in
`Vitrious` cannot reach it. Two independent copies exist — a browsable folder and
a zip — so losing one does not lose the baseline.

Excluded 97 cache files (~1 MB): `__pycache__`, `.pytest_cache`, `.DS_Store`, and
a Word `~$` lock file. Nothing functional omitted. **Included**
`database/inventra.db` and `submission/checkpoints.sqlite` on purpose, so demo
state and any paused cases restore too, not just source.

`RESTORE.md` documents the state honestly, including the four known defects
carried from Entries 001-003, so whoever restores is not misled into thinking the
baseline is clean.

**Verified:**
- SHA256 manifest comparison of source vs backup: **122 files, 122 matches, zero
  mismatches**. Not trusting robocopy's own summary — hashed both trees and
  compared with `Compare-Object`
- Zip contains **123** files (122 + manifest), matching expectation
- Backup destination checked for pre-existence before writing; would have aborted
  rather than overwrite
- Confirmed `submission/.env` **is** in the backup (needed to restore a running
  system) and flagged as a secret in `RESTORE.md`. Its contents were never read
  or echoed

**NOT verified:** The restore procedure in `RESTORE.md` was **not executed**.
Commands are written and reviewed but untested — testing them would mean
destroying the working copy. Treat the restore path as unproven; read it before
running it, and rename rather than delete, which is what the procedure says.

Also not verified: that the baseline actually runs. `python -m submission.app run`
was not invoked against the backup copy. It is byte-identical to a workspace the
user has been running, so this is low risk, but it is an assumption not a check.

**Blocked / open:** No change. **O1**, **O2**, **O3** remain open. O3 (git) is now
partially mitigated — a snapshot exists — but only as a single point in time.
There is still no incremental history, so work done between now and the next
manual backup remains unprotected.

**Plan changed?:** no

**Decisions added to DECISIONS.md:** none — backup is operational, not
architectural

**State after this session:**
- Phases A-H: **not started.** Still zero implementation.
- Planning: complete
- Handoff infrastructure: complete
- **Baseline backup: complete and hash-verified.** Safe to begin destructive
  implementation work.
- Tracker size at time of writing Entry 003's completion: 17,471 bytes / 3
  entries. Use that as the growth baseline (rule 2).

**Next recommended step:** Answer **O3** (git), then **O1**, then **Phase A1**.
The baseline removes the catastrophic-loss risk, so implementation can now start
even with O3 unresolved — but without git, any single agent mistake costs
everything since this snapshot.

**Notes for the next agent:**
- **The baseline is a point-in-time snapshot, not ongoing protection.** If you
  complete a phase and it works, either commit it (if O3 is resolved) or take a
  fresh dated snapshot the same way. Do not let a week of work sit unprotected on
  the strength of this one.
- `Compress-Archive` floods the terminal with progress-bar redraws — tens of
  thousands of characters, enough to truncate the output and hide the result. Set
  `$ProgressPreference = 'SilentlyContinue'` first.
- Robocopy exit codes **0-7 are success**, not just 0. It returned 1 here, which
  is normal ("files copied"). Do not read that as failure.
- Do not trust a copy tool's own summary as verification. Robocopy reported "2
  skipped" which looked alarming and was simply the two files intentionally
  excluded — only the hash comparison proved the backup was complete.

---

### Entry 005 — 2026-09-11 — Claude Opus 5 (Kiro) — docs

**Read:** `AUTONOMOUS_TRACKER.md` (Entries 001-004),
`Inventra_Agent_Readable_Pack/07_inventra_student_design_challenge.md` (deliverables
list), `submission/README.md`, `submission/design.md`, `submission/test_report.md`,
`submission/app.py`, `submission/config.py`, `submission/agents/models.py`,
`tools/sales.py`, `tools/execution.py`, `submission/graph/nodes.py` (compute_risk)

**Phase / tasks touched:** none of Phases A-H. This was submission documentation
for the **existing** system, not autonomous-monitor work.

**Files created:**
- `requirements.txt` (repo root) — pinned to the verified environment

**Files modified:**
- `submission/README.md` — full rewrite
- `submission/test_report.md` — full rewrite
- `submission/design.md` — two targeted fixes
- `AUTONOMOUS_TRACKER.md` (this entry)

**Did:** Rewrote the submission documentation against **live verified behaviour**
rather than the brief or the previous docs. Ran the system repeatedly, seeded
fresh, executed every seeded SKU, and completed a full approve-to-write cycle.

The existing docs were materially stale. Findings, all verified by running:

1. **`README.md` was wrong on its headline limitations.** It claimed "there is no
   reorder guard" and "an approved order does not reserve budget, so cancelling
   one releases nothing." **Both are false.** Proven live: `committed_amount`
   moved 5000 → 9200 on approving a $4200 order (exact), and re-running AC-003
   after its 14-unit order returned `NO_ACTION` instead of a duplicate proposal
   (15 + 14 = 29 units → 14.5d cover > 14d target).
2. **`requirements.txt` did not exist.** The README's first setup command
   referenced a missing file, so the documented install path was broken. Created
   it, pinned to the live environment; `pip install --dry-run` resolves clean.
3. **Test counts were wrong in both docs.** README said 81 across 16 files,
   `test_report.md` said 129 across 22. Actual: **136 across 23**, ~85s.
4. **The README's demo section did not work.** It claimed `AC-001 DEL-01`
   demonstrates `NO_ACTION` — it actually produces a proposal. It claimed AC-005
   triggers `INSUFFICIENT_DATA` — it produces `NO_ACTION`.
5. **`AC-001` is nondeterministic and unusable as a demo.** 7-day window → 15.56d
   cover (not at risk); 30-day → 13.79d (at risk). The outcome depends on which
   window the LLM Demand Analyst picks; observed both outcomes from identical
   seed data. **AC-003 is the only SKU that reliably reaches
   `AWAITING_APPROVAL`.**
6. **`tools/sales.py` understates velocity.** It divides the window total by the
   window *length* rather than the observed day count, so the 7-day window
   (6 observations against a divisor of 7) reports 2.57/day for a SKU selling a
   steady 3.00. Biased low by ~1/7, which is what puts AC-001 on the threshold.
   Starter-package behaviour, left unmodified.
7. **`INSUFFICIENT_DATA` rule is "fewer than 3 observations in either window",**
   so AC-005's 14 days never triggers it. The seed comment claiming otherwise is
   misleading. Confirms Entry 001's flagged claim (item 2) — and confirms the
   related off-spec `BLOCKED`-instead-of-`NEEDS_INFORMATION` finding, which
   Phase E depends on.
8. **`app.py::_print_cancellation` prints a false statement** — "no budget was
   released; creating a request never reserved any." Contradicts actual
   behaviour. Documented as a known limit; **not fixed**, since fixing code was
   outside this task.
9. **`design.md` diagram was stale** — missing `await_window_choice` (1 of the 3
   interrupts) and the entire `apply_human_edit` / EDIT path. Its `PolicyReview`
   schema omitted the 8-row checklist and its validator. Both fixed.
10. **The contradictory budget tests from Entry 001 are confirmed real.** Both
    pass only because they use different warehouses. Live behaviour matches
    phase-11; the phase-10 assertion encodes superseded behaviour.

**Verified:**
- `136 passed in 83.79s`, exit 0, **re-run after all documentation work** so the
  README's claim holds in the delivered state
- Live CLI outcomes for all 8 seeded SKUs at DEL-01, from a fresh seed
- Full happy path: `run AC-003 DEL-01` → `AWAITING_APPROVAL` → `resume APPROVED`
  → `PURCHASE_REQUEST_CREATED PR-97C15FDC7DA7 created=True total_cost=4200.0`
- Budget reservation and reorder guard, by direct DB inspection before/after
- `pip install -r requirements.txt --dry-run` → no errors, no conflicts
- `design.md` edits present at lines 62-66 and 91-95
- Live provider confirmed: `provider=vertex model=gemini-2.5-flash-lite
  duration_s=7.5-9.5 ok=True` (note `config.model_provider` defaults to
  `gemini`; this machine's `submission/.env` sets `vertex`)

**Caught my own error during verification:** I first wrote AC-006 as
`AWAITING_APPROVAL`, inferred from its risk arithmetic (5.2d cover vs 14d
target). Running it showed `BLOCKED — No eligible vendor options (reliability or
deadline)`: it is at risk, but no supplier clears both the 0.90 reliability bar
and the arrival deadline. Corrected in three places. **Inference from the numbers
was not good enough; only running it was.** It turned out to be the cleanest demo
of brief scenario 12.

**NOT verified:**
- The Mermaid diagrams were not rendered. Syntax is conventional and node/edge
  content was cross-checked against `build_graph()` line by line, but no
  renderer confirmed they draw.
- Streamlit UI (`streamlit run submission/ui.py`) was **not launched**. Screen
  descriptions come from reading `ui.py` and `portfolio.py`, not from using it.
- Email and the approval-link server were **not exercised** — needs real Gmail
  credentials, and `smtp_host` is hardcoded so no local catcher can substitute.
- Individual SUITE-marked rows in `test_report.md` were carried forward from the
  previous version. The suite passes as a whole and the named tests exist, but I
  did not run each named test in isolation to confirm it proves the row it is
  cited for. LIVE-marked rows I ran myself.
- `requirements.txt` was not installed into a clean venv — only dry-run resolved.
  A fresh-machine install could still surface a missing transitive pin.

**Blocked / open:** **O1**, **O2**, **O3** unchanged. One new observation, not a
question: the false string in `app.py::_print_cancellation` is a one-line code
fix that would remove a documented-but-avoidable inaccuracy. Left alone
deliberately; worth doing before submission.

**Plan changed?:** no

**Decisions added to DECISIONS.md:** none — documentation work, no new
architecture

**State after this session:**
- Phases A-H: **not started.** Still zero autonomous-monitor implementation.
- Submission docs: **complete and verified against running code.** All brief §7
  deliverables present — `design.md` (architecture diagram, 3 agent charters,
  tool-permission matrix, state design, "what was deliberately not made
  agentic"), `README.md` (setup/run/demonstration), `test_report.md` (scenarios
  passed + known limits), plus `requirements.txt`
- Baseline backup from Entry 004 predates these doc changes — it holds the
  **stale** README. Fine as a fallback, but not a copy of current docs.

**Next recommended step:** Consider a fresh baseline snapshot capturing the
corrected docs (the Entry-004 backup has the stale README). Then **O3** → **O1**
→ **Phase A1**.

**Notes for the next agent:**
- **Use `AC-003 DEL-01` for any demo that needs to reach approval.** AC-001 is
  on the risk threshold and flips outcome depending on the LLM's window choice.
- `README.md §9 Gotchas` and `test_report.md §4 Deviations` now hold the
  verified oddities. Read them before trusting any number in the older docs;
  `PLAN.md`, `GAP_FIX_PLAN.md` and `UPGRADES.md` were **not** reviewed this
  session and may carry the same stale claims the README did.
- The `tools/sales.py` divide-by-window-length bug matters for Phase B. Any
  velocity statistic built on `get_sales_velocity` inherits the ~1/7 low bias.
  Phase B should compute μ and σ from `sales_daily` directly.
- Running the suite takes ~85s and mutates the database. Re-seed with
  `python database/seed.py && python -m submission.tests.seed_extra` before
  capturing any output intended for documentation.
- PowerShell reports exit code 1 whenever anything reaches stderr, including
  deprecation warnings. `136 passed` with exit 1 is a pass. Do not chase it.

---

### Entry 006 — 2026-09-11 — Claude Opus 5 (Kiro) — verification

Correcting entry. **Entry 005 contains two wrong diagnoses.** Appended rather
than folded in, per rule 1.

**Read:** `submission/prompts/demand.py`, `tools/sales.py` (window boundary),
`tools/execution.py::cancel_purchase_request` (return + audit payload),
`submission/tests/test_phase10_cancel_purchase_request.py` (`_insert_request`
helper and the budget test), plus a direct SQL measurement of AC-001's
`sale_date` range against today.

**Phase / tasks touched:** none

**Files modified:**
- `submission/README.md` — §9.1 rewritten; the "contradictory tests" limit replaced
- `submission/test_report.md` — velocity and test-contradiction limits replaced;
  new limit added for the borderline-SKU design gap
- `submission/design.md` — §4.1 Input corrected; known gap documented
- `AUTONOMOUS_TRACKER.md` (this entry)

**Did:** The user asked whether the three findings in Entry 005 were
implementation bugs, data bugs, or something else. Investigating properly showed
**two of my diagnoses were wrong**, both because I inferred from partial evidence
instead of reading the code.

**Correction 1 — `tools/sales.py`. Right bug, wrong cause.**
Entry 005 said it "divides by the window length, not the observed day count,"
implying the divisor is the defect. The divisor is **correct**: dividing by
calendar days is the right choice for demand planning, because a genuine
zero-sales day must count as a zero (stock drains on calendar time). Dividing by
observed days computes units per *selling* day and would badly overstate
intermittent demand — the standard spare-parts forecasting trap. My implied fix
would have introduced a worse bug.

The actual defect is the **window boundary**. `sale_date > today - N` spans
`today-(N-1) … today`, which includes **today** — a day that can never hold
complete data. Measured on AC-001 (sells exactly 3/day), today 2026-09-11: sales
run 08-12 → 09-10; the 7-day window resolves to `> 2026-09-04` = 6 rows, 18
units, 18/7 = 2.5714. Moving the boundary to the last 7 *complete* days gives
21/7 = **3.0000** with the divisor untouched. Same off-by-one on the 30-day
window (29 rows ÷ 30 = 2.9000). Not a seed artifact — a real nightly-ETL system
also lacks today's row.

**Correction 2 — the "contradictory budget tests" claim is withdrawn.**
Entry 005 (item 10) and Entry 001 both said
`test_phase10_cancel_purchase_request.py` and `test_phase11_budget_and_reorder_guard.py`
contradict each other and coexist "because they use different warehouses." **Both
halves were wrong**, and I asserted it from a grep without reading the test.

`_insert_request()` writes a `purchase_requests` row **directly via SQL** and its
INSERT column list **omits `committed_budget_month`**. So no reservation was ever
made for that row; on cancel `committed_budget_month` is NULL, `budget_released`
is `False`, and `committed_amount` is correctly unchanged. That is the
legacy-row path `cancel_purchase_request` documents explicitly. The two tests
cover **genuinely different scenarios and are both correct.** Only the phase-10
docstring ("create_purchase_request never increments committed_amount") and the
test name are stale. The coverage should be kept.

**Correction 3 — my hypothesis about the Demand Analyst was wrong, and
`design.md` was wrong too.**
I expected the agent to be starved of the stock position. It is not:
`prompts/demand.py::build_user_message` passes `sku`, `warehouse_id`,
**`target_cover_days`**, `product` and the full **`stock`** snapshot. So
`design.md §4.1`'s claim "No stock, no vendor, no budget data" was **factually
wrong** (pre-existing, not introduced by me). Corrected.

The real cause of the AC-001 flip is a **design gap, not a bug**: the agent's
ambiguity criterion is framed on *relative disagreement between the two
velocities*, while the decision-relevant question is whether the choice *changes
the outcome*. AC-001's windows differ by only 12.8% yet straddle the threshold
(15.56d healthy vs 13.79d at risk against a 14-day target). The system prompt
also forbids the agent from computing cover days, so it cannot see the flip even
with the data in hand.

**New finding — an internal inconsistency worth more than the bug itself.**
`portfolio.scan_portfolio()` already handles this case correctly: it computes risk
on **both** windows, takes `worst = min(..., key=cover_days)`, and labels the row
`Borderline` with "between X and Y days depending on which trend holds." The case
graph does neither. So the watchlist and the graph can disagree about the same
SKU, and the conservative logic needed to fix the graph already exists in the
same repository.

**Final classification:**
| Finding | Type |
|---|---|
| AC-001 flips outcome | **Design gap.** Ambiguity measured on the wrong quantity |
| `sales.py` velocity low | **Implementation bug** — off-by-one window boundary (starter package) |
| `app.py` cancellation string | **Stale output string.** Cosmetic, misleading. Logic is correct |
| "contradictory tests" | **Not a defect.** Withdrawn |

**Verified:**
- Window arithmetic proven by direct SQL: AC-001 sale_date 2026-08-12 → 2026-09-10
  (30 rows, every `units_sold` = 3); 7d boundary `> 2026-09-04` → 6 rows/18 units;
  30d boundary `> 2026-08-12` → 29 rows/87 units. 18/7=2.5714, 18/6=3.0,
  87/30=2.9, 87/29=3.0
- `prompts/demand.py` evidence dict read in full — confirms `stock` and
  `target_cover_days` are passed
- `_insert_request()` read in full — confirms direct SQL and the omitted column
- `budget_released` confirmed present in the **audit payload** but **absent from
  `CancellationResult`**, so the `app.py` fix is either deleting the line or adding
  a model field, not simply printing an existing value

**NOT verified:**
- **No code was fixed.** All four items remain in the codebase exactly as
  described; only the documentation now describes them correctly.
- Did not re-run the test suite this session — no code changed, only markdown.
  Last known state: 136 passed (Entry 005).
- Did not check whether `PLAN.md`, `GAP_FIX_PLAN.md`, `UPGRADES.md` or
  `GAP_NEEDS_INFORMATION.md` repeat the same withdrawn claim about the two budget
  tests. **They may.** Worth grepping before submission.

**Blocked / open:** O1, O2, O3 unchanged.

**Plan changed?:** no. But note for Phase B: the fix for the velocity bug is
"define the window over complete days", **not** "divide by observed days". Entry
005's note said the latter and was wrong.

**Decisions added to DECISIONS.md:** none

**State after this session:**
- Phases A-H: **not started**
- Submission docs: complete, and now **correctly** diagnosing four known issues
- Four known issues documented, **zero fixed**

**Next recommended step:** Unchanged — O3 → O1 → Phase A1. If a quick
pre-submission cleanup pass is wanted, the cheapest three wins are: delete the
false string in `app.py::_print_cancellation`, fix the phase-10 test docstring and
name, and grep the older plan documents for the withdrawn "contradictory tests"
claim.

**Notes for the next agent:**
- **Do not "fix" `sales.py` by dividing by the observed day count.** It looks
  right on this seed only because the seed has no true zero-demand days. It breaks
  intermittent demand. Fix the window boundary instead.
- Twice this session I asserted something from a grep or from arithmetic
  inference and was wrong (AC-006's outcome in Entry 005, and both corrections
  here). Both times only reading the full file or running the command caught it.
  In this codebase, partial evidence has a bad track record.
- `portfolio.py` is worth reading before changing risk logic in the graph — it
  already contains the conservative both-windows treatment the graph lacks.

---

### Entry 007 — 2026-09-12 — Claude Opus 5 (Kiro) — implementation + docs

Two distinct pieces of work in one session: a **code change to the shipped
submission** (the vendor comparison was ranking on the wrong quantity), and the
**plan amendment that follows from it** (§A6, §B10). Phases A-H remain not
started; nothing in this entry begins them.

**Read:** `AUTONOMOUS_TRACKER.md` (rules + Entry 006), `AUTONOMOUS_PLAN.md` (full),
`submission/graph/economics.py` (full), `submission/graph/nodes.py`
(`build_options`, `_validate_recommendation`, `compute_risk`),
`submission/config.py`, `submission/prompts/strategist.py`,
`submission/prompts/policy.py`, `submission/ui.py` (`_money`, `_approval_notes`,
`_render_approval`, `_render_order_proof`, supplier-switch expander),
`submission/agents/stubs.py`, `domain/tool_models.py` (VendorPerformance,
VendorOption), `submission/tests/test_phase6_revision_and_ui_reads.py`,
`submission/tests/test_phase9_policy_evidence_gap.py`, `DECISIONS.md` (D25, D26,
reversals table), `PLAN.md` §4 economics block, `submission/design.md`,
`submission/README.md`.

**Phase / tasks touched:** none of A-H. Plan sections **amended**: §A1, §A6 (new),
§B7, §B10 (new), §1 R10, what-already-exists table, scenario catalogue, open
decisions, Phase H, dependency order.

**Files created:** none

**Files modified:**
- `submission/graph/economics.py` — rewritten ranking (see below)
- `submission/config.py` — 4 new declared assumptions
- `submission/graph/nodes.py` — gate + audit payload
- `submission/agents/stubs.py` — stub strategist
- `submission/prompts/strategist.py` — v2 → v3
- `submission/prompts/policy.py` — cites the right field
- `submission/ui.py` — `_md()` added; approval note rewritten; ~12 render sites
- `submission/tests/test_phase6_revision_and_ui_reads.py` — 3 tests rewritten, 4 added
- `submission/tests/test_phase9_policy_evidence_gap.py` — field name
- `DECISIONS.md` — D29 + 2 reversals-table rows
- `PLAN.md`, `submission/design.md`, `submission/README.md` — stale rule corrected
- `AUTONOMOUS_PLAN.md` — see above
- `AUTONOMOUS_TRACKER.md` (this entry)

**Did:**

**Part 1 — the ranking bug (D29).** The user pushed back on the approval card's
claim that FastShip was "cheaper overall" on AC-004/DEL-01, and was right. The two
halves of the economics module contradicted each other: `required_quantity` sizes
per supplier from that supplier's lead time (correct — the target is N days of
cover *from arrival*, so a slower supplier funds more days of demand and needs
more units), and then `min(options, key=lambda o: o.total_cost)` compared those
different-sized orders by invoice total. Measured on the real seed at
target 14: FastShip 37u/$18,500/$510.20 per unit delivered vs Standard
42u/$18,900/$478.72. The old rule picked FastShip and the validation gate then
*forced* it. The system was overpaying for stock while telling the approver it was
saving money.

Ranking is now `all_in_cost_per_day_of_cover`. Sizing untouched. Three guards
added because normalising the metric removed the only brake: MOQ overshoot earns
no coverage credit; inventory carrying cost now exists (it did not, anywhere); and
delivery risk is priced per option from its own on-time rate against its own slack,
replacing a pairwise premium test that valued a premium option's buffer using that
option's own lateness probability and only worked with exactly two options.
Verdicts collapsed to `best_value_option` / `within_value_tolerance` /
`worse_value_option`, old names kept as aliases.

**I rejected one approach mid-session and the reasoning matters.** My first
proposal was to size every supplier to a shared horizon so the invoice comparison
becomes valid. The user rejected it correctly: it only works by giving the faster
supplier 11 days of post-arrival cover against a 10-day requirement, i.e. changing
the requirement so the arithmetic comes out tidier. The requirement is not
negotiable to suit the metric.

**Part 2 — the note was unreadable (a rendering bug, not a text bug).** The user
posted a screenshot of the approval card rendering as run-together glyphs.
Streamlit's markdown supports LaTeX, so a **pair** of `$` is read as math
delimiters. The note quotes six amounts, so it became three back-to-back
equations. Same bug was silently mangling the budget caption, the "Why this
supplier" rationale and the order-detail table. Added `ui._md()` (escapes `$` →
`\$`) at ~12 render boundaries. Escaped at the boundary rather than inside
`_money` because `st.metric` values are not markdown-parsed and would show the
backslash literally, and because agent prose and revalidation error strings carry
`$` without going through `_money`. Also rewrote the note as four short paragraphs
— it was a ~90-word block that appended `verdict_explanation`, repeating the
per-day figure and unit count twice.

**Part 3 — the plan amendment (what the user actually asked for last).** D29 made
four inputs visible as declared assumptions printed on the approval card. §A6
turns each into data with an explicit mapping (assumption → config knob → data →
consumer), and §B10 specifies the pure functions. §A6.2 names two things the
comparison ignores **entirely** today and that I had not previously flagged:
**freight** (the comparison is ex-works; `vendor_offers` has `unit_price` and
nothing else) and **payment terms**. §A6.3 names four things as deliberately out
of scope rather than overlooked: quantity-break pricing, stockout cost beyond lost
contribution, substitution, shelf life.

**Verified:**
- **140 tests pass** (`python -m pytest submission/tests -q`), up from 136 at
  Entry 005. Exit code 1 is the urllib3 stderr warning — Entry 005's note about
  that is still accurate.
- The recommendation **actually flips on real seeded data.** Ran the graph on
  AC-004/DEL-01, AC-003/DEL-08, AC-003/DEL-01 with a throwaway script and printed
  every option's figures. AC-004 now proposes Standard Supplier
  ($1,441.35/day) over FastShip ($1,535.68/day); `cheapest_offer_id` and
  `best_value_offer_id` genuinely differ on that case. Script deleted after use.
- AC-003/DEL-08 was the old `free_upgrade` tie case (both $5,400). Now resolved on
  merit: BudgetVendor $200/unit delivered beats FastShip $306.12. The total-cost
  tie was itself the artefact.
- The escaping was verified by rendering `_approval_notes` output through `_md`
  and inspecting the actual string, not by reasoning about it. Caught a real
  second-order defect that way: `from FastShip Inc..` (seeded vendor names end in
  a period), fixed by reordering the sentence.
- New regression tests: `test_the_smallest_invoice_is_not_the_best_value`,
  `test_a_near_tie_that_arrives_earlier_is_left_to_the_agent`,
  `test_a_supplier_minimum_earns_no_coverage_credit`,
  `test_amounts_in_approver_text_are_escaped_so_streamlit_does_not_typeset_them`.

**NOT verified:**
- **Nothing in §A6 or §B10 has been built.** They are specification only. No
  schema column, no table, no function exists.
- **Nothing was rendered in a real browser.** The escaping fix is verified at the
  string level and by `AppTest` (which executes `ui.py` for the watchlist only).
  I did not run `streamlit run` and look at the approval screen. Someone should,
  once, before submission — a rendering bug is exactly the class of defect that
  string assertions miss, which is how this one survived 139 tests.
- Did not check whether the same `$`-pair bug affects `notifications/email.py`. It
  builds its own HTML with a separate `_money` and should be immune, but I did not
  confirm it, and I did not send a test email.
- Did not grep the older plan documents (`GAP_FIX_PLAN.md`, `UPGRADES.md`,
  `GAP_NEEDS_INFORMATION.md`) for the now-superseded premium-justification rule.
  **They almost certainly repeat it** — Entry 006 flagged the same risk for the
  withdrawn "contradictory tests" claim and that grep was never done either.
- The four `config.assumed_*` values (25% margin, 20% carrying, 1 day late, billed
  on ordered) are **my defaults, not the user's business figures.** Every verdict
  in the system currently moves if they are wrong. O4 and O5 exist because of this.

**Blocked / open:** O1, O2, O3 unchanged. **Two new, both business facts that
cannot be derived from the schema:**
- **O4 — do suppliers invoice for units ordered or units shipped?** At a 0.94 fill
  rate this is ~$780 on a single 29-unit order, enough to move a verdict. Default
  is `ORDERED`, which is what the code already silently assumed; I made it explicit
  and configurable rather than continuing to assume it quietly.
- **O5 — is `selling_price` a single list price, or does it vary by region/promotion?**
  Worth answering *before* seeding 35 SKUs, because a single wrong figure produces
  a confidently wrong contribution number, which is worse than today's honest caveat.

**Plan changed?:** **yes.** §A6 and §B10 are new; §A1, §B7, §1 R10, the
what-already-exists table, the scenario catalogue (4 revised, 23-26 added), open
decisions (O4, O5), Phase H and the dependency graph all changed. Two amendments
worth calling out because they alter existing agreements:
1. **§A1 previously said "delete the two apologetic caveats."** There are now
   **five** — D29 turned three silent assumptions into stated ones. The count in
   the plan was wrong the moment D29 landed.
2. **§1 R10 (fail closed) now carries one named exception.** The four economics
   refinement inputs fall back to config with a per-figure caveat instead of
   blocking. Blocking a reorder because a warehouse lacks a storage rate trades a
   stockout for a bookkeeping gap. The line drawn: fail closed on facts that decide
   *whether to act*, fall back with a named caveat on facts that only refine *how
   much to pay*.

**Decisions added to DECISIONS.md:** **D29** — suppliers are compared on cost per
day of cover, not total cost. Includes the rejected shared-horizon alternative, the
three guards, and why the agent keeps a bounded near-tie choice. Two rows added to
the reversals table.

**State after this session:**
- Phases A-H: **not started** (unchanged from Entry 006)
- Submission codebase: **one real defect fixed** (vendor ranking) and **one real
  rendering defect fixed** (LaTeX escaping), 140 tests green
- Four previously-documented known issues from Entry 006: **still zero fixed**
- Plan: amended with the data requirements that follow from D29

**Next recommended step:** Unchanged in shape — O3 → O1 → Phase A1 — but O4 and O5
are now on the same list and both are one-line answers from the user. If a code
session is wanted instead, **A6.1 #1 (`products.selling_price`) is the cheapest
real win in the whole plan**: one column, one function, deletes the most prominent
caveat on the approval card, and `evaluate_options` already takes its inputs from
one place so the change is local.

**Notes for the next agent:**
- **`evaluate_options` is ranked on `all_in_cost_per_day_of_cover`, not
  `total_cost`.** If you find code or docs asserting "cheapest total wins", it is
  stale. The stub strategist in `agents/stubs.py` was doing exactly that and six
  tests failed closed the moment the gate started enforcing value — that was the
  gate working correctly, not a break. I only found the stub; check for other
  callers making the same assumption.
- **Do not "fix" the comparison by sizing every supplier to a shared horizon.** It
  was proposed and rejected this session. It silently changes the cover
  requirement. See D29's rejected-alternative note before re-deriving it.
- **Streamlit renders `$...$` as LaTeX.** Any new approver-facing string quoting
  two amounts must go through `ui._md()`. This bug was invisible to 139 tests
  because the strings were always correct — only the rendering was wrong.
- Entry 006's warning about partial evidence held again this session. The
  double-period defect and the AC-003 tie resolution were both found by *running*
  the thing and reading the output, not by reasoning about the code.
- The four `assumed_*` config values are load-bearing on every verdict. Treat them
  as placeholders awaiting O4/O5, not as settled figures.

### Entry 008 — 2026-09-12 — Claude Sonnet 5 (Kiro) — planning

**Read:** `AUTONOMOUS_PLAN.md` (full, both halves via two reads), `AUTONOMOUS_TRACKER.md`
(Entries 001-007, full), `DECISIONS.md` (D25-D29 region + heading list),
`policy.md` (full), `fixtures/scenarios.json` (full), `database/schema.sql`
(full), `database/migrate.py` (full), `database/seed.py` (via context-gatherer,
not read directly this session), `submission/config.py` (full),
`submission/graph/economics.py` (lines 1-440, via direct read + context-gatherer),
`tools/sales.py` (full), `tools/vendors.py` (full), `domain/tool_models.py`
(via context-gatherer only), `tools/inventory.py`, `tools/execution.py`,
`tools/policy.py`, `tools/memory.py`, `tools/langchain_tools.py` (all via
context-gatherer summary only, not read directly).

**Phase / tasks touched:** Planning only, for Phase A (A1-A6 of
`AUTONOMOUS_PLAN.md`). No implementation. No checkbox in `AUTONOMOUS_PLAN.md`
was ticked — this session produced a *sub-plan*, not completed work.

**Files created:**
- `PHASE_A_PLAN.md` (repo root) — a detailed execution plan for Phase A only:
  ground-truth corrections against the actual current schema/code, exact
  migration mechanics (`migrate.py`'s current column-only limitation and the
  new-table step it needs), a 9-step build order (schema → migrate → domain
  models → 3 new tool modules → fabricator module → seed rewrite →
  regression check), an A6-items-to-steps mapping table, three flow diagrams,
  session-sized execution ordering, concretely-checkable exit criteria, an
  explicit out-of-scope list, and new open questions surfaced by this review.

**Files modified:** `AUTONOMOUS_TRACKER.md` (this entry only)

**Did:** The user asked for a full, detailed Phase A plan they could follow
along with, without any implementation yet. Rather than restate
`AUTONOMOUS_PLAN.md`'s §Phase A checklist, I dispatched a context-gatherer
sub-agent across `database/`, `submission/graph/economics.py`,
`submission/config.py`, `domain/tool_models.py`, and every module in `tools/`,
then read the highest-risk files directly myself (`schema.sql`, `migrate.py`,
`config.py`, `sales.py`, `vendors.py`, `economics.py` lines 1-440,
`scenarios.json`, `policy.md`) to verify the sub-agent's claims rather than
trust them blind, per this session's own investigate-before-answering rule.

That verification caught real gaps between the plan's prose and the actual
code, all recorded in `PHASE_A_PLAN.md` §1's "ground truth" table:
- **No `warehouses` table exists today.** `warehouse_id` is a bare TEXT
  column on 4 different tables with no FK anywhere; `portfolio.py` derives
  the warehouse list via `SELECT DISTINCT`. The plan's A1 checklist adds
  `warehouses.storage_cost_per_m3_month` as if the table already existed —
  it needs to be created, not altered.
- **No `vendor_performance` table exists.** It's computed live in
  `tools/vendors.py::get_vendor_performance()` from `vendors`' three rate
  columns every call. Confirmed by reading the function body directly.
- **`migrate.py` cannot create tables today** — only `ALTER TABLE ADD COLUMN`
  on tables that already exist, and it explicitly skips-with-a-warning if the
  table is absent (its own docstring says "Columns only"). A1's five new
  tables (`warehouses`, `stock_receipts`, `sku_policy`, `policy_rules`,
  `parked_items`, `carrying_cost_inputs`) need a new `_ADDITIVE_TABLES` step
  added to `migrate.py`, not just new tuples in the existing
  `_ADDITIVE_COLUMNS` list. This is the single most important sequencing
  finding: schema.sql changes must land before any seed rewrite, and
  migrate.py's new-table mechanism must land in the same step as the tables
  themselves.
- **The seed today is far smaller than A2 describes**: 8 products (`AC-001`
  through `AC-006` plus 2 orphaned, unused fixtures `REF-001`/`TV-001`), 1
  warehouse (`DEL-01` hardcoded on every row), 5 vendors, all hand-written
  inline with flat/constant velocity (no trend, seasonality, or noise
  anywhere). A2's "~35 SKUs, 3-4 warehouses, 9 demand personalities" is a
  substantial rewrite of `seed.py`, not an extension.
- **`tools/sales.py`'s window-boundary bug (Entry 006) already appears
  fixed** in the current file — the code and its inline comment both describe
  the "last N complete days, ending yesterday" logic Entry 006 recommended.
  Flagged in the plan as "re-verify at A2/A3 time, don't just trust this
  read" in case of a later revert.
- **`economics.py`'s four assumption fields** (`assumed_gross_margin_rate`,
  `assumed_annual_carrying_rate`, `assumed_late_days_when_late`,
  `vendor_billed_on_units_shipped`) were confirmed exactly as Entry 007
  described, with exact consumption points. Flagged a small discrepancy: the
  plan's A1 text says "retire the five caveats" but only four assumption
  *fields* were found — recorded as an open question to resolve via a literal
  grep before Phase B/A6.4 work, not resolved here.
- **`tools/vendors.py::build_vendor_options()` still contains the naive
  sizing formula** (`max(offer.moq, int(available_units * 0.5))`) that
  `submission/graph/economics.py`'s docstring says was superseded — confirmed
  by reading both functions directly. Flagged as a trap for A2/A3 fabricator
  work: don't trust this tool's own `quantity` field as ground truth for what
  "correct" sizing looks like.

`PHASE_A_PLAN.md` also produces a concrete 9-step build order (schema+migrate
→ domain models → 3 new tool modules [`tools/warehouses.py`,
`tools/receipts.py`, `tools/policy_floors.py`] → fabricator module
[`fixtures/fabricator.py`] → seed rewrite → regression check), an explicit
mapping of every A6 checklist item to which step it lands in, three ASCII
flow diagrams (migration flow, fabrication flow, and "where Phase A's output
is first read" — the last one existing specifically to demonstrate Phase A is
safe to ship without touching `submission/graph/` at all), concretely
checkable exit criteria (literal SQL queries and a test-count invariant, not
just prose), and an explicit out-of-scope section so a future agent doesn't
accidentally start Phase B or G work while "still doing Phase A."

**Verified:**
- Every claim attributed to a direct file read in this entry was confirmed by
  my own `read_file`/`read_code`/`grep_search` calls, not taken from the
  context-gatherer's report unchecked — specifically: `schema.sql`'s full
  table list and the `sales_daily` UNIQUE constraint, `migrate.py`'s exact
  mechanism and docstring, `config.py`'s four assumed_* fields and their env
  var names/defaults, `economics.py`'s `OptionEconomics`/`OptionsEconomics`
  dataclass fields (lines 233-380) and `evaluate_options`'s signature and
  opening ~90 lines, `tools/sales.py`'s full body including its window-fix
  comment, `tools/vendors.py`'s full body including the naive sizing line,
  `fixtures/scenarios.json`'s full 12-scenario content, `policy.md`'s full
  content, and the exact heading list of `DECISIONS.md` via grep (confirmed
  D1-D29 exist, no gaps, no duplicate numbers).
- Cross-checked the context-gatherer's claims about `domain/tool_models.py`
  and the remaining `tools/*.py` modules only by consistency against the
  files I *did* read directly (e.g. `tools/vendors.py`'s actual `VendorOption`
  usage matches the context-gatherer's description of that model) — did not
  independently re-read `tool_models.py`, `inventory.py`, `execution.py`,
  `policy.py`, `memory.py`, or `langchain_tools.py` myself. See NOT verified.

**NOT verified:**
- `domain/tool_models.py`, `tools/inventory.py`, `tools/execution.py`,
  `tools/policy.py`, `tools/memory.py`, `tools/langchain_tools.py`,
  `database/seed.py`, and `database/reset_db.py` / `submission/tests/reset_db.py`
  were **not read directly by me this session** — everything about them in
  `PHASE_A_PLAN.md` rests on the context-gatherer's report. Flagged explicitly
  in the plan (§3 step 9: "read them again at implementation time"). Anyone
  implementing step 3, 5, 6, or 9 of `PHASE_A_PLAN.md` should treat those
  file's exact current contents as unconfirmed until read directly.
- **Nothing was implemented, run, or tested this session.** `PHASE_A_PLAN.md`
  is a planning artifact only. No schema change, no migration, no new tool
  module, no fabricator code exists as a result of this session.
- Did not re-run the 140-test suite (no code changed; nothing to regress).
- Did not check whether `PLAN.md`, `GAP_FIX_PLAN.md`, `GAP_NEEDS_INFORMATION.md`
  repeat the "five caveats" language or any other since-corrected claim —
  same gap Entry 006 and Entry 007 both already flagged and neither closed.
  Still open.

**Blocked / open:** O1-O5 unchanged (not addressed this session — the user
asked only for a Phase A plan, not decisions on the open items). **Two new
questions, both scoped to Phase A specifically, recorded in
`PHASE_A_PLAN.md` §9:**
- Should `sku_policy` have `UNIQUE(sku, warehouse_id, as_of_date)`? The plan
  lists the table's columns but not a uniqueness constraint; Phase B's
  monthly-recompute logic will depend on this being right. Recommended in
  the plan but not decided unilaterally since it's a schema commitment.
- Is "retire the five caveats" (plan §A1) actually five, or is the plan's
  count off by one against the four assumption fields found in
  `economics.py`? Needs a literal grep of `caveats.append(` before Phase
  B/A6.4 work, not before Phase A.

**Plan changed?:** No changes to `AUTONOMOUS_PLAN.md` itself this session —
`PHASE_A_PLAN.md` is a new, separate companion document that expands Phase A
into concrete steps without altering any checkbox, task, or decision in the
main plan. If Phase A implementation later deviates from `PHASE_A_PLAN.md`
(e.g. a different table-creation mechanism is chosen), that should be recorded
as a plan change at that time, not assumed now.

**Decisions added to DECISIONS.md:** none — this was a planning/documentation
session, no new architecture decided. The `sku_policy` uniqueness
recommendation and the caveat-count question are flagged as open in
`PHASE_A_PLAN.md`, not decided, so neither warrants a `D<n>` record yet.

**State after this session:**
- Phases A-H: **still not started.** Zero implementation, same as Entry 007.
- Phase A: now has a detailed, ground-truth-verified execution plan
  (`PHASE_A_PLAN.md`) in addition to the original `AUTONOMOUS_PLAN.md` §Phase A
  checklist. The two documents should be read together — `AUTONOMOUS_PLAN.md`
  for *why*, `PHASE_A_PLAN.md` for *how* and *in what exact order against
  the real current code*.
- O1-O5: unchanged, still open.

**Next recommended step:** Start `PHASE_A_PLAN.md` §6 execution order, step 1
(schema.sql + migrate.py changes), after the user reviews and approves
`PHASE_A_PLAN.md`. Before starting step 3/5/6/9, read `domain/tool_models.py`,
`tools/execution.py`, `tools/policy.py`, `tools/memory.py`,
`tools/langchain_tools.py`, `database/seed.py`, and both `reset_db.py` files
directly — this session's plan relied on a sub-agent's report for those and
flagged them as unverified.

**Notes for the next agent:**
- **`migrate.py` cannot create tables today.** This is the single most
  important mechanical finding in this session — do not start writing A1's
  five new tables as if `_ADDITIVE_COLUMNS`-style tuples will handle them.
  They need `CREATE TABLE IF NOT EXISTS` in `schema.sql` plus a new
  `_ADDITIVE_TABLES` step in `migrate.py`.
- **`seed.py`'s current `AC-001`..`AC-006` stories are load-bearing for the
  140-test suite and for the one reliable demo path (`AC-003 DEL-01`, per
  Entries 005-006).** `PHASE_A_PLAN.md` §3 step 8 and step 9 both say: keep
  these SKUs' names and stories intact inside the larger ~35-SKU catalogue,
  don't rename or restructure them away, even though they'll gain new columns
  (`selling_price`, `lifecycle`, etc.).
- I did not independently re-verify the context-gatherer's report on
  `domain/tool_models.py` or several `tools/*.py` files (listed under NOT
  verified above). Treat those specific claims in `PHASE_A_PLAN.md` as
  secondhand until someone reads the files directly — this matters most for
  step 3 (new Pydantic model shapes) and step 5/6 (new tool module patterns),
  since getting the existing convention wrong there is exactly the kind of
  thing Entry 006 warned about ("partial evidence has a bad track record in
  this codebase").

---

## Entry 009 — Phase A implementation complete (2026-09-12)

**Did:** Implemented the Phase A data foundation without changing the graph,
agents, or Streamlit UI. The schema now has measured economics fields and the
additive `warehouses`, `stock_receipts`, `sku_policy`, `policy_rules`,
`parked_items`, and `carrying_cost_inputs` tables. `migrate.py` now creates
new tables idempotently before adding new columns.

The seed is now deterministic and standalone (`python database/seed.py`),
with 35 SKUs, four warehouses, 24-month histories, demand personalities,
vendor trade-offs, receipts, budgets, policy floors, and retained AC-001…006
legacy scenario semantics. New narrow warehouse, receipt, and policy-floor
tools plus the fabricator provide auditable data access and manipulation.

**Verified:** Focused Phase A tests passed (4 tests) after a genuine RED run;
the legacy graph scenario suite and Phase A tests were also run together after
preserving the original core offer IDs and vendor-ineligibility fixture. The
standalone seed command completed with 35 products, 4 warehouses, 420 receipts,
4 policy floors, and zero duplicate daily sales groups. See
`docs/testing/phase_a_data_foundation.tdd.md`.

**Deferred by design:** `roll_forward()` and the Phase B wiring that replaces
economics assumptions with these measured facts. Those are explicitly outside
Phase A.


### Entry 010 — 2026-09-12 — Claude Sonnet 5 (Kiro) — planning

**Read:** `AUTONOMOUS_TRACKER.md` (Entries 001-009, full, including the new
Entry 009 recording Phase A's completion), `database/schema.sql` (full, current
state post-Phase-A), `submission/state/state.py` (full), `submission/graph/nodes.py`
lines 108-318 (`fetch_evidence` through the start of `compute_risk`, plus
`_override_ambiguity_if_windows_disagree_on_risk` and `apply_window_choice` in
full), `requirements.txt` (full — confirmed no numpy/scipy/pandas dependency
exists), `PHASE_A_PLAN.md` (own prior-session document, re-read for the
`roll_forward` deferral note and the `sku_policy` uniqueness question's
resolution), plus a context-gatherer sweep covering: `database/migrate.py`
(confirmed `_ADDITIVE_TABLES` step landed), `database/seed.py` (confirmed
35-SKU/4-warehouse structure, 8 demand profiles, `stock_receipts` +
`carrying_cost_inputs` + `policy_rules` all seeded, `sku_policy` NOT seeded),
`fixtures/fabricator.py` (full function signature list), `tools/warehouses.py`,
`tools/receipts.py`, `tools/policy_floors.py` (full signatures), the whole of
`domain/tool_models.py` (all Phase-A models + the pre-existing models Phase B
builds on, exact fields), `tools/sales.py` (confirmed the window-boundary fix
from Entry 006 is live), `tools/inventory.py` (confirmed
`calculate_stock_risk`'s `daily_velocity <= 0 → 0.1` floor is exactly the B2
defect, unchanged), the remainder of `submission/graph/nodes.py` (full node
list/order) and `submission/graph/economics.py` (lines 440-end — the caveats
list construction and `as_evidence()`), `submission/portfolio.py` (full,
including the still-stale `list_warehouses()` and the `scan_portfolio`
both-windows/"Borderline" logic), `docs/testing/phase_a_data_foundation.tdd.md`,
and the `submission/tests/` directory listing.

**Phase / tasks touched:** Planning only, for Phase B (B1-B10 of
`AUTONOMOUS_PLAN.md`). No implementation. No checkbox in `AUTONOMOUS_PLAN.md`
was ticked.

**Files created:**
- `PHASE_B_PLAN.md` (repo root) — full end-to-end Phase B execution plan:
  ground-truth table verified against the post-Phase-A codebase, five explicit
  design decisions requiring confirmation (DB1-DB5), a complete new-files
  manifest (`submission/statistics/` package with 7 new modules, 2 new tool
  modules, domain model additions, one graph-adjacent fix), a task-by-task
  plan for B1 through B10 with concrete function signatures and formulas, an
  orchestrator design (`classify_portfolio`) with a full data-flow diagram, a
  9-step session-sized execution order, 8 concretely-checkable exit criteria,
  an explicit out-of-scope section, and new open questions.

**Files modified:** `AUTONOMOUS_TRACKER.md` (this entry only)

**Did:** The user asked for a full, detailed, end-to-end Phase B implementation
plan (planning only, matching the Phase A precedent from Entry 008). Rather
than restate `AUTONOMOUS_PLAN.md`'s §Phase B checklist, dispatched a
context-gatherer across the post-Phase-A codebase (migrate.py, seed.py,
fabricator.py, the three Phase-A tool modules, tool_models.py, sales.py,
inventory.py, the rest of nodes.py and economics.py, portfolio.py, the Phase A
TDD doc, and the test directory), then independently verified the
highest-stakes claims by reading `schema.sql`, `state.py`, and the
`fetch_evidence`/`assess_demand`/`compute_risk` region of `nodes.py` directly
myself, per this session's investigate-before-answering discipline.

That verification surfaced several findings that materially shape the plan,
all recorded in `PHASE_B_PLAN.md` §1's ground-truth table:
- **`sku_policy` exists (with the `UNIQUE(sku, warehouse_id, as_of_date)`
  constraint Entry 008 had flagged as an open question) but is never written
  to by any code path.** The open question from `PHASE_A_PLAN.md` §9 was
  resolved during Phase A implementation — confirmed by direct schema read.
- **`tools/inventory.py::calculate_stock_risk`'s `daily_velocity <= 0 → 0.1`
  floor is exactly the B2 "known defect" the plan names, unchanged, and it is
  live in the current graph** (`compute_risk` calls it directly on every
  case). Fixing it changes `StockRisk.cover_days` from `float` to
  `Optional[float]`, which ripples to exactly four call sites — enumerated by
  name in the plan (`_override_ambiguity_if_windows_disagree_on_risk`,
  `compute_risk`, `portfolio.py`'s `min(..., key=cover_days)`, and any UI
  render of `cover_days`). Flagged as the one task in this phase that touches
  code the live graph already depends on, with an explicit commitment to
  re-grep before implementation rather than trust this session's enumeration
  as final.
- **A real, unintentional inconsistency Phase A left behind**:
  `economics.py`'s caveats #2/#3/#4 still say "this schema has no selling
  price" / "no warehousing... figures" / "no promised-date-vs-receipt
  history" — all now factually false, since Phase A added exactly those
  fields/tables (`products.selling_price`, `carrying_cost_inputs`,
  `stock_receipts`). This wasn't caught when Phase A landed. B10 is the fix,
  and the plan treats it as closing a real defect, not just "nice to have."
- **No numpy/scipy/pandas dependency exists** (confirmed via direct
  `requirements.txt` read). B8's safety-stock z-score needs an
  inverse-normal-CDF; the plan decides (DB1, flagged not silently assumed) to
  implement a pure-Python rational approximation rather than add a new pinned
  dependency for one function.
- **ABC classification needs a per-SKU unit-cost figure `products` doesn't
  provide** (only `selling_price`, which is the wrong number — using it would
  rank importance by revenue, not cost commitment). DB2 resolves this via
  B10's `landed_unit_cost()` against the cheapest active offer, with a
  documented fallback chain, flagged as a proxy rather than decided silently.
- **No proper statistical test is available for regime-shift "significance"**
  without scipy. DB3 proposes a named, bounded heuristic (magnitude ratio +
  two-subwindow sustained check) and is explicit that it is weaker than a
  real z-test, matching the project's existing house style of naming
  assumptions rather than dressing them up (cited against
  `config.assumed_late_days_when_late`'s own docstring as precedent).
- **B4's ABC ranking requires classifying the whole portfolio's consumption
  values in one batch**, not SKU-by-SKU — this changes `classify()`'s call
  shape from a simple per-SKU pure function into a two-level design: a
  `classify_portfolio(warehouse_id, as_of)` orchestrator that batches ABC
  ranking across all SKUs in a warehouse, then finishes each SKU's row. This
  is reflected in the plan's own §5 design and its B9 backfill script, which
  the plan is explicit must run oldest-month-first so hysteresis state
  accumulates correctly (running newest-first would leave the oldest month
  with no prior row to compare against).
- **`portfolio.py::list_warehouses()` still does `SELECT DISTINCT
  warehouse_id`**, unchanged since before Phase A, despite `tools/warehouses.py`
  and the `warehouses` table existing now — noted as a cheap adjacent cleanup,
  explicitly marked out of scope for Phase B's own exit criteria.

The plan also makes an explicit scope reading not stated outright in
`AUTONOMOUS_PLAN.md`: **hysteresis (B6) is scoped to the ABC dimension only**,
since the plan's own text only ever gives A/B/C-direction examples (B→A
promotion, A→B downgrade) and never describes a promotion/downgrade direction
for XYZ or demand-quadrant reclassification. Flagged as an open question (§9)
rather than treated as settled, since it changes `classify_portfolio`'s
internal shape if the user wants hysteresis applied more broadly.

**Verified:**
- Every ground-truth claim attributed to a direct read in this entry was
  confirmed by my own `read_file`/`grep_search` calls: `schema.sql`'s full
  current table list (confirming all six Phase-A tables and the `sku_policy`
  UNIQUE constraint), `state.py`'s complete `CaseState` field list (confirming
  no classification field exists yet), the exact body of `fetch_evidence`,
  `_override_ambiguity_if_windows_disagree_on_risk`, `assess_demand`, and
  `apply_window_choice` in `nodes.py`, and `requirements.txt`'s full dependency
  list.
- Cross-checked the context-gatherer's claims wherever they overlapped with
  material I could verify independently (e.g. its description of
  `tools/sales.py`'s window-boundary logic matches this session's own
  understanding from Entry 006's prior investigation, restated correctly).

**NOT verified:**
- `database/migrate.py`, `database/seed.py`, `fixtures/fabricator.py`,
  `tools/warehouses.py`, `tools/receipts.py`, `tools/policy_floors.py`, the
  full `domain/tool_models.py`, `tools/inventory.py`'s complete body (only the
  defect line was independently corroborated by the context-gatherer's report,
  not re-read by me directly this session), the remainder of
  `submission/graph/nodes.py` beyond the region I read directly, the
  remainder of `submission/graph/economics.py` (lines 440-end, including the
  exact caveat strings quoted in the plan), `submission/portfolio.py`, the
  Phase A TDD doc, and the test directory listing were **not read directly
  by me this session** — everything about them in `PHASE_B_PLAN.md` rests on
  the context-gatherer's report, one level less verified than the items
  listed under Verified above. This matters most for the exact caveat text
  quoted in §4 B10 (six numbered strings) and the exact fabricator/tool
  function signatures quoted throughout §3-4 — anyone implementing against
  those exact strings/signatures should re-read the source files first rather
  than trust this plan's transcription as authoritative.
- **Nothing was implemented, run, or tested this session.** `PHASE_B_PLAN.md`
  is a planning artifact only.
- Did not re-run the test suite (no code changed).
- Did not independently verify the exact caveat count claim ("5 unconditional
  + 1 conditional = 5 or 6 total") beyond the context-gatherer's transcription
  — this resolves the open question `PHASE_A_PLAN.md` §9 raised about "five
  caveats vs four assumption fields," but only at second hand. Worth a direct
  read of `economics.py`'s caveat-building code before B10 implementation
  starts, not just before this plan was written.

**Blocked / open:** O1-O5 unchanged (not addressed this session). **New,
scoped to Phase B, recorded in `PHASE_B_PLAN.md` §9 (restating DB1-DB5 plus
two more):**
- DB1: pure-Python inverse-normal-CDF vs adding scipy — this plan chooses
  pure Python, flagged not silently decided.
- DB2: ABC's unit-cost proxy (landed cost of cheapest active offer, with a
  fallback chain) — proxy nature flagged.
- DB3: regime-shift "significance" is a named heuristic, not a formal
  statistical test, given no scipy dependency.
- DB4: `StockRisk.cover_days` becomes `Optional[float]`, with an exact,
  enumerated four-site ripple — flagged for explicit confirmation since it's
  the one Phase B change touching code the live graph depends on.
- DB5: B10's module placement — no real ambiguity, `AUTONOMOUS_PLAN.md`
  already specifies it; restated for completeness.
- New: is hysteresis (B6) ABC-only, or should it also apply to XYZ/quadrant?
  This plan reads it as ABC-only from the plan text's own examples.
- New: the service-level floor/cap numbers in §4 B7
  (`{"A": 0.95, "B": 0.90, "C": 0.80}` etc.) are this plan's own provisional
  defaults, not sourced from `AUTONOMOUS_PLAN.md` or the brief — same
  treatment as O1/O2/O4/O5, flagged rather than decided.

**Plan changed?:** No changes to `AUTONOMOUS_PLAN.md` itself this session.
`PHASE_B_PLAN.md` is a new, separate companion document, same relationship
`PHASE_A_PLAN.md` had to the main plan for Phase A.

**Decisions added to DECISIONS.md:** none — DB1-DB5 and the two new open
questions are flagged as proposals/defaults in `PHASE_B_PLAN.md`, not decided,
so none warrant a `D<n>` record yet. If the user confirms any of them as final
during implementation, they should be promoted to `DECISIONS.md` at that time.

**State after this session:**
- Phase A: **complete** (per Entry 009), unchanged by this session.
- Phase B: **not started.** Zero implementation. Now has a detailed,
  ground-truth-verified execution plan (`PHASE_B_PLAN.md`) in addition to the
  original `AUTONOMOUS_PLAN.md` §Phase B checklist.
- Phases C-H: not started, unchanged.
- O1-O5: unchanged, still open. DB1-DB5 and the two new Phase-B-scoped
  questions are new and also open.

**Next recommended step:** Get the user's confirmation on DB1-DB5 (especially
DB4's `Optional[float]` ripple, since it's the one change touching live graph
code) and the two new open questions (ABC-only hysteresis scope, service-level
floor/cap numbers), then start `PHASE_B_PLAN.md` §6 execution order, step 1
(`submission/statistics/normal.py` + `demand.py`, B1). Before starting steps
4, 6, or later — which lean on the context-gatherer's unverified transcription
of `fabricator.py`, the tool modules, `tool_models.py`, and `economics.py`'s
exact caveat strings — read those files directly first, per this entry's own
NOT-verified list.

**Notes for the next agent:**
- **`calculate_stock_risk`'s `0.1` velocity floor is real and live in the
  graph.** Do not treat B2 as "just add a new function" — it edits a function
  every existing case already calls, and its `Optional[float]` ripple must be
  grepped fresh (`\.cover_days\b` across `submission/` and `tools/`) rather
  than assumed to be exactly the four sites this plan names, since this
  session did not exhaustively grep before writing the plan.
- **The `economics.py` caveats are currently lying about what the schema
  has.** This is not a hypothetical B10 nice-to-have; it's a live, shipped
  inaccuracy on every approval card today, dated back to Phase A landing
  without a corresponding `economics.py` update. Worth confirming this
  directly (read the caveat-building code) before treating B10 as low
  priority relative to the statistics work.
- **`sku_policy`'s ABC ranking needs a whole-portfolio batch, not a per-SKU
  call.** If a future session starts implementing `classify()` as a simple
  per-SKU pure function (the naive reading of `AUTONOMOUS_PLAN.md`'s B1-B9
  task list, which is written per-SKU throughout), it will hit this wall at
  B4 and need to restructure into the two-level `classify_portfolio` design
  this plan already worked out. Save the rework by reading `PHASE_B_PLAN.md`
  §5 first.
- No numpy/scipy dependency exists in this repo. Don't casually `pip install
  scipy` for one z-score function without first checking whether the pure-
  Python approximation in this plan's DB1 is acceptable — it's a design
  decision, not a foregone conclusion.

### Entry 011 — 2026-09-12 06:51 UTC — GPT-5 (Codex) — implementation

**Read:** `PHASE_B_PLAN.md`, `AUTONOMOUS_PLAN.md` Phase B, `DECISIONS.md`, this
tracker, and the direct implementation surfaces in `database/`, `domain/`,
`tools/`, `submission/graph/`, `submission/portfolio.py`, and
`submission/ui.py`.

**Phase / tasks touched:** B1-B10.

**Files created:** `submission/statistics/` (normal, demand, windows,
abc_xyz, maturity, hysteresis, service_level, safety_stock, classify),
`tools/classification.py`, `tools/cost_inputs.py`,
`database/backfill_classification.py`, Phase-B focused tests, and the TDD
evidence record.

**Files modified:** schema/migration/seed paths, tool models, sales and vendor
tools, stock-risk consumers, economics, configuration, and the phase plan.

**Did:** Implemented deterministic demand classification, Croston level,
calendar windows, ABC/XYZ, maturity, ABC hysteresis, service-level bounds,
safety stock/ROP, persisted policy records, oldest-first classification
backfill, and optional measured economics inputs. Removed the fictional
zero-demand velocity floor so cover is explicitly `None` when not meaningful.

**Verified:** Focused Phase-B test suite passed 7 tests. `compileall` passed.
A fresh isolated seeded database completed the backfill and contained 391
`sku_policy` records across 34 SKU/warehouse pairs. The RED gate was recorded:
the new test originally failed because `submission.statistics` did not exist.

**NOT verified:** The shared-database graph regression target could not reset:
Windows reported `database/inventra.db` was held by another process. It failed
before collection, not on a Phase-B behavior. Per-figure measured-economics
and backfill behaviors need broader integration coverage before calling the
phase complete.

**Blocked / open:** The default database lock must be released before the full
regression suite can run. The documented B6 scope (ABC-only hysteresis) and
policy service-level defaults were implemented as the plan's defaults.

**Plan changed?:** Yes — checked implemented B1 and selected B10 items; did
not mark unverified exit criteria complete.

**Decisions added to DECISIONS.md:** none; implementation followed the
documented Phase-B defaults authorized by the user's request.

**State after this session:** Phase A remains complete. Phase B is implemented
with focused evidence but remains verification-in-progress until the shared DB
lock permits the regression suite and the remaining exit-criterion coverage.

**Next recommended step:** Stop the process holding `database/inventra.db`,
run the full suite once, and add integration tests for measured per-figure
economics and class-history transitions.

**Notes for the next agent:** Do not replace `None` cover with infinity or a
velocity floor. The seeded backfill is intentionally separate from raw seeding
but invoked after `seed_data()` commits. `load_cost_inputs()` remains optional
to live graph calls by design; Phase B adds the capability without changing
the existing case graph.

### Entry 012 — 2026-09-12 07:00 UTC — GPT-5 (Codex) — implementation + verification

**Read:** Current Phase-B implementation and the Phase B requirement checklist
in `AUTONOMOUS_PLAN.md`.

**Phase / tasks touched:** B2, B5, B8, B9.

**Files created:** none.

**Files modified:** `submission/statistics/safety_stock.py`,
`submission/statistics/hysteresis.py`, `submission/statistics/classify.py`,
and `submission/tests/test_phase_b_statistics_and_policy_engine.py`.

**Did:** Replaced normal-distribution safety stock for intermittent/lumpy
demand with a deterministic empirical rolling lead-time demand quantile.
Annualised partial-history consumption for ABC ranking, prevented an
insufficient-history SKU from receiving a permanent active class, and added an
end-to-end temporary-database classification persistence test.

**Verified:** `python -m pytest submission/tests/test_phase_b_statistics_and_policy_engine.py -q`
passed **8** tests. `python -m compileall -q domain tools database submission`
passed.

**NOT verified:** Full shared-database regression is still unavailable due to
the pre-existing Windows lock on `database/inventra.db`.

**Blocked / open:** Release that lock before the complete suite. B10 needs
additional focused tests for every independently assumed/measured input before
the plan's exit criteria are honestly complete.

**Plan changed?:** no.

**Decisions added to DECISIONS.md:** none.

**State after this session:** Phase B implementation has advanced, but its
full exit criteria remain verification-in-progress.

**Next recommended step:** Add B10 per-figure fallback/verdict tests, then run
the full suite after the shared DB lock is released.

**Notes for the next agent:** For intermittent/lumpy demand, use
`empirical_safety_stock`; do not reintroduce a normal z-score on zero-inflated
history.

### Entry 013 — 2026-09-12 07:10 UTC — GPT-5 (Codex) — implementation + verification

**Read:** B10 requirements and the current economics, vendor, receipt, and
tool-model implementations.

**Phase / tasks touched:** B8, B10.

**Files created:** none.

**Files modified:** receipt/cost/vendor/model/economics paths, focused tests,
and the Phase-B TDD evidence.

**Did:** Made receipt-lateness reads respect an explicit database path, added
freight to vendor options, and made optional economics score each option on its
quantity-dependent landed cost. Added measured-input provenance tests and a
fully-measured economics test proving assumption caveats disappear.

**Verified:** Focused Phase-B suite: **10 passed**. Compilation: passed.

**NOT verified:** The full shared-DB suite remains unavailable because the DB
is held by another process.

**Blocked / open:** Run the full suite after the lock is released; its results
are still required for full regression proof.

**Plan changed?:** no.

**Decisions added to DECISIONS.md:** none.

**State after this session:** Phase B has focused integration evidence for its
statistics and measured-economics seams; broad regression verification remains.

**Next recommended step:** Release the shared database lock and run the full
test suite, then audit remaining unticked Phase-B exit criteria against actual
seeded outcomes.

**Notes for the next agent:** Freight is not a constant: it must be divided by
the actual option quantity inside `evaluate_options`, not resolved once per SKU.

### Entry 014 — 2026-09-12 07:25 UTC — GPT-5 (Codex) — verification

**Read:** Current test runner state and B10 implementation paths.

**Phase / tasks touched:** B10 verification.

**Files created:** none.

**Files modified:** none beyond the preceding B10 implementation/test work.

**Did:** Ran the test suite against an isolated `DATABASE_PATH` so the user’s
live `database/inventra.db` was not touched or locked. The full suite and the
Phase 2/3 graph target both completed as live Python processes; temporary test
database was then removed. The execution wrapper did not preserve their final
pytest summary/exit result, so this is execution evidence, not a green-suite
claim.

**Verified:** Focused Phase-B suite remains 10 passing tests; compilation
remains passing from Entry 013.

**NOT verified:** Full-suite pass/fail result is not available from the
detached test process output and must be captured explicitly in a future run.

**Blocked / open:** none for implementation. Full-regression result capture is
still required for final verification.

**Plan changed?:** no.

**Decisions added to DECISIONS.md:** none.

**State after this session:** Phase B functionality and focused verification
are in place; broad regression evidence is incomplete rather than failed.

**Next recommended step:** Run the full suite through a result-capturing test
runner or CI and inspect the final exit status before declaring Phase B done.

**Notes for the next agent:** The seed path now backfills classification, so
suite resets are materially slower. Never start two tests using the same
isolated `DATABASE_PATH` concurrently.

### Entry 015 — 2026-09-12 07:35 UTC — GPT-5 (Codex) — implementation + verification

**Read:** The B7/B10 shared-carrying-cost requirement and current classifier
and cost-input implementations.

**Phase / tasks touched:** B7, B10.

**Files created:** none.

**Files modified:** `tools/cost_inputs.py`, `submission/statistics/classify.py`,
`submission/config.py`, and focused Phase-B tests.

**Did:** Made the classifier call B10’s shared contribution and carrying-cost
functions instead of duplicating database arithmetic. Added lifecycle-driven
obsolescence carrying rates for `DECLINING` and `EOL` products, while retaining
configurable values and the measured finance/storage inputs.

**Verified:** Focused Phase-B suite: **10 passed**. Compilation: passed.

**NOT verified:** Captured final result of the full regression suite remains
unavailable; isolated suite processes did run to completion as recorded in
Entry 014.

**Blocked / open:** Explicit broad-suite result capture is still needed before
claiming all existing graph behavior remains green.

**Plan changed?:** no.

**Decisions added to DECISIONS.md:** none.

**State after this session:** Phase B has one shared carrying-cost derivation
for B7 and B10, plus focused coverage of EOL cost loading.

**Next recommended step:** Capture a complete regression report and then mark
only evidence-backed Phase-B checklist entries complete.

**Notes for the next agent:** `carrying_rate_per_day` now accepts an optional
database path; use it in testable orchestration rather than mutating global
configuration.

### Entry 016 — 2026-09-12 08:00 UTC — GPT-5 (Codex) — focused verification

**Read:** Phase-B implementation state and the user instruction to stop the
broad/full-suite run.

**Phase / tasks touched:** verification of B1-B10 implementation.

**Files modified:** `database/seed.py` (synthetic selling prices now remain
above the lowest landed cost during backfill).

**Did:** Stopped the isolated full-suite process at the user's request and
did not restart it. Kept verification scoped to the Phase-B test module.

**Verified:** `python -m pytest submission/tests/test_phase_b_statistics_and_policy_engine.py -q` — **10 passed**; `python -m compileall -q domain tools database submission` — passed.

**NOT verified:** The full existing test suite was intentionally not rerun.

**Blocked / open:** Broad regression compatibility remains unclaimed until a
future explicitly requested full-suite run.

**Plan changed?:** no.

**Decisions added to DECISIONS.md:** none.

**State after this session:** Phase-B focused behavior is green and the
implementation compiles; full-suite execution is intentionally deferred.


### Entry 017 — 2026-09-12 — Claude Sonnet 5 (Kiro) — planning

**Read:** `AUTONOMOUS_TRACKER.md` (Entries 001-016, full, including Entries
009-016 recording Phase A completion and the full Phase B implementation
history from GPT-5/Codex sessions), `tools/warehouses.py` (full, direct read),
`database/seed.py` (grepped for `backfill_all` call site, confirmed present at
line ~104-105), `submission/graph/routes.py` (full 13-function list via grep +
context), a **live query against `database/inventra.db`** confirming
`sku_policy` currently holds 817 rows across 35 distinct (sku, warehouse_id)
pairs, plus a context-gatherer sweep covering: `submission/statistics/classify.py`
(full, `classify_portfolio`'s exact signature and self-persisting side effect),
`tools/classification.py` (full, all 3 signatures), `database/backfill_classification.py`
(full), `submission/state/state.py` (full, confirmed no classification field
exists yet), `submission/graph/nodes.py` (structural summary + exact `_fail`/
`emit_audit` signatures + confirmed `app.py::run_case` is the only case-creation
entry point), `submission/graph/workflow.py` (full — `build_graph`,
`compile_graph`, `latest_thread_id`/`latest_thread_ids`), `submission/portfolio.py`
(full — confirmed `list_warehouses()` is still stale, `scan_portfolio()`'s
exact risk logic, and `list_pending_cases()`'s dedup pattern), `tools/execution.py`
(full — exact budget reservation/release SQL), `tools/memory.py` (full),
`submission/config.py` (full current field list, confirmed no sweep-specific
config exists), `submission/tests/` directory (full listing + the exact
isolated-`DATABASE_PATH` test mechanism), `submission/app.py` (full CLI command
list), and `fixtures/scenarios.json` (confirmed scenarios 13-26 already exist,
added during Phase A/B, not just the original 12).

**Phase / tasks touched:** Planning only, for Phase C (C1-C6) and Phase C2
(policy floor reconciliation) of `AUTONOMOUS_PLAN.md`. No implementation. No
checkbox in `AUTONOMOUS_PLAN.md` was ticked.

**Files created:**
- `PHASE_C_PLAN.md` (repo root) — full end-to-end Phase C + Phase C2 execution
  plan: a ground-truth table verified against the post-Phase-B codebase, seven
  explicit design decisions (DC1-DC7), a complete new-files manifest (a new
  `submission/sweep/` package with 5 modules, 2 new tool modules, 1 new table
  `sweep_runs`, `CaseState`/`ApprovalDecision`/`ReplenishmentProposal` field
  additions), a task-by-task plan for C1 through C6 plus all of Phase C2's
  C2.1-C2.4 with concrete function signatures and exact reuse-vs-new-code
  boundaries, two flow diagrams, a 9-step session-sized execution order, an
  explicit testing section naming exactly which test file to run after each
  step (never the full suite as a routine step), an explicit out-of-scope
  list, and new open questions.

**Files modified:** `AUTONOMOUS_TRACKER.md` (this entry only)

**Did:** The user asked for a full, detailed, end-to-end Phase C implementation
plan (matching the Phase A/B precedent from Entries 008/010), with an explicit
instruction to record that future implementation sessions must NOT run the
full test suite routinely — only the specific test files relevant to whatever
was just built, and only via an isolated `DATABASE_PATH`. Both instructions are
now embedded directly in `PHASE_C_PLAN.md` (a standalone warning paragraph at
the top of the document, and a full §7 "Testing — exactly what to run, and
what NOT to run" section with a per-step table and the exact PowerShell
mechanism), not just recorded here in the tracker, so the instruction survives
independent of anyone reading this specific tracker entry.

Ground-truth verification (mixing direct reads and one context-gatherer sweep,
cross-checked where they overlapped) surfaced several findings that materially
shape the plan, recorded in `PHASE_C_PLAN.md` §1:
- **`sku_policy` is confirmed live and populated** — 817 rows, 35 distinct
  (sku, warehouse_id) pairs, verified by a direct SQL query against the actual
  `database/inventra.db`, not inferred from tracker prose. `database/seed.py`
  calling `backfill_classification.backfill_all(db_path)` was confirmed by
  direct grep (the prior session's context-gatherer had flagged this as
  unverified; now closed).
- **`classify_portfolio` self-persists to `sku_policy` by default** when
  called with `conn=None` — a real API sharp edge for the sweep to design
  around explicitly rather than trip over. Resolved as DC2: the sweep uses
  this write-through deliberately (refreshing classification at sweep time is
  more correct than trusting a stale backfilled row), not avoided.
- **No bulk "latest sku_policy row per SKU in a warehouse" read exists** —
  only single-SKU lookups in `tools/classification.py`. Phase C needs to add
  this (`get_latest_policies_for_warehouse`), named as new, additive work.
- **`scan_portfolio()` is explicitly NOT reusable as the candidate-detection
  seam** — it has zero awareness of `sku_policy`/ABC-XYZ/reorder points/policy
  floors, using only raw stock-risk math. The plan creates a fresh
  `submission/sweep/candidates.py::detect_candidates` rather than extending
  `scan_portfolio` in place, reasoning that the two serve different
  correctness bars (UI watchlist read vs. autonomous case-opening decision).
- **`portfolio.py::list_warehouses()` is still stale** (confirmed by direct
  read of `tools/warehouses.py` alongside the context-gatherer's report on
  `portfolio.py`) — still `SELECT DISTINCT warehouse_id FROM
  inventory_snapshots` with a docstring asserting no `warehouses` table
  exists, which has been false since Phase A. This was "nice-to-have" in the
  Phase A and Phase B plans; this session promotes it to a genuine Phase C
  prerequisite (DC7) since the sweep needs a warehouse list and shouldn't
  silently miss a warehouse with no inventory snapshot rows yet.
- **Budget reservation/release is confirmed per-warehouse-per-month** in
  `tools/execution.py`, with exact SQL — this is the mechanism Phase C's
  ranking/allocation step reuses, but the plan is explicit that the sweep's
  own budget check is only an *estimate* used for ordering, never a bypass of
  the graph's own live, authoritative budget check inside
  `fetch_budget_and_policy`/`draft_proposal`.
- **`fixtures/scenarios.json` already has scenarios 13-26** (not just the
  original 12) — confirmed via the context-gatherer's structural read, which
  the plan flags for a follow-up cross-check: the source plan's own scenario
  table numbers the two policy-floor scenarios "16, 17" while the
  already-implemented `phase_a_scenarios` array numbers them 21/22, and the
  plan explicitly does NOT assume these line up with specific SKU names
  without a direct read at implementation time (recorded as an open question,
  §9).
- **The isolated-test-database mechanism is confirmed exact**: `config.database_path`
  reads `DATABASE_PATH` from the environment at construction time; setting it
  before the process starts (not mid-test) points every tool's default DB path
  and `reset_db.py`'s reseed at a throwaway file. This is the mechanism the
  plan's entire §7 testing section is built on, and it matches what tracker
  Entries 014-016 (GPT-5/Codex sessions) were already doing by hand.

The plan makes seven explicit design decisions (DC1-DC7) rather than silent
choices, matching this project's established practice: a new
`submission/sweep/` package instead of extending `portfolio.py` (DC1);
deliberate use of `classify_portfolio`'s write-through default (DC2); a fresh
`detect_candidates` function instead of extending `scan_portfolio` (DC3); one
new optional `CaseState` field (`sku_policy_snapshot`) so the sweep can hand
its already-computed classification into the case graph without any node
recomputing it (DC4); `derived_cover_days` becomes the new target only for
sweep-opened cases, explicitly preserving the manual `app.py run` path's
existing behavior since stripping it is Phase F's job, not Phase C's (DC5);
the sweep never calls LLM agents directly, cost control is entirely structural
via C1/C2 filtering before any `graph.invoke` (DC6); and the `list_warehouses()`
fix is promoted from optional cleanup to a required prerequisite (DC7).

The plan is explicit throughout that **the case graph itself does not change
shape** — every node from `validate_request` through `finalize_success` stays
as Phase B left it, with exactly one bounded exception: Phase C2's
`fetch_budget_and_policy`/`apply_human_edit`/`review_policy` edits, which the
source plan's own D19 decision already specifies as "no new graph shape,"
followed exactly (new deterministic step folded into an existing node, no new
node, no new route, bounded by the existing `max_human_edit_cycles` config).

**Verified:**
- The live `sku_policy` row/pair count (817 rows, 35 pairs) via a direct
  `sqlite3` query against the actual `database/inventra.db` in this session —
  not inferred, not taken from tracker prose.
- `database/seed.py`'s call to `backfill_classification.backfill_all(db_path)`
  via direct grep, closing an explicit "not verified, only inferred from
  tracker text" gap the context-gatherer itself flagged.
- `tools/warehouses.py`'s full content via direct read, confirming it reads
  the real `warehouses` table correctly (the discrepancy is entirely in
  `portfolio.py`'s stale function, not in the underlying tool).
- `submission/graph/routes.py`'s complete 13-function list via direct grep,
  confirming zero existing routes are sweep-aware and that Phase C2's edits
  don't need to touch this file at all (per D19's "no new graph shape").

**NOT verified:**
- `submission/statistics/classify.py`, `tools/classification.py`,
  `database/backfill_classification.py`, `submission/state/state.py`,
  `submission/graph/nodes.py` (full body), `submission/graph/workflow.py`,
  `submission/portfolio.py` (full body), `tools/execution.py`,
  `tools/memory.py`, `submission/config.py` (full body),
  `submission/tests/` (individual file contents beyond directory listing +
  `conftest.py`/`reset_db.py` mechanism), `submission/app.py`, and
  `fixtures/scenarios.json` were **not read directly by me this session** —
  everything about them in `PHASE_C_PLAN.md` rests on the context-gatherer's
  report, one level less verified than the items listed under Verified above.
  This matters most for: the exact current location of
  `_checklist_covers_every_question_exactly_once` (flagged explicitly in
  `PHASE_C_PLAN.md` §9 as needing a direct grep before C2.4 implementation,
  since the context-gatherer's sweep did not pin this down), the exact
  `PolicyReview`/`ApprovalDecision` model shapes in
  `submission/agents/models.py` (referenced but not independently read), and
  the exact test file(s) that assert the current 8-item checklist contract
  (named as needing a grep at implementation time, not assumed).
- **Nothing was implemented, run, or tested this session.** `PHASE_C_PLAN.md`
  is a planning artifact only. No new package, no new table, no new tool
  module exists as a result of this session.
- Did not run any test file this session (no code changed; nothing to
  regress) — but the plan's own §7 was written specifically so that FUTURE
  implementation sessions have an unambiguous, pre-agreed answer to "which
  test do I run right now," precisely to prevent the full-suite-runtime/lock
  problems Entries 011-016 documented from recurring during Phase C work.
- Did not independently verify the exact `fixtures/scenarios.json` scenario
  numbering (13-26) against the actual seeded `policy_rules` rows' SKU names
  — flagged as an explicit open question (§9) rather than assumed, since the
  source plan's scenario table and the already-implemented
  `phase_a_scenarios` array use different numbers (16/17 vs 21/22) for what
  may or may not be the same two policy-floor scenarios.

**Blocked / open:** O1-O5 (original) and DB1-DB5 (Phase B) unchanged, not
addressed this session. **New, scoped to Phase C, recorded in
`PHASE_C_PLAN.md` §9:**
- Naming collision flagged: `AUTONOMOUS_PLAN.md` uses "C2" for both the
  in-phase "ranking and budget allocation" task and the separate top-level
  "Phase C2" (policy floor reconciliation). This plan preserves both usages
  exactly as the source document does but calls out the collision so it isn't
  misread.
- Whether `fixtures/scenarios.json`'s already-seeded `POLICY_LOW_FLOOR(21)`/
  `POLICY_HIGH_FLOOR(22)` rows are the same scenarios `AUTONOMOUS_PLAN.md`
  calls "16, 17" — needs a direct comparison against the 4 real seeded
  `policy_rules` rows before C2's tests assume specific SKU names.
- `urgency_score`'s exact ranking formula (economic value ÷ cover-days-
  remaining) is this plan's own provisional default, not sourced from
  `AUTONOMOUS_PLAN.md`'s text (which only says "urgency × economic value"
  without a formula) — flagged, not decided.
- Whether C5's "already has a pending case" check should treat cases paused
  at `await_missing_info`/`await_window_choice` the same as ones paused at
  `request_approval`, or differently — the source plan's C5 text only
  discusses the approval-gate case explicitly.
- The exact current file location of `_checklist_covers_every_question_exactly_once`
  needs a direct grep before C2.4 implementation starts (not resolved by the
  context-gatherer sweep this session).

**Plan changed?:** No changes to `AUTONOMOUS_PLAN.md` itself this session.
`PHASE_C_PLAN.md` is a new, separate companion document, same relationship
`PHASE_A_PLAN.md` and `PHASE_B_PLAN.md` had to the main plan for their
respective phases.

**Decisions added to DECISIONS.md:** none — DC1-DC7 and the new open questions
are flagged as proposals/defaults in `PHASE_C_PLAN.md`, not decided, so none
warrant a `D<n>` record yet. If the user confirms any as final during
implementation, promote them to `DECISIONS.md` at that time, per this
project's established convention.

**State after this session:**
- Phase A: complete (Entry 009), unchanged.
- Phase B: implemented with focused test evidence (Entries 011-016), full-suite
  regression still not captured — unchanged by this session.
- Phase C / Phase C2: **not started.** Zero implementation. Now has a detailed,
  ground-truth-verified execution plan (`PHASE_C_PLAN.md`) in addition to the
  original `AUTONOMOUS_PLAN.md` §Phase C / §Phase C2 checklists.
- Phases D-H: not started, unchanged.
- All open questions (O1-O5, DB1-DB5, and the new Phase-C-scoped ones above)
  remain open.

**Next recommended step:** Confirm DC1-DC7 (especially DC4's new `CaseState`
field and DC7's `list_warehouses()` fix, since DC7 is a prerequisite every
later Phase C step depends on) and the open questions in §9, then start
`PHASE_C_PLAN.md` §6 execution order, step 1 (the `list_warehouses()` fix +
new bulk classification read). Before starting steps that lean on the
context-gatherer's unverified transcription (most of §4's exact signatures
for `nodes.py`, `workflow.py`, `execution.py`, `memory.py`, `config.py`,
`app.py`), read those files directly first, per this entry's own
NOT-verified list — same discipline Entry 010 asked of whoever picked up
Phase B.

**Notes for the next agent:**
- **Do not run the full test suite as a routine verification step during
  Phase C implementation.** The user explicitly asked for this to be recorded.
  `PHASE_C_PLAN.md` §7 names the exact test file to run after each numbered
  step in its execution order, and gives the exact isolated-`DATABASE_PATH`
  PowerShell mechanism (confirmed working per Entries 014-016 and this
  session's own verification of `config.database_path`'s env-var behavior).
  Run the combined phase-lettered-file set (§7's last code block) only once,
  as a final gate, and only against an isolated DB — never the full
  `submission/tests/` directory, and never against the live
  `database/inventra.db`.
- **`classify_portfolio(warehouse_id, as_of, conn=None)` writes to
  `sku_policy` as a side effect by default.** This is used deliberately by
  the sweep (DC2) — don't "fix" it into a pure function without re-reading
  why `backfill_classification.py` passes its own `conn` to avoid double
  writes. Both behaviors are intentional, for different callers.
- **`scan_portfolio()` and `list_pending_cases()` in `submission/portfolio.py`
  are reference patterns, not code to extend in place.** `detect_candidates`
  is a fresh function; `list_pending_cases()`'s batched-`latest_thread_ids`-
  plus-one-graph-scan pattern is what C5's `check_in_flight_case` should
  copy, not call directly (it returns a different shape than C5 needs).
- **The sweep's own budget check (C2, `allocate_budget`) is an estimate for
  ordering only.** It must never be treated as replacing the graph's own live
  budget check inside `fetch_budget_and_policy`/`draft_proposal` — that check
  stays authoritative and unchanged. A real graph run's cost disagreeing with
  the sweep's cheap estimate is expected, not a bug.


### Entry 018 — 2026-09-12 — Claude Sonnet 5 (Kiro) — planning

**Read:** `AUTONOMOUS_TRACKER.md` (Entries 001-017, full — confirmed no
implementation entry for Phase C/C2 was ever appended despite the code
already existing; see Blocked/open below), `AUTONOMOUS_PLAN.md` §Phase D
(Gate 1, Gate 2, rejection-with-reason, reminders — read as the primary
source document per the user's explicit instruction to "read AUTOMATION.md
and any other file needed"; no file named `AUTOMATION.md` exists in this
workspace, confirmed by `file_search`, so `AUTONOMOUS_PLAN.md` was treated as
the intended target), `DECISIONS.md` D12 (two-gate rationale) in full,
`PHASE_C_PLAN.md` (own prior-session document, re-read for its explicit
"Gate 2 / reminder-delivery is Phase D territory" deferral note), and direct
reads of: `submission/graph/nodes.py` (`execute_purchase` through
`finalize_success`, full), `submission/graph/workflow.py` (full — every node,
every edge, all three existing `interrupt()` call sites, `checkpoint_allowlist`,
`compile_graph`, `latest_thread_id(s)`), `submission/graph/routes.py` (full 13
functions), `submission/graph/approval_server.py` (full), `submission/notifications/email.py`
(full), `submission/notifications/vendor_email.py` (full), `submission/notifications/tokens.py`
(full), `tools/execution.py` (the `get_vendor_send_status`/`mark_vendor_send_status`/
`cancel_purchase_request` region, full), `domain/tool_models.py` (`ProposalStatus`,
`PurchaseRequestStatus`, `ApprovalDecision`, `ReplenishmentProposal`,
`PurchaseRequestResult` regions), `submission/state/state.py` (full — confirmed
Phase C2's fields already landed: `sku_policy_snapshot`, `target_reconciliation`,
`policy_floor`, `target_provenance`), `submission/portfolio.py` (full,
`list_pending_cases`/`scan_portfolio`/`list_warehouses` — confirmed
`list_warehouses()` was already fixed to delegate to `tools.warehouses`, closing
the DC7 prerequisite `PHASE_C_PLAN.md` had named), `submission/sweep/resweep.py`
and `submission/sweep/run.py` (full — both already built), `submission/sweep/candidates.py`
and `submission/sweep/ranking.py` (full — both already built), `submission/ui.py`
(the Gate-1 approval-screen button/decision region, full), `submission/app.py`
(full — confirmed a `sweep` CLI command already exists), `database/schema.sql`
(`purchase_requests`'s exact current columns, confirmed no reminder-tracking
columns exist yet), `submission/agents/models.py` (`PolicyQuestion`/`PolicyReview`
region — confirmed the 9th `POLICY_FLOOR` checklist item is already live, not
just planned), and both existing Phase C test files
(`test_phase_c_autonomous_sweep.py`, `test_phase_c2_policy_floor_reconciliation.py`,
both in full).

**Phase / tasks touched:** Planning only, for Phase D (Gate 1 unchanged-shape
confirmation, Gate 2, rejection-with-reason at both gates, reminders) of
`AUTONOMOUS_PLAN.md`. No implementation. No checkbox in `AUTONOMOUS_PLAN.md`
was ticked.

**Files created:**
- `PHASE_D_PLAN.md` (repo root) — full end-to-end Phase D execution plan: a
  ground-truth table verified against the post-Phase-C codebase (including
  the discovery that Phase C2 is already implemented, not merely planned —
  see below), eight explicit design decisions (DD1-DD8), a complete
  new-files/modified-files manifest, a task-by-task plan splitting the
  single `execute_purchase` node into the Gate-1/Gate-2 pair the source plan
  calls for, two flow diagrams, a 9-step session-sized execution order, a
  full §7 testing section naming exactly which test file to run after each
  step (never the full suite as a routine step, matching the explicit
  instruction the user repeated this session), an explicit out-of-scope
  list, and new open questions.

**Files modified:** `AUTONOMOUS_TRACKER.md` (this entry only)

**Did:** The user asked for a full, detailed, end-to-end Phase D
implementation plan (matching the Phase A/B/C precedent), explicitly
repeating the instruction that future implementation sessions must not run
the full test suite routinely, and asking me to read "AUTOMATION.md" first.
No such file exists — confirmed by `file_search` before proceeding — so I
treated `AUTONOMOUS_PLAN.md` (the actual, only plan document with that role
in this workspace) as the intended source, and said so plainly in
`PHASE_D_PLAN.md`'s own header rather than silently substituting it without
comment.

**The single most important finding this session**, recorded prominently in
`PHASE_D_PLAN.md` §1: **there is currently no Gate 2 at all.**
`submission/graph/nodes.py::execute_purchase` creates the purchase request
**and**, in the same synchronous call and the same node, sends the vendor
email if `config.vendor_email_enabled` is true — with zero pause, zero
human review, and no interrupt between the two actions. This means Phase D
is not "add a reminder feature to an existing second gate" — it is "split
one node into two graph stages separated by a real `interrupt()`," mirroring
the exact shape Gate 1's own `request_approval`/`_await_approval` pair
already has. This reframing is the core of the entire plan's Gate-2 section
(§4).

A second load-bearing finding: **Gate 1's own `REJECTED` path has no reason
requirement today**, at either the UI (`submission/ui.py`'s "Reject" button
is enabled by name alone, unlike "Ask for changes" which requires a
non-empty comment) or the CLI (`app.py::resume_case`'s `comments` parameter
is `Optional[str] = None` with no validation) or the model itself
(`ApprovalDecision` has no validator on `comments` at all). This is exactly
what `AUTONOMOUS_PLAN.md`'s own "same discipline at gate 1" line is pointing
at — the plan makes this an explicit, flagged behavior change (DD6) to an
existing, shipped path, not bundled silently into Gate 2's new work, since
it changes what a currently-valid API call will now reject.

A third finding worth recording: **Phase C2 (policy floor reconciliation) is
already fully implemented**, not merely planned as `PHASE_C_PLAN.md` left
it. Confirmed by direct reads: `submission/graph/support.py::reconcile_target`/
`TargetReconciliation` exist; `PolicyQuestion.POLICY_FLOOR` is a real 9th
checklist item with `PolicyReview.checklist` pinned at `min_length=9,
max_length=9`; `ApprovalDecision.chosen_target_basis` exists;
`nodes.apply_human_edit` handles a target-basis switch (verified by reading
`test_phase_c2_policy_floor_reconciliation.py::test_target_basis_edit_reprices_through_existing_edit_cycle`
in full, which exercises exactly that path end to end). **No tracker entry
between Entry 017 and this one records who built Phase C/C2 or when** — the
`submission/sweep/` package, the two new Phase C test files, the
`sweep_runs` table, and all of Phase C2's graph changes exist in the
codebase with no corresponding append-only log entry. This is flagged
explicitly under Blocked/open below, since it is a real break in this
project's own established practice (every phase's implementation up to
Entry 016 was logged; this one silently was not).

A fourth finding: **`portfolio.py::list_warehouses()` was already fixed**
(now delegates to `tools.warehouses.list_warehouses()`) — the DC7
prerequisite `PHASE_C_PLAN.md` §2 named has been closed, consistent with the
Phase C implementation being complete even though undocumented in the
tracker.

Ground-truth verification also surfaced, all recorded in `PHASE_D_PLAN.md`
§1: the schema already has `vendor_sent_at`/`vendor_send_status` (unused
until now, per D12's own note, now finally given a purpose); no
reminder-count/last-reminded-timestamp columns exist anywhere (new, additive
columns needed, DD3); no `ProposalStatus` value exists yet for "awaiting
vendor-send approval" or "cancelled at gate 2" (DD1/DD2, both additive enum
values); `cancel_purchase_request` already correctly refuses once a vendor
has been emailed (an existing safety rail the plan is explicit must not be
weakened, since it's exactly the boundary that makes Gate 2 meaningful);
`list_pending_cases()`'s detection mechanism (checking `snapshot.next`, not a
specific status string) will pick up a Gate-2 pause automatically once it
exists, needing no changes to its own query logic; `check_in_flight_case`
(Phase C's C5) only recognizes `AWAITING_APPROVAL` today, confirmed by direct
read, and its own docstring says delivery of any reminder "remains a Phase D
concern" — closing the loop `PHASE_C_PLAN.md` §4 C5 had explicitly left open;
and the existing email-approval-link machinery (`tokens.py`,
`approval_server.py`) is generic enough over `decision`/`case_id`/`proposal_hash`
that Gate 2 needs new call sites and one new token-payload discriminator
field, not new token machinery.

The plan makes eight explicit design decisions (DD1-DD8) rather than silent
choices: two new additive `ProposalStatus` values (DD1/DD2); reminder
tracking lives on `purchase_requests` itself via two new columns, not a new
table (DD3); `execute_purchase` is split into a Gate-1-side node (unchanged
name, vendor-email logic removed) plus a new `request_vendor_approval`/
`_await_vendor_approval`/`handle_vendor_decision` triple mirroring Gate 1's
existing node shapes exactly (DD4); a new small `VendorSendDecision` model
rather than overloading `ApprovalDecision` with fields that mean nothing at
Gate 2 (DD5); Gate 1 gets a rejection-reason validator (DD6, the one
behavior change to existing shipped code); the Gate-2 request/reminder
emails reuse `notifications/email.py`'s existing pattern, not a new module,
and `vendor_email.py` itself stays untouched (DD7); and Gate 2's email links
reuse the existing `tokens.py`/`approval_server.py` machinery via one new
discriminator field on the token payload rather than a second server or
port (DD8).

The plan is explicit that the new Gate 2 routing is **conditional on
`config.vendor_email_enabled`**, not always-on: with the flag at its
existing default (`False`), every case reaches `finalize_success` exactly as
it does today, with zero new pauses ever appearing — this is what makes the
change backward-compatible by construction for every existing test and demo
that doesn't configure vendor email, the same discipline `PHASE_B_PLAN.md`'s
B10 task used for `evaluate_options(inputs=None)`.

**Verified:**
- No `AUTOMATION.md` file exists in this workspace (`file_search`, zero
  results) — confirmed before treating `AUTONOMOUS_PLAN.md` as the intended
  document, rather than silently guessing.
- `execute_purchase`'s exact current body, including the specific
  `if config.vendor_email_enabled: try: send_purchase_order(...)` block that
  proves no Gate-2 pause exists today — read directly, not inferred.
- Gate 1's `REJECTED` path has no reason requirement anywhere (model,
  UI button condition, CLI parameter) — confirmed by direct reads of all
  three surfaces, not assumed from the source plan's prose alone.
- Phase C2's full implementation (`reconcile_target`, the 9-item checklist,
  `chosen_target_basis`, the target-basis edit cycle) — confirmed by direct
  reads of `submission/graph/support.py`, `submission/agents/models.py`, and
  the full `test_phase_c2_policy_floor_reconciliation.py` test file, not
  taken on the tracker's word (since the tracker had no entry documenting
  it at all).
- `portfolio.py::list_warehouses()`'s fix, `tools/execution.py`'s
  `cancel_purchase_request`'s existing "already sent" refusal, the complete
  absence of reminder-tracking columns in `schema.sql`, and the complete
  absence of any `AWAITING_VENDOR_APPROVAL`-equivalent `ProposalStatus`
  value — all confirmed by direct reads/greps in this session, not inferred.
- `check_in_flight_case`'s exact current behavior and its own docstring's
  "delivery remains a Phase D concern" comment — read directly in full.

**NOT verified:**
- **Nothing was implemented, run, or tested this session.** `PHASE_D_PLAN.md`
  is a planning artifact only.
- Did not trace the exact propagation behavior of a `ValueError` raised
  from inside `ApprovalDecision.model_validate(...)` when called from
  `_await_approval` — flagged explicitly in `PHASE_D_PLAN.md` §4/§9 as
  needing verification at implementation time before assuming DD6's
  validator fails gracefully rather than raising an unhandled exception
  inside a LangGraph node.
- Did not grep the full `submission/tests/` directory for every existing
  call site constructing `ApprovalDecision(decision="REJECTED", ...)`
  without comments — named explicitly in `PHASE_D_PLAN.md` §7's testing
  table as a required step before DD6 lands, not performed this session.
- Did not verify whether `submission/portfolio.py::list_pending_cases()`'s
  status-labeling needs any code change at all to correctly surface a
  future `AWAITING_VENDOR_APPROVAL` pause, versus already working via its
  existing pass-through of `state["status"]` — flagged in §3's file
  manifest as "confirm at implementation time, do not assume."
- Did not run any test file this session (no code changed).

**Blocked / open:** O1-O5 (original), DB1-DB5 (Phase B), and the Phase-C-scoped
open questions from Entry 017 all remain unaddressed this session. **New,
scoped to Phase D, recorded in `PHASE_D_PLAN.md` §9:**
- Whether a Gate-1 rejection should also write an `agent_memory_signals` row
  (this plan scopes that write to Gate-2-only, on the reading that Gate 1
  rejects the *order* while Gate 2 rejects the *vendor send*, but flags this
  as a scope reading rather than a settled fact).
- Whether `finalize_vendor_cancelled` should reuse `notify_blocked`'s
  generic template or get its own wording (defaulted to reuse, flagged as a
  cheap-to-change presentation choice).
- The `ApprovalDecision.model_validate` exception-propagation question above.
- Whether Gate 2's email links should share `approval_server.py`'s existing
  single `/decide` endpoint via a new discriminator field, or get a
  dedicated path (defaulted to the shared-endpoint approach, matching the
  file's own existing internal branching style).

**Also newly flagged, not a Phase D design question but a process gap:**
**there is no tracker entry for whoever implemented Phase C, Phase C2, or
the `submission/sweep/` package.** The code is real, tested (two dedicated
test files exist and were read in full this session), and functioning
(confirmed via direct reads, not assumed) — but this project's own
`AUTONOMOUS_TRACKER.md` append-only-log discipline, which every prior
phase's implementation followed without exception through Entry 016, was
not followed for this one. This is worth the user's attention: either a
session ran without following the steering rule that mandates an append
before finishing, or an entry was written and then lost some other way. I
am not able to determine which from the evidence available (the tracker
file itself shows no sign of tampering — entries 001-017 are intact and
sequential — it simply jumps from Entry 017 planning directly to this
Entry 018 with a fully-built Phase C/C2 in between and no record of it).

**Plan changed?:** No changes to `AUTONOMOUS_PLAN.md` itself this session.
`PHASE_D_PLAN.md` is a new, separate companion document, same relationship
`PHASE_A_PLAN.md`/`PHASE_B_PLAN.md`/`PHASE_C_PLAN.md` had to the main plan
for their respective phases.

**Decisions added to DECISIONS.md:** none — DD1-DD8 and the new open
questions are flagged as proposals/defaults in `PHASE_D_PLAN.md`, not
decided, so none warrant a `D<n>` record yet.

**State after this session:**
- Phase A: complete (Entry 009).
- Phase B: implemented with focused test evidence (Entries 011-016).
- Phase C / Phase C2: **implemented** (confirmed by direct code reads this
  session — `submission/sweep/` package, `sweep_runs` table, the 9-item
  policy checklist, `reconcile_target`, both dedicated test files all
  exist and were read in full) but **with no corresponding tracker entry**
  — flagged above as a process gap for the user's attention.
- Phase D: **not started.** Zero implementation. Now has a detailed,
  ground-truth-verified execution plan (`PHASE_D_PLAN.md`).
- Phases E-H: not started, unchanged.
- All open questions (O1-O5, DB1-DB5, Phase-C's open questions, and the new
  Phase-D-scoped ones above) remain open.

**Next recommended step:** Resolve the missing-tracker-entry gap first (either
by asking whoever ran that session to append a late, honestly-dated entry, or
by the next agent writing a best-effort reconstruction entry based on reading
the code — per rule 5, "be honest about what you did not do," a
reconstruction should say plainly it is inferred from code, not witnessed).
Then confirm DD1-DD8 and the §9 open questions, then start `PHASE_D_PLAN.md`
§6 execution order, step 1 (DD6's Gate-1 reason-requirement validator).

**Notes for the next agent:**
- **Phase C and Phase C2 are done.** Do not re-plan or re-implement them.
  `submission/sweep/candidates.py`, `ranking.py`, `parking.py`, `resweep.py`,
  `run.py` all exist and work; `submission/graph/support.py::reconcile_target`
  and the 9-item policy checklist are live. `PHASE_C_PLAN.md` describes the
  *plan* for this work, written before it was built — treat its "not yet
  built" language as historical, not current, and cross-check against the
  actual code (as this session did) rather than trusting that document's own
  state description.
- **There is no Gate 2 today.** `execute_purchase` does both the order
  write and the vendor-send in one node, synchronously, no pause. This is
  the thing Phase D actually has to build — do not mistake the *existing*
  `vendor_email.py`/`get_vendor_send_status`/`mark_vendor_send_status`
  machinery (which is real and correct) for a working Gate 2 (which does not
  exist; that machinery is currently called unconditionally, with no human
  review point in between).
- **Do not run the full test suite as a routine verification step during
  Phase D implementation.** Same instruction as Entry 017 gave for Phase C,
  repeated because the user explicitly asked again this session.
  `PHASE_D_PLAN.md` §7 names the exact file(s) to run after each step.
- **Whoever builds Phase D: append a tracker entry when you finish.** This
  session flagged that the previous phase's implementation skipped this
  step. Do not repeat that gap.


### Entry 019 — 2026-09-12 — Claude Sonnet 5 (Kiro) — planning

**Read:** `AUTONOMOUS_TRACKER.md` (Entries 001-018, full — including Entry
018's flag that Phase C/C2 was implemented with no corresponding tracker
entry, and its confirmation that Phase D is now implemented too — see
below), `AUTONOMOUS_PLAN.md` §Phase E (the primary source document — the
user asked to "read the automation file", and no file named `AUTOMATION.md`
exists in this workspace, confirmed by `file_search`, same non-finding
`PHASE_D_PLAN.md` §0 already recorded; `AUTONOMOUS_PLAN.md` was treated as
the intended target, stated plainly in `PHASE_E_PLAN.md`'s own header),
`DECISIONS.md` D20-D24 in full (the insufficient-data/parking/window-choice
decision records — all read *before* writing the plan, since they turned
out to already describe most of Phase E's design), `PHASE_D_PLAN.md` (own
prior-session document, re-read for the two-gate approval shape this
phase's changes must not disturb), and a context-gatherer sweep plus direct
reads of: `submission/graph/nodes.py` (`fetch_evidence`, `_fail`,
`assess_demand`, `apply_window_choice`,
`_override_ambiguity_if_windows_disagree_on_risk`, all `finalize_*` nodes,
full), `submission/graph/routes.py` (full, all 13 functions),
`submission/graph/workflow.py` (full — every node/edge, all four current
interrupt call sites), `domain/tool_models.py` (`ErrorCode`,
`ProposalStatus`, `SalesVelocity`, `ParkedItemRecord`, `SkuPolicy`,
`ApprovalDecision`, `VendorSendDecision` regions), `submission/state/state.py`
(full), `tools/sales.py` (full — the `<3`-observation rule and its exact
window-boundary formula, confirming Entry 006's fix is still live),
`tools/parking.py` (full), `submission/sweep/parking.py` and `candidates.py`
(full), `fixtures/fabricator.py` (full), `fixtures/scenarios.json` (the
`INSUFFICIENT_SALES_HISTORY`/`MISSING_DATA`/`phase_a_scenarios` entries),
`database/schema.sql` (`parked_items`, `sales_daily`, `purchase_requests`
regions), `database/migrate.py` (`_ADDITIVE_TABLES`/`_ADDITIVE_COLUMNS`
mechanism), `submission/app.py` (full CLI, `resume_case`, `resume_vendor_send`,
`resume_missing_info`, `resume_demand_clarification`, `_print_pending`,
`_print_result`), `submission/ui.py` (`_render_window_choice_form`, the
missing-info form, the status-label dict region), `submission/notifications/email.py`
(`notify_blocked`, `notify_needs_information`, `notify_no_action`,
`notify_outcome` region), `tools/memory.py` (`record_signal`'s best-effort
convention), `tools/receipts.py` (full), and every existing test file
touching this territory in full or in the relevant region
(`test_phase9_demand_clarification_message.py` full,
`test_phase10_demand_clarification_resume.py` full,
`test_phase5_remaining_scenarios.py`'s scenario-11 test and its
`INSUFFICIENT_HISTORY_CASE` fixture in `seed_extra.py`,
`test_phase6_revision_and_ui_reads.py`'s trending-disagreement test,
`test_phase_c_autonomous_sweep.py`'s parking-related tests,
`test_phase_d_two_gate_approval.py` full).

**Phase / tasks touched:** Planning only, for Phase E ("Insufficient data
loop") of `AUTONOMOUS_PLAN.md`. No implementation. No checkbox in
`AUTONOMOUS_PLAN.md` was ticked.

**Files created:**
- `PHASE_E_PLAN.md` (repo root) — full end-to-end Phase E execution plan: a
  ground-truth table verified against the post-Phase-D codebase, eight
  explicit design decisions (DE1-DE8), a complete new/modified-files
  manifest, a task-by-task plan (6 tasks) with concrete code sketches, a
  10-test new-file specification (`test_phase_e_insufficient_data_loop.py`),
  an explicit accounting of exactly what happens to the two existing tests
  this phase breaks (one deleted outright, one rewritten-not-deleted), a
  full §7 testing section naming exactly which test file to run after each
  task (repeating, at the user's explicit instruction, that the full suite
  must NOT be run as a routine step), an explicit out-of-scope list, open
  questions, and a concretely-checkable exit-criteria checklist mapped to
  the plan's own numbered tests.

**Files modified:** `AUTONOMOUS_TRACKER.md` (this entry only)

**Did:** The user asked for a full, detailed Phase E implementation plan,
explicitly repeating the instruction not to run the full test suite during
implementation, and asked me to read "the automation file" first — read as
`AUTONOMOUS_PLAN.md` (per the same reasoning `PHASE_D_PLAN.md` §0 already
used for an identically-phrased request in Entry 018; no `AUTOMATION.md`
exists, confirmed by `file_search` again this session, zero results).

**The single most important finding this session, and the one that reframes
the entire plan:** the design for Phase E is **already fully written down**
in `DECISIONS.md` D20 through D24 — decision records that read as completed
("Decision. Change `nodes.fetch_evidence` so `INSUFFICIENT_DATA` produces
`NEEDS_INFORMATION`", D22; "Decision. Remove `_await_window_choice`", D21) —
but **none of it has actually been implemented.** Direct reads this session
confirm: `fetch_evidence` still calls `_fail(...)` without a status
argument, so it still defaults to `BLOCKED`; `_await_window_choice`,
`apply_window_choice`, and `route_after_window_choice` are all still fully
wired into the graph, with a dedicated, currently-passing test file
(`test_phase10_demand_clarification_resume.py`) asserting the pause node's
presence and the CLI's `resume_demand_clarification` entry point. This is
the mirror image of the process gap Entry 018 flagged for Phase C (code
built with no tracker entry describing it) — here, a decision was written
and reasoned through in full, and then never executed. `PHASE_E_PLAN.md`'s
job, stated in its own §0, is explicitly framed as "build what D20-D24
already decided," not "decide what to build."

**A second finding, not previously documented anywhere and load-bearing for
the plan's Task 1:** fixing only `_fail`'s status argument would have **no
effect** on the final case outcome. `route_after_evidence` today routes
*any* non-null `error_code` to `"blocked"` → `finalize_blocked`, and
`finalize_blocked` **unconditionally overwrites**
`state["status"] = ProposalStatus.BLOCKED` regardless of what an earlier
`_fail` call set it to. So the real fix is a **routing** change
(`route_after_evidence` needs a new `"needs_information"` branch,
distinguishing `ErrorCode.INSUFFICIENT_DATA` from every other error this
node can produce, wired to the existing `finalize_needs_information`
terminal node) — the status-argument change is still made too, for
consistency and because a couple of UI/CLI reads look at `state["status"]`
before the terminal node runs, but it is not sufficient on its own. This is
recorded as design decision DE1 and is the reason D22's "obvious" one-line
description was never actually executed as a one-line fix.

**A third finding, with real consequences for Phase C's cost-control
story:** the sales-velocity insufficient-data gate (`tools.sales`'s
`count_7 < 3 or count_30 < 3`) and the statistics-layer maturity gate
(`SkuPolicy.maturity == "INSUFFICIENT"`, already screened out by
`submission/sweep/candidates.py`) are **two different, unrelated signals**.
Maturity is about total history length; the sales-velocity gate is about a
specific recent window having too few sale-days, which can happen to a
well-established 24-month lumpy/intermittent SKU during a quiet patch.
`detect_candidates` does not call `tools.sales` at all today, so a
sweep-opened case for an established SKU can still hit `fetch_evidence`'s
`INSUFFICIENT_DATA` path post-fix — meaning Phase E's fix is a live
autonomous-sweep path, not just a manual-run edge case, and the sweep must
learn not to re-open (or re-spend an LLM call on) a SKU that is already
parked for this reason. Recorded as design decision DE4, with a concrete
new `ExclusionReason.ALREADY_PARKED` check in `detect_candidates`.

**A fourth finding:** a parking mechanism already exists in full
(`tools/parking.py::park_item`/`get_open_parked_items`/`resolve_park`,
backed by the real `parked_items` table, with `ParkedItemRecord`'s exact
current shape confirmed: `park_id, sku, warehouse_id, reason (free text),
parked_at, resolved_at, resolved_by, note (free text)` — no structured
`question`/`unblocking_action`/`actionable_now` fields). It is currently
wired **only** to the sweep's maturity check
(`submission/sweep/parking.py::maybe_park`), never called from inside the
graph itself. The plan's DE3/DE5 decisions are explicit that Phase E reuses
this exact existing shape (encoding the question and unblocking action into
the free-text `note`, exactly as `maybe_park` already does) rather than
extending the schema — flagged as a deliberate scope boundary (§8), since
extending `ParkedItemRecord` with structured fields would need a migration
this phase otherwise does not require.

**A fifth finding:** no "backfill missing sales" fabricator function
exists. `fixtures/fabricator.py::fabricate_history` inserts a *fresh* run of
days ending yesterday and **raises `ValueError`** on any duplicate
`(sale_date, sku, warehouse_id)` row (R7's loud-guard discipline) — it
cannot be re-run over a partially-populated range, which is exactly what
"backfill the gap" needs. The plan's DE8/Task 5 designs a new,
deliberately-different-contract function (`backfill_missing_sales`) that
treats "row already exists" as success, not an error, for this one
gap-filling operation specifically — named explicitly as a departure from
`fabricate_history`'s existing convention, not a silent inconsistency.

The plan also identifies, ahead of implementation, exactly which two
existing tests this phase breaks and what happens to each (§6): one file
(`test_phase10_demand_clarification_resume.py`) is deleted wholesale, with
its two regression-guard tests explicitly inverted (not dropped) into the
new phase file, asserting absence instead of presence; one test
(`test_phase6_revision_and_ui_reads.py`'s disagreement test) is rewritten,
not deleted, because the user-facing guarantee it protects (a human is told
*why* a case is stuck, with the actual conflicting numbers) still needs a
regression guard even though the mechanism proving it (pause-then-resume)
no longer exists once D21 is executed.

**Verified:**
- `fetch_evidence`'s exact current `_fail` call (no status argument, so
  `BLOCKED` applies) — read directly, not inferred from D22's description.
- `route_after_evidence`'s exact current body (`"blocked" if error_code is
  not None else "ok"`, no third branch) and `finalize_blocked`'s
  unconditional `state["status"] = ProposalStatus.BLOCKED` overwrite — both
  read directly, which is what surfaced the "status-argument fix alone does
  nothing" finding above.
- `_await_window_choice`/`apply_window_choice`/`route_after_window_choice`
  all still present and wired, via direct reads of `workflow.py` (full) and
  `nodes.py` (the full `apply_window_choice` function body) and
  `routes.py` (the full `route_after_window_choice` function) — not taken
  on D21's word that this "is safe to remove," which only argued *that* it
  should be removed, not confirmed *whether* it already had been.
- `tools/sales.py::get_sales_velocity`'s exact `<3`-observation rule and
  window-boundary formula, confirming Entry 006's fix is still live (no
  regression) — read in full.
- `tools/parking.py`'s three functions and `ParkedItemRecord`'s exact
  current field list — read in full, confirming no structured
  question/unblocking-action fields exist today.
- `fixtures/fabricator.py`'s full content, confirming no backfill-style
  function exists and `fabricate_history`'s exact duplicate-refusal
  behavior.
- `fixtures/scenarios.json`'s `INSUFFICIENT_SALES_HISTORY` entry's exact
  `"expected_outcome": "NEEDS_INFORMATION or BLOCKED"` hedge — confirming
  the JSON scenario catalogue itself needs no change.
- `test_phase5_remaining_scenarios.py::test_insufficient_sales_history_blocks`'s
  exact current assertion (`status == BLOCKED`) and
  `test_phase10_demand_clarification_resume.py`'s full test list and exact
  assertions — both read in full to determine precisely what breaks and
  what the replacement assertions should say.
- `submission/app.py`'s and `submission/ui.py`'s exact dead-code surfaces
  once the interrupt is retired (`resume_demand_clarification`, the
  `"resume-window"` CLI branch, `_print_result`'s `demand_clarification`-kind
  branch, `_render_window_choice_form` and its dispatch condition) — all
  read directly.

**NOT verified:**
- **Nothing was implemented, run, or tested this session.** `PHASE_E_PLAN.md`
  is a planning artifact only. No node, route, or fabricator function
  described in it exists as a result of this session.
- Did not independently re-verify every claim the context-gatherer sub-agent
  returned about files this session's own direct reads did not separately
  cover (e.g. the exact current wording inside `submission/ui.py`'s status
  label dict beyond the `AWAITING_VENDOR_APPROVAL` line already quoted in
  Entry 018) — cross-checked wherever direct reads overlapped, consistent
  with the sub-agent's report everywhere they did.
- Did not run any test file this session (no code changed; nothing to
  regress) — but, matching the discipline `PHASE_C_PLAN.md`/`PHASE_D_PLAN.md`
  established, `PHASE_E_PLAN.md` §7 is written so a future implementation
  session has an unambiguous, pre-agreed answer to "which test do I run
  right now," specifically to avoid the full-suite/lock problems Entries
  011-016 documented recurring during this phase's work.
- Did not verify whether any test file **beyond** the ones this session's
  greps found references `_await_window_choice`/`apply_window_choice`/
  `route_after_window_choice`/`resume_demand_clarification` — the grep this
  session ran across `submission/tests/*.py` is believed exhaustive (the
  tool reported all matches, not a truncated/capped result), but a future
  agent should re-grep immediately before deleting anything, per this
  project's own "partial evidence has a bad track record" lesson (Entry
  006).
- Did not verify the exact current contents of `submission/ui.py`'s
  `_render_window_choice_form` function body beyond its opening ~20 lines
  (read enough to confirm it exists and its dispatch condition, not its
  full body) — sufficient for "delete this function," insufficient if a
  future session wanted to salvage any part of its rendering logic for
  something else (this plan does not propose salvaging any of it).

**Blocked / open:** O1-O5 (original), DB1-DB5 (Phase B), the Phase-C-scoped
open questions from Entry 017, and Phase D's open questions from
`PHASE_D_PLAN.md` §9 all remain unaddressed this session, carried forward
unchanged. **New, scoped to Phase E, recorded in `PHASE_E_PLAN.md` §9:**
- Whether `test_phase6_revision_and_ui_reads.py`'s rewritten disagreement
  test should be kept as a UI-layer-specific check alongside the new phase
  file's equivalent test, or considered redundant and deleted once the new
  test exists — defaulted to "keep both" but flagged as a five-minute call
  at implementation time, not decided now.
- The exact final wording of `fetch_evidence`'s enriched insufficient-data
  message — Task 2's draft preserves the existing test's exact substrings
  alongside new content, but should be checked against
  `test_phase9_demand_clarification_message.py`'s assertions before the
  task is considered done, not assumed to match by construction.
- Whether `resolve_park`'s existing validation should get a dedicated new
  test now that Phase E is the first caller to populate `parked_items` from
  inside the graph itself — flagged as optional, not required for this
  phase's exit criteria.

**Plan changed?:** No changes to `AUTONOMOUS_PLAN.md` itself this session.
`PHASE_E_PLAN.md` is a new, separate companion document, same relationship
`PHASE_A_PLAN.md`/`PHASE_B_PLAN.md`/`PHASE_C_PLAN.md`/`PHASE_D_PLAN.md` had
to the main plan for their respective phases. No change to `DECISIONS.md`'s
D20-D24 — this session's plan treats them as already-correct decisions
awaiting execution, not as needing revision.

**Decisions added to DECISIONS.md:** none — DE1-DE8 are flagged as this
plan's own implementation-level decisions in `PHASE_E_PLAN.md`, distinct
from (and downstream of) the already-recorded D20-D24, which this session
did not need to re-decide. If a future session wants DE1/DE4 in particular
promoted to `DECISIONS.md` as their own `D<n>` records (since DE1's routing
finding and DE4's sweep-exclusion finding are both genuinely new
architecture, not just an execution detail of D20-D24), that is a reasonable
next step but was not done here, per this session's planning-only scope.

**State after this session:**
- Phase A: complete (Entry 009).
- Phase B: implemented with focused test evidence (Entries 011-016).
- Phase C / Phase C2: implemented (confirmed in Entry 018), tracker gap
  flagged in Entry 018, unchanged by this session.
- Phase D: implemented (confirmed in this session's own direct reads of
  `domain/tool_models.py::VendorSendDecision`, `submission/graph/nodes.py::request_vendor_approval`/
  `handle_vendor_decision`/`finalize_vendor_cancelled`, `workflow.py`'s
  `_await_vendor_approval` node, and the full, passing-looking
  `test_phase_d_two_gate_approval.py` — this closes Entry 018's own
  "not started" status for Phase D; **note that Entry 018 itself only
  planned Phase D and does not claim to have built it, so there may be an
  Entry between 018 and this one that also went unlogged, the same
  process gap Entry 018 flagged for Phase C** — this session did not
  investigate who built Phase D or when, since that was not this session's
  task; flagged here for visibility only).
- Phase E: **not started.** Zero implementation. Now has a detailed,
  ground-truth-verified execution plan (`PHASE_E_PLAN.md`) that identifies
  Phase E's design as already fully decided (D20-D24) and unbuilt.
- Phases F-H: not started, unchanged.
- All open questions (O1-O5, DB1-DB5, Phase-C's, Phase-D's, and Phase-E's
  new ones above) remain open.

**Next recommended step:** Investigate (briefly) whether an unlogged
tracker entry exists for Phase D the way Entry 018 flagged for Phase C, OR
proceed directly to `PHASE_E_PLAN.md` §6 execution order, Task 1
(`route_after_evidence`'s new branch) — the two are independent and either
order is fine. Task 1 is deliberately first because it is the smallest,
most isolated change and the plan's own §1 explains why the "obvious" fix
(the status argument alone) does not work without it.

**Notes for the next agent:**
- **Do not "fix" `fetch_evidence` by only changing the `_fail(...)` call's
  status argument.** `finalize_blocked` unconditionally overwrites
  `state["status"]` before anything downstream ever sees it, because
  `route_after_evidence` still routes every non-null `error_code` to
  `"blocked"`. The routing function needs the new branch — see `PHASE_E_PLAN.md`
  §1 and Task 1. This was not previously documented anywhere and is the
  most important trap in this phase.
- **Do not run the full test suite as a routine verification step during
  Phase E implementation.** Same instruction as Entries 017/018 gave for
  Phases C/D, repeated because the user explicitly asked again this
  session. `PHASE_E_PLAN.md` §7 names the exact file(s) to run after each
  task.
- **`_await_window_choice` retirement touches five files**
  (`nodes.py`, `workflow.py`, `routes.py`, `app.py`, `ui.py`) and deletes one
  whole test file. Do the mechanical deletion as one contained task (Task 3
  in the plan), not spread across several sessions — a half-retired
  interrupt (e.g. the node removed from `workflow.py` but
  `apply_window_choice` still present in `nodes.py`) is a worse state than
  either "fully present" or "fully retired."
- **The sales-velocity insufficient-data gate and the maturity-based park
  gate are different signals covering different SKUs.** Do not assume
  fixing `fetch_evidence` alone protects the sweep's LLM-call budget — the
  sweep needs its own new exclusion check (DE4, Task 4) against open
  `parked_items` rows, or an established lumpy SKU having a quiet week will
  get re-opened and re-spend a full 3-LLM-call case run on every sweep
  until a human resolves the park.


### Entry 020 — 2026-09-12 — Claude Sonnet 5 (Kiro) — planning

**Read:** `AUTONOMOUS_TRACKER.md` (Entries 001-019, full), `GAP_FIX_PLAN.md`
(full), `GAP_NEEDS_INFORMATION.md` (full), `UPGRADES.md` (full),
`AUTONOMOUS_PLAN.md` §Phase F, §Phase G, §Phase H and the scenario catalogue
(full text of each), plus targeted greps confirming no `manual_order`-style
file exists yet (Phase F unbuilt) and re-confirming `tools/sales.py`'s
window-boundary fix is live (already known from Entry 019, re-checked for
this document's own accuracy).

**Phase / tasks touched:** none — planning/inventory only. No checkbox in
`AUTONOMOUS_PLAN.md` was ticked.

**Files created:**
- `PHASE_E1_PLAN.md` (repo root) — explicitly **not** a ground-truth-verified
  execution plan like `PHASE_A_PLAN.md` through `PHASE_E_PLAN.md`. It is a
  consolidated inventory of every not-yet-built item currently scattered
  across `AUTONOMOUS_PLAN.md` (Phases F, G, H), `GAP_NEEDS_INFORMATION.md`,
  and `UPGRADES.md`, each tagged with a confidence level (confirmed unbuilt /
  believed unbuilt / possibly already superseded) and a recommended order,
  so that once Phase E ships there is a ready queue instead of needing to
  re-read four separate documents.

**Files modified:** `AUTONOMOUS_TRACKER.md` (this entry only)

**Did:** The user asked for a "Phase E.1"-style follow-on document: after
Phase E is implemented, what else is left to build, everything included, so
nothing outstanding gets missed. Rather than write a fifth full
ground-truth-verified plan (which Phase E's own `PHASE_E_PLAN.md` already
is, for the item the user originally asked about), this session instead
read the three older backlog documents in full and cross-referenced them
against what Phases A-D have already built, flagging overlaps explicitly:

- **Phase H's "supplier confirmation path" item and `GAP_NEEDS_INFORMATION.md`'s
  "`CONFIRMED` is unreachable" gap are the same defect**, described in two
  places — flagged so a future session does not build it twice.
- **Phase H's "real background scheduler" item and Upgrade 1's "proactive
  monitoring agent" are largely the same ask**, and Upgrade 1's own
  scan-and-open-a-case half is now **already done** by Phase C's sweep
  (`submission/sweep/run.py::run_sweep`) — what's left of Upgrade 1 is
  narrower than its original 2026-09-06 write-up: just the scheduler itself
  and the two-way email conversation loop, both of which depend on Upgrade 4.
- **Upgrade 3 (vendor ordering integration) is now largely superseded** —
  this session confirmed (via Entry 019's own direct reads, re-cited here)
  that Phase D already built the send capability, the trust model (templated
  content, gated behind approval, idempotent, a dedicated second gate). What
  remains of Upgrade 3 is a real-world operational step (SPF/DKIM/DMARC
  go-live review before flipping `vendor_email_enabled` for real), not code.
- **`GAP_NEEDS_INFORMATION.md`'s `confirmed_inbound`/duplicate-order gap is
  possibly already mitigated** by Phase B/C's reorder guard
  (`get_open_order_quantity`), which sidesteps the need for
  `confirmed_inbound` to ever be accurate by checking open purchase requests
  directly instead — flagged as "possibly superseded, re-verify before
  treating as open" rather than asserted either way, since this session did
  not re-read `get_open_order_quantity`'s exact current logic in full to
  confirm it fully closes the gap versus only reducing its likelihood.
- The `tools/sales.py` window-boundary item still listed in
  `AUTONOMOUS_PLAN.md` §Phase H is **confirmed already fixed** (per Entry
  006 and this session's own re-check) — flagged as "remove this line item,
  it's done" rather than left ambiguous.
- The `app.py::_print_cancellation` false-string item is flagged as
  "possibly already fixed" — `GAP_NEEDS_INFORMATION.md`'s own 2026-09-11
  verification pass says `CancellationResult.budget_released` was added and
  `_print_cancellation` now reads it, which contradicts `AUTONOMOUS_PLAN.md`
  §Phase H still listing it as outstanding. Not resolved either way this
  session — flagged for a direct read before anyone acts on it.

Upgrade 4 (two-way email, on-premise reply parsing) is called out as the one
item in the entire backlog still worth a **dedicated planning pass of its
own** rather than a checklist line — it is the only piece that would make
the system genuinely conversational over email, and it carries a real
security/data-residency design constraint (replies are untrusted input;
parsing must stay local, never sent to a hosted LLM) that a checklist entry
would under-serve.

**Verified:**
- Direct read of all three backlog source documents in full this session
  (not summarized from memory or from prior tracker entries' descriptions of
  them).
- `AUTONOMOUS_PLAN.md`'s exact current Phase F, Phase G, Phase H, and
  scenario-catalogue text, read directly (not paraphrased from Entry 001's
  original description of the plan, which predates several since-added
  sections like A6/B10).
- No file matching `manual_order` exists in the workspace (`file_search`,
  zero results) — supports, but does not by itself prove, that Phase F is
  unbuilt (a differently-named implementation could still exist; this
  session's "believed unbuilt, not re-verified" tag for Phase F reflects
  that this was a filename search, not a full code read, unlike the
  direct-code-read confirmation this session did perform for Phase E's own
  claims in Entry 019).

**NOT verified:**
- **Nothing was implemented this session.** `PHASE_E1_PLAN.md` is an
  inventory document, explicitly labeled as such and explicitly **not**
  claiming the same ground-truth-verification rigor as
  `PHASE_A_PLAN.md`-`PHASE_E_PLAN.md`.
- Did not directly re-read `tools/execution.py::get_open_order_quantity` or
  `nodes.compute_risk` this session to confirm whether the reorder guard
  fully closes the `confirmed_inbound`/duplicate-order gap or only reduces
  its likelihood — flagged explicitly in `PHASE_E1_PLAN.md` §3 as
  "possibly already mitigated... worth re-reading... before assuming."
- Did not directly re-read `app.py::_print_cancellation`'s current body to
  resolve the contradiction between `AUTONOMOUS_PLAN.md` §Phase H (lists it
  as outstanding) and `GAP_NEEDS_INFORMATION.md`'s 2026-09-11 note (says it
  was fixed) — flagged as unresolved, not guessed at either way.
- Did not directly re-read `submission/notifications/email.py::send_email`
  to confirm or deny whether a test-mode escape hatch already exists for
  the "email cannot be tested without live Gmail credentials" gap — flagged
  as "likely still true, worth a quick check" rather than asserted.
- Did not verify whether Phase F (manual order path) exists under some
  other name/module the `manual_order` filename search would have missed —
  a filename search is weaker evidence than the direct code reads this
  session performed for the Phase C/D/Upgrade-1/Upgrade-3 overlap claims
  above.

**Blocked / open:** No new open questions specific to this session beyond
what `PHASE_E1_PLAN.md` §3 already flags inline (the three "possibly already
superseded/fixed" items above, each needing a direct read before being
trusted either way). All prior open items (O1-O5, DB1-DB5, Phase C's,
Phase D's, Phase E's) remain open and are out of this session's scope.

**Plan changed?:** No changes to `AUTONOMOUS_PLAN.md`, `GAP_FIX_PLAN.md`,
`GAP_NEEDS_INFORMATION.md`, or `UPGRADES.md` this session — `PHASE_E1_PLAN.md`
is a new, separate consolidation document that references all four without
editing any of them, so their own histories stay intact and this document
can be treated as disposable/regeneratable if it goes stale, rather than as
a fifth source of truth to keep in sync by hand.

**Decisions added to DECISIONS.md:** none — this session made no
architecture decisions, only inventoried existing ones.

**State after this session:**
- Phase A: complete.
- Phase B: implemented with focused test evidence.
- Phase C / Phase C2: implemented (tracker gap noted in Entry 018).
- Phase D: implemented (tracker gap noted in Entry 019).
- Phase E: not started, fully planned (`PHASE_E_PLAN.md`) — still the
  immediate next step.
- Phase F, Phase G, Phase H: not started (F and G believed unbuilt, not
  independently re-verified beyond a filename search this session; H is a
  checklist with at least one item confirmed already done and two more
  flagged as possibly already done).
- Older backlog (`GAP_NEEDS_INFORMATION.md`, `UPGRADES.md`): several items
  now believed superseded by Phases B/C/D's actual implementation, flagged
  individually in `PHASE_E1_PLAN.md` rather than assumed resolved without
  comment.

**Next recommended step:** Implement Phase E per `PHASE_E_PLAN.md` (unchanged
from Entry 019's recommendation). `PHASE_E1_PLAN.md` is queued behind it, not
instead of it.

**Notes for the next agent:**
- **`PHASE_E1_PLAN.md` is intentionally lower-rigor than the phase-lettered
  plans.** Before starting any single item from it, re-verify that item's
  "unbuilt" status with a direct code read — this project has now had two
  phases (C/C2 per Entry 018, D per Entry 019) built with no tracker entry
  recording them, so "the plan says it's not built" is measurably weaker
  evidence in this specific codebase than it would be elsewhere. The
  document says this about itself in its own §5, but it's worth repeating
  here since it's the main risk of a consolidation document like this one:
  staleness.
- If `PHASE_E1_PLAN.md` itself goes stale (e.g. Phase F gets built and this
  document isn't updated), prefer regenerating it fresh from the current
  state of `AUTONOMOUS_PLAN.md`/`GAP_NEEDS_INFORMATION.md`/`UPGRADES.md`
  over hand-patching it — it was built as a snapshot/index, not as a
  living document with its own append-only discipline like the tracker.


### Entry 021 — 2026-09-12 — Claude Sonnet 5 (Kiro) — verification + planning

**Read:** `AUTONOMOUS_TRACKER.md` (Entries 001-020, full), `AUTONOMOUS_PLAN.md`
§Phase F (full), `DECISIONS.md` D23 (full), `PHASE_E1_PLAN.md` (own prior
session's inventory document, re-read for its Phase-F entry), and direct
re-reads (not trusted from Entries 018/019's own descriptions) of:
`submission/graph/nodes.py` (`fetch_evidence`, `_override_ambiguity_if_windows_disagree_on_risk`,
`compute_risk`, `fetch_budget_and_policy`, `draft_proposal`,
`apply_human_edit`, `request_vendor_approval`, `handle_vendor_decision`, full
region), `submission/graph/routes.py` (full, confirming
`route_after_evidence`'s current exact body), `submission/graph/workflow.py`
(confirmed via targeted greps: no `await_window_choice` node remains),
`submission/graph/support.py` (`TargetReconciliation`/`reconcile_target`,
full), `submission/graph/economics.py` (`size_order_quantity`'s docstring and
signature), `submission/app.py` (full), `submission/state/state.py` (full),
`submission/portfolio.py` (`scan_portfolio`, `_stocked_pairs`, full),
`submission/ui.py` (sidebar target slider, `screen_watchlist`,
`screen_investigate`, `screen_case` dispatch region), `submission/config.py`
(target-cover fields), `domain/tool_models.py` (`ProductRecord`,
`ReplenishmentProposal`'s provenance fields, `SkuPolicy`, `ErrorCode`,
`ProposalStatus`), `tools/inventory.py` (`get_product`, `get_stock_position`,
`calculate_stock_risk`, full), `tools/classification.py` (full),
`fixtures/fabricator.py` (confirmed `backfill_missing_sales` exists),
`submission/sweep/candidates.py` (confirmed `ALREADY_PARKED` exclusion
exists), and `docs/testing/phase_e_insufficient_data_loop.tdd.md` (full).

**Phase / tasks touched:** Verification of Phases D and E (no changes), then
planning only for Phase F ("Manual order path") of `AUTONOMOUS_PLAN.md`. No
implementation. No checkbox in `AUTONOMOUS_PLAN.md` was ticked.

**Files created:**
- `PHASE_F_PLAN.md` (repo root) — full end-to-end Phase F execution plan: a
  §0 re-verification section confirming Phases D and E are genuinely still
  implemented (direct code reads, not trust in prior tracker entries), a
  ground-truth table for Phase F itself, eight explicit design decisions
  (DF1-DF8), a new/modified-files manifest, a 4-task implementation plan
  with code sketches, a 9-test new test file specification
  (`test_phase_f_manual_order_path.py`), a testing section naming exact
  narrow commands per task (repeating the user's standing instruction not to
  run the full suite routinely), an explicit out-of-scope list, open
  questions, and a concrete exit-criteria checklist.

**Files modified:** `AUTONOMOUS_TRACKER.md` (this entry only)

**Did:** The user asked to re-verify that Phases D and E (both flagged in
Entries 018/019 as implemented with no corresponding tracker entry) are
still genuinely in the code, since code can change between sessions, and
then to write a ground-truth-verified Phase F plan.

**Re-verification result: both phases are confirmed still fully live**,
by direct reads performed fresh this session, not by trusting Entry
018/019's own descriptions. Phase D: `request_vendor_approval`,
`handle_vendor_decision`, `finalize_vendor_cancelled`, `VendorSendDecision`,
`resume_vendor_send`, and the `approve-vendor-send`/`reject-vendor-send` CLI
commands all read directly and confirmed present, unchanged in shape. Phase
E: `route_after_evidence`'s `"needs_information"` branch, `fetch_evidence`'s
exact-deficit message and `park_item(...)` call, `backfill_missing_sales`,
and the sweep's `ALREADY_PARKED` exclusion all read directly and confirmed
present; a repo-wide grep for `apply_window_choice`/`_await_window_choice`/
`route_after_window_choice` found zero matches, confirming the retirement
Phase E's plan called for actually happened. `docs/testing/phase_e_insufficient_data_loop.tdd.md`
exists, recording 8 passing tests against a RED baseline of 3 failures —
this is itself evidence the phase was implemented following something close
to the plan's own TDD discipline, even though no tracker entry records the
session that did it. **The tracker gap remains open** (still no logged entry
for who built Phase D or Phase E, or exactly when) — this session did not
attempt to resolve that gap, only confirmed the code itself is real and
correct, which was the user's actual question.

**The single most important technical finding for Phase F itself:** a
manual order path already exists in a basic form (`app.py run` / the
watchlist's "Look into this" button both already work for any SKU,
including one with thin data) — so Phase F is **not** "build a manual order
path from scratch." What's actually missing, and what this session's
ground-truth reads confirm, is narrower and more specific than
`AUTONOMOUS_PLAN.md`'s own bullet list implies at a glance:

1. No override mechanism for `fetch_evidence`'s `INSUFFICIENT_DATA` path —
   confirmed by reading the full current function body (same one Phase E
   just finished), which has no hook for "a human already supplied the
   demand assumption."
2. **Critically, and not previously flagged anywhere in this project's own
   documents**: simply bypassing the `INSUFFICIENT_DATA` check is not
   sufficient. `compute_risk` reads `sales.window_7_days`/`window_30_days`
   directly to get a velocity number, and `size_order_quantity` sizes
   strictly from that velocity — a case that skips the check with a zero
   velocity (which is what `tools.sales.get_sales_velocity`'s own
   insufficient-data branch always returns) would size an order of
   essentially zero units, defeating the entire point of ordering a
   brand-new product. D23's own phrase "the human has supplied the demand
   assumption the data could not" was read literally this session: the
   human must supply an actual number (an assumed velocity), not merely
   permission to skip a check. This reframes Phase F's core design (DF1) and
   is the reason this plan is not simply "add an `override_insufficient_data:
   bool` flag."
3. `target_provenance`/`target_basis` fields already exist on
   `ReplenishmentProposal` (built for Phase C2's floor reconciliation) and
   are already wired through `draft_proposal` — Phase F reuses them for
   free, no new model field needed.
4. Policy floors already apply unconditionally in `fetch_budget_and_policy`
   — D23's "policy floors still apply to manual orders" requirement is
   **already satisfied with zero changes**, confirmed by reading the exact
   call site.
5. No approval-card rendering exists for a blunt "this was a human's
   assumption, not derived data" warning — the existing `target_provenance`
   render in `ui.py` is a factual footer (shown alongside the statistical/
   active/floor numbers), not a warning banner; D23 requires the card to
   "state plainly" the gap, which needs new, dedicated rendering.

The plan's eight design decisions (DF1-DF8) follow directly from these five
findings: the override supplies a velocity number, not just a bypass flag
(DF1); it's carried as a new small `CaseState["demand_override"]` field
rather than overloading the shared `SalesVelocity` model (DF2);
`fetch_evidence` checks for it before, not after, the real sales read, so a
manually-overridden case never gets parked by Phase E's own mechanism
(DF3); `create_initial_state` gains two new optional parameters, matching
the pattern every prior phase has used for backward-compatible extension
(DF4); the sweep is never wired to set this field, enforced by simply never
touching its call site rather than a runtime guard (DF5); the warning is a
new UI block distinguishing "a human supplied a demand assumption" from "a
human picked a different vendor" (Phase C2's `apply_human_edit`, which also
uses a `human:<name>`-shaped provenance string and must not accidentally
trigger this new warning) (DF6); the CLI extends the existing `run` command
with two optional trailing arguments rather than forking a new command
(DF7); and the UI gets a deliberate, separate "Order manually instead"
button rather than a silent fallback (DF8), directly required by
`AUTONOMOUS_PLAN.md`'s own R5 rule about explicit, audited exceptions to
"no per-product human input."

**Verified:**
- Every claim in §0 and §1 of `PHASE_F_PLAN.md` was confirmed by a direct
  `read_file`/`grep_search` this session, not carried over from Entry
  018/019's descriptions — specifically re-reading `fetch_evidence`,
  `route_after_evidence`, and `compute_risk` in full to confirm both the
  Phase E retirement and the velocity-dependency finding above.
- `ReplenishmentProposal.target_provenance`/`target_basis`'s existing
  presence and `draft_proposal`'s exact read of
  `state.get("target_provenance", "derived")` — confirmed by direct read,
  not assumed from Phase C2's own plan document.
- `fetch_budget_and_policy`'s unconditional call to
  `get_active_policy_floor` — confirmed by direct read, establishing that
  D23's floor requirement needs no new code.
- The three known callers of `create_initial_state`
  (`app.py::run_case`, `submission/ui.py::screen_investigate`,
  `submission/sweep/run.py::execute_candidate`) — confirmed by grep; none
  currently pass anything resembling a manual-override parameter, so Task
  1's new optional parameters are purely additive to all three.
- `calculate_stock_risk`'s explicit "do not invent a velocity floor"
  handling of `daily_velocity <= 0` — read in full, which is what surfaced
  finding #2 above (a zero-velocity manual order would compute
  `cover_days=None`/an effectively-zero-sized order, not an error, meaning
  the bug would be silent rather than loud — worth flagging as the kind of
  defect that's easy to miss without reading this function directly).

**NOT verified:**
- **Nothing was implemented this session.** `PHASE_F_PLAN.md` is a planning
  artifact only.
- Did not verify `checkpoint_allowlist()`'s exact serialization behavior for
  a plain `dict`-typed `CaseState` field (flagged as an open question in
  `PHASE_F_PLAN.md` §8) — `vendor_rejection_detail: Optional[dict]` is cited
  as existing precedent for a plain-dict `CaseState` field, but this session
  did not trace `checkpoint_allowlist`'s exact mechanism deeply enough to
  guarantee a new dict field behaves identically; flagged for
  implementation-time confirmation rather than asserted.
- Did not exhaustively catalogue every existing Streamlit `AppTest` usage in
  `submission/tests/` to confirm which file, if any, already tests
  UI-warning-banner-style rendering the way `PHASE_F_PLAN.md` §5 test 8
  proposes to mirror — flagged in §6's testing table as "confirm exact
  filename by grep before running," not resolved here.
- Did not verify whether any `emit_audit` event-type naming convention
  document exists beyond reading actual call sites in `nodes.py` — the new
  `"demand_override_applied"` event name follows the existing snake_case
  pattern by observation, not against a documented naming standard (none
  appears to exist in this codebase, based on this session's reads).

**Blocked / open:** O1-O5, DB1-DB5, Phase C's/D's/E's open questions all
carried forward unchanged, out of this session's scope. **New, scoped to
Phase F, recorded in `PHASE_F_PLAN.md` §8:**
- Exact shape of `CaseState["demand_override"]` (plain dict vs. frozen
  dataclass) — needs a `checkpoint_allowlist()` check before finalizing.
- Whether the manual-order entry point should be reachable only from the
  existing thin-data watchlist row, or also from a general "order something
  brand new" search — defaulted to "only from the existing row" as the
  narrower, D23-literal reading.
- Exact final wording of the approval-card warning — D23 quotes a specific
  required phrase; use it verbatim rather than the plan's own illustrative
  draft text.

**Plan changed?:** No changes to `AUTONOMOUS_PLAN.md`, `DECISIONS.md`, or any
other existing document this session. `PHASE_F_PLAN.md` is a new, separate
companion document, same relationship every prior `PHASE_*_PLAN.md` has had
to the main plan. `PHASE_E1_PLAN.md`'s own Phase F entry (from Entry 020) is
now superseded by this fuller plan — not edited (append-only discipline
applies to the tracker, not to `PHASE_E1_PLAN.md`, but for clarity: a future
session should treat `PHASE_F_PLAN.md` as authoritative over
`PHASE_E1_PLAN.md`'s brief Phase F summary, which was written without a
direct-code-read pass).

**Decisions added to DECISIONS.md:** none — DF1-DF8 are this plan's own
implementation-level decisions, downstream of and consistent with the
already-recorded D23, which this session did not need to re-decide. If a
future session wants DF1 (the velocity-number finding) promoted to its own
`D<n>` record, given it's genuinely new architecture insight not previously
written anywhere, that would be reasonable but was not done here.

**State after this session:**
- Phase A: complete.
- Phase B: implemented with focused test evidence.
- Phase C / Phase C2: implemented (tracker gap noted in Entry 018,
  unresolved).
- Phase D: implemented, **re-confirmed live this session** by direct code
  read (tracker gap noted in Entry 019, unresolved).
- Phase E: implemented, **confirmed live this session** by direct code
  read, including confirmation that its own TDD evidence doc exists
  (tracker gap for who built it remains, same pattern as C/D, unresolved).
- Phase F: not started. Zero implementation. Now has a detailed,
  ground-truth-verified execution plan (`PHASE_F_PLAN.md`).
- Phases G, H: not started, unchanged.
- `PHASE_E1_PLAN.md`'s Phase F entry: superseded by this fuller plan (not
  edited, per its own §5 note that it's a regeneratable snapshot, not a
  living document).

**Next recommended step:** Implement Phase F per `PHASE_F_PLAN.md`,
starting with Task 1 (`CaseState`/`create_initial_state`'s new optional
parameters) since it's the smallest, most isolated change and every later
task depends on it existing first.

**Notes for the next agent:**
- **Phases D and E are real. Trust them, but the tracker gap around who
  built them is still open** — this session is now the second one to
  re-confirm Phase D's code (Entry 019 built it or found it; this session
  independently re-verified it's still there) and the first to independently
  re-verify Phase E's code from scratch (Entry 019 planned it; this session
  confirmed it was actually built, matching but not identical to that
  plan's exact test names).
- **A manual order that skips `INSUFFICIENT_DATA` but doesn't supply a real
  velocity number is a silent bug, not a loud one.** `calculate_stock_risk`
  and `size_order_quantity` will not error on a zero velocity — they will
  quietly size a near-zero order. Do not implement Phase F as "just remove
  the block"; the assumed-velocity design (DF1) is load-bearing.
- **`fetch_budget_and_policy` already applies policy floors to every case
  unconditionally.** Do not add a special case for manual orders here —
  there is nothing to add; this exit criterion is already met.
- Do not run the full test suite as a routine step during Phase F
  implementation — same standing instruction as every prior phase, `PHASE_F_PLAN.md`
  §6 names the exact narrow command per task.


### Entry 022 — 2026-09-12 — Claude Sonnet 5 (Kiro) — planning (plan amendment)

**Read:** `AUTONOMOUS_TRACKER.md` (Entries 001-021), `AUTONOMOUS_PLAN.md`
§Phase G (full, pre-amendment), §Phase F, §1 global rules R1-R10,
`submission/statistics/maturity.py` (full, direct read — the load-bearing
check for this session), `tools/sales.py::get_sales_velocity`'s
`<3`-observations rule (re-confirmed from Entry 021's read),
`submission/ui.py`'s sidebar slider region and its two consumers
(`scan_portfolio`, `run_case`), `submission/app.py`'s `run` command and
`resume_missing_info`, `submission/config.py`'s target-cover fields,
`submission/graph/nodes.py::apply_human_edit` (the `chosen_target_basis`
handling), `tools/policy_floors.py`, `fixtures/fabricator.py::backfill_missing_sales`,
`tools/parking.py` (`park_item`/`resolve_park` signatures), and
`database/schema.sql`'s table list (to separate input tables from derived
tables for G1.1).

**Phase / tasks touched:** Phase G (amended substantially), plus a new global
rule **R11** added to §1 that applies retroactively across every phase. No
implementation. No checkbox ticked as complete.

**Files created:** none

**Files modified:**
- `AUTONOMOUS_PLAN.md` — §Phase G rewritten and substantially expanded; new
  global rule **R11** added inside the Phase G section (see "Plan changed?"
  below for why it landed there rather than in §1's original R1-R10 block).
- `AUTONOMOUS_TRACKER.md` (this entry)

**Did:** The user set a design rule that contradicts and supersedes
`PHASE_F_PLAN.md`'s DF1 (my own prior-session decision), then asked when the
two UIs get built and required that the data UI support real, validated
database editing.

**The rule, in the user's own framing:** the system must never accept a
human-supplied demand number. When data is insufficient, the system tells the
human what is missing, **the human enters it into the actual database**, the
human confirms, and the system **re-fetches from the database** — never from
a form field. The single permitted exception: when history exists but is too
thin to trust (their example: "only 4 months old"), a human may enter **how
many days of stock they want for that product, and nothing else**, and the
agents then do all their work against that target.

**Verified the rule is coherent against the code, and it made Phase F
simpler rather than harder.** Direct read of
`submission/statistics/maturity.py` confirms the thresholds:
`INSUFFICIENT` under 3 months, `PROVISIONAL` 3-12 months, `ESTABLISHED` 12+.
Separately, `tools/sales.py::get_sales_velocity` needs only **3 sale-days in
each window**. So at four months of history the **demand rate is available
from data** (`get_sales_velocity` succeeds) and what is actually
untrustworthy is the **derived cover target** (maturity `PROVISIONAL`). Two
different signals had been conflated — including by me, in Entry 021.

**This means Entry 021's DF1 was wrong and is now superseded.** DF1 proposed
that a manual order accepts a human-typed daily velocity. That solves a
problem which does not exist at four months (the velocity is right there in
the data) and is the wrong fix at zero months (where the correct answer is
Phase E's existing park → backfill → re-fetch loop, already built). The
user's rule is both stricter and closer to what the codebase already
supports. `PHASE_F_PLAN.md` §2 DF1 must be rewritten before Phase F is
implemented — **flagged, not yet done this session** (see NOT verified).

**Also corrected: advice I gave the user to relay to another agent.** In the
prior turn I told them to answer "human-entered daily demand rate" to an
external agent's question about the manual-order sizing basis. That advice
was wrong under this rule and I said so plainly this session, supplying a
replacement answer (reject all three offered options; park-and-refetch for
thin data, days-of-cover only for immature data, fully derived for
established).

**Answered the UI question:** both UIs are **Phase G** — G1 the simulator /
data console, G2 the agent console. Phase G's existing text was one line for
the entire data-editing capability ("Browse and edit every table"), which is
nowhere near what the user described and, more importantly, is now
load-bearing: **under R11, G1 is the only legitimate way a human supplies
missing data.** Without a real screen writing real rows into real tables,
Phase E's park → backfill → re-run loop is terminal-only and the rule
degrades back into "type a number into the agent."

**The Phase G amendment**, in five parts:
1. **New global rule R11** — humans supply data, never answers. States the
   never-type-a-number rule, the enter-it-in-the-table-then-re-fetch
   mechanism, the one maturity-gated exception, and explicitly preserves what
   is *not* an override (choosing among computed options: `edited_offer_id`,
   `chosen_target_basis`, and `policy_rules` floors, the last already an
   audited R5 exception).
2. **Four named R11 violations that are live today**, all found this
   session by direct read and none previously flagged anywhere in this
   project's documents:
   - `submission/ui.py`'s sidebar days-of-cover slider feeds **both**
     `scan_portfolio()` **and** `run_case()`, so a human-typed number
     currently drives the risk assessment of **every product on every
     screen**. This is the biggest one — it is the flat-14 problem D2 exists
     to remove, still fully present, and it is not a manual-order concern at
     all; it is the default behaviour of the whole watchlist.
   - `app.py run <sku> <wh> [target_cover_days]` accepts the input on every
     case regardless of maturity.
   - `resume_missing_info`'s form offers `target_cover_days`
     unconditionally (its `sku`/`warehouse_id` fields are fine — those
     identify which product, they are not evidence).
   - `config.target_cover_default_days = 14` as a flat fallback for every
     product.
3. **G1.1 — real database editing with real validation.** Full CRUD on the
   ten **input** tables; the six **derived** tables
   (`sku_policy`, `sweep_runs`, `parked_items`, `purchase_requests`,
   `audit_events`, `agent_memory_signals`) explicitly **read-only and
   labelled as such**, on the reasoning that hand-editing a derived row puts
   a number into the evidence chain that no computation produced — precisely
   the failure R3/R11 exist to prevent. Per-field validation specified
   concretely (type/range, FK integrity with the missing key named, the
   `UNIQUE(sale_date, sku, warehouse_id)` R7 constraint surfaced as "a row
   exists for that day, edit it instead" rather than an IntegrityError, date
   sanity, and a warn-not-block cross-field check for `selling_price` below
   landed cost, which B10 already treats as a data error). All writes go
   through the existing fabricator/tool layer, never a raw SQL box, so there
   is one write path and the fabrication log stays complete.
4. **G1.2 — the missing-sales-data screen**, which is what makes R11
   workable in practice: deep-linked from G2's park queue carrying the SKU,
   warehouse and exact date range the park record already stores; shows the
   range day by day with gaps visibly empty; accepts per-day or bulk entry
   via Phase E's already-built `backfill_missing_sales`; a live counter
   showing how many more observations the `<3` threshold needs; and a "data
   is in — re-run this case" button that **re-runs so the graph re-fetches
   from the database**, explicitly never passing the entered numbers into
   the run.
5. **G2's days-of-cover input is now gated on maturity rather than removed
   outright** — a **superseded-note amendment** to an existing task. The old
   text said "`target_cover_days` input **removed entirely**", which is
   correct for an `ESTABLISHED` SKU and wrong for a
   `PROVISIONAL`/`INSUFFICIENT` one, where the derived target is the
   untrustworthy number and a human target is the legitimate exception. Now
   specified three ways by maturity tier, with `target_provenance` shown on
   the approval card either way.

Exit criteria rewritten to be checkable: the full park → enter real data →
re-run → proposal loop must work from the two screens with no terminal; an
invalid edit must be refused with a specific readable reason and leave the
row untouched; and a proposal produced after a G1.2 backfill must
demonstrably have taken its `daily_velocity` from the newly written
`sales_daily` rows — which is the test that proves the re-fetch, not a form
value, fed the arithmetic.

**Verified:**
- `submission/statistics/maturity.py`'s exact tier thresholds by direct read
  (`INSUFFICIENT` < 3 months, `PROVISIONAL` < 12, else `ESTABLISHED`) — this
  is the fact the entire amendment rests on and it was read directly, not
  inferred from `AUTONOMOUS_PLAN.md` §B5's own table (which describes the
  same tiers in prose and agrees).
- The sidebar slider's two consumers (`scan_portfolio(st.session_state.target, ...)`
  at `ui.py` ~line 420 and `run_case(sku, warehouse_id, st.session_state.target)`
  at ~line 495) — confirmed by grep this session, which is what established
  that this violation is portfolio-wide rather than manual-order-only.
- The input-vs-derived table split used in G1.1 was taken from
  `database/schema.sql`'s actual table list as read across this session and
  Entry 019/021, not from memory of the plan's own descriptions.
- `fabricator.backfill_missing_sales` and `tools/parking.resolve_park`'s
  existence and signatures (both confirmed in Entry 021 and re-cited here) —
  G1.2 is specified to call existing functions, not new ones.

**NOT verified:**
- **Nothing was implemented this session.** The amendment is to
  `AUTONOMOUS_PLAN.md` only.
- **`PHASE_F_PLAN.md` has NOT been updated yet** and now contains a
  superseded design (DF1's human-entered velocity, and DF7/DF8's CLI/UI
  surfaces built around it). It must be rewritten before Phase F is
  implemented. The user was told this and offered the rewrite; they moved on
  to the UI question first. **A future agent must not implement
  `PHASE_F_PLAN.md` as currently written** — read R11 in `AUTONOMOUS_PLAN.md`
  §Phase G first, then treat DF1/DF7/DF8 as void.
- Did not re-count `AUTONOMOUS_PLAN.md`'s checkbox total after this
  amendment. Prior sessions used that count (247 at Entries 001-002) as an
  integrity check; this edit legitimately adds a substantial number of new
  checkboxes, so the old baseline is no longer meaningful and a fresh count
  was not taken. Worth re-establishing a baseline if anyone still relies on
  that check.
- **R11 was placed inside the Phase G section rather than in §1's R1-R10
  block.** This is a deliberate but debatable choice: it is a global rule and
  arguably belongs beside R1-R10, but placing it there would have meant
  editing the §1 block that every prior phase's work was carried out
  against, and R11's four named violations are all Phase-G fix targets. A
  future session may reasonably want to promote R11 into §1 proper and leave
  a pointer behind in Phase G — flagged rather than done unilaterally.
- Did not verify whether `submission/ui.py`'s existing three screens can be
  extended into G2 or whether G2 is better built fresh alongside them; Phase
  G's own plan document (not yet written) should settle that.

**Blocked / open:** O1-O5, DB1-DB5, and Phase C/D/E/F's open questions carry
forward. **New this session:**
- **`PHASE_F_PLAN.md` needs rewriting** against R11 before Phase F starts
  (see NOT verified). Not a design question — a known, named documentation
  debt.
- **Should R11's four named violations be fixed in Phase G, or earlier?**
  The sidebar-slider violation in particular is live on every screen today
  and is not gated behind any unbuilt phase — it could be fixed immediately,
  independently of Phase G's larger UI work. Placed in Phase G by this
  amendment because that is where the UI work lives, but flagged: this is
  arguably a bug fix that should not wait for a phase.
- **Should Phase G move ahead of Phase F in the build order?** Under R11,
  G1.2's data-entry screen is what makes the "enter it in the database"
  mechanism usable by a human at all, and Phase F's remaining scope shrank
  considerably once DF1 was voided. Not reordered unilaterally — the plan's
  §Dependency order still reads A → B → C → C2 → D → E → F → G → H.

**Plan changed?:** **Yes, substantially.** `AUTONOMOUS_PLAN.md` §Phase G
rewritten (G1 expanded from 7 lines to three subsections G1.1-G1.3; G2's
cover-target task amended with a superseded note; exit criteria rewritten),
and a new global rule **R11** added. One existing task's meaning was
deliberately changed rather than merely expanded: G2's "`target_cover_days`
input **removed entirely**" became "gated on maturity", carrying an explicit
superseded note explaining why, per this project's existing convention for
amending a landed decision (same treatment §A1's caveat-count and §1's R10
exception already use).

**Decisions added to DECISIONS.md:** none yet — **R11 is genuinely new
architecture and arguably warrants its own `D<n>` record** (it constrains
every phase and it voids part of an existing plan document), but it was
written into `AUTONOMOUS_PLAN.md` as a rule this session rather than into
`DECISIONS.md` as a decision record. A future session should promote it to
`D30` with the reasoning (why enter-then-refetch beats accepting a form
value, why the maturity-gated exception is the only one, and what it voids
in `PHASE_F_PLAN.md`). Flagged as owed, not done.

**State after this session:**
- Phases A-E: implemented (C/C2, D, E all carry the unresolved
  who-built-it tracker gap noted in Entries 018/019/021).
- Phase F: not started. **Its plan document is now partly invalid** —
  `PHASE_F_PLAN.md` DF1/DF7/DF8 are superseded by R11 and must be rewritten
  first.
- Phase G: not started. Now specified properly for the first time —
  previously one line for all data editing, now three subsections plus
  checkable exit criteria.
- Phase H: not started.
- New global rule R11 in force from this session onward, with four named
  live violations recorded as Phase G fix targets.

**Next recommended step:** Rewrite `PHASE_F_PLAN.md` §2 against R11 (void
DF1, rework DF7/DF8, keep DF2-DF6 which survive largely intact), then decide
the two ordering questions above (whether the sidebar-slider violation is
fixed immediately as a bug rather than waiting for Phase G, and whether
Phase G moves ahead of Phase F).

**Notes for the next agent:**
- **Do not implement `PHASE_F_PLAN.md` as currently written.** Its DF1
  ("the human supplies an assumed daily velocity") is void under R11. Read
  R11 in `AUTONOMOUS_PLAN.md` §Phase G first.
- **The distinction that matters, and that I got wrong once already:**
  `get_sales_velocity` failing (`<3` sale-days in a window) and
  `maturity == PROVISIONAL/INSUFFICIENT` are **different conditions with
  different remedies.** Thin *observations* → park, human enters real rows,
  re-fetch (Phase E, built). Thin *history length* → the derived target is
  untrustworthy, so a human may set days-of-cover only (Phase F/G, unbuilt).
  A four-month SKU has a perfectly good measured velocity and an
  untrustworthy target. Conflating them produces either a needless park or
  an illegal human-typed demand number.
- **The sidebar slider is a live, portfolio-wide R11 violation, not a Phase
  F edge case.** `st.session_state.target` feeds `scan_portfolio()` as well
  as `run_case()`, so today every risk figure on the watchlist is computed
  against a human-typed cover target. Nobody had flagged this before this
  session.
- **G1 must write through the fabricator/tool layer, never a raw SQL box.**
  A SQL box would bypass R7's duplicate guard, the FK checks, and the
  fabrication log all at once — and would let a human write a derived table,
  which is the specific thing G1.1 forbids.


### Entry 023 — 2026-09-12 — GPT-5 (Codex `/root`) — Phase F completion follow-up

**Read:** `AUTONOMOUS_PLAN.md` (Phase F, R11, and Phase G),
`AUTONOMOUS_TRACKER.md` (latest Entry 022), `PHASE_F_PLAN.md`,
`docs/testing/phase_f_manual_target_constraints.tdd.md`, the relevant Phase F
test, and the state, graph, CLI, UI, portfolio, policy, and sales modules.

**Phase / tasks touched:** The R11-valid part of Phase F: a person may set
whole-number days of cover only after real sales evidence is usable for an
immature SKU. The obsolete human-entered demand-velocity plan was not
implemented.

**Files created:**
- `submission/ui_messages.py` — dependency-free helper for the approval-card
  manual-cover provenance warning.

**Files modified:**
- `submission/graph/workflow.py` — manual-cover resume now requires exactly
  `target_cover_days` and nonblank `requested_by`; it records
  `target_provenance = human:<name>` and writes the named audit actor.
- `submission/app.py` — CLI/API resume path accepts and documents the name.
- `submission/ui.py` — manual-cover form requires the name and shows the
  mandatory approval warning for this path.
- `submission/portfolio.py` — fixed the UI-blocking `min(..., reverse=True)`
  error found by the focused UI smoke test; undefined cover remains highest
  priority, otherwise the lowest cover is selected.
- `submission/tests/test_phase_f_manual_target_constraints.py` — tests named
  provenance, missing-name rejection, and warning wording.
- `PHASE_F_PLAN.md`, `docs/testing/phase_f_manual_target_constraints.tdd.md`
  — documented that DF1/DF3/DF7/DF8's velocity override is superseded by R11
  and recorded this run's factual evidence.
- `AUTONOMOUS_TRACKER.md` (this entry only).

**RED/GREEN evidence:**
- RED: `python -m pytest submission/tests/test_phase_f_manual_target_constraints.py -q`
  produced 3 expected failures: unnamed manual resumes were accepted,
  named resumes were rejected by the old payload contract, and no warning
  helper existed.
- GREEN: the same focused command produced **8 passed**.
- UI smoke: `python -m pytest submission/tests/test_phase9_ui_deep_links.py -q`
  first exposed the unrelated portfolio `min(..., reverse=True)` crash;
  after the focused correction it produced **2 passed**.
- `python -m py_compile submission/graph/workflow.py submission/app.py
  submission/ui.py submission/ui_messages.py submission/portfolio.py
  submission/tests/test_phase_f_manual_target_constraints.py` succeeded.

**Not run:** no full suite, per the standing focused-test rule and the user's
explicit request. Deprecation warnings from existing datetime/SQLite/Pydantic
usage were present but did not fail either targeted test.

**State after this session:** A manual cover target is now auditable as a
named human decision and plainly disclosed at approval. Missing sales data is
still handled by Phase E's park → enter real `sales_daily` rows → re-fetch
path, as R11 requires. Phase G remains responsible for the data-entry UI and
the remaining portfolio-wide R11 violations.


### Entry 023 — 2026-09-12 — Claude Sonnet 5 (Kiro) — verification + planning

**Read (all fresh this session — the user explicitly instructed not to rely on
earlier sessions' notes, which turned out to be correct):**
`AUTONOMOUS_TRACKER.md` (Entries 001-022), `AUTONOMOUS_PLAN.md` §Phase G
(post-Entry-022 amendment, including R11), and direct reads of:
`submission/graph/workflow.py` (full), `submission/graph/routes.py`
(`route_after_evidence`, `route_after_target_cover`,
`route_after_demand_assessment`, `route_after_risk`),
`submission/graph/nodes.py` (`resolve_target_cover` in full),
`submission/state/state.py` (`CaseState` + `create_initial_state`),
`submission/app.py` (full), `submission/ui.py` (imports, module-level sidebar,
`screen_watchlist`, `screen_investigate`, `screen_case` dispatch,
`_render_manual_cover_form`, `VIEWS`), `submission/ui_messages.py` (full),
`submission/portfolio.py` (full function list, `scan_portfolio`,
`_stocked_pairs`, `list_pending_cases`),
`submission/tests/test_phase_f_manual_target_constraints.py` (full),
`database/schema.sql` (full `CREATE TABLE` list), `fixtures/fabricator.py`
(full function list), `tools/` (full module list + signatures in
`policy_floors.py`, `warehouses.py`, `sweep_runs.py`, `classification.py`),
`tools/workflow.py` (full), `.streamlit/config.toml` (full), and
`submission/tests/` (full directory listing — now **31 files**).

**Phase / tasks touched:** Verification of Phase F (no changes made), then
planning only for Phase G. No implementation. No checkbox ticked.

**Files created:**
- `PHASE_G_PLAN.md` (repo root) — full end-to-end Phase G plan: a prominent
  standing testing instruction at the top, §1 fresh ground truth (including
  what Phase F actually shipped versus what `PHASE_F_PLAN.md` proposed), ten
  design decisions (DG1-DG10), a files manifest, 9 tasks (G1-1..G1-5,
  G2-1..G2-3) with concrete specs, two new test files specified test-by-test
  (22 tests total), a per-task testing table, an out-of-scope list, open
  questions, and 13 checkable exit criteria.

**Files modified:** `AUTONOMOUS_TRACKER.md` (this entry only)

**Did:** The user asked for a Phase G plan and explicitly said to re-read the
code rather than trust my own prior information, because it changes and is
still changing. That instruction was correct — three things had changed since
Entry 022 and two documents are now stale.

**Phase F is implemented, and the shipped design is materially better than
`PHASE_F_PLAN.md` proposed.** `PHASE_F_PLAN.md` is now **superseded** and
should not be implemented from. What actually shipped:
- A new graph node `resolve_target_cover` between `fetch_evidence` and
  `assess_demand`, plus route `route_after_target_cover`
  (`ready`/`manual_target_required`/`blocked`), plus a new interrupt
  `_await_manual_target_cover`.
- `run_case(sku, warehouse_id)` — **two parameters only.** A test asserts this
  by `inspect.signature`, so no public entrypoint can smuggle a target,
  quantity or rate into the arithmetic.
- `_await_manual_target_cover` validates its resume payload **strictly**: the
  key set must be *exactly* `{target_cover_days, requested_by}`, so an extra
  key (e.g. a smuggled `demand_rate`) fails closed with "only accepts days of
  stock"; the value must be a real `int` (bools explicitly rejected) inside
  policy bounds; `requested_by` must be a non-empty string. This is a stronger
  enforcement of R11 than my own plan specified — my DF1 would have *accepted*
  a human demand rate.
- New `CaseState` fields `target_mode` (`UNRESOLVED` → `DERIVED` |
  `MANUAL_COVER_REQUIRED` → `MANUAL_COVER_CONFIRMED`) and `target_provenance`
  (`pending` → `derived:sku_policy` | `pending_manual_cover_days` →
  `human:<name>`); `target_cover_days` is now `Optional[int]` starting `None`.
- New `submission/ui_messages.py::manual_cover_warning` returning the exact
  required sentence, dependency-free so it is testable without Streamlit.
- `resolve_target_cover` **deliberately discards** any `target_cover_days`
  supplied at state construction — its own docstring says so.

**A concern I raised to the user last session was already handled.** I had
warned that a missing `sku_policy` row might fall back to the flat
`config.target_cover_default_days = 14`. It does not: `resolve_target_cover`
fails with `NEEDS_INFORMATION` and the message "Refresh `sku_policy` from
`sales_daily`, then re-run this case." Recorded so nobody re-raises it.

**Two R11 violations remain, and this plan assigns both to Phase G:**
1. **`scan_portfolio` still ranks the whole watchlist against a flat 14.**
   `submission/ui.py` now correctly calls `scan_portfolio(None, ...)` (the
   sidebar slider is gone — that half of the Entry-022 finding is fixed), but
   `portfolio.scan_portfolio`'s own body does
   `target = target_cover_days or config.target_cover_default_days`. So the
   graph is fully per-SKU while the screen that decides *which products a human
   looks at* is still flat-14. This is the last live instance of the plan's own
   problem §0.2. → DG6 / Task G2-1.
2. **`_await_missing_info` still accepts `target_cover_days`** in its interrupt
   payload and applies it unconditionally — a second, ungated route to the
   target that bypasses `resolve_target_cover`'s maturity gate entirely. Its
   `sku`/`warehouse_id` fields are legitimate. → DG7 / Task G2-2, flagged as a
   behaviour change to a shipped API because
   `test_phase9_needs_information_resume.py` very likely constructs that
   payload.

**Findings that shaped the plan, none previously recorded anywhere:**
- **The existing write layer is scenario-shaped, not CRUD-shaped.** The
  fabricator has 15 useful functions but **no create or delete for
  `products`/`vendors`/`vendor_offers`, no delete for anything at all**, no
  setter for `products.lifecycle` or `unit_volume_m3`, no deactivate for
  `policy_rules`, and no way to edit an existing `sales_daily` row (only
  additive backfill). G1's "full CRUD" is therefore real new work, not a UI
  wrapper over existing functions.
- **The fabrication log does not survive a restart.** `fabricator._LOG` is a
  module-level in-memory list. G1.3's "a demo is explainable afterwards"
  requirement is unmeetable with it, so DG5 adds a persisted `data_change_log`
  table via the existing `_ADDITIVE_TABLES` mechanism, with `fabricator._log`
  left working as-is for tests.
- **A manual-cover pause is indistinguishable from a missing-fields pause in
  the pending queue.** `list_pending_cases()` reports `values["status"]`, and
  `MANUAL_COVER_REQUIRED` carries status `NEEDS_INFORMATION` — the same string
  a missing-`sku` pause carries. G2 must branch on `target_mode`. → DG8.
- **There are two files named `workflow.py`.** `submission/graph/workflow.py`
  is the real LangGraph wiring; **`tools/workflow.py` is unused
  starter-package legacy** — a parallel simpler recommendation path that ranks
  on `min(total_cost)`, which D29 explicitly replaced. Nothing imports it.
  Recorded as a trap in `PHASE_G_PLAN.md` §1.4: do not wire a console to it and
  do not "fix" it.
- **The exact input-vs-derived table split**, confirmed against `schema.sql`:
  10 input tables editable in G1 (`products`, `warehouses`,
  `inventory_snapshots`, `sales_daily`, `vendors`, `vendor_offers`,
  `monthly_budgets`, `stock_receipts`, `policy_rules`, `carrying_cost_inputs`),
  6 derived tables read-only (`sku_policy`, `parked_items`, `sweep_runs`,
  `purchase_requests`, `audit_events`, `agent_memory_signals`).
- **No second app and no `pages/` directory exist.** `submission/ui.py` is one
  flat script with a module-level sidebar and a 5-entry `VIEWS` dict.

**Design decisions recorded (DG1-DG10), the load-bearing ones being:** G2 is
`submission/ui.py` evolved in place, because it already *is* the agent console
and rebuilding it would discard working, tested screens; G1 is a new
`submission/data_console.py` (DG1). G1 writes through a new
`submission/dataops/` package — never raw SQL, never the fabricator directly —
because a SQL box would bypass R7's duplicate guard, the FK checks, the
derived-table ban and the change log all at once (DG2). Validation is one
declarative per-table spec that both the screen and its tests read, so a rule
cannot be enforced on one screen and forgotten on another (DG4). G1.2's
"data is in, re-run" starts a **fresh run**, not a resume, because a thin-data
case terminates and has no live checkpoint — and because a fresh run is what
forces `fetch_evidence` to re-read the database, which is the mechanism that
makes R11 true rather than aspirational (DG9).

**DG10 is a deliberate security call the user should see.** G2 today is
read-plus-approve; **G1 will be able to write every input table** — prices,
budgets, stock levels — and both consoles run unauthenticated. This plan does
not add auth (that is Phase H), but it refuses to ship the write surface
silently: G1 must bind localhost only in its documented run command, carry a
visible "local demo tool, no access control" banner, and the limitation must be
recorded in `test_report.md`.

**Two test files specified**, 22 tests total. The two that matter most:
`test_backfilling_the_named_range_then_rerunning_produces_a_proposal_from_the_new_rows`
(the R11 keystone — asserts the proposal's `daily_velocity` matches the
newly-written `sales_daily` rows, proving the number came from a database
re-read and not a form value), and
`test_resolve_target_cover_is_the_only_route_to_a_target` (a structural
grep/AST guard that the only writes to `state["target_cover_days"]` are in
`resolve_target_cover` and `_await_manual_target_cover` — the cheapest strong
R11 regression guard available).

**The standing testing instruction was carried into the document itself**, as a
blockquote at the top rather than only a §6 section, because the user has now
repeated it in four separate sessions. `PHASE_G_PLAN.md` also notes why it
matters most here: there are **31 test files** now, and Phase G touches no
graph node and no agent, so nearly all of them are irrelevant noise for it.

**Verified:**
- Every §1 claim by direct read this session, listed above. Specifically
  re-read rather than trusted: `run_case`'s two-parameter signature,
  `_await_manual_target_cover`'s exact validation logic,
  `resolve_target_cover`'s full body including its missing-policy branch,
  `scan_portfolio`'s `or config.target_cover_default_days` line, and
  `_await_missing_info`'s payload still containing `target_cover_days`.
- The 10/6 input-vs-derived table split against `schema.sql`'s actual
  `CREATE TABLE` statements, not from memory of earlier plans.
- `fixtures/fabricator.py`'s complete current function list (grep for
  `^def \w+`), which is what established the CRUD gaps.
- `tools/workflow.py`'s full content, confirming it is unused legacy ranking on
  `min(total_cost)` rather than anything Phase G should touch.
- The test directory's current 31-file listing, including the new
  `test_phase_f_manual_target_constraints.py`.

**NOT verified:**
- **Nothing was implemented this session.** `PHASE_G_PLAN.md` is planning only.
- **Did not open `test_phase_a_data_foundation.py` to check whether its schema
  assertion is an exact set match or an `issubset`.** If exact, DG5's new
  `data_change_log` table breaks it and that test must be updated in Task
  G1-2. Flagged as the first open question in §8 rather than assumed either way
  — an earlier read (Entry 019) suggested `issubset`, but that read was of a
  different assertion and I did not re-confirm it this session.
- Did not read the bodies of `test_phase9_needs_information_resume.py`,
  `test_phase9_pending_queue.py`, `test_phase9_ui_deep_links.py`,
  `test_phase10_pending_scan_cost.py`, or
  `test_phase6_revision_and_ui_reads.py` — they are *named* in §6's per-task
  table as the files to run, on the basis of their filenames and of what each
  task touches, not on a read of what they actually assert. Whoever implements
  G2-1/G2-2 should read them before editing, since DG6/DG7 are behaviour
  changes to code those files cover.
- Did not read `submission/ui.py` in full (~1350 lines) — read the imports,
  the module-level sidebar, `screen_watchlist`, `screen_investigate`,
  `screen_case`'s dispatch, `_render_manual_cover_form`, and `VIEWS`. The
  `VIEWS` dict's exact full membership was partially truncated in the grep
  output; §1.3 states 5 screens on the basis of the visible entries plus a
  `_goto("pending")` call. Confirm before assuming.
- Did not verify that two Streamlit processes writing the same SQLite file
  behave acceptably under concurrent writes. §7 names multi-user concurrency as
  out of scope and asks only that a lock error surface readably, but the actual
  failure mode was not tested.
- Did not check whether `docs/testing/` already contains a Phase F TDD
  evidence document (the pattern for A/B/C/E exists); `PHASE_G_PLAN.md` assumes
  the convention continues and specifies one for Phase G.

**Blocked / open:** O1-O5, DB1-DB5, and Phase C/D/E's open questions carry
forward. **New, scoped to Phase G, in `PHASE_G_PLAN.md` §8:** whether
`test_phase_a_data_foundation.py`'s schema assertion tolerates a new table;
whether G1 may create a brand-new product SKU (this plan says yes;
`PHASE_F_PLAN.md` §7 had put it out of scope, so the two documents disagree and
the newer one should win but the user should confirm); where the operator name
comes from; whether the freshness control writes anything durable; and whether
`scan_portfolio` should refuse or merely label a pair with no `sku_policy` row.

**Plan changed?:** No edit to `AUTONOMOUS_PLAN.md` this session — Entry 022
already amended §Phase G and added R11, and `PHASE_G_PLAN.md` implements that
amendment rather than revising it. **`PHASE_F_PLAN.md` is now formally
superseded** by the shipped Phase F code; it was not edited (same treatment
`PHASE_E1_PLAN.md` got — these are regeneratable snapshots, not living
documents), but `PHASE_G_PLAN.md` §1.1 says so explicitly and this entry
records it.

**Decisions added to DECISIONS.md:** none. **Still owed from Entry 022: R11
should be promoted to a `D30` record** — it constrains every phase, it voided a
plan document, and Phase F's shipped implementation is now the concrete
expression of it. Two sessions have now deferred this. DG1-DG10 are
implementation-level and do not need records.

**State after this session:**
- Phases A-E: implemented (C/C2, D, E carry the unresolved who-built-it
  tracker gap from Entries 018/019/021).
- Phase F: **implemented**, verified live this session, and implemented
  *better* than its own plan document proposed. `PHASE_F_PLAN.md` superseded.
  No tracker entry records who built it — the same gap, now for the fourth
  phase running.
- Phase G: not started. Has a full, freshly-ground-truthed plan
  (`PHASE_G_PLAN.md`).
- Phase H: not started.
- R11 in force; **two violations remain**, both now assigned to Phase G tasks
  (G2-1 and G2-2).

**Next recommended step:** Answer `PHASE_G_PLAN.md` §8's first two open
questions (the schema-assertion check is a 30-second read; the create-a-product
question is a scope call only the user can make), then start Task **G1-1** —
the table spec and validator, which are pure functions with no UI and no
database and which everything else in G1 leans on.

**Notes for the next agent:**
- **Do not implement `PHASE_F_PLAN.md`.** Phase F is built, and built
  differently — `resolve_target_cover` + `_await_manual_target_cover`, with
  `run_case` reduced to two parameters. Read the code, not that document.
- **Two R11 violations are still live and they are both in Phase G's scope**:
  `scan_portfolio`'s flat-14 fallback, and `_await_missing_info` still
  accepting `target_cover_days`. Neither is hypothetical; both were read
  directly this session.
- **`tools/workflow.py` is not the graph.** Unused starter-package legacy that
  ranks suppliers on `min(total_cost)`, which D29 replaced. Two files share the
  name; a search for "workflow" hits both.
- **The fabricator cannot delete anything and cannot create a product, vendor
  or offer.** Do not plan G1's editor as a thin wrapper over it.
- **Do not run the full 31-file suite as a routine step.** `PHASE_G_PLAN.md`
  §6 gives a per-task table. Phase G touches no graph node and no agent, so
  nearly the whole suite is irrelevant to it.
- **Confirm filenames before running tests.** This session found two plan
  documents stale and a `tools/workflow.py` no earlier note mentioned, within
  one working day. The names in `PHASE_G_PLAN.md` §6 are accurate as of this
  session only.

---

### Entry 024 — 2026-09-12 — Claude Sonnet 5 (Claude Code) — implementation

**Read:** AUTONOMOUS_PLAN.md (full, both halves), PHASE_G_PLAN.md (full),
AUTONOMOUS_TRACKER.md (Entries 001-023, both 023s), database/schema.sql (full),
database/migrate.py (full), fixtures/fabricator.py (full), submission/config.py
(full), submission/portfolio.py (full), submission/ui.py (imports, sidebar,
watchlist, pending, history, VIEWS -- not the full ~1350 lines), submission/app.py
(full), submission/graph/workflow.py (_await_missing_info,
_await_manual_target_cover), submission/graph/nodes.py (validate_request,
resolve_target_cover), tools/policy_floors.py, tools/parking.py,
tools/sweep_runs.py, tools/classification.py, tools/warehouses.py (all full),
submission/statistics/*.py (function signatures only), submission/tests/
test_phase9_needs_information_resume.py, test_phase_c_autonomous_sweep.py,
test_phase_e_insufficient_data_loop.py, test_phase_a_data_foundation.py
(relevant sections), .streamlit/config.toml, .claude/launch.json,
fixtures/scenarios.json (shape only).

**Phase / tasks touched:** Phase G in full: R11 (both live violations), G1-1
through G1-5, G2-1 through G2-3, per PHASE_G_PLAN.md's own task breakdown.
Phases A-F untouched except the two files DG7 named.

**Files created:**
- submission/dataops/__init__.py, spec.py, validate.py, write.py, read.py,
  scenarios.py, stats_panel.py
- submission/data_console.py (G1 entry point)
- submission/tests/test_phase_g_data_console.py (14 tests)
- submission/tests/test_phase_g_agent_console.py (7 tests)

**Files modified:**
- database/schema.sql -- +data_change_log table (DG5)
- database/migrate.py -- +data_change_log in _ADDITIVE_TABLES
- fixtures/fabricator.py -- + create/delete for products, vendors,
  vendor_offers; update_sales_day/delete_sales_day; lifecycle/unit_volume
  setters; deactivate_policy_floor; delete for warehouses, inventory
  snapshots, monthly budgets, stock receipts, carrying_cost_inputs
- submission/portfolio.py -- scan_portfolio now looks up each pair's own
  sku_policy.derived_cover_days instead of "target_cover_days or
  config.target_cover_default_days" (DG6); WorklistRow gained
  target_basis_label; list_pending_cases now exposes target_mode (DG8)
- submission/graph/workflow.py -- _await_missing_info no longer accepts or
  applies target_cover_days (DG7)
- submission/ui.py -- watchlist shows target_basis_label per row;
  screen_pending branches on target_mode for the manual-cover label (DG8);
  new screen_monitor (sweep controls, sweep history, park queue with deep
  links into the data console); VIEWS gained "monitor"; sidebar gained an
  "Autonomous monitor" button
- submission/tests/test_phase9_needs_information_resume.py -- rewritten: the
  pause/resume mechanism is now exercised via a missing warehouse_id instead
  of an out-of-range target_cover_days (the old fixture stopped being legal
  under DG7); added test_resume_missing_info_no_longer_accepts_a_cover_target
- .claude/launch.json -- added the inventra-data-console entry (port 8502)

**Did:** Ground-truthed the codebase myself before touching anything (per this
plan's own Phase G amendment note not to trust earlier sessions' claims), and
found both things PHASE_G_PLAN.md section 1.2 predicted were narrower than
expected:

- app.py's run command and resume_missing_info/ui._render_missing_info_form
  were already clean of target_cover_days before this session (Phase F's
  rewrite apparently got there first). Only workflow.py::_await_missing_info's
  interrupt payload and apply block still carried it. DG7 was therefore a
  two-line removal, not the three-file change the plan described -- confirmed
  by direct read before editing, not assumed.
- scan_portfolio's flat-14 fallback was real and is now fixed (DG6): each row
  is judged against sku_policy.derived_cover_days when ESTABLISHED, and
  against an explicitly-labelled placeholder otherwise (target_basis_label,
  e.g. "provisional maturity -- using 14-day placeholder until established"
  or "not yet derived -- needs classification") -- never a silent 14.

Built G1 as a new submission/dataops/ package (DG2) plus
submission/data_console.py (DG1): a declarative TABLE_SPECS covering all 10
input tables (DG4), a validator that names the field and reason for every
rejection (required/type/range/enum/FK/date-sanity/R7-duplicate/warn-not-
block-on-cheap-selling-price/delete-dependent-count), and a write layer that
delegates to fixtures/fabricator.py where a primitive existed and added the
missing ones (create/delete product, vendor, vendor_offer; edit/delete a
sales_daily row; delete for the remaining input tables) rather than
duplicating SQL. Every write is logged to a new persisted data_change_log
table (DG5) -- the in-memory fabricator._LOG does not survive a restart, so
this is the durable record G1.3/G1.5 needed.

G1 has four screens: the generic table editor (create/edit/delete, derived
tables shown read-only with the DG3 banner), the missing-sales-data screen
(day-by-day view, bulk backfill, readiness counter, re-run, resolve-park),
levers + scenario catalogue + live statistics (reads sku_policy and
get_stock_position, plus a "recompute" button that re-runs classify_portfolio
and upserts), and the change-log viewer.

G2 additions to the existing submission/ui.py (evolved in place per DG1, not
rebuilt): a new "Autonomous monitor" screen with "Run monitor now", sweep
history (from tools.sweep_runs.get_sweep_history), and a park queue with a
deep link into the data console (http://127.0.0.1:8502/?sku=...&warehouse_id=...);
the pending queue now distinguishes MANUAL_COVER_REQUIRED ("Needs
days-of-stock (immature policy)") from a generic missing-fields pause, since
both share the NEEDS_INFORMATION status string (DG8).

**Caught and fixed two real bugs by actually clicking through the UI, not
just reading the code** (the session's own recurring lesson, per Entries
005-007): (1) write.py's create_row/update_row/delete_row indexed
TABLE_SPECS[table] before checking whether table was derived, so attempting
to write a derived table raised KeyError instead of the intended
WriteRejected. (2) A row read back from SQLite carries 0/1 ints for a
boolean column (SQLite has no native boolean), and the validator originally
required isinstance(value, bool) exactly -- so editing any already-existing
row with an active column failed validation on its own unchanged value.
Fixed by accepting int 0/1 for bool columns specifically. (3) A UX defect,
also only found by clicking the form: st.number_input cannot represent
"leave blank", so every optional numeric field defaulted to 0.0/0, which
then failed its own min_value > 0 check on every row that did not
explicitly set it. Fixed by adding a per-field "Set X" checkbox for optional
numeric columns, defaulting off, so "not set" and "set to zero" are
distinguishable.

**Verified:**
- test_phase_g_data_console.py: 14/14 passed (isolated tmp_path +
  config.database_path override, matching test_phase_c_autonomous_sweep.py's
  pattern). Covers: exact input/derived table split, range/type/FK/duplicate/
  date-sanity rejections each naming the field, the warn-not-block
  selling-price case, the delete-dependent-count guard, all-or-nothing on a
  rejected edit, change-log rows with before/after JSON, no-operator-name
  refusal, derived-table write refusal, migration idempotency for
  data_change_log, and the R11 keystone test
  (test_backfilling_the_named_range_then_rerunning_produces_a_proposal_from_the_new_rows):
  a thin-history case pauses at NEEDS_INFORMATION; a real 29-day range is
  backfilled through dataops.create_row; a fresh graph run (DG9 -- no resume,
  since a thin-data case has no live checkpoint) re-reads sales_daily and its
  window_30_days numerically matches what was just written ((29*6+4)/30),
  proving the number came from a database re-read and not a value carried in
  memory.
- test_phase_g_agent_console.py: 7/7 passed. Covers: two SKUs with different
  derived_cover_days are judged against different targets (not both against
  14); a SKU with no sku_policy row is labelled rather than defaulted;
  resume_missing_info's signature has no target_cover_days
  (inspect.signature); _await_missing_info's source contains no
  "target_cover_days" string literal (AST-anchored read of the function
  body); list_pending_cases's source mentions target_mode (the DG8
  structural guard); a parked_items row carries sku/warehouse/a date-range
  note; sweep_runs round-trips its detail JSON.
- test_phase9_needs_information_resume.py: 3/3 passed after the DG7-driven
  rewrite.
- python -m py_compile clean on every new/modified file.
- Live in the browser, both apps running (streamlit run submission/ui.py
  --server.port 8501 and submission/data_console.py --server.port 8502, both
  bound to 127.0.0.1): watchlist renders with per-row target_basis_label
  (all rows currently show "provisional maturity" against this seed, proven
  not-silent by the explicit label, not by a passing assumption);
  "Autonomous monitor" screen renders with empty sweep history and empty
  park queue; data console's table editor create/edit/delete cycle
  exercised live end-to-end on a real products row (TEST-001) -- created,
  confirmed in the Edit-tab row picker, deleted, and the data_change_log
  screen showed the CREATE entry with changed_by=Bala, table products,
  row_key TEST-001; derived-table read-only banner confirmed on sku_policy
  (no write controls rendered); levers screen live-verified against
  AC-003/DEL-01 (position 15, maturity PROVISIONAL, derived cover days 6.8,
  full mu/sigma/CV/ADI/service-level line); clicking "Look into this" on the
  watchlist opened a real case and correctly rendered the Phase F
  manual-cover form (not the generic missing-info form) for a PROVISIONAL
  SKU, and the pending queue correctly labelled it "Needs days-of-stock
  (immature policy)" instead of the generic label -- this is DG8 working
  against a real case, not a unit test. No console errors in either app.

**NOT verified:**
- The sweep was never actually run, live or in a test beyond
  record_sweep_run/get_sweep_history round-tripping. run_sweep fires real
  LLM calls per candidate (3 calls times 17+ at-risk SKUs on this seed) --
  judged too slow/costly for this session's UI smoke check. The button,
  spinner and result rendering are verified; the actual sweep body (already
  covered by test_phase_c_autonomous_sweep.py, which I did not re-run) is
  not.
- The full G1.2 to G2 R11 loop was not walked in one continuous browser
  session against a genuine thin-data park record. I checked AC-005 for the
  missing-sales screen, which already had complete history (30/30
  observations) -- a poor demo target, discovered only after filling the
  form. The mechanism is proven by the keystone test (a fresh graph run
  reading back exactly what was backfilled), and every individual control
  (backfill, re-run, resolve-park) was clicked and rendered without error,
  but I did not manufacture a real park record and click through the deep
  link end to end in the browser.
- Only products was clicked through by hand in the data console's CRUD
  screens. The other 9 input tables share the identical generic
  TABLE_SPECS-driven dispatch path and are covered by
  test_phase_g_data_console.py, but I did not individually click through
  create/edit/delete for warehouses, vendors, vendor_offers,
  inventory_snapshots, sales_daily, monthly_budgets, stock_receipts,
  policy_rules, or carrying_cost_inputs in the browser.
- Freshness-threshold control (G1.3): not built at all, per the plan's own
  open question about whether it should be session-only or promoted to a
  settings table -- flagged rather than half-built.
- Sweep progress/per-candidate live streaming (G2): not built. run_sweep is
  a single blocking call; there is no callback to stream from, so the UI
  shows a spinner then a final summary, not "which product is being
  evaluated right now."
- Did not re-verify ui_messages.manual_cover_warning's exact wording on the
  approval card this session (Entry 023 verified the mechanism exists; I
  did not re-read the string).
- Did not run the broader legacy regression files
  (test_phase6_revision_and_ui_reads.py, test_phase9_pending_queue.py,
  test_phase9_ui_deep_links.py, test_phase10_pending_scan_cost.py) to a
  clean pass this session. A first attempt hit PermissionError on
  database/inventra.db from a leftover process of my own (a manual
  debugging reset_business_state() call that took long enough on this
  machine's slow disk that I moved on and left it running, then it held a
  Windows-exclusive file lock into the next command). Killed the stray PID
  and confirmed via a direct AppTest run of submission/ui.py against
  whatever the shared database currently holds that the app itself raises
  no exception. Per this plan's own standing testing instruction (do not
  run the full suite; run the focused files a task names) and the user's
  explicit instruction mid-session to stop waiting on slow test runs, I did
  not re-attempt the full 4-file legacy regression pass. This is an honest
  gap: those four files' current pass/fail state against the DG6/DG7/DG8
  changes is unconfirmed beyond the reasoning that the edits are narrow,
  additive, and every new focused test targeting the same code paths
  passes.

**Blocked / open:** O1-O5 unchanged. New, scoped to Phase G, matching
PHASE_G_PLAN.md section 8: test_phase_a_data_foundation.py's schema
assertion is confirmed issubset (checked before writing the migration, not
after -- data_change_log does not break it). The "can G1 create a
brand-new product" question is resolved in the affirmative by this
session's implementation (create_product exists and is wired into the
table editor) -- if that conflicts with PHASE_F_PLAN.md section 7's stated
out-of-scope, this session's code is the newer decision and should win, but
it was not separately confirmed with the user.

**Plan changed?:** Yes -- ticked the R11, G1.1, G1.2, G1.3, G2 and
Phase-G-exit-criteria checkboxes in AUTONOMOUS_PLAN.md that this session
actually verified, each with an inline note where the built version is
narrower than the original spec (missing-sales screen has no separate
per-day entry grid, only bulk fill; levers screen does not duplicate every
fabricator setter as its own quick-control; scenario picker jumps to a pair
rather than re-fabricating it; sweep progress is not live-streamed). Left
unchecked: the freshness-threshold control (not built) and sweep
per-candidate live progress (not built) -- both named explicitly rather
than silently marked done.

**Decisions added to DECISIONS.md:** none this session -- DG1-DG10 were
already recorded in PHASE_G_PLAN.md by the prior planning session and this
session implemented against them without revising any.

**State after this session:**
- Phases A-F: unchanged (implemented, per Entry 023)
- Phase G: implemented and live-verified in the browser, with the gaps
  named above (freshness control, live sweep progress, per-day sales entry,
  per-tool levers, one-click scenario re-fabrication) explicitly not built
  rather than silently skipped
- Phase H: not started
- R11: both violations named in the plan (scan_portfolio flat-14,
  _await_missing_info's second target route) are fixed and covered by
  regression tests

**Next recommended step:** If a full live demo is wanted, manufacture a
genuine thin-data SKU/warehouse pair (fewer than 3 sales observations in
both windows) so the G1.2 to G2 park-backfill-re-run loop can be walked
end-to-end in the browser against a real park record, rather than relying
on the keystone test alone. Otherwise, Phase H (freshness control decision,
sweep progress streaming, and the known-limits documentation the brief's
test_report.md needs) is the next open work.

**Notes for the next agent:**
- This machine is unusually slow for anything touching database/inventra.db
  at scale. A bare init_db() (schema-only, no seed data) took ~41 seconds in
  isolation; reset_business_state() (35 SKUs times 24 months) did not finish
  in over 6 minutes before I killed it. This is almost certainly the Windows
  Defender real-time-scanning interaction with SQLite writes noted in prior
  sessions' memory, not a regression from this session's code -- a bare
  CREATE TABLE sequence has no reason to be CPU-bound. Budget for this
  before running any full-seed test file; prefer the isolated-tmp_path
  pattern (like this session's two new test files) wherever the test does
  not specifically need the full 35-SKU seed.
- If a python process running reset_business_state() is left running and
  you move on, it will hold an exclusive Windows lock on
  database/inventra.db and every subsequent test/CLI/Streamlit call against
  the shared database will fail with PermissionError: [WinError 32], not a
  logic error. Check running python processes' command lines before
  assuming a fresh failure is a code bug.
- Two files are genuinely named workflow.py (section 1.4 of
  PHASE_G_PLAN.md, restated here because it is exactly the kind of trap
  that costs a full read to rediscover): submission/graph/workflow.py is
  the real graph; tools/workflow.py is unused legacy. Neither Phase G nor
  this entry touched the second one.
- app.py's run CLI command and resume_missing_info/
  ui._render_missing_info_form were already clean of target_cover_days
  before this session -- PHASE_G_PLAN.md's DG7 task list describes a
  three-file change; only workflow.py::_await_missing_info still needed it.
  Re-verify claims like this by reading the actual file, not by trusting a
  plan document's file list, even a carefully-written one from the same
  day.
- st.number_input cannot represent "unset." Any future optional numeric
  field in submission/data_console.py needs the same "Set X" checkbox
  pattern _field_input now uses, or it will silently coerce to 0 and fail
  any min_value > 0 check on every row that did not explicitly touch that
  field.
- SQLite has no boolean type. A row read back for an active column carries
  a Python int (0/1), not a bool -- submission/dataops/validate.py::_coerce's
  bool branch accepts int 0/1 specifically for this reason; do not tighten
  it back to isinstance(value, bool) without re-breaking every edit to an
  existing row.
