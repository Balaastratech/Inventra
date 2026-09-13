# DECISIONS.md

Why the autonomous-monitor design in `AUTONOMOUS_PLAN.md` looks the way it does.
One record per decision: what was decided, what else was considered, and why the
alternative lost.

Where a decision reverses or revises something already documented in the
codebase, that is called out explicitly — silent reversals are how a design
loses its integrity.

---

## D1 — No simulation clock. Fabricate the data's dates instead.

**Decision.** The system always reads the real `datetime.utcnow()`. Demo control
comes from writing history with dates backdated relative to real now.

**Considered.** A virtual clock: store `simulation_date` in a control table,
route every "now" read through one function, add an "advance N days" operation.

**Why the clock lost.** It required routing roughly 45 wall-clock call sites
across `tools/`, `submission/` and `database/` through a single accessor. Miss
one and you get a time-travel bug that is miserable to trace. More importantly,
it was solving a problem that does not exist: **every statistic in this system is
computed over a window that ends at now.** Write history backdated from real now
and everything reads correctly with no abstraction at all. `database/seed.py`
already does exactly this with `now - timedelta(days=...)`; the fabricator is
just a repeatable, parameterised version of what is already there.

**Bonus that made it clearly the better call.** The one component that genuinely
needs to evaluate as of a past date — the classifier — takes that date as a
**function argument** (`classify(sku, warehouse, as_of=date)`) rather than
reading ambient state. That is a pure function: trivially testable, and it lets
24 months of classification history be backfilled in one pass at seed time. So
monthly hysteresis is visible the moment the database is seeded, with genuine
transitions computed over genuine windows, instead of requiring a demo to wait
or a history to be staged.

**Attribution.** This reversal came from the user, correcting an over-engineered
first proposal.

---

## D2 — `target_cover_days` becomes a derived output, not an input.

**Decision.** Remove the human input entirely. The number is computed per SKU
from that SKU's own demand statistics, its supplier's lead time, and a service
level derived from its economics.

**Considered.** Keeping it as an optional manual override in the UI.

**Why removal won.** Leaving the field visible invites its use, and the entire
point is that nobody should type a per-product number. A field that exists but
should not be used is worse than no field. The manual-order path (Phase F) covers
the legitimate case where a human genuinely must supply the number, and records
that they did.

**What it replaces.** `config.target_cover_default_days = 14`, applied flatly to
every product in the catalogue regardless of whether it is a fast-moving AC unit
or a slow-moving TV.

---

## D3 — The reorder decision is a reorder point, not a cover-days threshold.

**Decision.** Trigger on `position < reorder_point`, where
`reorder_point = μ × L + safety_stock` and
`safety_stock = z(service_level) × sqrt(L × σ² + μ² × σL²)`.

**Considered.** Keeping the existing "is cover below target days" test with a
smarter target.

**Why the reorder point won.** It asks the right question. "Do I have fewer than
14 days of cover" is a threshold someone typed. "Am I below the point where,
given how this product actually sells and how long this supplier actually takes,
I would run out before a replacement lands" is a question the data can answer.
The second one also naturally absorbs demand variability and lead-time
variability, which a days-of-cover threshold cannot express at all.

**Consequence.** `target_cover_days` survives internally as a *derived* value so
that `economics.size_order_quantity` keeps its existing contract. The reorder
point is expressed in days at the boundary rather than replacing the sizing
function.

---

## D4 — ABC uses 12 rolling months; the forecast uses the recent level. Two windows, two jobs.

**Decision.** Economic classification reads a rolling 12 completed months.
The reorder point reads the current demand level from a short recent window.

**Why both.** They answer different questions. ABC asks "how economically
important is this product" — a stable, annual view is correct, and monthly
recalculation over a rolling year is what commercial systems do. The reorder
point asks "what will sell tomorrow" — a 12-month mean actively causes stockouts
when demand has shifted. If the 12-month mean is 12/day and the last 14 days are
25/day, planning against 12 guarantees running out.

**The valuable side effect.** The **gap between the two windows is the
regime-shift signal.** No separate detector needed as a primary mechanism; the
divergence itself is the evidence. That is what catches a demand ramp.

---

## D5 — Demand quadrant switches the forecasting method, not just the label.

**Decision.** Classify every SKU into smooth / erratic / intermittent / lumpy by
ADI and CV² (Syntetos-Boylan-Croston cutoffs 1.32 and 0.49), and **use a
different method per quadrant.** Normal-based safety stock for smooth and
erratic; Croston-style or bootstrap for intermittent and lumpy.

**Why this matters more than classification.** For an item that sells 40 units
once a month and nothing on other days, "mean daily demand 1.3" describes no day
that ever happened. Normal-distribution safety stock built on that number is not
approximately right, it is structurally wrong.

**This exposes a live defect in the existing code.**
`tools/inventory.calculate_stock_risk` computes
`cover_days = available / daily_velocity` and derives `projected_stockout_date`
from it. For a lumpy item both are fiction — and that fictional date currently
drives vendor eligibility (`meets_deadline`) and a hard policy checklist row that
can block a case. Fixing this is not optional polish; it is a correctness issue
in the current system that the autonomous layer would amplify across the whole
portfolio.

---

## D6 — Service level from the newsvendor critical ratio, bounded by ABC class.

**Decision.** Compute
`service_level = understock_cost / (understock_cost + overstock_cost)`, then
floor and cap the result per ABC class as a policy guardrail.

**Considered.** Fixed service levels per class (A = 98%, B = 95%, C = 90%).

**Why the ratio won.** Fixed per-class service levels are simple but demonstrably
away from cost-optimal — a point the user's own research surfaced. Deriving the
level from a product's own margin and holding cost means a high-margin,
cheap-to-hold item earns high availability on the arithmetic rather than on its
letter.

**Why the class bounds stay.** An unbounded ratio can produce absurd answers on
thin or noisy data. Class-based floors and caps keep the classification
meaningful as a guardrail without letting it dictate the number.

**Assumption traded, not eliminated.** This requires `selling_price` (added to
the schema) and an annual holding-cost rate (a new config assumption,
conventionally 20-25%). Net effect: it removes the assumed-25%-margin caveat that
`economics.evaluate_options` currently emits in every proposal, and replaces it
with a standard, auditable one. The system apologising for a guess in every
output it produces is a credibility cost worth paying to remove.

---

## D7 — Monthly recalculation with asymmetric hysteresis.

**Decision.** Recalculate monthly. Require **2** consecutive confirmations to
promote a class (raising service) and **3** to downgrade it (lowering service).
Allow a fast path for statistically significant, sustained regime shifts.

**Considered.** Recalculating quarterly, or acting on every monthly result
immediately.

**Why hysteresis.** A single large order can push a SKU across an ABC boundary.
Acting on it immediately produces B→A→B→A oscillation and a service level that
flaps, which is worse than a slightly wrong stable answer.

**Why asymmetric.** Carrying slightly too much stock for one more month is
cheaper than prematurely removing protection from a genuinely important product
and causing a stockout. The costs are not symmetric, so the confirmation
requirements should not be either.

**Why the fast path.** A C-class item whose demand jumps 500% with a 60-day lead
time cannot wait three months for confirmation. The fast path exists precisely so
that stability does not become paralysis, and it must record its reason and
confidence so the exception is auditable.

---

## D8 — New and thin-data SKUs get provisional classification with confidence, never a default C.

**Decision.** Maturity tiers: under 3 months is `INSUFFICIENT`, 3-12 months is
provisional with annualised consumption and a confidence score, 12+ months is
established. Confidence is driven by **effective observations**, not elapsed
months.

**Why not months alone.** A SKU with 3 months and thousands of demand events
carries far more information than one with 12 months and 3 events. Gating on
calendar time alone gets both cases wrong.

**Why never a default C.** A new product ranks low on historical consumption for
the trivial reason that it has no history. Dumping it in C and giving it the
lowest service level is a self-fulfilling failure — it stocks out, sells less,
and stays in C.

---

## D9 — The monitor is deterministic. It is not an agent.

**Decision.** The sweep, the statistics, the reorder point, the ranking, the
budget allocation and the trigger condition are all plain Python with no LLM.

**Considered.** Making the monitor a fourth agent that reasons about which
products need attention.

**Why deterministic won.** Three reasons, in order of weight:

1. The brief requires that authoritative arithmetic comes from tools. A model
   inventing a reorder point violates that directly.
2. The brief allows 2-4 agents and states plainly that more agents earn no marks.
   Staying at 3 is both compliant and cheaper to defend.
3. The existing codebase already enforces this discipline hard —
   `_override_policy_checklist` overrides the model on every mechanically
   checkable row, and `_validate_recommendation` refuses a premium the
   arithmetic does not support. A monitor that reasoned its way to a quantity
   would be the one component nobody could audit.

**Corollary.** This answers the "do we need agent → monitor → agent" question:
no. There is nothing to interpret before the arithmetic is done. The monitor runs
once, deterministically, before any case opens.

---

## D10 — Budget is allocated across ranked candidates before drafting.

**Decision.** The sweep ranks candidates by urgency × economic value and
allocates the month's remaining budget down that list **before** any proposal is
drafted. Candidates beyond the line are deferred with a named reason.

**Why.** This fixes a real defect that only appears once the system goes
portfolio-wide. Today each case reads `budget.remaining` independently, and money
is not reserved until execution. Sweep eight candidates and all eight
individually "fit", a human approves all eight, and the last three fail
revalidation *after* approval. It fails safe, but it wastes human attention and
looks broken. Allocating up front means the critical items get the money and the
marginal ones are honestly deferred instead of being approved and then killed.

---

## D11 — Per-item approval. No batching, no consolidation.

**Decision.** One purchase request per SKU, one approval per SKU, one email per
SKU, each with its own identifiers.

**Considered.** One batched approval covering the whole sweep; and consolidating
multiple SKUs from the same vendor into one purchase order.

**Why per-item won.** The controlling requirement is the ability to reject and
re-run a single item without disturbing the others. Consolidation and per-item
approval are in direct conflict — you cannot independently reject one line of a
consolidated PO without re-cutting the whole thing.

**What is being given up, acknowledged.** Real procurement does consolidate, for
freight efficiency and vendor relationship reasons. That is recorded in Phase H
as a deliberate deferral rather than pretended away.

---

## D12 — Two approval gates: the order, then the vendor email.

**Decision.** Gate 1 approves the order and creates the purchase request
(`PENDING`, budget reserved). Gate 2 presents the drafted vendor email and
approves the send.

**Why two.** They are different decisions with different consequences. Gate 1
commits budget internally and is reversible by cancellation. Gate 2 sends
something to an external party, which is not reversible. Collapsing them means
one click does both, and the more consequential half gets less scrutiny.

**Schema already anticipated this.** `purchase_requests.vendor_sent_at` and
`vendor_send_status` exist today and are unused. Gate 2 gives them a purpose.

**The honest limitation.** A reminder for an untouched gate 2 requires something
to run. With no background scheduler, reminders are produced by the sweep and by
opening the pending screen. That is documented as a deployment concern in Phase
H, not disguised as a design feature.

---

## D13 — Policy floors override statistics, and both numbers are always shown.

**Decision.** A `policy_rules` table holds per-SKU minimum stock floors. The
monitor triggers on `position < max(reorder_point, policy_floor)` — either breach
fires. The proposal always carries both the **statistical target** and the
**active target**, and shows the divergence.

**Why this is not an invention.** It is a named industry practice — a *safety
stock override* or *min/max policy override* — implemented by every serious
inventory platform. StockIQ's design is the direct precedent: it applies the
override to planning while still displaying its own calculated figures under a
"Statistical Inventory" heading alongside the "Active" values in force. Netstock
detects conflicts between minimum and maximum safety-stock policies from
different sources. Microsoft Dynamics 365 supports a minimum coverage quantity
driving min/max logic. The vocabulary of *active* versus *statistical* comes from
these systems and is worth adopting rather than reinventing.

**Sources.**
[StockIQ safety stock overrides](https://support.stockiqtech.com/hc/en-us/articles/360033789774-Safety-Stock-Overrides) ·
[StockIQ statistical vs active values](https://support.stockiqtech.com/hc/en-us/articles/360034439874-Safety-Stock-Tab) ·
[Netstock policy override conflicts](https://help.netstock.com/en/articles/11822358-how-to-troubleshoot-safety-stock-policy-overrides) ·
[Microsoft Dynamics 365 minimum coverage](https://learn.microsoft.com/en-us/dynamics365/supply-chain/master-planning/safety-stock-journal)

*Content from these sources was rephrased for compliance with licensing
restrictions.*

---

## D14 — Floors live in a table, not in `policy.md`.

**Decision.** The numbers go in `policy_rules`. `policy.md` documents only that
floors exist, that they override statistics, and how conflicts are resolved.

**Why.** `policy.md` is read by the LLM as guidance. A floor is an authoritative
number that must be enforced deterministically. Putting it in prose makes the
model the enforcer, which breaks the discipline the entire codebase is built on —
and would be the one place where a hallucination directly changes what gets
ordered.

**Secondary benefit.** A table is editable by the simulator UI, which is what
makes the floor demo possible.

---

## D15 — Floors carry a stated business reason.

**Decision.** Every row in `policy_rules` records a reason and a source — an SLA
commitment to a named account, a warranty service-parts obligation, and so on.

**Why.** A floor with a reason is defensible under review. A bare number looks
arbitrary, and an arbitrary number that overrides statistics is exactly the kind
of thing a reviewer will attack.

**On realism for this dataset.** The catalogue is electronics in a warehouse, not
hospital supply, so "must never run out" is not clinically motivated here. But
policy floors are still entirely realistic in this setting — the justifications
are contractual rather than clinical: minimum purchase and stock commitment
clauses in distribution agreements, inventory SLAs where a supplier commits to a
minimum fill rate over a horizon, warranty service parts, and showroom or demo
units.

**Sources.**
[Minimum commitment clauses](https://fynk.com/en/clauses/minimum-commitment/) ·
[Inventory SLAs as coordination mechanisms](https://pubsonline.informs.org/doi/abs/10.1287/msom.1070.0188)

*Rephrased for licensing compliance.*

---

## D16 — When a floor exceeds the statistics, honour the floor and quantify the waste.

**Decision (provisional — open item O1).** The agent recommends the **floor**,
flags the excess, and quantifies it: "the statistics support 5; the floor forces
5 extra units, ₹X of working capital for no measured service gain." Both options
are still offered to the approver.

**Considered.** Recommending the statistical figure and treating the floor as
advisory.

**Why the floor wins by default.** A floor is usually a *commitment*, not a
preference. If it exists because of an SLA with a key account, an agent that
quietly orders less has breached a contract on statistical grounds it is not
authorised to weigh. The correct behaviour is to obey the policy, surface the
waste in plain numbers, and let a human relax the floor if they choose.

**Flagged as a config flag, not a hardcoded belief**, because it is a genuine
business-judgment call and different organisations would answer differently.

---

## D17 — Humans choose among computed options. They never type a quantity.

**Decision.** The approval card offers a small set of **computed** targets — the
policy floor, the statistical target, the statistical minimum — each re-priced by
the same deterministic sizing code. The human selects a basis.

**Why this matters.** `nodes.apply_human_edit` currently forbids quantity editing
entirely, and documents the reason at length: order quantity is derived per
supplier from velocity, lead time, fill rate and MOQ, so a hand-typed number
would reintroduce exactly the manual figure this system exists to eliminate, and
would silently invalidate the economics block that both the policy reviewer and
the approval notes read.

**This is a deliberate revision of that documented decision, not an oversight.**
Offering a choice among three computed figures respects the original principle —
no hand-computed numbers ever enter the system — while allowing the judgment the
floor reconciliation requires. Recording it here so the revision is visible
rather than looking like the rule was forgotten.

---

## D18 — Going below a policy floor produces an EXCEPTION, never a silent PASS.

**Decision.** If a human chooses a target below the policy floor, `review_policy`
returns `EXCEPTION` — a deliberate, named, audited policy breach.

**Why.** The alternative is that a policy floor can be quietly ignored, which
makes it not a policy. `EXCEPTION` records that a human knowingly overrode a
stated commitment.

**Reuses an existing pattern.** This is exactly how the over-budget tolerance
already works: within tolerance becomes `EXCEPTION` rather than auto-approving or
hard-blocking. Same mechanism, no new machinery, and consistency across two
similar situations is worth more than a bespoke path.

---

## D19 — The floor reconciliation reuses the existing edit cycle. No new graph shape.

**Decision.** Extend `ApprovalDecision` with a chosen target basis, and let
`apply_human_edit` handle it alongside `edited_offer_id`. The case re-enters the
**existing** loop: `apply_human_edit → draft_proposal → review_policy →
request_approval → await_approval`.

**Considered.** A new interactive graph capable of moving back and forth between
the monitor and the agents.

**Why the existing cycle won.** It is already the back-and-forth being asked for.
That loop exists today so a human switching vendors gets a fully recomputed
proposal, a fresh policy review, a new hash and a re-approval — bounded by
`config.max_human_edit_cycles = 3`. LangGraph graphs are cyclic by design, and
LangChain's own documentation names the four canonical human actions as approve,
edit, reject and respond. A quantity-basis choice is an **edit**, the same
category as the vendor switch. Building a second mechanism for the same shape of
interaction would add surface area for no capability.

**Source.**
[LangChain human-in-the-loop: approve, edit, reject, respond](https://docs.langchain.com/oss/python/langchain/human-in-the-loop)

*Rephrased for licensing compliance.*

---

## D20 — Parking, not blocking, for undecidable single SKUs.

**Decision.** A SKU the sweep cannot decide on is written to `parked_items` with
everything a human needs to act, and **the sweep continues**.

**Why.** One uncertain product must never stop a portfolio run. The failure mode
of the alternative is that the single worst-data SKU in the catalogue prevents
the other 34 from ever being evaluated.

**Why the park record is heavy.** A park that says "needs more data" is a dead
letter. The record carries what *was* computed (so the human sees how far the
analysis got), what specifically was missing, the one precise question, and a
concrete unblocking action naming the exact date range to backfill. That is what
makes it a work item rather than a complaint.

---

## D21 — Retire the ambiguous-demand-window interrupt.

**Decision.** Remove `_await_window_choice`. Genuinely undecidable demand is
parked instead.

**Why it is safe to remove.** Checked the brief directly. Its scenario 2 is
"Warehouse or SKU is absent → NEEDS_INFORMATION with one precise question" —
that is *missing request fields*, and `_await_missing_info` already satisfies it.
The 7d-vs-30d ambiguity pause was an addition on top of the brief, not a
requirement of it.

**Why it becomes obsolete.** Once forecasting reads full history and switches
method by demand quadrant, there is no binary window choice to be ambiguous
about. The pause was solving a problem created by only having two windows.

**What replaces it.** Parking, which handles the genuine case — insufficient or
irreconcilable data — without stopping the run.

---

## D22 — Insufficient sales history returns NEEDS_INFORMATION, not BLOCKED.

**Decision.** Change `nodes.fetch_evidence` so `INSUFFICIENT_DATA` produces
`NEEDS_INFORMATION` with a specific, actionable question.

**Why this is a fix, not a feature.** The current code calls `_fail` without
overriding the default status, so the case ends as `BLOCKED`. But
`05_inventra_case_flow.md` scenario 11 and the Investigator agent interface both
specify `NEEDS_INFORMATION` for thin sales history — the interface states
outright that `NEEDS_INFORMATION` covers "bad input or sales history too thin to
trust." So the current behaviour is off-spec.

**Why it matters beyond compliance.** It is exactly the path required for the
requested workflow: the system says the data is insufficient → a human tells the
data team → the data is entered → the case re-runs. `BLOCKED` is a dead end;
`NEEDS_INFORMATION` is a request. One fix serves both the spec and the feature.

---

## D23 — The manual order path stays, and may override insufficient data.

**Decision.** A human can order any product by supplying only how many days of
cover they want. It runs the same graph. A manual order may proceed past
`INSUFFICIENT_DATA`, subject to three conditions: the override is audited as a
named human's decision, the approval card states plainly that there is not enough
sales history and who set the target, and the agent still performs all vendor
work.

**Why the path exists.** Excluding thin-data products entirely would be worse
than the problem it solves. A planner who needs to order a new product should
still get vendor selection, economics, policy review and a drafted proposal.

**Why the override is acceptable here specifically.** The reason
`INSUFFICIENT_DATA` blocks an autonomous run is that the system cannot claim to
know the demand. In a manual order the human has supplied that assumption and
taken responsibility for it. The block was protecting against the system
guessing, not against a human deciding.

**Why the warning must be blunt.** The alternative is laundering a human's guess
as an agent's finding. The approval card names the person and states the data
gap, so an approver knows exactly what they are approving.

---

## D24 — Freshness threshold stays configurable, with the divergence documented.

**Decision.** Keep `data_freshness_hours` as a config value. Document that the
brief's business-rules table says 2 hours while `policy.md` says 2 days, and that
the code follows `policy.md`.

**Why not just pick one.** Both sources are authoritative in their own frame, and
the deviation is already documented in the config module. What changes with an
autonomous sweep is the *consequence*: at a 2-hour threshold, essentially every
snapshot is stale unless the fabricator writes a fresh one, which would make the
whole sweep return `DATA_STALE` and demonstrate nothing.

**How the risk is handled.** A hard rule in the plan (R6): every fabricated
scenario writes a fresh snapshot at `utcnow()`. The simulator exposes the
threshold so a demo can tighten it to 2 hours to satisfy the brief, or relax it
while working.

---

## D25 — Schema changes are in scope, and two apologies get deleted.

**Decision.** Add `selling_price` and `lifecycle` to `products`, plus new tables
`stock_receipts`, `sku_policy`, `policy_rules` and `parked_items`.

**Why `selling_price`.** `economics.evaluate_options` currently emits a caveat in
every single proposal saying that contribution per unit is an assumption because
the schema has no selling price, and that changing the assumed margin changes the
verdicts. A system that apologises for a guess in every output it produces is
paying a credibility cost on every case.

**Why `stock_receipts`.** The same function emits a second caveat: delivery risk
is modelled coarsely as `1 - on_time_rate` because the schema holds no history of
how late late deliveries are. Real receipt history gives measured lead-time
variance (σL), which is a direct input to safety stock. Without it, safety stock
is missing one of its two variance terms.

**Net effect.** Both caveats are deleted, and the two numbers they were
apologising for become measured rather than assumed.

---

## D26 — Green tests are not a gate right now.

**Decision.** Verify real working paths manually through Phases A-F. Defer formal
test restoration to Phase H.

**Why.** Several existing tests assert behaviour this plan changes deliberately —
a suite that fails because the design moved is not evidence of a defect. Chasing
green during a design change means either fighting the tests or weakening the
change.

**Correction, 2026-09-11 (tracker Entry 006).** An earlier version of this record
claimed `test_phase10_cancel_purchase_request.py` and
`test_phase11_budget_and_reorder_guard.py` contradict each other on budget
reservation, and that "both cannot be true." **That was wrong**, asserted from a
grep without reading the test.

The phase-10 helper `_insert_request()` writes a `purchase_requests` row directly
via SQL and its INSERT column list omits `committed_budget_month`. Nothing was
ever reserved for that row, so cancelling correctly releases nothing and
`budget_released` is `False` — exactly the legacy-row path
`cancel_purchase_request` documents. Phase-11 covers the normal
`create_purchase_request` path, which does reserve and release. **Both tests are
correct and cover different scenarios.** Only the phase-10 docstring
("create_purchase_request never increments committed_amount") and the test name
are stale.

The decision above — that green tests are not a gate during a design change —
stands unchanged. Only this supporting example was wrong.

---

## D27 — Two Streamlit apps, and the honest note about marks.

**Decision.** Two separate Streamlit apps on separate ports against one database:
a simulator/data console and an agent console. UI polish deferred to Phase H.

**Why two rather than one.** They serve opposed purposes. The simulator exists to
change the world; the agent console exists to observe what the agent did about
it. Mixing them in one app makes it unclear, during a demo, whether a change came
from the operator or from the system.

**The uncomfortable note, recorded deliberately.** The brief's rubric allocates
**zero marks** for a dashboard, and explicitly lists "a large dashboard" under
what does not earn marks. The two apps exist for demonstration and operator
understanding, which is a legitimate reason — but they must not consume time
budgeted for the engine. This is written down so the trade-off stays visible when
the UI starts looking tempting to polish.

---

## D28 — No runtime web search.

**Decision.** The system has no web-search tool.

**Why.** The brief lists it explicitly under tools you are not given. Web
research informed the design decisions recorded in this document; it is not a
capability of the running system, and adding one would require justifying a new
tool against a stated prohibition.

---

## D29 — Suppliers are compared on cost per day of cover, not on total cost.

**Decision.** `economics.evaluate_options` ranks eligible options on
`all_in_cost_per_day_of_cover` and the validation gate enforces that ranking.
`total_cost` keeps its role as the cash figure checked against the budget, and
loses its role as the supplier comparison. Order sizing is **unchanged**:
`velocity × (target_cover_days + lead_time_days) − available`, grossed up by
fill rate.

**Why.** The two halves of the old logic contradicted each other. Sizing is
per-supplier because the requirement is N days of cover *once the goods land*,
so a slower supplier has to fund more days of demand and legitimately needs more
units. The ranking was then `min(total_cost)` — comparing those different-sized
orders by their invoice totals. On AC-004/DEL-01:

| | units | invoice | per unit delivered | days funded | all-in per day |
|---|---|---|---|---|---|
| FastShip Inc. | 37 | $18,500 | $510.20 | 12.1 | $1,535.68 |
| Standard Supplier | 42 | $18,900 | $478.72 | 13.2 | $1,441.35 |

The old rule called FastShip "cheaper overall" and the gate then *forced* that
pick. But Standard's five extra units are not $400 of waste — they are more days
of demand served plus fill-rate shrinkage, and they get sold. The system was
systematically overpaying for stock while telling the approver it was saving
money.

**Rejected alternative: size every supplier to one shared horizon.** It makes
the invoice comparison valid, but only by giving the faster supplier 11 days of
post-arrival cover against a 10-day requirement. That changes what the business
asked for so the arithmetic comes out tidier. The requirement is not negotiable
to suit the metric; the metric was the thing that was wrong.

**Three guards, because normalising the metric removes the old brake.**

1. Minimum-order overshoot earns no coverage credit — otherwise a 200-unit MOQ
   posts a flattering per-day figure by handing over two months of stock. Test:
   `test_a_supplier_minimum_earns_no_coverage_credit`.
2. Inventory carrying cost now exists (`config.assumed_annual_carrying_rate`).
   It previously did not, anywhere in the codebase. Total spend was the only
   thing discouraging a large order; removing it as the ranking metric would
   have left nothing.
3. Delivery risk is priced per option, from its own on-time rate against its own
   slack. This replaces the pairwise "premium vs the cheapest" test, which
   valued a premium option's buffer using *that option's* lateness probability —
   when the risk being insured against belongs to the option you would otherwise
   pick — and which only worked with exactly two options.

**Consequence for the agent.** With risk inside the score there is no separate
"is the premium justified" judgment left, so a pure argmin would reduce the
Strategist to a rubber stamp. `within_value_tolerance`
(`config.vendor_value_tolerance_rate`, default 2%, and the option must also
arrive earlier) keeps a bounded real choice. The gate bounds judgment; it does
not delete it.

**Two new declared assumptions, same pattern as the margin rate.**
`assumed_annual_carrying_rate` and `assumed_late_days_when_late` — the latter
replacing the old model that treated any late delivery as consuming the entire
buffer, which inflated buffer value and was the arithmetic behind the $1,450
recommendation. Deliberately a flat assumption rather than a fitted
distribution: building percentiles out of a single on-time percentage would be a
fabricated model wearing a statistician's coat. It retires when D25's
`stock_receipts` lands. A third, `vendor_billed_on_units_shipped`, makes explicit
something the code had been assuming silently — at a 0.94 fill rate, invoicing
on units ordered vs units shipped differs by hundreds of dollars on one order.

---

## Reversals and revisions, collected

For anyone reading the codebase later and wondering why documented behaviour
changed.

| Existing documented behaviour | Change | Record |
|---|---|---|
| Vendors compared on `total_cost`; verdicts `cheapest_option` / `premium_justified` / `premium_not_justified` / `costs_more_but_arrives_no_earlier` / `free_upgrade` | Compared on `all_in_cost_per_day_of_cover`; verdicts collapse to `best_value_option` / `within_value_tolerance` / `worse_value_option`, old names kept as aliases | D29 |
| A premium is justified when `cost_per_extra_buffer_day <= expected_value_of_one_extra_buffer_day` | Retired — delivery risk is priced inside each option's own score, so there is no separate premium test | D29 |
| Quantity is never human-editable (`apply_human_edit` docstring) | Humans may now choose among **computed** target bases, still never typing a number | D17 |
| `INSUFFICIENT_DATA` ends a case as `BLOCKED` | Becomes `NEEDS_INFORMATION` per the case-flow spec | D22 |
| Ambiguous 7d/30d demand pauses for a human (`_await_window_choice`) | Retired; genuinely undecidable SKUs are parked | D21 |
| `PolicyReview.checklist` contains exactly 8 items | Becomes 9, adding the policy-floor row | Plan §C2.4 |
| `target_cover_days` is a validated human input | Becomes a derived output; input removed from the UI | D2 |
| Contribution margin assumed at 25% with a caveat in every proposal | Measured from `selling_price`; caveat deleted | D25 |
| Delivery risk approximated as `1 - on_time_rate` with a caveat | Measured lead-time variance from `stock_receipts`; caveat deleted | D25 |
| First proposal in this design discussion: a virtual simulation clock | Rejected in favour of fabricating data dates | D1 |
