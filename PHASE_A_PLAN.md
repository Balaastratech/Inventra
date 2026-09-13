# PHASE_A_PLAN.md

Detailed execution plan for **Phase A — Data foundation**, expanding
`AUTONOMOUS_PLAN.md`'s Phase A section into concrete steps, file-by-file diffs,
call flows, and an execution order. This is a **planning document only**.
Nothing described here has been built. See `AUTONOMOUS_TRACKER.md` for what
has actually shipped so far (as of Entry 007: nothing in Phases A-H).

Companion to, not a replacement for, `AUTONOMOUS_PLAN.md` §Phase A. Read that
first for the *why*; this is the *how*, *in what order*, and *against what
exact code*.

---

## 0. What Phase A actually has to produce

Two deliverables, both databases-and-generators, zero graph/agent changes:

1. **A schema** that can hold: real margin, real carrying cost, real lateness
   history, per-SKU policy floors, and the classification record Phase B will
   write into.
2. **A fabricator + generator** that can populate that schema with 24 months
   of *coherent* daily history across ~35 SKUs and several warehouses, on
   demand, reproducibly — replacing today's 8-product, 1-warehouse,
   hand-written `seed.py`.

Phase A does **not** touch `submission/graph/`, `submission/agents/`, or the
Streamlit UI, except for the one already-shipped, backward-compatible optional
argument on `evaluate_options` that A6/B10 plugs into later (Entry 007 already
did the ranking-metric half of that; A6/B10 do the data half). Phase A is
pure `database/` + new `tools/` read functions + `fixtures/`.

---

## 1. Ground truth: what exists today (verified by reading the code, not the plan's prior description)

This corrects a few places where `AUTONOMOUS_PLAN.md` describes the *target*
state in a way that could be misread as the *current* state.

| Plan calls it | Actually named / actually exists as | File |
|---|---|---|
| `warehouses` table | **Does not exist.** `warehouse_id` is a bare `TEXT` column repeated on `inventory_snapshots`, `sales_daily`, `monthly_budgets`, `purchase_requests`, with no FK anywhere. `submission/portfolio.py::list_warehouses()` derives the list via `SELECT DISTINCT warehouse_id FROM inventory_snapshots` and says so in a comment. | `database/schema.sql`, `submission/portfolio.py` L126-134 |
| `vendor_performance` table | **Does not exist as a table.** `tools/vendors.py::get_vendor_performance()` computes it live every call: `reliability = avg(on_time_rate, fill_rate, quality_score)`, `eligible = reliability >= 0.90`, straight from the `vendors` table's three rate columns. | `tools/vendors.py` L128-179 |
| `budgets` table | Named **`monthly_budgets`** | `database/schema.sql` L96-110 |
| "3-4 warehouses" (A2) | **1 warehouse today** (`DEL-01`), hardcoded on every row in `seed.py` | `database/seed.py` |
| "~35 SKUs" (A2) | **8 products seeded** (`AC-001..006`, plus 2 orphaned fixtures `REF-001`, `TV-001` with no inventory/sales/offers at all) | `database/seed.py` |
| vendor_offers has no warehouse scoping | Confirmed — offers are SKU-only, no `warehouse_id` column. Already called out in `test_phase9_agent_memory.py`. | `database/schema.sql` L75-90 |
| "five caveats" to retire (A1) | Confirmed by reading `economics.py` directly: `assumed_gross_margin_rate`, `assumed_annual_carrying_rate`, `assumed_late_days_when_late`, `vendor_billed_on_units_shipped` are each read once and surfaced twice — once as an `OptionsEconomics`/`OptionEconomics` field via `as_evidence()`, once as a caveat string. That's 4 assumptions, but the plan's "five" counts caveat *strings*, not fields — worth reconciling with a grep of the actual `caveats.append(...)` calls before A6 work starts, since the plan text and the code may disagree by one. | `submission/graph/economics.py` (`evaluate_options`, ~L388-676) |
| `tools/sales.py` window bug | **Already fixed**, per the module's own comment (L46-52): it now uses "last N complete calendar days, ending yesterday", not "including today". Tracker Entry 006 diagnosed this correctly and it appears to already be live in the code, not just documented as a fix. **Re-verify this at A2 time** — if it's fixed, Phase B's velocity functions can reuse it as-is; if a future edit reverted it, catch that before B1. | `tools/sales.py` L46-90 |
| `policy.md`-based floors | Today there is **no** `policy_rules` table. `tools/policy.py::get_policy_guidance()` reads flat markdown from `policy.md`. A4 adds a *parallel* structured table; it does not replace the markdown file (the markdown documents policy *reasoning*, the table holds policy *floors* — see A4 below). | `tools/policy.py`, `policy.md` |
| `build_vendor_options`'s own sizing | **Confirmed stale/superseded**: `tools/vendors.py::build_vendor_options()` still sizes orders with `max(offer.moq, int(available_units * 0.5))` — a naive formula. The correct sizing (`economics.required_quantity` / `size_order_quantity`) lives downstream in `graph/nodes.py::build_options()`, which re-derives quantity after the fact. A2/A3 fabricator work must not accidentally start trusting the tool's own quantity field. | `tools/vendors.py` L215-244 vs `submission/graph/economics.py` L155-230 |

**Net implication for sequencing:** A1 (schema) is a bigger lift than the plan's
checklist implies, because `warehouses` and `vendor_performance` don't just need
new *columns* (which `migrate.py`'s additive-column mechanism handles) — `warehouses`
is a **new table**, which `migrate.py` in its current form cannot create (it only
does `ALTER TABLE ADD COLUMN` on tables that already exist; see §2 below).

---

## 2. Migration mechanics — the one real constraint on sequencing

`database/migrate.py` today is a single list, `_ADDITIVE_COLUMNS`, of
`(table, column, coltype)` tuples, applied idempotently via
`PRAGMA table_info` + conditional `ALTER TABLE ... ADD COLUMN`. It explicitly
**skips with a warning** if the table itself doesn't exist (L52-54) — it was
designed for column-only changes to an already-live database, and says so in
its own docstring ("Columns only; nothing here drops or rewrites data").

Phase A needs two categories of change, and they need **two different
mechanisms**:

1. **New columns on existing tables** (`products.selling_price`,
   `products.lifecycle`, `products.unit_volume_m3`, `vendors.billing_basis`,
   `vendor_offers.freight_flat`, `vendor_offers.freight_per_unit`,
   `vendors.payment_terms_days`) → append tuples to `_ADDITIVE_COLUMNS`, exactly
   the existing pattern. Zero new mechanism needed.
2. **New tables** (`warehouses`, `stock_receipts`, `sku_policy`, `policy_rules`,
   `parked_items`, `carrying_cost_inputs`) → these must be added to
   `schema.sql` as `CREATE TABLE IF NOT EXISTS` (matching every existing table's
   style), **and** `migrate.py` needs a new, small `_ADDITIVE_TABLES` step —
   a list of `(table_name, create_statement)` executed with `CREATE TABLE IF
   NOT EXISTS` against a live database, run before the column step. This is a
   ~15-line addition to `migrate.py`, not a redesign: idempotent by
   construction (`IF NOT EXISTS`), so it's safe to run on both `seed.py`'s
   fresh databases and a hypothetical live one.

`seed.py::init_db()` deletes the file and re-runs `schema.sql` wholesale, so it
never needs `migrate.py` — schema.sql alone is sufficient for the seeded demo
database. `migrate.py` matters only for a database someone doesn't want to
throw away. Phase A should still update both, since the plan explicitly says
"every addition is additive and idempotent" and a grader or later session may
run against a live db.

**Sequencing rule this produces:** schema.sql changes (A1) must land *before*
`seed.py` can be rewritten (A2/A3), and `migrate.py`'s new-table step must land
in the same commit as the new tables so the two files never disagree about
what exists.

---

## 3. Task-by-task plan, in build order

### Step 1 — `database/schema.sql`: add tables and columns (A1)

Additive only; no existing table's existing column changes type or is
dropped. In this order (children after parents, for FK-mindedness even though
SQLite doesn't enforce FKs by default here):

1. **New `warehouses` table** — `warehouse_id TEXT PRIMARY KEY`, `name TEXT`,
   `storage_cost_per_m3_month REAL`. Backfilled from the existing distinct
   `warehouse_id` values already in use (`DEL-01` today, plus whatever A2's
   generator adds). `submission/portfolio.py::list_warehouses()` should be
   left alone in Phase A (it still works, reading distinct IDs) — swapping it
   to read the new table is a Phase A **nice-to-have**, not a blocker, and
   changing it touches `submission/`, which Phase A is scoped to avoid unless
   necessary. Flag it for Phase B/C instead.
2. **`products` — 3 new columns**: `selling_price REAL`, `lifecycle TEXT`,
   `unit_volume_m3 REAL`. Nullable (existing 8 products get backfilled by A2's
   updated seed, not by a migration default).
3. **`vendors` — 2 new columns**: `billing_basis TEXT` (`ORDERED|SHIPPED`),
   `payment_terms_days INTEGER` (A6.2).
4. **`vendor_offers` — 2 new columns**: `freight_flat REAL`,
   `freight_per_unit REAL`.
5. **New `stock_receipts` table** — as specified in the plan: `receipt_id PK`,
   `request_id`, `sku`, `warehouse_id`, `vendor_id`, `quantity_ordered`,
   `quantity_received`, `ordered_at`, `promised_at`, `received_at`,
   `lead_time_days_actual`. No FK enforcement needed beyond matching the
   existing style (`FOREIGN KEY (sku) REFERENCES products(sku)`, same as
   `sales_daily`).
6. **New `sku_policy` table** — the classification record. This is a **Phase B
   consumer**, but the table itself is schema, so it belongs in A1 per the
   plan's own listing. One row per `(sku, warehouse_id, as_of_date)`; no
   `UNIQUE` constraint stated in the plan text, but should have one — add
   `UNIQUE(sku, warehouse_id, as_of_date)` so Phase B's monthly recompute is
   naturally idempotent (re-running a month's classification overwrites via
   `INSERT ... ON CONFLICT` rather than duplicating rows). **This is a plan
   gap worth flagging to the user before B lands**, not something to silently
   decide.
7. **New `policy_rules` table** — `rule_id PK`, `sku`, `warehouse_id`,
   `min_units`, `min_cover_days`, `reason`, `source`, `set_by`,
   `effective_from`, `effective_to`, `active`.
8. **New `parked_items` table** — full shape per plan §C4 (built now since
   it's schema, populated starting Phase C).
9. **New `carrying_cost_inputs` table** — `cost_of_capital_annual_rate`,
   `insurance_annual_rate`, `shrinkage_annual_rate`, `effective_from`,
   `set_by`, `note`. No `warehouse_id` — company-level, as the plan states.

Every `CREATE TABLE` uses `IF NOT EXISTS`, matching the file's existing
convention exactly (every current table already does this).

### Step 2 — `database/migrate.py`: teach it about new tables

Add `_ADDITIVE_TABLES: list[tuple[str, str]]` (table name → its
`CREATE TABLE IF NOT EXISTS ...` statement, copy-pasted from schema.sql so
the two never drift silently — or better, import the statements from a shared
constant so there is only one source of truth; decide which when writing the
code, not now). `apply_migrations()` runs the table step first, then the
existing column step, in one transaction. Append the 7 new columns from step 1
to `_ADDITIVE_COLUMNS`.

### Step 3 — `domain/tool_models.py`: new Pydantic shapes (A1 support)

No graph changes yet, but the new tables need read-tool return shapes before
any tool function can be written cleanly, following the existing
`evidence_id` / `retrieved_at` / `error: Optional[ErrorCode]` convention every
other model uses:

- `StockReceipt` (mirrors one `stock_receipts` row)
- `LatenessDistribution` (`vendor_id`, `n_observations`, `on_time_rate_measured`,
  `mean_late_days`, `p50_late_days`, `p90_late_days`, `evidence_id`) — this is
  what B10's `lateness_distribution()` returns; defining it now means A6.5's
  fabricator helper and any A-phase smoke test have something to construct
  against.
- `Warehouse` (`warehouse_id`, `name`, `storage_cost_per_m3_month`)
- `PolicyFloor` (mirrors one `policy_rules` row) — needed by A4

These are **data shapes only** — no `evaluate_options` change in Phase A. B10
is what wires them into the economics module; Phase A just makes sure the
models exist so B10 isn't also inventing schema-adjacent Pydantic models
under time pressure.

### Step 4 — new tool module: `tools/warehouses.py` (thin, matches existing style)

- `get_warehouse(warehouse_id) -> Warehouse | None`
- `list_warehouses() -> list[Warehouse]` — reads the new table directly.
  `submission/portfolio.py` keeps its own derivation for now (see step 1); this
  is the tool other Phase A/B code should prefer once the table exists.

### Step 5 — new tool module: `tools/receipts.py`

- `get_lateness_distribution(vendor_id, sku=None, min_observations=5) ->
  LatenessDistribution | None` — computed **over late deliveries only**
  (`received_at > promised_at`), per the plan's explicit instruction not to
  blend late and on-time deliveries into one mean. Returns `None` below the
  observation floor so B10/A6 can apply its per-figure fallback.
- `record_receipt(request_id, promised_at, received_at, quantity_received) ->
  StockReceipt` — a **write** tool, narrow and purpose-built (matches
  `tools/memory.py::record_signal`'s pattern: never LLM-callable, best-effort
  where appropriate). This doubles as A6.5's `add_receipt(...)` fabricator
  helper — no need to build it twice.

Both follow the existing per-module `_get_db_connection()` copy-paste
convention (every tool module in this codebase repeats this helper rather than
sharing one — Phase A should match that, not "fix" it; a shared connection
helper is an unrelated refactor and out of scope here).

### Step 6 — `tools/policy_floors.py` (A4)

- `get_active_policy_floor(sku, warehouse_id, as_of=None) -> PolicyFloor |
  None` — the higher of `min_units` and `min_cover_days`-converted-to-units at
  current velocity is **not** computed here (that needs `daily_velocity`,
  which this tool doesn't have) — this tool returns the raw floor row(s);
  Phase B/C2's `fetch_budget_and_policy` node does the unit conversion once
  velocity is available. Keeps this tool a pure single-table read, matching
  the "narrow, purpose-built" rule the codebase already follows for
  `tools/memory.py`.
- `set_policy_floor(...)` — write tool, records `set_by` and `reason` always
  required (never optional — this is what makes D15's "stated business
  reason" enforceable in code, not just in convention).

### Step 7 — the fabricator: `fixtures/fabricator.py` (A3)

New module, not a rewrite of `seed.py` in place — `seed.py` becomes a thin
caller of this module (see step 8). Functions, each a thin wrapper over
direct SQL writes against the tables from step 1 (fabricator code is allowed
to use raw SQL — it is not an agent-facing tool, it is test/demo
infrastructure, same tier as `database/seed.py` today):

- `fabricate_history(sku, warehouse_id, days, profile, conn=None)` — one
  `sales_daily` row per day, backdated, ending **yesterday** (never today —
  matches `tools/sales.py`'s own boundary logic, so a freshly fabricated SKU
  is immediately readable without an off-by-one surprise). `profile` is one
  of the 9 named personalities from A2 (steady, trending-up, trending-down,
  seasonal, promo-spiky, intermittent, lumpy, brand-new, dead/EOL) —
  implemented as a small strategy table of parameter generators (base level,
  trend slope, weekday multiplier, annual seasonal amplitude, spike windows,
  noise σ, zero-probability), not a hardcoded per-SKU literal list like
  today's `seed.py`.
- `set_position(sku, warehouse_id, on_hand, reserved, confirmed_inbound,
  conn=None)` — one `inventory_snapshots` row at `utcnow()`.
- `set_cover_days(sku, warehouse_id, days, conn=None)` — reads current
  velocity (via `tools/sales.py::get_sales_velocity`, reusing the real
  production function rather than re-deriving velocity in fabricator code —
  this is the one place the fabricator should call a real tool instead of raw
  SQL, so the "N days of cover" it writes matches what the system will itself
  compute), then calls `set_position`.
- `age_snapshot(sku, warehouse_id, hours, conn=None)` — backdates the latest
  `captured_at`.
- `expire_offer(offer_id, conn=None)` / `set_vendor_reliability(vendor_id,
  on_time_rate=None, fill_rate=None, quality_score=None, conn=None)`.
- `set_budget(warehouse_id, month, amount, spent, committed, conn=None)`.
- `set_selling_price(sku, price, conn=None)`, `set_carrying_inputs(...)`,
  `set_storage_cost(warehouse_id, rate, conn=None)`,
  `set_billing_basis(vendor_id, basis, conn=None)`,
  `set_freight(offer_id, flat, per_unit, conn=None)` — the A6.5 fabricator
  helpers, grouped here rather than in a separate file since they're the same
  kind of single-row mutation as everything else in this module.
- `add_receipt(...)` — delegates to `tools/receipts.py::record_receipt`
  (per step 5, not duplicated).
- Guard: every write in this module goes through one internal
  `_insert_or_raise(...)` helper that surfaces a `sqlite3.IntegrityError`
  from the `UNIQUE(sale_date, sku, warehouse_id)` constraint as a clear
  `ValueError` naming the exact duplicate — turning R7 from "the DB happens to
  reject it" into "the fabricator explains why it refused," per the plan's
  explicit ask.
- Every function appends one row to an in-memory list (or a `fabrication_log`
  table — **decide table-vs-in-process-list when writing the code**; a table
  survives past the Python process and can be inspected after the fact in the
  Streamlit console G1 will build later, which argues for a table even though
  Phase A doesn't build G1 yet) describing what was written, so a demo run is
  explainable afterward per the plan's explicit requirement.
- `roll_forward(days, conn=None)` — **explicitly deferred**, exactly as the
  plan marks it "optional, lower priority." Not attempted in Phase A.

### Step 8 — rewrite `database/seed.py` to call the fabricator (A2)

`seed.py` keeps its two responsibilities — `init_db()` (delete + recreate from
schema.sql, unchanged) and `seed_data()` — but `seed_data()`'s body changes
from ~250 lines of hand-written per-SKU literals to a loop over a **scenario
table**: for each of ~35 SKUs, look up (product metadata, warehouse
assignment, demand profile, vendor mix, policy floor if any) and call the
Step 7 fabricator functions. This is where `fixtures/scenarios.json` earns its
new role: rather than being pure documentation of 12 SKUs' intended stories,
it becomes the literal input the seed loop reads, extended to name a
`demand_profile` and `warehouse_id` per entry, plus new entries for scenarios
23-26 (measured margin, vendor lying by omission, bulky low-value stock,
freight inversion) and the two policy-floor scenarios (16, 17).

Concretely, `seed_data()` becomes:

```
for warehouse in WAREHOUSES:            # 3-4, from step 1's new table
    fabricator.upsert_warehouse(warehouse)
for vendor in VENDORS:                  # existing 5 kept, extended with
    ...vendor row with billing_basis, payment_terms_days...
for sku_spec in SKU_CATALOGUE:          # ~35 entries, replaces AC-00x literals
    fabricator.fabricate_history(sku_spec.sku, sku_spec.warehouse,
                                  days=730, profile=sku_spec.profile)
    fabricator.set_position(...)        # or set_cover_days(...) per spec
    for offer in sku_spec.vendor_offers:
        ...write offer with freight, and one vendor whose lateness truth
           diverges from its on_time_rate (scenario 24)...
    fabricator.add_receipt(...)         # backfilled stock_receipts history
for floor_spec in POLICY_FLOOR_CATALOGUE:  # 3-4, per A4/O2
    fabricator.set_policy_floor(...)
fabricator.set_budget(...)              # every warehouse, current + prior month
```

Deterministic seeding: a fixed RNG seed (e.g. `random.seed(42)` once at the
top of `seed_data()`) so the ~35-SKU generator produces the same history on
every run — required for the plan's "reproducible" exit criterion and for the
`SELECT ... HAVING count(*) > 1` uniqueness check to be a meaningful, repeatable
verification rather than a one-off.

### Step 9 — `database/reset_db.py` / `submission/tests/reset_db.py` — check for breakage

Both exist and are used by the test suite to get a known starting point
before each test module. **Read them again at implementation time** — if
either hardcodes assumptions about the current 8-SKU/1-warehouse seed (row
counts, specific SKU names used as test fixtures like `AC-001`/`AC-003`),
Phase A's larger seed will break them. This is exactly the kind of "existing
tests will break by design" the plan already accepts (D26) — but it's worth
distinguishing "breaks because the design changed" from "breaks because
Phase A accidentally renamed a SKU the whole test suite keys off of." Keep
`AC-001` through `AC-006` **as-named, as-storied** entries inside the new
35-SKU catalogue (just richer — real margin, real lifecycle, etc.) rather
than renaming them, so the 140 passing tests and the existing scenario-driven
demo flow (`AC-003 DEL-01` is the one reliable demo path per Entry 005/006)
keep working unmodified through Phase A.

---

## 4. A6 — the economics-input schema slice, mapped to what step above it belongs to

A6 is not a separate build track — it's threaded through steps 1, 3, 5, 7, 8
above. Restated here as a single checklist so nothing gets lost:

| A6 item | Lands in step | New code | Notes |
|---|---|---|---|
| `products.selling_price` | 1 | schema column | scenario 23 needs 2 SKUs with very different values |
| `warehouses.storage_cost_per_m3_month` + `products.unit_volume_m3` | 1 | schema columns + new table | scenario 25 needs one bulky-cheap SKU + one dear warehouse |
| `vendors.billing_basis` | 1 | schema column | O4 default: `ORDERED` |
| `vendor_offers.freight_flat` / `freight_per_unit` | 1 | schema columns | scenario 26 needs one small order where freight inverts ranking |
| `vendors.payment_terms_days` | 1 | schema column | A6.2, not in the original A1 list — added here per plan §A6.2 |
| `stock_receipts` table | 1 | new table | scenario 24's vendor needs receipts showing 93% on-time but 4-day slips |
| `carrying_cost_inputs` table | 1 | new table | company-level, one row is enough for Phase A |
| `LatenessDistribution`, `StockReceipt`, `Warehouse`, `PolicyFloor` models | 3 | new Pydantic classes | consumed by B10 later, defined now |
| `get_lateness_distribution`, `record_receipt` | 5 | new tool functions | pure reads/writes, no LLM exposure |
| fabricator A6.5 helpers | 7 | new fabricator functions | `set_selling_price`, `set_carrying_inputs`, `set_storage_cost`, `add_receipt`, `set_billing_basis`, `set_freight` |
| scenarios 23-26 in the seed catalogue | 8 | new `SKU_CATALOGUE` entries | the actual demonstrable proof each schema addition works |

**What A6 does *not* touch in Phase A:** `evaluate_options`, `config.py`'s
`assumed_*` defaults, `OptionEconomics`/`OptionsEconomics`, any `*_basis` flag,
`ui._approval_notes`. Those are **B10 + the A6.4 integration**, explicitly
Phase B work. Phase A only makes the *data* real; Phase B is what makes
`evaluate_options` prefer it over the config fallback. Building B10's
functions during Phase A is fine if capacity allows (the plan already notes
B10 "depends on nothing in B1-B9... can be built in parallel"), but it is not
a Phase A exit criterion and should not block Phase A sign-off.

---

## 5. Flow diagrams

### 5.1 Migration flow (steps 1-2)

```
schema.sql (source of truth, CREATE TABLE IF NOT EXISTS x N)
        │
        ├── seed.py::init_db()  ──── DELETE inventra.db, executescript(schema.sql)
        │                             (test path / fresh demo path — unaffected by migrate.py)
        │
        └── migrate.py::apply_migrations(db_path)  ──── for a DB you don't want to delete
                │
                ├── 1. _ADDITIVE_TABLES:  CREATE TABLE IF NOT EXISTS  (new in Phase A)
                │        warehouses, stock_receipts, sku_policy,
                │        policy_rules, parked_items, carrying_cost_inputs
                │
                └── 2. _ADDITIVE_COLUMNS: PRAGMA table_info → ALTER TABLE ADD COLUMN
                         (existing mechanism, 7 new tuples appended)
```

### 5.2 Fabrication flow (steps 7-8) — replacing today's hand-written seed

```
fixtures/scenarios.json (extended: +profile, +warehouse_id, +23-26, +floors)
        │
        ▼
database/seed.py :: seed_data()
        │
        ├── for each warehouse  → fabricator.upsert_warehouse(...)
        ├── for each vendor     → INSERT vendors (+billing_basis, +payment_terms_days)
        │
        ├── for each SKU spec  ──────────────────────────────────────────────┐
        │     fixtures/fabricator.py                                        │
        │       fabricate_history(sku, wh, 730d, profile) → sales_daily × N  │
        │       set_position(...) / set_cover_days(...)  → inventory_snapshots
        │       INSERT vendor_offers (+freight_flat/per_unit)                │
        │       add_receipt(...) × M                     → stock_receipts   │
        │     each call appends to the fabrication log ───────────────────┘
        │
        ├── for each policy floor spec → fabricator.set_policy_floor(...)
        └── for each warehouse/month   → fabricator.set_budget(...)
                │
                ▼
        database/inventra.db  (~35 SKUs × 3-4 warehouses × 24mo history,
                                reproducible under a fixed RNG seed)
```

### 5.3 Where Phase A's output is first *read* (confirms Phase A is self-contained)

```
inventra.db  ──▶  tools/sales.py::get_sales_velocity           (existing, unchanged)
             ──▶  tools/inventory.py::get_stock_position        (existing, unchanged)
             ──▶  tools/vendors.py::list_vendor_offers / get_vendor_performance (existing, unchanged)
             ──▶  tools/warehouses.py::get_warehouse / list_warehouses   (NEW, step 4)
             ──▶  tools/receipts.py::get_lateness_distribution           (NEW, step 5)
             ──▶  tools/policy_floors.py::get_active_policy_floor        (NEW, step 6)
```

None of the *existing* read tools change signature or behavior in Phase A —
they simply have more/better rows to read (real margin, real warehouses,
more SKUs). The three new tool modules are additive, unused by the existing
graph until Phase B/C wires them in. **This is what makes Phase A safe to
ship on its own**: the 140 currently-passing tests should still pass
unmodified after Phase A, because nothing they exercise changed shape — only
row counts and new, not-yet-called functions were added. Confirming this with
a full test run is Phase A's own verification step (§7 below), not deferred to
Phase B.

---

## 6. Execution order (session-sized chunks)

Suggested order, each a plausible single agent session:

1. **Schema + migrate** (steps 1-2). Verify: fresh `python database/seed.py`
   still runs against the *old* seed body (schema-only change, seed untouched
   yet) — proves the new tables/columns don't break anything before any seed
   rewrite begins. Run the 140-test suite once here as a checkpoint.
2. **Domain models + new tool modules** (steps 3-6). Verify: unit-testable in
   isolation against the schema from step 1, with a few rows inserted by hand
   or a small throwaway script (no seed rewrite needed yet).
3. **Fabricator module** (step 7), built and unit-tested against a scratch
   database, independent of `seed.py`.
4. **Seed rewrite** (step 8) — the biggest single step, because it's where
   the ~35-SKU catalogue, 9 demand profiles, and scenarios 16/17/23-26 all get
   authored concretely. Likely 2 sessions on its own: one for the profile
   generator + catalogue structure, one for authoring the actual per-SKU
   entries and tuning them until each named scenario is demonstrably true
   (e.g. actually running `get_sales_velocity` against the fabricated lumpy
   SKU and confirming ADI/CV² land in the LUMPY quadrant once B1 exists to
   check it — Phase A can at least confirm the *raw shape* of the data by eye
   / simple pandas check, without B1's classifier existing yet).
5. **Regression check** (step 9 + full exit criteria, §7) — confirm
   `AC-001`..`AC-006` still tell their original stories, confirm the 140 tests
   still pass, confirm the new exit-criteria queries all return the expected
   answer.

Do not parallelize steps 1 and 4 — everything after step 1 depends on the
final column/table shape being settled, and schema changes are the most
expensive thing to redo mid-stream.

---

## 7. Phase A exit criteria — concretely checkable

Restating the plan's exit criteria as literal checks, so "done" is not a
judgment call:

1. `python database/seed.py` (or its future equivalent) completes without
   error and is **re-runnable** (delete + recreate) with **identical** row
   contents given the same RNG seed — verify by hashing a canonical dump of
   `sales_daily` across two consecutive runs.
2. Every scenario 1-26 in the catalogue is reachable by name — verify by a
   small script that, for each scenario id in the (extended) `scenarios.json`,
   asserts the specific fact the scenario needs (e.g. scenario 24: query
   `stock_receipts` for that vendor and confirm `mean_late_days > 1` while
   `vendors.on_time_rate >= 0.93`).
3. `SELECT count(*) FROM sales_daily GROUP BY sale_date, sku, warehouse_id
   HAVING count(*) > 1` returns zero rows.
4. `SELECT count(*) FROM products WHERE selling_price IS NULL OR
   unit_volume_m3 IS NULL` returns zero for the seeded set (every seeded
   product has both).
5. `SELECT count(*) FROM warehouses WHERE storage_cost_per_m3_month IS NULL`
   returns zero.
6. `SELECT count(*) FROM vendors WHERE billing_basis IS NULL` returns zero.
7. At least one SKU/warehouse/vendor combination has **every** A6.1 input
   measured (so a later Phase B/A6.4 case reaches the approval card with no
   assumption sentence at all) — verify by construction (know which SKU this
   is) rather than by querying for it after the fact.
8. At least one SKU has a **named single missing fact** (e.g. a brand-new
   vendor offer with zero `stock_receipts` rows) — proving the eventual A6
   per-figure fallback has something real to fall back for.
9. `python -m pytest submission/tests -q` still reports the same pass count
   as before Phase A (140, per Entry 007) or higher — never lower, and no
   newly-failing test should trace back to a Phase A change (if one does,
   that's a real regression, not an accepted design-drift failure per D26,
   because Phase A is explicitly scoped to not touch graph/agent behavior).

---

## 8. Explicitly out of scope for Phase A (do not build these here)

- Anything in `submission/graph/`, `submission/agents/`, `submission/ui.py` —
  including B10's `load_cost_inputs()` / `EconomicsInputs` wiring into
  `evaluate_options`. Phase A produces the data B10 will read; it does not
  read it itself.
- The classifier (`classify(sku, warehouse, as_of=date)`) and anything that
  writes into `sku_policy` beyond the table existing. That's Phase B (B1-B9),
  even though `sku_policy` the *table* is built here.
- `roll_forward(days)` — explicitly deferred per the plan.
- Rewriting `submission/portfolio.py::list_warehouses()` to use the new
  `warehouses` table (nice-to-have, not required — see step 1).
- Any UI (`G1`'s simulator console) — Phase A produces functions the console
  will eventually call; it does not build the console.
- Fixing the four Entry-006/Entry-005 documented-but-unfixed issues
  (`app.py::_print_cancellation`'s false string, the phase-10 test docstring)
  — unrelated to Phase A, tracked separately, cheap enough to do anytime.

---

## 9. Open questions this plan surfaces (in addition to O1-O5, already tracked)

- **New — `sku_policy` uniqueness.** The plan specifies the table's columns
  but not a uniqueness constraint. Recommend
  `UNIQUE(sku, warehouse_id, as_of_date)` (see step 1, item 6). Flagging
  rather than silently deciding, since Phase B's monthly-recompute logic
  depends on this being right.
- **New — "five caveats" vs four assumption fields.** `AUTONOMOUS_PLAN.md`
  §A1 says "retire the five caveats" but the code review here found exactly
  four assumption *fields* on `OptionsEconomics`. Worth a literal grep of
  `caveats.append(` in `economics.py` before A6.4 (Phase B) work starts, to
  settle whether it's five caveat *strings* (some assumption might emit two
  sentences) or the plan's count is off by one. Does not block Phase A.
- **Confirm, don't assume — `tools/sales.py`'s window-boundary bug.** Read
  as already fixed in the current code (§1 table). Re-confirm at the start of
  step 7/8, since fabricator work will be the first thing to depend heavily on
  correct velocity math, and a silent revert would quietly corrupt every
  demand-profile scenario's numbers without an obvious symptom.
