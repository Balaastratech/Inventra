# AUTONOMOUS_PLAN.md

> ## ⚠ MANDATORY FOR EVERY AGENT READING THIS FILE
>
> If you are an AI agent and you have opened this file, you have two obligations.
> They are not optional and they are not conditional on the size of your task.
>
> **1. BEFORE you do anything else — read [`AUTONOMOUS_TRACKER.md`](AUTONOMOUS_TRACKER.md).**
> It is the append-only work log for this plan. It tells you what has already
> been built, what was verified, what was written but never checked, what is
> blocked on a human answer, and which traps previous agents already hit. The
> **newest entry is the current state.** Reading this plan without the tracker
> will make you repeat work that is already done or rebuild something that was
> deliberately abandoned.
>
> **2. BEFORE you finish your session — append one entry to `AUTONOMOUS_TRACKER.md`.**
> Use the template in that file. Sign it with **your own agent name and model**.
>
> **APPEND ONLY.** Add your entry at the **bottom**. Never edit, reword,
> reformat, reorder, merge, summarise, compact or delete an existing entry — not
> even your own, not even to fix a typo. `git diff` on that file must only ever
> show **added** lines. If it shows a deletion, you have broken the rule: restore
> the file and re-append.
>
> Task completion status belongs in **this** file (tick the checkboxes).
> Who-did-what history belongs in the **tracker**. Why-we-chose-this belongs in
> [`DECISIONS.md`](DECISIONS.md).

---

Plan for turning Inventra from a human-triggered, single-SKU investigator into an
autonomous portfolio monitor that decides **what** to reorder, **how much**, and
**from whom**, with no per-product input from a human, and stops only at the
approval gates.

Status: **plan only. Nothing in this document has been built.**

Amended 2026-09-12: **§A6** and **§B10** are new, and §A1, §B7, the
what-already-exists table, the scenario catalogue and the open decisions changed
with them. They respond to a change that has already shipped in the submission
codebase, not to a change in this plan's ambition —
[`DECISIONS.md` D29](DECISIONS.md) replaced the vendor comparison's `total_cost`
ranking with all-in cost per day of cover. That metric is correct, and it made
four of its own inputs visible as declared assumptions printed on the approval
card. A6 turns those four into data.

### Companion files

| File | Role | Write mode |
|---|---|---|
| `AUTONOMOUS_PLAN.md` (this file) | What to build, in what order | Tick checkboxes; amend tasks as the design moves |
| [`AUTONOMOUS_TRACKER.md`](AUTONOMOUS_TRACKER.md) | Who did what, when, and what they learned | **Append only** |
| [`DECISIONS.md`](DECISIONS.md) | Why each choice was made, and what lost | Append new `D<n>` records |

---

## 0. The problem being solved

Two things are missing from the current system, and everything in this plan
follows from them.

**0.1 — There is no trigger.** Every run today starts with a human naming a SKU:

```
python -m submission.app run <SKU> <WAREHOUSE> [target_cover_days]
```

or clicking a watchlist button. There is no scheduler, no poller, no sweep that
opens a case on its own. `portfolio.scan_portfolio()` computes portfolio-wide
risk but is explicitly read-only and never opens a case.

**0.2 — `target_cover_days` is a human input with a flat default.** Every product
in the catalogue is planned against `config.target_cover_default_days = 14`,
whether it is a fast-moving AC unit or a slow-moving TV. This is the
"user has to say we want 10 days of stock for this product" problem. It must
become a **derived, per-SKU output**.

### What already exists and must not be rebuilt

| Exists | Where | Note |
|---|---|---|
| Portfolio-wide risk sweep (read-only) | `submission/portfolio.py::scan_portfolio` | The seam the monitor plugs into |
| Reorder guard (no double-ordering) | `nodes.compute_risk` + `get_open_order_quantity` | Already autonomy-safe |
| Budget reservation on write / release on cancel | `tools/execution.py` | Confirmed by `test_phase11` |
| Per-supplier order sizing incl. lead-time demand, fill-rate gross-up, MOQ floor | `submission/graph/economics.py` | Correct; extend, don't replace |
| Vendor ranking on **all-in cost per day of cover** + verdicts | `economics.evaluate_options` | Keep the metric. **Replace its four assumed inputs with measured data — see A6** |
| Human edit loop (cyclic, bounded) | `apply_human_edit → draft_proposal → review_policy → request_approval` | **This is the "back and forth" the floor reconciliation needs** |
| Deterministic policy checklist override | `nodes._override_policy_checklist` | Extend to 9 rows |
| Memory signals from human decisions | `tools/memory.py` + `agent_memory_signals` | Feeds learned-preference scenario |
| Three durable interrupts | `graph/workflow.py` | One retired, one extended, one added |

---

## 1. Global design rules

These apply to every phase. A task that violates one of these is wrong even if
it works.

- [ ] **R1 — No simulation clock.** The system always reads the real
  `datetime.utcnow()`. Demo control comes from writing data with **fabricated
  dates relative to real now**, exactly as `database/seed.py` already does with
  `now - timedelta(days=...)`.
- [ ] **R2 — `as_of` is a function argument, never ambient state.** The only
  component that needs to evaluate "as of" a past date is the classifier, and it
  takes that date as a parameter: `classify(sku, warehouse, as_of=date)`.
- [ ] **R3 — Arithmetic is deterministic; the LLM never computes an
  authoritative number.** The monitor, the statistics engine, safety stock,
  reorder point, service level, order quantity and every threshold are plain
  Python. Matches the brief's "authoritative arithmetic comes from tools".
- [ ] **R4 — Agent count stays at 3.** Demand analyst, sourcing strategist,
  policy reviewer. The monitor is **not** an agent. Brief allows 2-4 and states
  more agents earn no marks.
- [ ] **R5 — No per-product human input.** Policy dials are per-class or
  per-rule, never per-SKU-typed-by-a-human. The only exception is an explicit
  manual order (Phase F) and an explicit policy floor (Phase A), both of which
  record who set them and why.
- [ ] **R6 — Every fabricated scenario writes a fresh inventory snapshot at
  `utcnow()`.** Without this the freshness gate blocks the entire sweep and the
  demo shows nothing.
- [ ] **R7 — One `sales_daily` row per day per SKU per warehouse.** Never lump
  units onto today's date. The `UNIQUE(sale_date, sku, warehouse_id)` constraint
  enforces this; the fabricator must respect it by construction.
- [ ] **R8 — Humans choose among computed options; they never type a
  quantity.** Preserves the rule documented in `nodes.apply_human_edit`.
- [ ] **R9 — No web-search tool at runtime.** The brief explicitly lists it under
  tools you are not given. Web research informed this plan; it is not a
  capability of the system.
- [ ] **R10 — Fail closed.** Any new gate, filter or reconciliation that cannot
  establish a fact blocks or parks. It never proceeds on an assumption.
  - **One named exception, §A6.1:** the four economics *refinement* inputs
    (margin, carrying rate, lateness magnitude, billing basis) fall back to a
    config value with a caveat naming that specific assumption, rather than
    blocking. The distinction is *facts that decide whether to act* (stock, sales
    history, freshness, budget — these still block) versus *facts that refine how
    much to pay*. Blocking a reorder over a missing warehouse storage rate trades
    a stockout for a bookkeeping gap.

### Test execution rule

During implementation, run the smallest focused test file(s) that directly
exercise the changed behavior, plus syntax/type checks appropriate to the
edited modules. Do **not** repeatedly run the full regression suite after
each small change: its database reset/setup cost is intentionally high and a
failure in unrelated legacy behavior is not useful evidence for the current
edit. Run the full suite once at an explicit phase boundary (or when a change
crosses several existing subsystem contracts), then classify any failure as a
new-code regression versus an existing/legacy expectation before changing
production code to satisfy it. Record the exact focused commands and results
in the phase's evidence report.

---

## PHASE A — Data foundation

Goal: a database and a fabricator that can produce any demonstrable situation,
with statistics that stay coherent.

### A1 — Schema additions

- [ ] `products.selling_price REAL` — real margin instead of the assumed 25%
- [ ] `products.lifecycle TEXT` — `NEW | GROWTH | MATURE | DECLINING | EOL`
- [ ] `products.unit_volume_m3 REAL` — so warehouse storage cost can be
  apportioned per unit rather than assumed as a flat % of price (A6)
- [ ] `warehouses.storage_cost_per_m3_month REAL` — the measured half of
  carrying cost (A6)
- [ ] `vendors.billing_basis TEXT` — `ORDERED | SHIPPED`. At a 0.94 fill rate the
  two readings differ by hundreds of dollars on a single order, and the schema
  currently has no way to say which applies (A6)
- [ ] `vendor_offers.freight_flat REAL` and `vendor_offers.freight_per_unit REAL`
  — landed cost, not ex-works price. A cheap-slow vendor with expensive freight
  can invert the ranking, and today freight is invisible (A6)
- [ ] New table `stock_receipts` — measured lead-time actuals
  - `receipt_id`, `request_id`, `sku`, `warehouse_id`, `vendor_id`,
    `quantity_ordered`, `quantity_received`, `ordered_at`, `promised_at`,
    `received_at`, `lead_time_days_actual`
  - Purpose (two consumers, not one):
    1. real lead-time mean and variance (σL) for safety stock (B8), replacing
       the `1 - on_time_rate` proxy
    2. **the distribution of lateness magnitude** for the vendor comparison
       (A6/B10), replacing `config.assumed_late_days_when_late`. `on_time_rate`
       answers "how often"; `promised_at` vs `received_at` is the only thing in
       the design that can answer "by how much"
- [ ] New table `sku_policy` — the classification record, one row per
  (sku, warehouse, as_of_month)
  - `sku`, `warehouse_id`, `as_of_date`
  - `mean_daily_demand`, `std_daily_demand`, `cv`, `adi`, `cv_squared`
  - `demand_quadrant` (`SMOOTH | ERRATIC | INTERMITTENT | LUMPY`)
  - `abc_class`, `xyz_class`, `consumption_value_12m`, `cumulative_share`
  - `service_level`, `safety_stock_units`, `reorder_point_units`,
    `derived_cover_days`
  - `maturity` (`INSUFFICIENT | PROVISIONAL | ESTABLISHED`), `confidence`
  - `candidate_class`, `candidate_since`, `consecutive_confirmations`
  - `active_class`, `change_reason`
- [ ] New table `policy_rules` — policy floors (see A4)
  - `rule_id`, `sku`, `warehouse_id`, `min_units`, `min_cover_days`,
    `reason`, `source`, `set_by`, `effective_from`, `effective_to`, `active`
- [ ] New table `parked_items` — the park queue (see C4)
- [ ] New table `carrying_cost_inputs` — one row per effective-from date
  - `cost_of_capital_annual_rate`, `insurance_annual_rate`,
    `shrinkage_annual_rate`, `effective_from`, `set_by`, `note`
  - Company-level finance inputs. Separated from `warehouses` because they are
    not a property of a building, and separated from `config` because they are
    business facts with an owner and a date, not engineering thresholds
- [ ] Extend `database/migrate.py` so every addition is additive and idempotent
- [ ] Retire the **five** caveats `economics.evaluate_options` currently emits,
  one at a time as its data lands — see A6 for the mapping. (The plan previously
  said "two"; D29 added three more when carrying cost, lateness magnitude and
  billing basis became explicit assumptions instead of silent ones.)

### A2 — Synthetic data generator

- [ ] ~35 SKUs across 3-4 warehouses
- [ ] 24 months of daily history (two years, so one seasonal cycle can be learned
  and a second compared against it)
- [ ] Demand personalities, each chosen to exercise a different code branch:
  - [ ] steady / smooth (low CV)
  - [ ] trending up
  - [ ] trending down / dying
  - [ ] seasonal (annual cycle)
  - [ ] promo-spiky (erratic: short high bursts)
  - [ ] intermittent (many zero days, small quantities)
  - [ ] lumpy (many zero days, large quantities when they occur)
  - [ ] brand-new (6 weeks of history only)
  - [ ] dead / EOL (history then flatline)
- [ ] Generator is parameterised, not hardcoded: base level, trend, weekday
  pattern, annual seasonality, spike windows, noise, zero-probability
- [ ] Vendor mix per SKU with real trade-offs: cheap-slow, dear-fast,
  balanced, unreliable, expired offer
- [ ] `stock_receipts` history backfilled so lead-time variance is measured, not
  assumed — including one vendor whose actuals are much worse than its
  `on_time_rate` suggests
- [ ] Budgets for every warehouse for the current and prior months
- [ ] Deterministic seeding (fixed RNG seed) so a demo is reproducible

### A3 — Data fabricator (the simulator's engine)

- [ ] `fabricate_history(sku, warehouse, days, profile)` — writes one
  `sales_daily` row per day, backdated, ending yesterday
- [ ] `set_position(sku, warehouse, on_hand, reserved, confirmed_inbound)` —
  writes an `inventory_snapshots` row at `utcnow()`
- [ ] `set_cover_days(sku, warehouse, days)` — convenience: computes the position
  that yields N days of cover at current velocity, then calls `set_position`
- [ ] `age_snapshot(sku, warehouse, hours)` — backdates the latest snapshot to
  force `DATA_STALE`
- [ ] `expire_offer(offer_id)` / `set_vendor_reliability(vendor_id, rate)`
- [ ] `set_budget(warehouse, month, amount, spent, committed)`
- [ ] `roll_forward(days)` *(optional, lower priority)* — shifts every historical
  timestamp back N days, appends N new sampled days ending today, drains stock
  accordingly, and lands any purchase order whose lead time has now elapsed.
  This is the "manipulate time and date" lever expressed as a data rewrite
  rather than a clock. Deferrable without losing any scenario.
- [ ] Every mutation writes an entry to a fabrication log so a demo is
  explainable afterwards
- [ ] Guard: fabricator refuses to write two sales rows for the same
  (date, sku, warehouse) — enforces R7 loudly rather than silently

### A4 — Policy floors

- [ ] Populate `policy_rules` for 3-4 SKUs *(exact count OPEN — see §Open
  Decisions)*, each with a **stated business reason**, not a bare number:
  - [ ] one SLA / contractual minimum-stock commitment to a key account
  - [ ] one warranty / service-parts obligation
  - [ ] one where the floor turns out to be **far too low** (statistics demand
    much more) — the dramatic demo
  - [ ] one where the floor is **clearly too high** (statistics demand much
    less) — the waste demo
- [ ] Support both `min_units` and `min_cover_days`; the effective floor is the
  higher of the two once converted to units at current velocity
- [ ] Floors live in the **table**, never in `policy.md` prose
- [ ] `policy.md` gains a section documenting: that floors exist, that they
  override statistics, and how a conflict between floor and statistics is
  resolved and surfaced

### A5 — Freshness configuration

- [ ] Keep `data_freshness_hours` configurable via env, as it already is
- [ ] Document the brief-vs-policy.md divergence (2 hours vs 2 days) in
  `DECISIONS.md` and in the config docstring
- [ ] Simulator exposes the value so a demo can tighten or relax it live

### A6 — Data the vendor comparison needs to stop guessing

**Why this section exists.** `economics.evaluate_options` was rewritten under
[`DECISIONS.md` D29](DECISIONS.md) to rank suppliers on **all-in cost per day of
cover** instead of `total_cost`. The metric is now right; four of its inputs are
still declared assumptions, and every one of them is printed on the approval card
because the schema cannot supply the fact. The approver currently reads:

> Those two figures include delivery risk and the cost of holding stock. They
> assume each unit earns 25% of its purchase price and costs 20% a year to hold —
> this database has no selling price and no warehousing cost, so both are
> configured assumptions.

That sentence is honest, and it is also the single largest credibility cost in the
output. An agent asked "is this the right supplier?" cannot answer better than the
worst of its inputs, and two of those inputs are round numbers someone typed into
`config.py`. This section makes them data.

#### A6.1 — The four assumptions, and what replaces each

| # | Assumption today | Config knob | Data that replaces it | Consumer |
|---|---|---|---|---|
| 1 | Each unit earns 25% of its purchase price | `assumed_gross_margin_rate` | `products.selling_price` → `contribution = selling_price − landed unit cost` | `daily_contribution_at_risk`, `expected_stockout_cost`; also B7's newsvendor ratio |
| 2 | Stock costs 20% a year to hold | `assumed_annual_carrying_rate` | `carrying_cost_inputs` (capital + insurance + shrinkage) **+** `warehouses.storage_cost_per_m3_month × products.unit_volume_m3` | `carrying_cost`, and the MOQ-overshoot penalty that stops a bulk minimum winning |
| 3 | A late delivery is 1 day late | `assumed_late_days_when_late` | `stock_receipts`: `received_at − promised_at` per vendor → mean, p50, p90 | `expected_days_short_if_late`, `expected_stockout_cost` |
| 4 | Suppliers invoice for units ordered | `vendor_billed_on_units_shipped` | `vendors.billing_basis` | `cover_purchase_cost` — i.e. the ranking numerator itself |

- [ ] Each of the four is replaced **independently**. There is no big-bang switch:
  a SKU with a selling price gets a measured margin even if its vendor has no
  receipt history yet
- [ ] **Per-figure fallback, per-figure caveat.** When a measured value is absent
  the config value is used *for that figure only*, and the caveat naming *that
  one assumption* is emitted. Today the caveats are unconditional; they must
  become conditional, or the credibility problem simply persists in a portfolio
  where 30 of 35 SKUs are fully measured
- [ ] **This is a deliberate, narrow exception to R10 (fail closed).** Blocking a
  reorder because a warehouse has no `storage_cost_per_m3_month` would trade a
  stockout for a bookkeeping gap. The rule instead is: *fail closed on facts that
  decide whether to act, fall back with a named caveat on facts that only refine
  how much to pay.* Missing stock, missing sales history and stale snapshots keep
  blocking. Missing carrying-cost inputs do not
- [ ] Record which basis each figure used, per option, so it is auditable rather
  than inferred: `margin_basis`, `carrying_basis`, `lateness_basis`,
  `billing_basis` ∈ `measured | assumed`

#### A6.2 — Two things the comparison ignores entirely today

Not assumptions — omissions. Both change which supplier wins.

- [ ] **Freight.** `vendor_offers` has `unit_price` and nothing else, so the
  comparison is ex-works. A vendor $20/unit cheaper with $900 of freight on a
  25-unit order is $16/unit dearer, and the system cannot see it. Add
  `freight_flat` + `freight_per_unit`, fold both into a **landed unit cost**, and
  make landed cost — not `unit_price` — the input to every figure in A6.1
- [ ] **Payment terms.** Net-60 from a dearer vendor can beat net-15 from a
  cheaper one once cost of capital is real (which A6.1 #2 makes it). Add
  `vendors.payment_terms_days` and credit the financing benefit at the same
  `cost_of_capital_annual_rate` the carrying cost uses — one rate, two uses, so
  they can never disagree
- [ ] Both are additive to the existing formula. Neither changes the metric, the
  verdict vocabulary, or the graph

#### A6.3 — Named as out of scope, so it is a choice and not an oversight

- [ ] **Quantity-break pricing.** One flat `unit_price` + MOQ is modelled; real
  price ladders are not. This interacts with the MOQ-overshoot penalty — a break
  at 200 units might genuinely justify the overbuy the penalty currently
  discourages. Deferred to Phase H, **not** silently ignored
- [ ] **Stockout cost beyond lost margin.** SLA penalties, backorder handling and
  customer churn are real and are not modelled; `expected_stockout_cost` is lost
  contribution only, so it is a **floor**. Policy floors (A4) are the existing
  proxy for products where the true cost is much higher
- [ ] **Substitution.** If a customer buys an alternative SKU, the lost margin is
  the *difference*, not the whole contribution. Needs a substitution map; no
  schema support planned
- [ ] **Shelf life.** No expiry data, so overbuy is priced as capital cost only,
  never as spoilage. Fine for the seeded catalogue (AC units, TVs); wrong for
  perishables, and the plan should say so rather than imply generality

#### A6.4 — How it integrates into the current flow

The graph shape does not change. No new node, no new agent, no new interrupt.

```
fetch_vendor_evidence          (existing) reads offers + vendor performance
        │                      NEW: also reads vendors.billing_basis,
        │                           freight, payment terms
        ▼
[NEW, deterministic]  load_cost_inputs(sku, warehouse, vendor_ids)
        │             → EconomicsInputs: contribution/unit, carrying rate/day,
        │               per-vendor lateness distribution, billing basis,
        │               plus a *_basis flag per figure (measured | assumed)
        │             pure read, no LLM, folded into the existing
        │             fetch_vendor_evidence node — not a new graph node
        ▼
build_options                  (existing) sizing unchanged — D29 kept
        │                      required_quantity() exactly as it is
        ▼
evaluate_options(risk, options, vendor_performance, inputs=…)
        │                      NEW optional 4th argument. Absent → today's
        │                      config-driven behaviour, so nothing breaks and
        │                      the existing 140 tests keep passing
        ▼
recommend_vendor → _validate_recommendation   (existing gate, unchanged)
        ▼
draft_proposal → review_policy → request_approval → ui._approval_notes
                               NEW: caveat text is conditional on the
                               *_basis flags; a fully measured case shows
                               no assumption sentence at all
```

- [ ] `EconomicsInputs` is a frozen dataclass in `graph/economics.py`, built by a
  new pure function `load_cost_inputs(...)` in a **tool** module (agents never
  see SQL — brief constraint, unchanged)
- [ ] `evaluate_options` takes it as an **optional** argument defaulting to
  `None`. With `None` it reads `config` exactly as it does now. This is what makes
  A6 shippable in four independent slices instead of one risky cut
- [ ] `config.assumed_*` values survive as **documented fallbacks**, not defaults
  — same treatment B7 already plans for `assumed_gross_margin_rate`
- [ ] `OptionEconomics` gains the four `*_basis` fields; `as_evidence()` exposes
  them so the **Strategist can say "measured" or "assumed" without computing
  anything** — it stays a citation, never a calculation (R3)
- [ ] `ui._approval_notes` builds the assumption paragraph from the flags, so it
  shrinks as data lands and disappears when everything is measured
- [ ] The three-consumer invariant holds throughout: prompt, gate and approval
  card read one object. A6 adds fields to that object; it does not add a second
  source of numbers

#### A6.5 — Fabricator support (so the effect is demonstrable)

- [ ] `set_selling_price(sku, price)` — flip a verdict live by changing margin
- [ ] `set_carrying_inputs(...)` / `set_storage_cost(warehouse, rate)`
- [ ] `add_receipt(request_id, promised_at, received_at, qty_received)` — build a
  lateness history for one vendor without waiting for real orders
- [ ] `set_billing_basis(vendor_id, basis)` / `set_freight(offer_id, flat, per_unit)`
- [ ] At least one seeded vendor whose **measured lateness is far worse than its
  `on_time_rate` implies** (93% on time, but 4 days late when it slips). Under
  today's flat 1-day assumption it looks safe; measured, it loses. That single
  contrast is the whole argument for this section, in one screen

**Phase A exit criteria**
- [ ] A single command seeds a full, reproducible portfolio with 24 months of
  coherent daily history
- [ ] Every scenario in §Scenario Catalogue can be reached by calling fabricator
  functions, with no manual SQL
- [ ] `SELECT count(*) FROM sales_daily GROUP BY sale_date, sku, warehouse_id
  HAVING count(*) > 1` returns nothing
- [ ] Every seeded product has a `selling_price` and a `unit_volume_m3`; every
  warehouse a `storage_cost_per_m3_month`; every vendor a `billing_basis` — so at
  least one case reaches the approval card with **no assumption sentence at all**
- [ ] At least one case still shows a caveat, for a **named single missing fact**
  (e.g. a brand-new vendor with no receipt history), proving the fallback is
  per-figure rather than all-or-nothing

---

## PHASE B — Statistics and policy engine

Goal: pure, deterministic functions that turn history into a reorder point and a
service level. **No LLM anywhere in this phase.**

### B1 — Demand statistics

- [x] `mean_daily_demand`, `std_daily_demand` over a given window
- [x] `cv = σ / μ`
- [x] `adi` = average demand interval (mean gap between non-zero demand days)
- [x] `cv_squared` on non-zero demand sizes
- [ ] Quadrant classification (Syntetos-Boylan-Croston cutoffs, configurable):
  - `SMOOTH`: ADI < 1.32 and CV² < 0.49
  - `ERRATIC`: ADI < 1.32 and CV² ≥ 0.49
  - `INTERMITTENT`: ADI ≥ 1.32 and CV² < 0.49
  - `LUMPY`: ADI ≥ 1.32 and CV² ≥ 0.49
- [x] Zero-demand-day count, non-zero observation count

### B2 — Forecasting, switched by quadrant

- [ ] `SMOOTH` / `ERRATIC` → level from a short recent window; normal-based
  safety stock is valid
- [ ] `INTERMITTENT` / `LUMPY` → Croston-style (or bootstrap) estimate;
  normal-based safety stock is **not** valid and must not be used
- [ ] Explicit guard: for intermittent/lumpy items, "daily velocity" is recorded
  as not-meaningful and downstream consumers must read the quadrant before
  trusting it
- [ ] **Known defect to fix here:** `tools/inventory.calculate_stock_risk`
  computes `cover_days = available / daily_velocity` and derives
  `projected_stockout_date` from it. For a lumpy item that number is fiction,
  and it currently drives vendor eligibility (`meets_deadline`) and a hard
  policy checklist row. Route lumpy/intermittent items through the
  quadrant-appropriate path instead.

### B3 — Two windows for two jobs

- [ ] **ABC economic importance** uses a rolling **12 completed months**
- [ ] **Reorder point / forecast** uses the **current demand level** from a short
  recent window
- [ ] The **gap between them is the regime-shift signal**: if the 12-month mean
  is 12/day and the last 14 days are 25/day, planning against 12 guarantees a
  stockout
- [ ] `detect_regime_shift(...)` returns magnitude, sustained-ness and
  significance, and feeds the accelerated-reclassification path (B6)

### B4 — ABC / XYZ classification

- [ ] `consumption_value_12m = demand_12m × unit_cost`
- [ ] Sort descending, compute cumulative share, assign A/B/C at **configurable**
  cumulative thresholds (default ~70-80% / next ~15-20% / remainder)
- [ ] XYZ from CV: X predictable, Y moderately variable, Z erratic
- [ ] Combined ABC×XYZ grid carried on the record

### B5 — Maturity and confidence

| History | Behaviour |
|---|---|
| < 3 months | `INSUFFICIENT` — no permanent class assigned |
| 3-6 months | provisional, annualised, **low** confidence |
| 6-12 months | provisional, annualised, confidence scaled by observations |
| ≥ 12 months | `ESTABLISHED` — full classification from rolling 12 months |
| ≥ 24 months | seasonality and trend analysis additionally available |

- [ ] Annualise available consumption when < 12 months of history
- [ ] Confidence is driven by **effective observations**, not months alone — a
  SKU with 3 months and thousands of demand events carries more information
  than one with 12 months and 3 events
- [ ] A new SKU is never dumped into C purely because its historical
  consumption is small

### B6 — Hysteresis

- [ ] Recalculate monthly (driven by month-ends in the data, via `as_of`)
- [ ] Track `candidate_class`, `candidate_since`, `consecutive_confirmations`
- [ ] **Promotion** (e.g. B→A, raising service): **2** consecutive confirmations
- [ ] **Downgrade** (e.g. A→B, lowering service): **3** consecutive confirmations
- [ ] Confirmation counts configurable
- [ ] **Fast path**: a statistically significant, sustained regime shift with
  material economic impact may bypass the confirmation requirement, and must
  record its reason and confidence
- [ ] Every class change stores a human-readable `change_reason`

### B7 — Service level from economics, bounded by class

- [ ] Newsvendor critical ratio:
  `service_level = understock_cost / (understock_cost + overstock_cost)`
  where understock = lost margin per unit (needs `selling_price`) and
  overstock = holding cost per unit for the period
- [ ] Floor and cap the result **per ABC class** as a policy guardrail, so
  classification constrains the answer without dictating it
- [ ] **Holding cost is no longer an assumption here** — take it from A6.1 #2
  (`carrying_cost_inputs` + warehouse storage rate + unit volume). Superseded
  note: an earlier draft of this task called it "the one remaining assumption;
  expose it as config". Config is now the *fallback*, not the source
- [ ] **One holding-cost function, two callers.** B7's overstock cost and
  `economics.carrying_cost` must read the same derivation. If the newsvendor ratio
  and the vendor comparison disagree about what a day of stock costs, the service
  level and the order it sizes are arguing with each other
- [ ] Retire `assumed_gross_margin_rate` as a *default* once `selling_price`
  exists (keep as fallback only)

### B8 — Safety stock, reorder point, derived cover

- [ ] `safety_stock = z(service_level) × sqrt(L × σ² + μ² × σL²)`
  - σL from `stock_receipts` (measured), not from `1 - on_time_rate`
- [ ] `reorder_point = μ × L + safety_stock`
- [ ] `derived_cover_days` = the reorder point expressed in days, so it can be
  handed to the existing `economics.size_order_quantity` without changing that
  function's contract
- [ ] `statistical_target` (units) recorded separately from `active_target`
  (units) — **both always computed, both always shown**, following the
  active-vs-statistical convention used by commercial inventory systems

### B9 — Backfilled classification history

- [ ] At seed time, run `classify(..., as_of=month_end)` for each of the last 24
  month-ends and store every result
- [ ] Result: real hysteresis transitions are visible immediately after seeding,
  with no waiting and no staged data

### B10 — Measured economics inputs (the functions A6 needs)

Pure, deterministic, no LLM — same discipline as the rest of Phase B. Depends on
nothing in B1-B9, so it can be built in parallel with them; it depends only on the
A1/A6 schema additions.

- [x] `contribution_per_unit(sku, landed_unit_cost)` →
  `selling_price − landed_unit_cost`, or `None` when `selling_price` is absent
  - [x] Guard: a negative result is a **data error**, not a small number. Selling
    below landed cost must be surfaced loudly, never quietly fed into a stockout
    valuation that then reads as "running out is free"
- [x] `carrying_rate_per_day(sku, warehouse)` →
  `(cost_of_capital + insurance + shrinkage) / 365` on landed value,
  **plus** `storage_cost_per_m3_month × unit_volume_m3 / 30` as an absolute
  per-unit-per-day term
  - [ ] Returns both components separately, not one blended rate: an approver
    asking "why is holding this expensive?" gets "it is bulky" or "capital is
    dear", which are different problems with different fixes
  - [ ] Obsolescence loads onto `DECLINING`/`EOL` lifecycle, so scenario 3 (dying
    product) gets a carrying cost that argues against stockpiling
- [ ] `lateness_distribution(vendor_id, sku=None)` from `stock_receipts` →
  `n_observations`, `on_time_rate_measured`, `mean_late_days`,
  `p50_late_days`, `p90_late_days`
  - [ ] Computed over **late deliveries only** — the mean lateness of shipments
    that slipped, not smeared across the on-time ones, since `p_late` already
    carries the frequency. Blending the two would double-discount
  - [ ] Minimum observation count below which it returns `None` and the config
    fallback applies, with the caveat. Three late deliveries is not a distribution
  - [ ] Report `on_time_rate_measured` alongside the stored
    `vendor_performance.on_time_rate` and **flag a material divergence.** The
    stored figure is the one the eligibility gate uses; if receipts disagree with
    it, that is a finding, not a rounding difference
- [x] `landed_unit_cost(offer)` → `unit_price + freight_per_unit + freight_flat / quantity`
  - [ ] Quantity-dependent by construction, which means it must be recomputed
    when the human switches supplier (`apply_human_edit`) — the existing re-draft
    loop already does this, but the dependency is easy to miss
- [x] `load_cost_inputs(sku, warehouse, vendor_ids)` assembles the above into the
  `EconomicsInputs` object A6.4 describes, setting each `*_basis` flag
- [ ] Unit tests with hand-checked values for every function, including the
  `None`/fallback path for each one **independently** — the per-figure fallback is
  the part most likely to regress into all-or-nothing

**Phase B exit criteria**
- [ ] Every function is pure, takes `as_of` where relevant, and has a unit test
  with hand-checked expected values
- [ ] A lumpy SKU and a smooth SKU with the same mean produce visibly different
  safety stock
- [ ] At least one SKU in the seed shows a class change with a confirmation
  history in `sku_policy`
- [ ] A measured margin and a measured carrying rate change at least one vendor
  **verdict** compared with the 25% / 20% config defaults — proving the inputs
  are load-bearing and not decoration
- [ ] The vendor whose measured lateness is worse than its `on_time_rate` implies
  (A6.5) loses a comparison it wins under the flat 1-day assumption
- [ ] B7's overstock cost and `economics.carrying_cost` demonstrably call the same
  function

---

## PHASE C — Autonomous sweep

Goal: something decides on its own which products to open cases for.

### C1 — Candidate detection

- [ ] Deterministic, no LLM
- [ ] Trigger condition: `current_position < max(reorder_point, policy_floor)` —
  **either** breach fires
- [ ] `current_position = on_hand − reserved + confirmed_inbound + open_order_units`
  (reuse the existing reorder-guard arithmetic)
- [ ] Exclusions before any model call:
  - [ ] snapshot stale → not a candidate, reported separately
  - [ ] already has a pending case awaiting a human → skipped (see C5)
  - [ ] already on order in sufficient quantity → skipped
  - [ ] product inactive / EOL → skipped with reason
  - [ ] maturity `INSUFFICIENT` → **parked**, not blocked (see C4)
- [ ] Records **why** every non-candidate was excluded, so "nothing happened" is
  explainable

### C2 — Ranking and budget allocation

- [ ] Rank candidates by urgency × economic value
- [ ] **Allocate the month's remaining budget down the ranked list before any
  drafting begins**
- [ ] Candidates beyond the budget line are **deferred with a named reason**, not
  silently failed
- [ ] Fixes a real defect: today each case reads `budget.remaining`
  independently and money is only reserved at execution, so N candidates can all
  individually "fit", all get approved, and the last few fail revalidation
  *after* a human approved them

### C3 — Per-candidate execution

- [ ] For each surviving candidate, run the **existing case graph** with a
  **derived** `target_cover_days`
- [ ] Nothing about the graph's core path changes — evidence → demand →
  sourcing → economics → policy → draft → approve
- [ ] Cost control: 3 LLM calls per candidate, so the deterministic filter must
  be strict. 35 SKUs swept blindly would be ~105 calls; the filter should reduce
  that to the handful genuinely at risk

### C4 — Parking (per-SKU, never blocks the sweep)

A parked item is written to `parked_items` and carries **all** of:

- [ ] `sku`, `warehouse_id`, `sweep_run_id`, `parked_at`
- [ ] `reason_code` plus a plain-language `reason`
- [ ] What **was** computed: μ, σ, CV, ADI, quadrant, class, confidence — so a
  human can see how far the analysis got
- [ ] What was **missing or conflicting**, specifically
- [ ] `question` — the one precise question for the human
- [ ] `unblocking_action` — concrete, e.g. "backfill sales for DEL-01 / AC-005
  from 2026-08-01 to 2026-08-14", not "needs more data"
- [ ] `actionable_now` — whether the human can act, or it's waiting on someone
  else (e.g. the data team)
- [ ] `resolved_at`, `resolved_by`, `resolution`
- [ ] Appears in a queue in the agent UI with an action button
- [ ] **A parked SKU never stops the sweep.** The rest of the run continues.

### C5 — Re-sweep behaviour

- [ ] A SKU with a case already awaiting a human is **not** re-opened
- [ ] Instead, freshness is re-checked:
  - [ ] still fresh → send a **reminder** email with approve/reject
  - [ ] gone stale → the reminder changes its message to "this needs
    re-validation before it can be sent"
- [ ] `case_id` remains `CASE-{sku}-{warehouse}` (stable); each sweep run gets a
  new `thread_id`, as the current design already does

### C6 — Sweep record

- [ ] Every sweep writes a run record: when, how many pairs examined, how many
  candidates, how many parked, how many deferred for budget, how many cases
  opened, total model calls
- [ ] This is what the monitoring UI reads

**Phase C exit criteria**
- [ ] "Run monitor now" opens cases with zero human input and zero per-product
  configuration
- [ ] A healthy portfolio produces zero cases and zero LLM calls
- [ ] Sweeping a portfolio whose budget covers only some candidates produces
  proposals for the top-ranked ones and named deferrals for the rest, with no
  post-approval revalidation failures

---

## PHASE C2 — Policy floor reconciliation

Goal: policy floors override statistics, the divergence is surfaced, and a human
chooses between computed options.

### C2.1 — Three figures, always

- [ ] `policy_floor` — from `policy_rules`, in units
- [ ] `statistical_target` — from Phase B
- [ ] `active_target` — the one the order is sized to
- [ ] `target_basis` — `POLICY_FLOOR | STATISTICAL | STATISTICAL_MINIMUM`
- [ ] `target_provenance` — `derived` or `human:<name>`
- [ ] All carried on `CaseState` and on the proposal, all shown on the approval
  card

### C2.2 — Divergence cases

| Case | Behaviour |
|---|---|
| Statistics **exceed** the floor (floor 10, stats 25) | Recommend **25**. Prove the floor is insufficient with the arithmetic: "at 25 units/day and a 3-day lead time, 10 units is under half a day of cover — you would stock out before any delivery lands." |
| Floor **exceeds** statistics (floor 10, stats 5) | Recommend **10** — honour the floor *(provisional; see Open Decisions)*. Flag the excess and quantify it: "the statistics support 5; the floor forces 5 extra units, ₹X of working capital for no measured service gain." |
| They agree | No choice offered. Normal approve / reject. |

- [ ] Both alternatives are always offered to the approver, re-costed by the
  **same** deterministic sizing code
- [ ] The human **selects a basis**; they never type a quantity (R8)

### C2.3 — Graph changes (small, reuses the existing cycle)

- [ ] Read `policy_rules` in a deterministic node (fold into
  `fetch_budget_and_policy`)
- [ ] `ApprovalDecision` gains `chosen_target_basis`
- [ ] `apply_human_edit` handles **target basis** as well as `edited_offer_id`
- [ ] Re-enters the **existing** loop:
  `apply_human_edit → draft_proposal → review_policy → request_approval`
  — which already recomputes quantity, cost, budget line and proposal hash, and
  already re-runs the policy review
- [ ] Already bounded by `config.max_human_edit_cycles = 3`. No new bound needed.
- [ ] **No new graph shape. No agent-before-monitor. No new interactive
  mechanism.**

### C2.4 — Policy review changes

- [ ] Add a **9th** `PolicyQuestion`: does the proposal respect the policy floor
- [ ] Force-override it deterministically, exactly like the other seven
  mechanically-checkable rows
- [ ] Update `_checklist_covers_every_question_exactly_once` and the
  `PolicyReview` contract (currently pinned at exactly 8 items)
- [ ] A human choosing to go **below** the floor produces an **EXCEPTION**
  verdict, never a silent PASS — a deliberate, named, audited policy breach.
  Mirrors the existing over-budget tolerance pattern.

**Phase C2 exit criteria**
- [ ] A floor-too-low SKU produces a proposal above the floor with the
  arithmetic proving why
- [ ] A floor-too-high SKU produces a floor-compliant proposal that names the
  excess cost, with the lower option offered
- [ ] Choosing the alternative re-drafts, re-reviews, re-hashes and requires
  re-approval

---

## PHASE D — Two-gate approval

Goal: approve the order, then separately approve the vendor email.

### Gate 1 — approve the order

- [ ] Unchanged in shape from today: `request_approval → await_approval`
- [ ] Approve → revalidate → `create_purchase_request` (status `PENDING`, budget
  reserved)
- [ ] **One approval per item, one email per item, its own identifiers**, so any
  single item can be rejected and re-run without touching the others
- [ ] **No batching.** One purchase request per SKU. Multi-SKU consolidation per
  vendor is deliberately deferred to Phase H.

### Gate 2 — approve the vendor email

- [ ] New interrupt **after** the purchase request exists
- [ ] Presents the **drafted vendor email** for review
- [ ] Approve → send → stamp `vendor_sent_at` and `vendor_send_status`
  (columns already exist in `purchase_requests`, currently unused)
- [ ] Do nothing → the request sits at gate 2 and generates reminders (see
  **Reminders** below)

### Rejection with a recorded reason

- [ ] Rejecting at gate 2 **requires** a reason before the graph will resume
- [ ] Email reject link opens a form that captures the reason
- [ ] Store `cancelled_by`, `cancel_reason`, `cancelled_at`
- [ ] `cancel_purchase_request` releases the reserved budget against the same
  `committed_budget_month` it reserved
- [ ] Write an `agent_memory_signals` row so a later case on the same product
  sees the history
- [ ] Same discipline at gate 1: rejection reasons are stored, not just audited

### Reminders

- [ ] Generated by the **sweep** — "Run monitor now" also scans for requests
  stuck at gate 2 and re-emails them
- [ ] Reminder re-checks freshness first:
  - [ ] fresh → "approve or reject"
  - [ ] stale → "this needs re-validation before it can be sent"
- [ ] Reminder count and last-reminded timestamp tracked, so it escalates rather
  than repeating identically
- [ ] Documented honestly: **without a background scheduler, a reminder can only
  be produced when something runs.** A real scheduler is a deployment concern
  recorded in Phase H, not a design gap.

**Phase D exit criteria**
- [ ] An approved order that is never emailed appears in a reminder on the next
  sweep
- [ ] A gate-2 rejection releases the budget, stores the reason and the rejector,
  and leaves no PO in a sent state
- [ ] Rejecting one item leaves the other items from the same sweep untouched

---

## PHASE E — Insufficient data loop

Goal: when the data is too thin, ask; don't die.

- [ ] **Fix an off-spec behaviour:** `nodes.fetch_evidence` currently fails
  `INSUFFICIENT_DATA` with the default `BLOCKED` status. The case-flow spec
  (`05_inventra_case_flow.md`, scenario 11) and the Investigator interface both
  say insufficient sales history is **`NEEDS_INFORMATION`**, not `BLOCKED`.
- [ ] Route it to a pause/park that states exactly what is missing
- [ ] The question is specific: which SKU, which warehouse, which date range,
  how many observations short
- [ ] Human path: operator sees the park → tells the data team → data is entered
- [ ] Resume path: once the data exists, the case re-runs and proceeds normally
- [ ] Simulator supports the demo: a "backfill missing sales" action that writes
  the missing days
- [ ] **Retire** the ambiguous-demand-window interrupt (`_await_window_choice`).
  It is not required by the brief (brief scenario 2 is *missing request fields*,
  which `_await_missing_info` already covers), and full-history forecasting
  makes the 7d-vs-30d choice largely obsolete. Genuinely undecidable cases are
  **parked** instead.
- [ ] Keep `_await_missing_info` — it is what satisfies brief scenario 2

**Phase E exit criteria**
- [ ] A thin-data SKU produces `NEEDS_INFORMATION` with a precise, actionable
  question — not `BLOCKED`
- [ ] Backfilling the named date range and re-running produces a normal proposal
- [ ] Brief scenario 2 still demonstrably passes

---

## PHASE F — Manual order path

Goal: a human can order anything, including a no-history item, and still get
full agent value on vendor selection and drafting.

- [ ] Manual entry supplies **only** how many days of cover they want
- [ ] Runs the **same graph** — vendor selection, economics, policy review,
  drafting, approval are all identical
- [ ] `target_provenance = human:<name>` recorded and shown on the approval card
- [ ] **Insufficient-data override:** a manual order may proceed past
  `INSUFFICIENT_DATA`, because the human has supplied the demand assumption the
  data could not. Conditions:
  - [ ] the override is audited as a named human's decision
  - [ ] the approval card says plainly: "there is not enough sales history for
    this product; the cover target was set by `<name>`, not derived from data"
  - [ ] the agent still does all vendor work; it simply stops claiming to know
    the demand
- [ ] Policy floors still apply to manual orders

**Phase F exit criteria**
- [ ] A no-history SKU can be ordered manually, with the warning visible on the
  approval card and the provenance in the audit trail
- [ ] A manual order with a derived-vs-supplied divergence still surfaces both
  numbers

---

## PHASE G — Two Streamlit apps

Goal: two separate URLs, functional not pretty. Visual polish is explicitly
deferred to Phase H — but **full, validated database editing is not polish, it
is the point of G1** (see R11 below and §G1.1).

Amended 2026-09-12: G1 was previously one line ("browse and edit every
table"). It is now specified properly, because the **no-human-override rule
(R11)** makes G1 the *only* legitimate way a human supplies missing data. If
the human cannot enter real rows into the real tables from a real screen,
then Phase E's park → backfill → re-fetch loop is only reachable from a
terminal, and the rule collapses back into "type a number into the agent and
hope."

### R11 — Humans supply data, never answers *(new global rule, applies from here back through every phase)*

- [x] **A human never types a number that feeds a calculation.** Not a demand
  rate, not a target quantity, not an order quantity.
- [x] **When data is missing, the system names exactly what is missing and the
  human enters it into the relevant table.** The human then confirms, and the
  system **re-reads from the database.** No user-input field is ever read as
  evidence — the database is re-fetched, so the value that drives arithmetic
  came from a table, not from a form.
- [x] **One named exception, and only one:** when history exists but is
  immature (`maturity` = `PROVISIONAL` or `INSUFFICIENT`), the derived
  cover target cannot be trusted, so a human may enter **how many days of
  stock they want for that product — and nothing else.** The demand rate
  still comes from `get_sales_velocity`. Every agent step (sourcing,
  economics, policy review, drafting) then runs against that target exactly
  as it would against a derived one.
- [x] **When `maturity` = `ESTABLISHED`, no human input is offered at all** —
  `derived_cover_days` is the target and the field is not rendered.
- [x] Choosing among **computed** options is not an override and stays legal:
  `edited_offer_id` (pick a different eligible supplier),
  `chosen_target_basis` (pick between floor / statistical), and
  `policy_rules` floors (a contractual commitment, not derivable from data —
  already an audited exception under R5).

**Known R11 violations to fix in this phase** *(found 2026-09-12; all live
today)*:
- [x] `submission/ui.py`'s sidebar days-of-cover slider feeds **both**
  `scan_portfolio()` and `run_case()`, so a human-typed number currently
  drives the risk assessment of **every product on every screen**. This is
  the flat-14 problem D2 exists to remove, still present.
  Fixed 2026-09-12 (Sonnet 5): `scan_portfolio` now looks up each pair's own
  `sku_policy.derived_cover_days` (DG6); the slider was already gone from
  `ui.py` before this session, confirmed by re-read.
- [x] `app.py run <sku> <wh> [target_cover_days]` accepts the same input on
  every case, regardless of maturity.
  Re-verified 2026-09-12: `main()`'s `run` command already takes only
  `sku, warehouse_id` (no third CLI arg) — this was fixed before this
  session as part of Phase F's `run_case(sku, warehouse_id)` signature.
- [x] `resume_missing_info`'s form offers `target_cover_days` unconditionally.
  Its `sku`/`warehouse_id` fields are fine — those identify *which* product,
  they are not evidence.
  Fixed 2026-09-12 (Sonnet 5): removed `target_cover_days` from
  `_await_missing_info`'s interrupt payload and apply block in
  `submission/graph/workflow.py` (DG7). `app.resume_missing_info` and
  `ui._render_missing_info_form` were already clean of it on re-read —
  only the graph-side payload/apply block still carried it.
- [x] `config.target_cover_default_days = 14` is a flat fallback for every
  product. Once targets are derived, it should only ever apply to the
  `PROVISIONAL`/`INSUFFICIENT` case as a pre-filled suggestion in the one
  legal input, never as a silent default on an established SKU.
  `scan_portfolio` now only falls back to it with an explicit
  "provisional maturity" / "not yet derived" label (`target_basis_label`),
  never silently.

### G1 — Simulator / data console

#### G1.1 — Real database editing, with real validation *(the core of this phase)*

- [x] **Full create / read / update / delete on every input table**, from the
  screen, with no SQL and no terminal: `products`, `warehouses`, `vendors`,
  `vendor_offers`, `inventory_snapshots`, `sales_daily`, `monthly_budgets`,
  `policy_rules`, `carrying_cost_inputs`, `stock_receipts`
  Built via `submission/dataops/{spec,validate,write,read}.py` +
  `submission/data_console.py`'s generic table editor, driven entirely by
  `TABLE_SPECS`. Live-verified in the browser for `products` (create, edit,
  delete all worked); the other 9 tables share the same generic dispatch
  path and are covered by `test_phase_g_data_console.py`, not individually
  clicked through in the browser.
- [x] **Derived tables are read-only in the UI**, and visibly labelled as
  such: `sku_policy`, `sweep_runs`, `parked_items`, `purchase_requests`,
  `audit_events`, `agent_memory_signals`. Hand-editing a derived row would
  put a number into the evidence chain that no computation produced — the
  exact failure R3 and R11 exist to prevent. To change a derived value, edit
  its **inputs** and recompute.
- [x] **Per-field validation before any write**, with the reason shown on the
  field, never a silent rejection and never a raw traceback:
  - [x] type and range (e.g. `on_hand >= 0`, `0 <= on_time_rate <= 1`,
    `unit_price > 0`, `moq >= 1`, `selling_price > 0`)
  - [x] foreign-key integrity (a `sales_daily` row for an unknown `sku`, or a
    `vendor_offers` row for an unknown `vendor_id`, is refused with the
    specific missing key named)
  - [x] the `UNIQUE(sale_date, sku, warehouse_id)` constraint on
    `sales_daily` (R7) — surfaced as "a row already exists for that day,
    edit it instead" rather than an IntegrityError
  - [x] date sanity (`valid_from <= valid_until`; `promised_at`/`received_at`
    not before `ordered_at`; no future `sale_date`)
  - [x] cross-field business sanity, warn-not-block: `selling_price` below
    the cheapest landed cost is flagged loudly (B10 already treats a negative
    contribution as a data error, not a small number)
- [x] **Every UI write goes through the existing tool/fabricator layer**
  (`fixtures/fabricator.py`, `tools/*.py`), never a raw SQL box. One write
  path, already-tested guards, and the fabrication log stays complete.
  `submission/dataops/write.py` delegates to fabricator for
  products/vendors/vendor_offers/sales_daily/warehouses and falls back to a
  generic spec-driven statement for the rest.
- [x] **Every UI write is logged to the fabrication log** with who, what,
  when, and the before/after value — so a demo is explainable afterwards and
  an accidental edit is findable.
  Persisted to the new `data_change_log` table (DG5), not the in-memory
  `fabricator._LOG`, so it survives a restart. Live-verified in the browser.
- [x] Refuse and explain, never partially apply: a rejected multi-field edit
  leaves the row exactly as it was.

#### G1.2 — The missing-sales-data screen *(what makes R11 workable)*

- [x] Reached from G2's park queue by deep link, carrying the SKU, warehouse
  and **exact date range** the park record named
  G2's park queue (`screen_monitor`) links to
  `http://127.0.0.1:8502/?sku=...&warehouse_id=...`; the missing-sales screen
  reads `sku`/`warehouse_id` from `st.query_params` (date range is left to
  the operator's own start/end pickers rather than also carried in the URL —
  a narrower deep link than the plan describes; noted as a gap, not silently
  dropped).
- [x] Shows the range day by day, with the existing rows filled in and the
  gaps visibly empty, so "what is missing" is a picture rather than a
  sentence
- [x] Accepts per-day units, or a bulk fill for a selected span, both writing
  real `sales_daily` rows via `fabricator.backfill_missing_sales`
  (already built in Phase E — additive-safe, skips days that already exist)
  Bulk fill only (through `dataops.create_row`, which itself calls
  `backfill_missing_sales`); a per-day entry grid was not built separately —
  the day-by-day table is read-only/informational, and the bulk-fill control
  is the one write path. Narrower than the plan's "per-day entry, and a bulk
  fill" — flagged, not silently reduced.
- [x] Live counter: how many observations exist in each window now, and how
  many more the `<3` threshold still needs — so the human can see the moment
  the case becomes runnable
- [x] **"Data is in — re-run this case"** button, which re-runs the case so
  the graph **re-fetches from the database**. It never passes the entered
  numbers into the run.
  Live-verified in the browser (`test_backfilling_the_named_range_then_
  rerunning_produces_a_proposal_from_the_new_rows` proves the re-fetch
  numerically).
- [x] Resolving the park record (`tools.parking.resolve_park`) requires a name
  and a resolution note, which the existing function already enforces

#### G1.3 — Levers, scenarios, and visible effect

- [x] Per-SKU levers: position, cover days, snapshot age, offer validity,
  vendor reliability, budget, selling price, unit volume, freight, billing
  basis
  Built: position, cover days, snapshot age, recompute-classification.
  Vendor reliability/selling price/unit volume/freight/billing basis are
  reachable through the generic table editor (Levers screen does not
  duplicate them as separate quick-controls) — narrower than a dedicated
  lever per item, flagged rather than silently reduced.
- [x] Scenario picker — one click sets the whole database to a named situation
  from the scenario catalogue
  Narrower than specified: `fixtures/scenarios.json` describes *outcomes*
  (sku/warehouse/expected status), not a fabricator recipe, so there is no
  existing mapping from a scenario name to the calls that would produce it.
  The picker reads and displays the catalogue so an operator can jump to a
  named pair; it does not re-fabricate the scenario's data. See
  `submission/dataops/scenarios.py` docstring. Recorded as a known
  simplification, not silently dropped.
- [x] Policy-floor editor (writes `policy_rules`), requiring a stated business
  reason and a `set_by` name — the floor is an audited exception, so an
  unexplained floor is not accepted (A4/D15)
- [x] Live statistics panel: μ, σ, CV, ADI, quadrant, ABC/XYZ class,
  maturity + confidence, service level, safety stock, reorder point, derived
  cover days, current position — recomputed after every edit, so the effect of
  a change is visible immediately
  Live-verified in the browser against AC-003/DEL-01.
- [ ] Freshness-threshold control — **not built.** Flagged as an open
  question in `PHASE_G_PLAN.md` §8 (`config.data_freshness_hours` is
  read from env at process start, so a UI control could only affect the
  running process; deferred rather than half-built).
- [x] Fabrication log, filterable and exportable
  The **persisted** `data_change_log` (DG5), not the in-memory
  `fabricator._LOG` — filterable by table, exportable as JSON.
  Live-verified in the browser.

### G2 — Agent console

- [x] "Run monitor now"
  Wired to `app.run_sweep`; rendered and clicked through in the browser,
  but the sweep itself was **not actually triggered** in this session (it
  fires real LLM calls against every at-risk SKU on the seeded portfolio —
  17+ candidates × 3 calls each — judged too slow/costly for a UI smoke
  check). The button, spinner and result-summary rendering are verified;
  a full live sweep run is not.
- [ ] Sweep progress: **which product is being evaluated right now** — **not
  built.** `run_sweep` runs to completion and returns one `SweepRun`; there
  is no intermediate per-candidate callback to stream from. Only the
  after-the-fact summary and per-candidate `detail` (from `sweep_runs.detail_json`)
  are shown, not live progress.
- [x] Per-candidate outcome as it lands, with each agent's output
  Shown after the fact via the sweep-history `detail` JSON expander, not
  streamed live (see above).
- [ ] Loading / in-progress indicators so the run is legible — a single
  `st.spinner` around the whole sweep, not per-candidate. Narrower than
  the plan's "which product is being evaluated right now."
- [x] Pending approvals queue (gate 1 and gate 2 distinguished)
- [x] Park queue with unblocking actions, each **deep-linking into G1.2's
  data screen** for that exact SKU / warehouse / date range — the park record
  already carries all three
  Deep link carries sku/warehouse_id; date range is not carried in the URL
  (see G1.2 note above) — the operator picks the range on arrival.
- [x] Audit playback per case
  Pre-existing (`_render_timeline` / `read_case_history`), confirmed
  unchanged and still working.
- [x] **The days-of-cover input is gated on maturity (R11), not removed
  outright.** Superseded note: this task previously read "`target_cover_days`
  input **removed entirely**". That is right for an `ESTABLISHED` SKU and
  wrong for a `PROVISIONAL`/`INSUFFICIENT` one, where the derived target is
  the untrustworthy number and a human target is the legitimate exception.
  Concretely:
  - [x] `ESTABLISHED` → no input rendered; `derived_cover_days` is shown as a
    fact, with the statistics that produced it
  - [x] `PROVISIONAL` / `INSUFFICIENT` → one field, days of stock wanted,
    pre-filled with the derived figure and labelled with why it cannot be
    trusted (months of history, observation count, confidence)
    Pre-existing Phase F work (`_render_manual_cover_form`), confirmed still
    correct and live-verified in the browser against SKU-002/MUM-01.
  - [x] Either way, the approval card shows `target_provenance`
    (`derived` vs `human:<name>`) and, when human-set, says plainly that the
    target was set by a person and the history behind it is thin
    Pre-existing Phase F work (`ui_messages.manual_cover_warning`), not
    re-verified word-for-word this session — not re-read this session, so
    left checked on the strength of Entry 023's prior verification rather
    than a fresh one.
- [x] **No screen anywhere offers a demand rate, a target quantity, or an
  order quantity input** — those are computed, always
  True of every screen added this session (data console has no such field
  anywhere); pre-existing agent-console screens unchanged.

**Phase G exit criteria**
- [x] Two apps run on separate ports against the same database
  Live-verified: `submission/ui.py` on 8501, `submission/data_console.py` on
  8502, both against the same seeded `database/inventra.db`.
- [ ] A full demo is possible without touching a terminal — including
  Phase E's park → enter real sales data → re-run → proposal loop, entirely
  from the two screens
  Mechanically wired (deep link, backfill, re-run, resolve-park all present
  and clicked through individually), but **not walked end-to-end in one
  continuous session** against a genuinely thin-data SKU with a real park
  record — the SKU tried in the browser (AC-005) already had full history.
- [x] Every input table is editable from G1 with validation that explains
  itself; every derived table is visibly read-only
- [x] An invalid edit (bad type, broken FK, duplicate `sales_daily` day,
  reversed date range) is refused with a specific, readable reason and leaves
  the row untouched
  Proven by `test_phase_g_data_console.py` (10 of its 14 tests are exactly
  this), and live-verified once in the browser (a bare min-value violation
  on `selling_price`/`unit_volume_m3` before the optional-field fix).
- [x] Backfilling from G1.2 and re-running from G2 produces a proposal whose
  `daily_velocity` demonstrably came from the newly written `sales_daily`
  rows — proving the re-fetch, not a form value, is what fed the arithmetic
  Proven by
  `test_backfilling_the_named_range_then_rerunning_produces_a_proposal_from_the_new_rows`,
  which asserts the post-backfill `sales.window_30_days` numerically matches
  what was written. Not additionally re-walked live in the browser (see the
  demo-loop item above).
- [x] No screen asks for a per-product cover target on an `ESTABLISHED` SKU;
  the one legal input appears only for `PROVISIONAL`/`INSUFFICIENT`, and is
  labelled and audited when used

---

## PHASE H — Upgrade and gap document

Goal: known limits written down, not left as silent holes. Feeds the brief's
required `test_report.md`.

- [ ] UI polish / responsive redesign / non-Streamlit frontend
- [ ] Multi-SKU purchase order consolidation per vendor
- [ ] Quantity-break / price-ladder pricing, and its interaction with the
  MOQ-overshoot penalty (see A6.3) — a genuine break at 200 units may justify an
  overbuy the current penalty discourages
- [ ] Stockout cost beyond lost contribution: SLA penalties, backorder handling,
  churn. `expected_stockout_cost` is a **floor**, and Phase H should say so in
  `test_report.md`
- [ ] Substitution map, so a lost sale on one SKU is valued at the margin
  *difference* rather than the whole contribution
- [ ] Shelf life / expiry, so overbuy is priced as spoilage and not only as
  capital cost
- [ ] Real background scheduler (cron / APScheduler) for sweeps and reminders
- [ ] Supplier confirmation path (so `confirmed_inbound` is written by something)
- [ ] Full seasonality modelling beyond level and trend
- [ ] Lateral transshipment between warehouses
- [ ] `roll_forward` simulator operation if deferred from Phase A
- [ ] Formal test suite restoration (see §Testing posture)
- [ ] Fix the stale `test_phase10_cancel_purchase_request.py` docstring and test
  name (the assertions are correct — see Testing posture below)
- [ ] Fix the `tools/sales.py` window boundary so each window covers N *complete*
  days instead of including today. Keep the divisor as the window length
- [ ] Delete the false cancellation message in `app.py::_print_cancellation`, or
  surface the real `budget_released` value by adding it to `CancellationResult`
- [ ] Make the graph handle threshold-straddling SKUs the way
  `portfolio.scan_portfolio()` already does — evaluate both windows, take the
  worse, or flag genuinely outcome-changing disagreement as ambiguous

---

## Scenario catalogue

Each exists to prove one capability. Covers all 10 brief acceptance scenarios
plus case-flow scenario 11 plus the new autonomous behaviour.

| # | Scenario | Fabricated | Capability proven |
|---|---|---|---|
| 1 | Steady state | Everything healthy | `NO_ACTION`, zero vendor calls, zero LLM spend — the sweep is cheap when nothing is wrong (brief 1) |
| 2 | **Demand ramp** | 60 days ramping 10 → 25/day; position ≈ 5 days cover | Autonomous trigger from a trend nobody pointed at; regime detection |
| 3 | **Dying product** | Declining trend, low cover, EOL lifecycle | Cover *is* low, so a naive system reorders. A correct one recognises decline and declines to buy. Judgment, not arithmetic |
| 4 | Cost vs speed | Cheap-slow and dear-fast, both eligible | Cost-per-day-of-cover ranking + strategist explaining a real trade-off (brief 4). **The cheap-slow vendor's invoice is the larger one** — it buys more units because it is slower — so this also proves the ranking is not comparing invoice totals (D29) |
| 5 | Budget squeeze | 5 candidates, budget covers 3 | Ranked allocation; deferrals named and explained; no post-approval failures (brief 5) |
| 6 | Reliability collapse | Vendor on-time drops below 0.90 | Eligibility filtering + per-vendor rejection detail |
| 7 | Learned preference | Prior human rejection of a vendor with a reason | `agent_memory_signals` influencing the next case on that product |
| 8 | Thin data | New SKU, 3 weeks of history | `NEEDS_INFORMATION` → data-team backfill → re-run succeeds (case-flow 11) |
| 9 | **Lumpy demand** | 40 units once a month, zero most days | Quadrant detection switching the forecasting method; "velocity 1.3" is fiction and the system knows it |
| 10 | Provisional class | 6 weeks of history, decent volume | Confidence-scored provisional class instead of dumping it in C |
| 11 | Class promotion | 14 months crossing the A/B boundary at month 12 | Hysteresis — two confirmations before the service level moves |
| 12 | Stale snapshot | Snapshot aged past threshold | `BLOCKED` with `DATA_STALE` (brief 3) |
| 13 | Facts change mid-pause | Budget drops during the approval pause | Revalidation invalidating a stale approval (brief 7) |
| 14 | Un-emailed PO | Gate 1 approved, gate 2 untouched | Reminder loop including the freshness re-check |
| 15 | Manual thin-data order | Human orders a no-history item | Manual path with provenance on the approval card |
| 16 | **Policy floor too low** | Floor 10, statistics demand 25 | Floor override reconciliation, upward |
| 17 | **Policy floor too high** | Floor 10, statistics demand 5 | Floor override reconciliation, downward; excess cost quantified; EXCEPTION path if the human goes below |
| 18 | Missing request fields | SKU or warehouse absent | `NEEDS_INFORMATION` with one precise question (brief 2) |
| 19 | Invalid model output | Agent omits a required field | One repair attempt then fail closed (brief 6) |
| 20 | Duplicate approval | Same proposal resumed twice | Exactly one purchase request (brief 8) |
| 21 | Human rejection | Approver rejects | Audited, reason stored, no write (brief 9) |
| 22 | Write failure | DB write raises | `WRITE_FAILED`, never claim success (brief 10) |
| 23 | **Measured margin flips the verdict** | Two SKUs, identical vendor options, very different `selling_price` | The stockout cost of a high-margin SKU justifies the faster vendor; the low-margin one does not. Under the flat 25% assumption both get the same answer — so this is the case that shows why A6.1 #1 matters, not just that it is tidier |
| 24 | **Vendor lies by omission** | 93% on-time, but 4 days late whenever it slips; `stock_receipts` proves it | Measured lateness beating the flat 1-day assumption. Wins the comparison on the assumed input, loses on the measured one (A6.5) |
| 25 | **Bulky low-value stock** | Cheap SKU, large `unit_volume_m3`, dear warehouse | Carrying cost as real data, not a % of price. A flat 20%-of-price rate makes bulky cheap goods look free to hold; measured storage cost is what stops a large minimum order winning (A6.1 #2) |
| 26 | **Freight inverts the price ranking** | Cheaper `unit_price`, expensive `freight_flat` on a small order | Landed cost vs ex-works. The comparison is blind to this today (A6.2) |

Lead a demo with **3 (dying product)** and **9 (lumpy demand)** — they are where a
naive implementation visibly fails. Follow with **24 (vendor lies by omission)**:
it is the shortest path to showing why measured data beats a reasonable-sounding
assumption, and it needs one screen.

---

## Brief compliance checklist

Carried forward so autonomy work does not break the graded requirements.

- [ ] 2-4 agents — stays at **3**; the monitor is deterministic
- [ ] Authoritative arithmetic from tools, not the LLM
- [ ] Pydantic-validated critical outputs
- [ ] Max **1** revision cycle
- [ ] Max **2** model attempts per agent
- [ ] Approval is an interrupt, not text classification
- [ ] Approval tied to an exact proposal hash
- [ ] Revalidation immediately before the write
- [ ] Idempotent, transaction-safe write
- [ ] No generic SQL or DB credentials given to agents
- [ ] **No web-search tool** at runtime
- [ ] Audit events carry structured summaries, not private reasoning
- [ ] All 10 required acceptance scenarios reachable and observable
- [ ] Deliverables kept current: architecture diagram, agent charters,
  tool-permission matrix, `design.md`, `test_report.md` with known limits
- [ ] **Noted:** the rubric awards **zero marks for a dashboard.** The two
  Streamlit apps exist for demonstration and operator understanding, not for
  marks. They must not consume time budgeted for Phases A-E.

---

## Testing posture

Agreed explicitly: **green tests are not required right now.**

- [ ] Verify real working paths manually during Phases A-F
- [ ] Formal test restoration deferred to Phase H
- [ ] Existing suite will break by design — several tests assert behaviour this
  plan changes deliberately
- [ ] **Corrected 2026-09-11 (tracker Entry 006).** An earlier draft of this plan
  claimed `test_phase10_cancel_purchase_request.py` and
  `test_phase11_budget_and_reorder_guard.py` contradict each other on budget
  reservation. **They do not.** The phase-10 helper `_insert_request()` writes a
  `purchase_requests` row directly via SQL and omits `committed_budget_month`, so
  nothing was ever reserved for that row and cancelling correctly releases
  nothing — the documented legacy-row path. Phase-11 covers the normal
  `create_purchase_request` path, which does reserve and release. Both are valid.
  Only the phase-10 **docstring** ("create_purchase_request never increments
  committed_amount") and test name are stale:
  - [ ] Fix the phase-10 docstring and rename the test; keep the coverage

---

## Open decisions

Provisional defaults are in place so nothing is blocked. O3 (git) lives in the
tracker, not here.

| # | Question | Provisional default | Why it matters |
|---|---|---|---|
| O1 | When a policy floor **exceeds** the statistical target, should the agent recommend the floor or the statistical figure? | **Recommend the floor.** A floor is usually a commitment, not a preference; an agent that quietly orders less has breached a contract on grounds it is not authorised to weigh. Surface the waste, let a human relax the floor. | Changes the default on every floor-constrained SKU. Config flag either way. |
| O2 | How many SKUs get policy floors? | **3-4 of ~35**, with distinct reasons (SLA, warranty parts, floor-too-low, floor-too-high) | Enough to show the mechanism from both directions without making every case a policy case |
| O4 | Do suppliers invoice for units **ordered** or units **shipped**? | **Ordered** (`vendor_billed_on_units_shipped=False`), which is what the code already assumed. Per-vendor once `vendors.billing_basis` exists (A6.1 #4) | Directly changes the ranking numerator. At a 0.94 fill rate it is worth ~$780 on one 29-unit order — enough to move a verdict. This is a **business fact, not a modelling choice**; it cannot be derived and should not be guessed indefinitely |
| O5 | Is `selling_price` a single list price, or does it need per-warehouse / time-varying pricing? | **Single list price on `products`.** Enough for a margin, and one column instead of a table | If real pricing varies by region or promotion, a single figure makes the contribution number confidently wrong rather than honestly approximate — worse than the current caveat. Ask before seeding 35 SKUs on the simple model |

---

## Dependency order

```
A (data foundation)
├── A6 (economics inputs schema)
│   └── B10 (measured economics functions) ── parallel to B1-B9
└── B (statistics engine)
    ├── C  (autonomous sweep)
    │   └── C2 (floor reconciliation)
    │       └── D (two-gate approval)
    ├── E  (insufficient-data loop)   ── can run parallel to C
    └── F  (manual order path)        ── needs B, independent of C
                                          │
                              G (two UIs) ─┘
                                          │
                              H (gap doc) ─┘
```

A and B carry the substance. C is where the system becomes autonomous.
Everything after is plumbing and surface. Do not start at C.

**A6 + B10 are the one branch that can ship on their own.** They touch no graph
node, no agent count and no interrupt — `evaluate_options` gains an optional
argument and falls back to today's config values when it is absent. So they can
land in four independent slices (margin, carrying cost, lateness, billing basis)
before the sweep exists, each one deleting a caveat from the approval card. If the
schedule slips, this is the branch that still produces visible value.
