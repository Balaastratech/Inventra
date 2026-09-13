# PHASE_B_PLAN.md

Detailed, end-to-end execution plan for **Phase B — Statistics and policy
engine**, expanding `AUTONOMOUS_PLAN.md`'s §Phase B (B1-B10) into concrete
files, function signatures, formulas, sequencing, and tests — against the
Phase A codebase as it actually exists today (verified by direct reads and
one context-gatherer sweep this session; see §1).

**This is a planning document. Nothing described here has been built.**
Companion to `AUTONOMOUS_PLAN.md` (the *why*) and `PHASE_A_PLAN.md` (the
same kind of document, one phase earlier — read that first if you haven't,
since it explains the fabricator/tool conventions Phase B inherits).

---

## 0. What Phase B actually has to produce

Per `AUTONOMOUS_PLAN.md`: "pure, deterministic functions that turn history
into a reorder point and a service level. No LLM anywhere in this phase."
Concretely, three deliverables:

1. **A statistics/classification engine** — pure functions, each independently
   unit-testable, that take raw sales history and return demand statistics,
   quadrant, ABC/XYZ class, maturity/confidence, safety stock, reorder point,
   and derived cover days.
2. **A `classify()` orchestrator** that assembles the above into one
   `sku_policy` row per `(sku, warehouse_id, as_of_date)`, reading real
   Phase-A data (not config assumptions) wherever Phase A supplied it.
3. **The B10 "measured economics" functions** — margin, carrying rate,
   lateness distribution, landed cost — wired into `economics.py` as an
   *optional* input, so `evaluate_options` prefers measured data over
   `config.assumed_*` on a per-figure basis, exactly as `AUTONOMOUS_PLAN.md`
   §A6.4 specifies.

Phase B does **not** build the autonomous sweep (Phase C), does not touch
`submission/agents/`, and does not add a new case-graph node that runs on
every case. The one deliberate, narrow exception — a real defect in a tool
the live graph already calls — is called out explicitly in §4 (B2) with its
exact blast radius, because it is the one place this phase's work reaches
into code Phase C and the existing graph depend on.

---

## 1. Ground truth: the codebase Phase B actually builds on

Verified this session by direct reads (`database/schema.sql`,
`submission/state/state.py`, `submission/graph/nodes.py` fetch_evidence
through compute_risk, `requirements.txt`) plus a context-gatherer sweep
of `database/migrate.py`, `database/seed.py`, `fixtures/fabricator.py`,
the three Phase-A tool modules, `domain/tool_models.py`,
`tools/sales.py`, `tools/inventory.py`, the rest of `submission/graph/nodes.py`,
`submission/graph/economics.py`'s remainder, `submission/portfolio.py`, the
Phase A TDD doc, and the test directory — cross-checked against my own
direct reads where they overlap.

| Fact | Detail |
|---|---|
| Phase A schema is live | `sku_policy` table exists with `UNIQUE(sku, warehouse_id, as_of_date)` (the open question from `PHASE_A_PLAN.md` §9 was resolved — it's in the schema) but **is never written to by any code path**. Confirmed empty after seeding. |
| Seed is 35 SKUs / 4 warehouses | `AC-001..006` (legacy, unchanged semantics) + `SKU-001..029` cycling 8 profiles (`steady, trending-up, trending-down, seasonal, promo-spiky, intermittent, lumpy, dead-eol`) across `DEL-01, MUM-01, BLR-01, CHE-01`. |
| `stock_receipts` is seeded | 12 receipts/SKU, alternating V-BALANCED/V-CHEAP, with periodic 4-day-late V-BALANCED deliveries — real data for B8's σL and B10's lateness distribution to read, no fabrication needed at Phase B time. |
| `carrying_cost_inputs` is seeded | One row via `fabricator.set_carrying_inputs(.12, .03, .02, ...)`. |
| `policy_rules` is seeded | 4 rows (matches A4/O2's "3-4 SKUs"). |
| **No statistics/classification code exists anywhere** | No ABC/XYZ classifier, no quadrant function, no safety-stock or reorder-point calculator, no `sku_policy`-writing tool. Confirmed absent from `fixtures/fabricator.py`, `tools/`, and `domain/tool_models.py`. |
| **`tools/inventory.py::calculate_stock_risk` has exactly the defect B2 names** | `if daily_velocity <= 0: daily_velocity = 0.1` — a hardcoded floor that manufactures a finite, fictional `cover_days` for genuinely zero-demand periods. This is live in the current case graph (`compute_risk` calls it directly), so fixing it touches shared code — see §4 B2 for the full ripple analysis. |
| **`economics.py`'s caveats are now stale, a Phase-A side effect nobody caught** | Caveats #2/#3/#4 (margin, carrying rate, lateness) still say "this schema has no selling price" / "no warehousing... figures" / "no promised-date-vs-receipt history" — all now **false**, since Phase A added exactly those fields/tables. This is not a Phase B design choice; it's a real inconsistency Phase A left behind, and B10 is precisely the fix (see §4 B10). |
| **`portfolio.py::list_warehouses()` still does `SELECT DISTINCT`** | Despite `tools/warehouses.py` and the `warehouses` table existing since Phase A. Cosmetic gap, not required for Phase B, noted in §8 as a cheap adjacent cleanup. |
| **No numpy/scipy/pandas dependency exists** | `requirements.txt` has none. Phase B's math (mean/std/percentiles/inverse-normal-CDF for safety stock's z-score) must be pure Python, or a new pinned dependency must be added and justified. This plan chooses pure Python (see §3, B8) — flagged as a decision, not silently assumed. |
| `CaseState` has no classification field | Confirmed via direct read of `submission/state/state.py`. Adding one is optional for Phase B (see §4.9) since the live graph does not need to read `sku_policy` until Phase C's candidate detection exists — but the field is cheap to add now so Phase C doesn't also have to touch `state.py`. |
| The graph's node order (confirmed by direct read) | `fetch_evidence → assess_demand → compute_risk → fetch_vendor_evidence → build_options → recommend_vendor → fetch_budget_and_policy → draft_proposal → review_policy → request_approval → ...`. `fetch_evidence` already fetches `sales` (7d/30d velocity only, via `get_sales_velocity`) before any agent call — this is the natural place Phase C will later insert a classification read, but Phase B does not need to insert a graph node at all (see §0). |

---

## 2. Design decisions this plan makes explicit (confirm before coding)

Several B-tasks require a judgment call the plan text doesn't fully pin
down. Flagging each rather than silently deciding, per this project's own
practice (see `PHASE_A_PLAN.md` §9 and `DECISIONS.md`'s D<n> convention).

**DB1 — pure-Python statistics, no new dependency.** `requirements.txt` has
no numpy/scipy. B8's `safety_stock = z(service_level) × sqrt(...)` needs an
inverse-normal-CDF (probit) function. Recommend implementing a standard
rational approximation (Beasley-Springer-Moro or Acklam's algorithm, both
~20 lines of pure Python, accurate to ~1e-9) rather than adding scipy for
one function. Unit-testable against known values (`z(0.5)=0`, `z(0.95)≈1.645`,
`z(0.99)≈2.326`).

**DB2 — ABC's `unit_cost` proxy.** `consumption_value_12m = demand_12m ×
unit_cost` needs a per-SKU cost figure. `products` has no standard-cost
column (only `selling_price`, added in Phase A for margin, which is the
*wrong* number here — using selling price would rank importance by revenue,
not cost commitment). Recommend: the lowest currently active vendor offer's
**landed unit cost** (via B10's `landed_unit_cost()`), mirroring
`economics.py`'s own existing convention of using `min(o.unit_price for o in
options)` as its cost basis. Document as a proxy, same spirit as A6's
per-figure assumed/measured flags. A SKU with zero active offers falls back
to its most recent historical purchase price from `stock_receipts` if any
exist, else is excluded from ABC ranking that cycle (parked-equivalent,
though Phase B has no park queue yet — just excluded with a logged reason).

**DB3 — regime-shift test is a documented heuristic, not a formal statistical
test.** No scipy means no proper two-sample test. Recommend a simple,
named, bounded heuristic: `magnitude = recent_mean / baseline_mean` (or its
inverse if declining); "significant" if `magnitude >= 1.5` or `<= 0.67`;
"sustained" if the most recent **two** sub-windows (e.g. last 7d and the 7d
before that) both show the same direction of shift, not just the latest
week. This is weaker than a z-test but honest about it, matching the
project's existing style of naming an assumption instead of dressing it up
(cf. `config.assumed_late_days_when_late`'s own docstring, which explicitly
rejects "a fitted distribution... wearing a statistician's coat").

**DB4 — `StockRisk.cover_days` becomes `Optional[float]`.** B2's fix (see
§4) removes the `0.1` floor. Zero genuine velocity with available stock
means "cover_days is undefined, not small" — `None`, not `inf` (a UI or
comparison bug is more likely from a silent `inf` than from an explicit
`None` that every consumer must handle). This ripples to exactly four call
sites, all identified by direct/sub-agent read (see §4 B2's ripple table).
This is the one place Phase B changes behavior of code the live graph
already depends on — flagged for explicit confirmation before starting,
per this session's own instruction to flag scope-affecting deviations.

**DB5 — where B10's functions live.** `AUTONOMOUS_PLAN.md` §A6.4 already
specifies this precisely: `load_cost_inputs(...)` lives in a **tools**
module (agents never see SQL), and `EconomicsInputs` is a frozen dataclass
in `graph/economics.py`. This plan follows that exactly — new module
`tools/cost_inputs.py`, not a new package. No deviation, stated for
completeness.

---

## 3. New files this phase creates

```
submission/statistics/
    __init__.py
    demand.py          B1  — mean/std/CV/ADI/CV²/quadrant classification
    windows.py          B3  — two-window extraction + regime-shift detection
    abc_xyz.py          B4  — ABC/XYZ classification from consumption value
    maturity.py          B5  — maturity tier + confidence from history length
    hysteresis.py         B6  — candidate/confirmation/promotion-downgrade logic
    service_level.py       B7  — newsvendor critical ratio, bounded by ABC class
    safety_stock.py        B8  — safety stock, reorder point, derived cover days
    normal.py            (support) — pure-Python inverse-normal-CDF (DB1)
    classify.py           orchestrator — ties B1-B9 into one sku_policy row

tools/
    classification.py    NEW — get_latest_sku_policy, get_sku_policy_history,
                          upsert_sku_policy (narrow, sku_policy-only, matches
                          existing tools/ convention)
    cost_inputs.py       NEW (B10) — contribution_per_unit, carrying_rate_per_day,
                          lateness_distribution (delegates to tools/receipts.py),
                          landed_unit_cost, load_cost_inputs

domain/tool_models.py    MODIFIED — add SkuPolicy, DemandHistory models

submission/graph/economics.py
                         MODIFIED — add EconomicsInputs dataclass; evaluate_options
                         gains optional `inputs` param; OptionEconomics gains
                         4 *_basis fields; caveats become per-figure conditional

tools/inventory.py       MODIFIED — calculate_stock_risk's velocity floor fix (B2)
domain/tool_models.py    MODIFIED (same file as above) — StockRisk.cover_days
                         becomes Optional[float]

database/backfill_classification.py
                         NEW (B9) — runs classify() for the last 24 month-ends
                         for every seeded (sku, warehouse) pair; called once
                         after database/seed.py::seed_data(), not merged into
                         seed.py itself (keeps seed.py's existing scope —
                         "write rows" — separate from "compute derived
                         classification", matching how migrate.py and seed.py
                         are already kept as separate concerns)

submission/config.py    MODIFIED — new config fields (see §4 per-task tables)

submission/tests/test_phase_b_statistics_and_policy_engine.py
                         NEW — one file, following the `test_phase_a_...`
                         naming precedent found in the test directory, split
                         into classes per B-task rather than per-file if it
                         grows past a few hundred lines
```

Nothing in `submission/graph/nodes.py`, `submission/agents/`, or
`submission/ui.py` changes in this phase, **except** the four call sites
that must become `Optional[float]`-aware because of B2's fix — those are
edits to existing lines, not new logic, enumerated exactly in §4 B2.

---

## 4. Task-by-task plan

### B1 — Demand statistics (`submission/statistics/demand.py`)

New tool first: `tools/sales.py::get_daily_sales_series(sku, warehouse_id,
start_date, end_date) -> DemandHistory` — a new, additive function in the
existing file (does not touch `get_sales_velocity`'s signature or behavior
at all, so nothing that already calls it is affected). Returns one entry
per calendar day in range, **zero-filled for days with no `sales_daily`
row** (defensive — Phase A's fabricator always writes a full run, but a real
gap must read as a true zero, per R7's spirit).

`DemandHistory` (new `domain/tool_models.py` model): `sku`, `warehouse_id`,
`start_date`, `end_date`, `daily_units: list[int]`, `evidence_id`,
`retrieved_at`, `error: Optional[ErrorCode]`.

Pure functions in `demand.py`, operating on `list[int]` (no DB access —
matches `StockRisk`'s existing precedent of pure-calc structures with no
`evidence_id`):

```python
@dataclass(frozen=True)
class DemandStats:
    mean_daily_demand: float
    std_daily_demand: float
    cv: float                    # std / mean, or None if mean == 0
    adi: float                   # mean gap between non-zero demand days
    cv_squared_nonzero: float    # CV² computed on non-zero demand SIZES only
    zero_demand_days: int
    nonzero_observations: int
    quadrant: str                # SMOOTH | ERRATIC | INTERMITTENT | LUMPY

def compute_demand_stats(daily_units: list[int],
                          adi_cutoff: float = config.quadrant_adi_cutoff,
                          cv_squared_cutoff: float = config.quadrant_cv_squared_cutoff
                          ) -> DemandStats: ...

def classify_quadrant(adi: float, cv_squared: float,
                       adi_cutoff: float, cv_squared_cutoff: float) -> str:
    # SMOOTH:       adi < cutoff and cv_squared < cv_cutoff
    # ERRATIC:      adi < cutoff and cv_squared >= cv_cutoff
    # INTERMITTENT: adi >= cutoff and cv_squared < cv_cutoff
    # LUMPY:        adi >= cutoff and cv_squared >= cv_cutoff
```

New config fields (`submission/config.py`): `quadrant_adi_cutoff: float =
1.32`, `quadrant_cv_squared_cutoff: float = 0.49` (Syntetos-Boylan-Croston
defaults, per the plan; configurable per `AUTONOMOUS_PLAN.md`'s own
instruction).

**CV² is computed on non-zero demand sizes only** — per the plan's B1 text
— i.e. `cv_squared_nonzero` uses `[u for u in daily_units if u > 0]`, a
*different* series from the one `cv` (the daily-level CV, used elsewhere)
is computed on. Both are kept as separate fields since B1 lists both
`cv_squared` (for quadrant classification, non-zero-sizes basis) and a plain
`cv` (implied by "cv = σ/μ" over the given window) — this plan keeps them
distinct rather than conflating, since conflating is exactly the kind of
subtle stats bug that would silently miscategorize every intermittent SKU.

### B2 — Forecasting switch + the `calculate_stock_risk` fix

**Forecasting-method switch** is a Phase B *policy*, not new code on its
own: `classify()` (§4 "orchestrator" below) records which method applies
(`quadrant in {SMOOTH, ERRATIC}` → level-based; `quadrant in {INTERMITTENT,
LUMPY}` → Croston-style) as a field on the `sku_policy` row
(`demand_quadrant`), and `derived_cover_days`/`reorder_point_units` for
lumpy/intermittent SKUs are computed via the Croston estimator (see B8)
instead of a plain mean. No new "forecast" module beyond what `demand.py`
and `safety_stock.py` already produce — the switch lives in which formula
`classify()` calls, driven by the quadrant it already computed in B1.

**Croston-style estimator** (new function, `demand.py` or a small
`croston.py` — recommend keeping it in `demand.py` since it's a direct
sibling of `compute_demand_stats`):

```python
def croston_level(daily_units: list[int], alpha: float = 0.1) -> tuple[float, float]:
    """Returns (demand_size_estimate, demand_interval_estimate) via simple
    exponential smoothing applied only at non-zero-demand events, per
    Croston's original method. `daily_velocity` for a lumpy/intermittent SKU
    is demand_size_estimate / demand_interval_estimate, NOT a plain mean."""
```

**The `calculate_stock_risk` fix** (`tools/inventory.py`) — the actual
defect:

```python
# BEFORE (current code):
if daily_velocity <= 0:
    daily_velocity = 0.1   # fabricates a finite, fictional cover_days

# AFTER:
if daily_velocity <= 0:
    cover_days = None if available_units > 0 else 0.0
    # ... skip the division entirely; at_risk becomes a direct
    # available_units-vs-policy-floor check when cover_days is undefined,
    # not a division against a manufactured non-zero rate.
```

`StockRisk.cover_days` changes from `float` to `Optional[float]`
(`domain/tool_models.py`). **Exact ripple, enumerated (DB4):**

| Call site | File | Change needed |
|---|---|---|
| `_override_ambiguity_if_windows_disagree_on_risk` | `submission/graph/nodes.py` | `f"{risk_7.cover_days:.1f}d"` → guard for `None` before formatting |
| `compute_risk` | `submission/graph/nodes.py` | reads `risk.cover_days` for downstream use — confirm no direct arithmetic; if any, guard |
| `scan_portfolio`'s `worst = min(risks.values(), key=lambda r: r.cover_days)` | `submission/portfolio.py` | `None` can't compare with `float` in Python 3 — needs a key function that treats `None` as "worse than any finite value" (e.g. `key=lambda r: (r.cover_days is None, r.cover_days or 0)` reversed appropriately, or sort None first since undefined-cover is the least certain, most attention-worthy case) |
| Any UI render of `f"{cover_days:.1f}"` | `submission/ui.py` | guard with a fallback string ("not meaningful" / "—") |

This table is the entire blast radius — confirmed by grep before
implementation starts, not assumed complete here; the plan commits to
re-grepping `\.cover_days\b` across `submission/` and `tools/` as the first
step of implementing B2, and treating any additional hit found as part of
this same task, not a follow-up.

### B3 — Two windows, two jobs + regime-shift detection

New functions in `submission/statistics/windows.py`:

```python
def rolling_12_months(as_of: date) -> tuple[date, date]:
    """Returns (start, end) for the last 12 *completed* calendar months
    ending before as_of's month — the ABC/economic-importance window."""

def recent_level_window(as_of: date, days: int = 30) -> tuple[date, date]:
    """The short recent window used for the current demand LEVEL (forecast),
    ending yesterday relative to as_of — same complete-days convention
    tools/sales.py already established post-Entry-006."""

@dataclass(frozen=True)
class RegimeShift:
    magnitude: float          # recent_mean / baseline_mean
    is_significant: bool      # per DB3's documented heuristic
    is_sustained: bool
    direction: str             # "increase" | "decrease" | "none"

def detect_regime_shift(recent_stats: DemandStats, baseline_stats: DemandStats,
                          recent_subwindow_stats: list[DemandStats]  # last 2 sub-windows, for "sustained"
                          ) -> RegimeShift: ...
```

`classify()` calls `rolling_12_months` for ABC (B4) and
`recent_level_window` for the forecast level (B1/B2/B8) — **two separate
calls to `get_daily_sales_series`**, each producing its own `DemandStats`.
`detect_regime_shift` compares them and feeds B6's fast-path bypass.

### B4 — ABC/XYZ classification (`submission/statistics/abc_xyz.py`)

```python
def consumption_value_12m(demand_12m_units: float, unit_cost: float) -> float:
    return demand_12m_units * unit_cost

def classify_abc(all_skus_consumption_value: dict[str, float], sku: str,
                  a_threshold: float = config.abc_a_cumulative_pct,
                  b_threshold: float = config.abc_b_cumulative_pct
                  ) -> tuple[str, float]:
    """Sorts descending, computes cumulative share, returns (class, cumulative_share)
    for the given sku. Needs the WHOLE portfolio's consumption values to rank
    against — classify() is responsible for gathering that once per run, not
    each per-SKU call re-querying the whole catalogue."""

def classify_xyz(cv: float, x_cutoff: float = config.xyz_x_cv_cutoff,
                  y_cutoff: float = config.xyz_y_cv_cutoff) -> str:
    # X: cv < x_cutoff (predictable), Y: x_cutoff <= cv < y_cutoff, Z: cv >= y_cutoff
```

New config fields: `abc_a_cumulative_pct: float = 0.75`,
`abc_b_cumulative_pct: float = 0.92` (A = top ~75%, B = next ~17%, C =
remainder — matches the plan's "~70-80% / next ~15-20% / remainder"),
`xyz_x_cv_cutoff: float = 0.5`, `xyz_y_cv_cutoff: float = 1.0` (documented
starting points, configurable).

**Unit cost source: per DB2** — `classify()` resolves `unit_cost` via
`tools/cost_inputs.py::landed_unit_cost()` against the cheapest currently
active offer for that SKU, falling back to the most recent `stock_receipts`
purchase price, falling back to exclusion from that cycle's ABC ranking
with a logged reason (no park queue exists yet in Phase B — this is a
plain log line / return-value note, not a `parked_items` write, since that
table's write path is Phase C's).

`classify_abc` needing "the whole portfolio's consumption values" means
`classify()` cannot classify one SKU in isolation for the ABC dimension —
it must be run as a **batch** over all SKUs at a given `as_of` before any
individual row's `abc_class` is final. This is why B9's backfill script
iterates warehouse-by-warehouse, computing every SKU's consumption value
first, then assigning classes, then writing rows — not SKU-by-SKU. Flagging
this explicitly since it changes `classify()`'s call shape from "one
function you call per SKU" to "a batch step, then a per-SKU finisher" — see
§4 "orchestrator" below for the resulting two-function split.

### B5 — Maturity and confidence (`submission/statistics/maturity.py`)

```python
def assess_maturity(first_sale_date: Optional[date], as_of: date,
                     nonzero_observations: int) -> tuple[str, float]:
    """Returns (maturity_tier, confidence).
    Tiers: INSUFFICIENT (<3mo), PROVISIONAL (3-12mo), ESTABLISHED (>=12mo).
    Confidence scales with min(1.0, nonzero_observations / config.maturity_confidence_full_at_observations),
    not with months alone -- a 3-month SKU with thousands of events should not
    read as less confident than a 12-month SKU with three."""
```

New config: `maturity_confidence_full_at_observations: int = 60` (a starting
point — "confidence reaches 1.0 once there are 60 non-zero demand
observations", tunable). `first_sale_date` comes from
`MIN(sale_date) FROM sales_daily WHERE sku=? AND warehouse_id=?` — a small
new query, add as `tools/sales.py::get_first_sale_date(sku, warehouse_id) ->
Optional[date]` (additive, same file).

### B6 — Hysteresis (`submission/statistics/hysteresis.py`)

```python
@dataclass(frozen=True)
class HysteresisResult:
    active_class: str
    candidate_class: Optional[str]
    candidate_since: Optional[date]
    consecutive_confirmations: int
    change_reason: str

def apply_hysteresis(previous: Optional[SkuPolicy], computed_class: str, as_of: date,
                      regime_shift: RegimeShift,
                      promotion_confirmations: int = config.hysteresis_promotion_confirmations,
                      downgrade_confirmations: int = config.hysteresis_downgrade_confirmations
                      ) -> HysteresisResult:
    """previous=None (first-ever classification) -> active_class = computed_class
    immediately, change_reason='initial classification', no candidate state.

    Otherwise: if computed_class == previous.active_class, reset any pending
    candidate and confirm. If it differs, either extend the existing candidate
    streak or start a new one. Promote/downgrade only once confirmations reach
    the threshold for that direction (2 up, 3 down, per D7/B6).

    Fast path: if regime_shift.is_significant and regime_shift.is_sustained,
    bypass the confirmation count entirely and change_reason names the
    override explicitly ('regime shift bypass: <magnitude>x change, sustained
    across 2 windows') -- never silent."""
```

New config: `hysteresis_promotion_confirmations: int = 2`,
`hysteresis_downgrade_confirmations: int = 3` (already named as literals in
the plan text — made configurable per the plan's own instruction).

"Promotion" vs "downgrade" direction is determined by an explicit class
ranking table (`{"A": 3, "B": 2, "C": 1}` for ABC — XYZ and quadrant don't
have a natural up/down direction for this rule, so the plan scopes
hysteresis to the **ABC** dimension only, per the plan text's own examples
(B→A, A→B) — XYZ and quadrant reclassifications apply immediately each
recompute, with no confirmation delay, since the plan never describes a
hysteresis rule for them. Flagging this as a scope reading, not silently
assumed: `AUTONOMOUS_PLAN.md` §B6 only ever gives ABC-direction examples.

### B7 — Service level (`submission/statistics/service_level.py`)

```python
def newsvendor_service_level(understock_cost_per_unit: float,
                              overstock_cost_per_unit_per_period: float) -> float:
    return understock_cost_per_unit / (understock_cost_per_unit + overstock_cost_per_unit_per_period)

def bounded_service_level(raw_service_level: float, abc_class: str,
                            floors: dict[str, float] = config.service_level_floor_by_class,
                            caps: dict[str, float] = config.service_level_cap_by_class) -> float:
    return min(caps[abc_class], max(floors[abc_class], raw_service_level))
```

New config: `service_level_floor_by_class: dict = {"A": 0.95, "B": 0.90, "C": 0.80}`,
`service_level_cap_by_class: dict = {"A": 0.995, "B": 0.98, "C": 0.95}`
(starting points; the plan calls these "a policy guardrail", exact numbers
are a business call — flagged as provisional defaults, same treatment as
O1/O2/O4/O5 elsewhere in this project).

**Holding cost is not computed here** — per the plan's explicit "one
holding-cost function, two callers" rule (B7), `overstock_cost_per_unit_per_period`
comes from `tools/cost_inputs.py::carrying_rate_per_day()` (B10), the exact
same function `economics.py::evaluate_options` calls for `carrying_cost`.
`understock_cost_per_unit` comes from `tools/cost_inputs.py::contribution_per_unit()`
(also B10). **This is why B10 must exist before B7 can be finished** — noted
in the execution order (§6).

### B8 — Safety stock, reorder point, derived cover (`submission/statistics/safety_stock.py`)

```python
def compute_safety_stock(service_level: float, lead_time_days: float,
                          demand_std: float, demand_mean: float,
                          lead_time_std: float) -> float:
    z = inverse_normal_cdf(service_level)   # normal.py, pure Python (DB1)
    return z * math.sqrt(lead_time_days * demand_std**2 + demand_mean**2 * lead_time_std**2)

def compute_reorder_point(demand_mean: float, lead_time_days: float, safety_stock: float) -> float:
    return demand_mean * lead_time_days + safety_stock

def derived_cover_days(reorder_point_units: float, demand_mean: float) -> Optional[float]:
    return None if demand_mean <= 0 else reorder_point_units / demand_mean
```

`lead_time_days` and `lead_time_std` (σL) come from
`tools/receipts.py::get_lateness_distribution(vendor_id, sku)` — **already
built in Phase A** — specifically its `n_observations`/timing fields feed a
new small helper, `submission/statistics/safety_stock.py::lead_time_variance_from_receipts(...)`,
that converts the existing `LatenessDistribution` (mean/p50/p90 late days,
on-time rate) into a `(mean_lead_time_days, std_lead_time_days)` pair usable
by `compute_safety_stock`. **Falls back to `1 - on_time_rate`-based proxy**
(the plan's own documented fallback path) when `get_lateness_distribution`
returns `None` (below the 5-observation floor) — same per-figure
measured/assumed discipline as B10, applied here to the safety-stock
consumer rather than the economics consumer.

`statistical_target` (units, from B8's ROP) is recorded on `sku_policy`
**separately** from `active_target` (units) — per the plan's explicit
"both always computed, both always shown" rule. In Phase B, `active_target`
is simply set equal to `statistical_target` (no policy floor reconciliation
exists yet — that's Phase C2). Once Phase C2 lands, `active_target` will
diverge when a `policy_rules` floor exceeds it; Phase B's job is just to
make sure both columns exist and are populated honestly today, not to
implement the reconciliation.

### B9 — Backfilled classification history

`database/backfill_classification.py` (new script, separate from `seed.py`
per §3's reasoning):

```python
def backfill_all(db_path: str = "database/inventra.db", months: int = 24) -> None:
    """For every (sku, warehouse_id) pair with at least one sales_daily row,
    run classify_batch() for each of the last `months` month-ends, oldest
    first (so hysteresis state accumulates correctly month over month --
    running newest-first would have no prior row to compare against for the
    OLDEST month and would need a second backward pass). Idempotent: reruns
    overwrite existing rows for the same (sku, warehouse, as_of_date) via
    the UNIQUE constraint + INSERT OR REPLACE in upsert_sku_policy."""
```

Called once at the end of `database/seed.py::seed_data()` — a single new
line (`from database.backfill_classification import backfill_all;
backfill_all(db_path)`), **not** merging the backfill logic into `seed.py`
itself. `seed.py` stays "write raw facts"; `backfill_classification.py` is
"derive and write classification from those facts" — same separation of
concerns the codebase already uses between `seed.py` and `migrate.py`.

### B10 — Measured economics inputs (`tools/cost_inputs.py` + `economics.py`)

Per `AUTONOMOUS_PLAN.md` §A6.4/§B10 exactly, and per this session's ground
truth finding that `economics.py`'s caveats are currently **factually
stale** post-Phase-A — this task is not optional polish, it fixes a real,
already-existing inconsistency.

```python
# tools/cost_inputs.py

def contribution_per_unit(sku: str, landed_unit_cost: float) -> Optional[float]:
    """selling_price - landed_unit_cost, or None if products.selling_price is NULL.
    Raises ValueError if the result is negative (B10's explicit guard --
    "a data error, not a small number")."""

def carrying_rate_per_day(sku: str, warehouse_id: str) -> tuple[float, float, str]:
    """Returns (rate_from_capital_insurance_shrinkage, rate_from_storage_volume, basis).
    First component: (cost_of_capital + insurance + shrinkage) / 365 from
    carrying_cost_inputs, on landed value. Second: storage_cost_per_m3_month
    * unit_volume_m3 / 30, an absolute per-unit-per-day term, from warehouses
    + products. basis = 'measured' if both source tables have rows for this
    sku/warehouse, else 'assumed' (falls back to config.assumed_annual_carrying_rate/365
    for the missing component only -- per-figure, not all-or-nothing, per A6.1).
    Returns the two components SEPARATE, not blended, per the plan's explicit
    "why is holding this expensive" requirement."""

def landed_unit_cost(offer: VendorOffer) -> float:
    return offer.unit_price + (offer.freight_per_unit or 0) + ((offer.freight_flat or 0) / quantity_being_priced)
    # NOTE: quantity-dependent -- caller must pass the actual order quantity,
    # not call this once and reuse across different quantities. Re-derive on
    # every apply_human_edit re-draft (B10's own explicit warning).

def load_cost_inputs(sku: str, warehouse_id: str, vendor_ids: list[str]) -> EconomicsInputs:
    """Assembles the above + tools/receipts.py::get_lateness_distribution per
    vendor + vendors.billing_basis into one EconomicsInputs object, setting
    each *_basis field independently."""
```

```python
# submission/graph/economics.py additions

@dataclass(frozen=True)
class EconomicsInputs:
    contribution_per_unit: Optional[float]
    margin_basis: str                    # "measured" | "assumed"
    carrying_rate_per_day: float
    carrying_basis: str
    lateness_by_vendor: dict[str, LatenessDistribution]
    lateness_basis_by_vendor: dict[str, str]
    billing_basis_by_vendor: dict[str, str]

def evaluate_options(risk, options, vendor_performance=None,
                      inputs: Optional[EconomicsInputs] = None) -> OptionsEconomics:
    # inputs=None -> EXACTLY today's behavior (config.assumed_* throughout).
    # inputs given -> each of margin/carrying/lateness/billing prefers the
    # measured figure for the specific option/vendor it applies to, falls
    # back to config for that ONE figure if the corresponding *_basis is
    # "assumed", and the caveat list is rebuilt CONDITIONALLY: a caveat only
    # appears for a figure that is actually assumed for at least one option
    # in this call. A fully-measured case (per PHASE_A_PLAN.md's exit
    # criterion #7 -- at least one seeded sku/warehouse/vendor combo has
    # every A6.1 input measured) produces ZERO caveats.
```

`OptionEconomics` gains four fields: `margin_basis: str`, `carrying_basis:
str`, `lateness_basis: str`, `billing_basis: str` — exposed via
`as_evidence()` so, per the plan's R3, "the Strategist can say 'measured' or
'assumed' without computing anything."

**This call is backward compatible by construction** (`inputs` defaults to
`None`) — the 140 existing tests keep passing unchanged, since every
existing call site (`submission/graph/nodes.py::build_options`) simply
never passes `inputs` until a later task (deliberately **not** this one —
see §8) wires it in. Phase B ships `evaluate_options`'s new capability
without switching any live case over to using it, exactly mirroring how
Phase A shipped new tables no live code read yet.

---

## 5. The `classify()` orchestrator — how B1-B9 actually compose

Two functions, per B4's batch requirement (§4 B4):

```python
# submission/statistics/classify.py

def classify_portfolio(warehouse_id: str, as_of: date, conn=None) -> list[SkuPolicy]:
    """The unit Phase B actually calls (from backfill_classification.py, and
    later from Phase C's sweep). For every (sku, warehouse_id) with sales
    history:
      1. get_daily_sales_series x2 (12mo window, recent window) -- B1/B3
      2. compute_demand_stats x2, detect_regime_shift               -- B1/B3
      3. gather unit_cost for every sku in this warehouse (batch)    -- B4/DB2
      4. classify_abc against the WHOLE batch's consumption values   -- B4
      5. classify_xyz per sku from its own recent-window cv          -- B4
      6. assess_maturity                                              -- B5
      7. get_latest_sku_policy(sku, warehouse_id) for prior state     -- B6
      8. apply_hysteresis                                             -- B6
      9. load_cost_inputs -> contribution_per_unit, carrying_rate      -- B10
     10. newsvendor_service_level -> bounded_service_level             -- B7
     11. lead_time_variance_from_receipts (or fallback)                -- B8
     12. compute_safety_stock, compute_reorder_point, derived_cover_days -- B8
     13. build one SkuPolicy row per sku, upsert_sku_policy each        -- write
    Returns the written rows. Every step's inputs/outputs are named fields
    on intermediate dataclasses, not a single giant tuple -- keeps each
    step independently testable with hand-checked fixtures, per the plan's
    own exit criterion ("every function is pure... has a unit test with
    hand-checked expected values")."""
```

`classify_portfolio` is itself **not** pure (it reads the DB via several
tools and writes `sku_policy`) — it is the one orchestration seam, deliberately
kept thin (mostly sequencing calls, no arithmetic of its own) so every actual
calculation stays in the pure, independently-tested functions from §4.

### 5.1 Data flow diagram

```
sales_daily ──┬─▶ get_daily_sales_series(12mo window)  ─▶ compute_demand_stats ──┐
              │                                                                  │
              └─▶ get_daily_sales_series(recent window) ─▶ compute_demand_stats ─┼─▶ detect_regime_shift
                                                                                  │
products, vendor_offers ──▶ landed_unit_cost ──▶ consumption_value_12m ──▶ classify_abc (batch)
                                                                          └─▶ classify_xyz (per-sku, from recent cv)

sku_policy (prior row) ──▶ get_latest_sku_policy ──▶ apply_hysteresis ◀── detect_regime_shift (fast path)

carrying_cost_inputs, warehouses, products.selling_price ──▶ load_cost_inputs ──┐
                                                                                  ├─▶ newsvendor_service_level ─▶ bounded_service_level
stock_receipts ──▶ get_lateness_distribution ──▶ lead_time_variance_from_receipts ┘

bounded_service_level, lead_time stats, recent-window DemandStats
        └─▶ compute_safety_stock ─▶ compute_reorder_point ─▶ derived_cover_days
                                                                    │
                                                                    ▼
                                              one SkuPolicy row ─▶ upsert_sku_policy ─▶ sku_policy table
```

### 5.2 Where B10 separately plugs into the live economics module

```
tools/cost_inputs.py::load_cost_inputs(sku, warehouse_id, vendor_ids)
        │  (pure read, no LLM -- same as A6.4's diagram)
        ▼
EconomicsInputs  ──optional──▶  economics.evaluate_options(risk, options,
                                    vendor_performance, inputs=inputs)
        │
        ▼
OptionEconomics.margin_basis / carrying_basis / lateness_basis / billing_basis
        │
        ▼
OptionsEconomics.as_evidence()["caveats"]   (now conditional, per-figure)
```

**Not built in Phase B:** the call site inside `submission/graph/nodes.py`
that actually constructs `EconomicsInputs` and passes it into
`build_options`'s call to `evaluate_options`. That one-line wiring is
listed in §8 as an explicit, deliberate deferral — see the reasoning there.

---

## 6. Execution order (session-sized chunks)

1. **`normal.py` + `demand.py` (B1) + tests.** Self-contained, no DB
   dependency beyond the new `get_daily_sales_series` tool function. Good
   first step because it's the most independently verifiable (hand-computed
   ADI/CV² fixtures against a few short synthetic series).
2. **`windows.py` (B3) + `maturity.py` (B5) + tests.** Both are thin, pure,
   and only need `demand.py`'s output shape.
3. **B2's `calculate_stock_risk` fix**, done as its own isolated step with
   the full grep-and-guard sweep from §4's ripple table, run and verified
   (existing 140 tests must still pass) before moving on — this is the one
   task touching shared/live code, so it gets its own checkpoint rather than
   being bundled with new-file work.
4. **`tools/classification.py` + `SkuPolicy`/`DemandHistory` domain models.**
   Needed before `abc_xyz.py`/`hysteresis.py` can be tested against a
   realistic "prior row" fixture.
5. **`abc_xyz.py` (B4) + `hysteresis.py` (B6) + tests.**
6. **`tools/cost_inputs.py` (B10) + `EconomicsInputs`/`evaluate_options`
   change in `economics.py` + tests** — including the specific regression
   test that a fully-measured case produces zero caveats, and that
   `inputs=None` reproduces today's 140-test baseline exactly unchanged.
7. **`service_level.py` (B7) + `safety_stock.py` (B8) + tests** — these
   depend on step 6's `tools/cost_inputs.py` per B7's "one function, two
   callers" rule, so step 6 must land first.
8. **`classify.py` orchestrator (§5) + tests against a small in-memory or
   scratch-db fixture** (2-3 SKUs, hand-computed expected `sku_policy` rows).
9. **`database/backfill_classification.py` (B9)**, run against the real
   seeded 35-SKU/4-warehouse database, verified against the exit criteria
   in §7.

Do not start step 6 or 7 before step 3 is verified green — B7/B8/B10 all
read real Phase-A tables, and if B2's `Optional[float]` ripple broke
something upstream, every later step's fixtures would be built on a moving
foundation.

---

## 7. Phase B exit criteria — concretely checkable

Restating `AUTONOMOUS_PLAN.md`'s own Phase B exit criteria as literal checks:

1. Every new function in `submission/statistics/` and `tools/cost_inputs.py`
   has at least one unit test with a hand-computed expected value (not just
   "runs without error") — checkable by reviewing the test file's assertions
   directly, not by coverage percentage alone.
2. `python -m pytest submission/tests -q` reports **140 passing, same as
   before Phase B started**, plus the new Phase B test file's count on top —
   never fewer, and any newly-red test traces to an intentional B2-style
   change with its ripple already accounted for, never a silent regression.
3. Run `classify_portfolio` for one known-lumpy seeded SKU (e.g. one of the
   `SKU-0xx` rows on the `lumpy` profile) and one known-steady SKU with the
   same approximate mean — verify by direct query that their
   `safety_stock_units` differ and that the lumpy one's `demand_quadrant =
   'LUMPY'` while the steady one's is `'SMOOTH'`.
4. After running `backfill_classification.py` across all 24 backfilled
   month-ends for at least one SKU, query `sku_policy` for that
   `(sku, warehouse_id)` and confirm at least one row shows
   `candidate_class` differing from `active_class` at some point in the
   history (proving hysteresis state was actually exercised, not just
   written once and left static).
5. `SELECT * FROM sku_policy WHERE sku='AC-004' AND warehouse_id='DEL-01'
   ORDER BY as_of_date DESC LIMIT 1` returns a row with non-null
   `service_level`, `safety_stock_units`, `reorder_point_units`,
   `derived_cover_days` — proving B7/B8 actually executed against a real
   seeded SKU, not just a synthetic fixture.
6. Call `evaluate_options(..., inputs=load_cost_inputs(sku, warehouse_id,
   vendor_ids))` for the one seeded sku/warehouse/vendor combination
   `PHASE_A_PLAN.md`'s exit criterion #7 named as "fully measured" and
   confirm `OptionsEconomics.caveats == []`.
7. Call `evaluate_options` with **no** `inputs` argument at all (today's call
   shape) on the same case and confirm the returned `OptionsEconomics` is
   byte-for-byte structurally identical to Phase A's pre-B10 behavior
   (same caveats, same fields) — the backward-compatibility guarantee,
   checked, not assumed.
8. A measured margin and a measured carrying rate actually change at least
   one vendor **verdict** compared to the `assumed_gross_margin_rate`/
   `assumed_annual_carrying_rate` config defaults on some seeded case —
   `AUTONOMOUS_PLAN.md`'s own exit criterion, proving the inputs are
   load-bearing, not decorative.

---

## 8. Explicitly out of scope for Phase B (do not build these here)

- **Wiring `EconomicsInputs` into the live `build_options` call site in
  `submission/graph/nodes.py`.** B10 makes `evaluate_options` *capable* of
  using measured data; it does not flip the live case graph over to
  actually calling it that way. Rationale: doing so changes what every
  in-flight case sees on its approval card, which is a behavior change to
  the shipped submission, not a data-foundation change — the same
  boundary Phase A drew around not touching `submission/graph/` at all.
  This is a one-line, low-risk follow-up once Phase B is verified, but it's
  a deliberate, separate decision point, not bundled in silently.
- **Any `CaseState`/graph-node change beyond B2's contained fix.** Phase C
  is where `sku_policy`'s `reorder_point_units` starts driving candidate
  detection; Phase B only makes that data exist and be correct.
- **The park queue (`parked_items` writes).** DB2's "excluded from ABC
  ranking with a logged reason" is a plain log/return value, not a
  `parked_items` row — that table's write path belongs to Phase C (C4).
- **Policy floor reconciliation** (`active_target` vs `statistical_target`
  actually diverging). Phase B populates both columns honestly; Phase C2
  is where a `policy_rules` floor can override `active_target`.
- **`roll_forward()`** — still deferred, unchanged from Phase A's deferral.
- **Fixing `portfolio.py::list_warehouses()`'s stale `SELECT DISTINCT`.**
  Noted as a cheap adjacent cleanup, not required for any Phase B exit
  criterion.

---

## 9. Open questions this plan surfaces (confirm before implementation)

- **DB1-DB5 above** are the primary ones — pure-Python inverse-normal-CDF,
  the ABC unit-cost proxy, the regime-shift heuristic's honesty tradeoff,
  the `StockRisk.cover_days` → `Optional[float]` ripple, and B10's module
  placement (this last one has no real ambiguity — the plan already
  specifies it — listed for completeness).
- **New — is ABC-only hysteresis the right scope, or should XYZ/quadrant
  also get a confirmation delay?** This plan reads `AUTONOMOUS_PLAN.md`
  §B6 as ABC-only (its examples are all A/B/C moves) and scopes
  `apply_hysteresis` accordingly. Worth a one-line confirmation before
  coding, since applying it more broadly changes `classify_portfolio`'s
  call shape (multiple hysteresis states per SKU instead of one).
- **New — service level floor/cap numbers (§4 B7) are placeholders.**
  `{"A": 0.95, "B": 0.90, "C": 0.80}` floors and their caps are this
  plan's own provisional defaults, not a number from `AUTONOMOUS_PLAN.md`
  or the brief. Same treatment as O1/O2/O4/O5 — flagged, not decided.
