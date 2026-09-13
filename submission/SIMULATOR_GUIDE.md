# Simulator Guide — testing the agent through the Data Console

This is the practical guide for exercising every scenario the agent needs to
handle, using the **Data Console** (`submission/data_console.py`) to stage a
condition and the **autonomous monitor** (`submission/monitor/service.py`,
driven from the Streamlit UI's Monitor screen) to let the agent discover and
react to it — the way an operator would actually use this system, not by
editing the database directly.

```bash
streamlit run submission/ui.py            # port 8501 — approval screens + monitor control
streamlit run submission/data_console.py  # port 8502 — stage test conditions
```

## The one rule: one scenario at a time

1. Stop monitoring.
2. Change one thing in Data Console.
3. Start monitoring with a 30-second interval.
4. Wait for the first scan.
5. Inspect **Needs my decision**, **Sweep history**, and **Park queue**.
6. Stop monitoring before changing the next scenario.
7. Reseed when you want a clean baseline again (`python database/seed.py && python -m submission.tests.seed_extra`).

**Do not edit the SQLite file directly for normal testing — use the Data
Console.** It's the same discipline the rest of this project follows: the
Data Console writes through the same tables the agent reads, so what you
stage is exactly what the agent sees, no more and no less.

---

## Scenario 1 — Healthy → low stock → approval case

In Data Console → **Levers & scenarios**:
- Enter your name.
- SKU: `AC-001`, Warehouse: `DEL-01`.
- Set cover days: `30`. Click **Apply cover days**.

Start monitoring for `DEL-01`.

**Expected:** Sweep history lists the SKU as healthy. Nothing appears in
Needs my decision.

Then set cover days to `2` and click **Apply cover days** again. Restart
monitoring, or wait for the next scan.

**Expected:** A case is created and appears in **Needs my decision**. Open
it — you should see supplier options, a demand explanation, a budget/policy
checklist, and Approve / Ask for changes / Reject.

## Scenario 2 — Reject a proposal

Use the low-stock case from Scenario 1. Open it from **Needs my decision**,
enter your name, enter a rejection reason, click **Reject**.

**Expected:** the case becomes blocked. No purchase request is created. The
timeline records your name and reason.

**Important:** stock is still low, so the next monitor scan can open a fresh
case for the same SKU again; rejecting a proposal does not change stock.

## Scenario 3 — Ask for changes

On a fresh approval case: enter your name, add a real comment (e.g. *"Please
explain why the faster supplier is worth the extra cost"*), click **Ask for
changes**.

**Expected:** the system revisits the same case — re-reads stock, sales,
offers, and budget, drafts again, reviews policy again, and returns a
revised proposal for approval. The timeline shows the revision.

**Only one revision is allowed.** A second attempt on the same case blocks
it (`config.max_revision_cycles = 1`).

## Scenario 4 — Choose a different supplier

On a fresh proposal with alternatives: enter your name, expand **Choose a
different supplier**, pick one of the eligible suppliers, click **Use this
supplier and re-check**.

**Expected:** quantity and price recalculate for that supplier, policy
review runs again, and the proposal returns to approval. You can do this up
to **three** times (`config.max_human_edit_cycles = 3`).

## Scenario 5 — Stale inventory

In **Levers & scenarios**: SKU `AC-001`, Warehouse `DEL-01`, set **Age
snapshot by** to `49` hours, click **Apply staleness**. Start/wait for
monitoring.

**Expected:** no approval case. Sweep history detail shows a stale snapshot
— the agent refuses to plan from inventory data older than
`config.data_freshness_hours` (48h by default).

## Scenario 6 — Missing/immature sales data

Use the prepared fixture: SKU `AC-003`, Warehouse `DEL-09`. Start monitoring
only for `DEL-09`.

**Expected:** it appears in **Park queue**, not as an approval case. Open its
Data Console link, go to **Missing sales data**, backfill the requested date
range, click **Data is in — re-run this case**.

**Expected after backfill:** the system reads the new sales data. If the
policy is still immature, it asks a person for **Days of stock to hold** and
a name — it does not let you type demand rate, quantity, or price.

## Scenario 7 — No eligible supplier / policy block

First make a SKU low stock (e.g. `AC-003` / `DEL-01`, cover days `2`). Then
in Data Console → **Table editor** → **Vendor offers**: find every offer for
`AC-003` and edit each one's **Valid until** to yesterday. Start monitoring.

**Expected:** the case reaches a blocked outcome. The reason states no
eligible vendor/supplier option is available. No approval, no purchase
request.

**Alternative:** instead of expiring the offers, lower the vendor's
on-time rate, fill rate, and quality score below the reliability threshold
(0.90 average).

## Scenario 8 — Budget deferral

Create two low-stock SKUs in the same warehouse (e.g. `AC-001`/`DEL-01` and
`AC-003`/`DEL-01`, both at 2-day cover via **Levers & scenarios**). Then in
**Table editor** → **Monthly budgets**, edit the current `DEL-01` row so
`budget_amount` is equal to (or barely above) `spent_amount + committed_amount`.
Start monitoring.

**Expected:** Sweep history shows budget deferrals — the monitor's budget
allocation won't open approval cases it can't support. Higher-priority SKUs
are considered before lower-priority ones.

## Scenario 9 — Policy floor violation / exception

In **Levers & scenarios**, set `AC-001`/`DEL-01` to ~10-14 days cover. In
**Policy floor**: SKU `AC-001`, Warehouse `DEL-01`, Minimum cover days `30`,
Reason *"Demo contractual service level"*, click **Set policy floor**. Start
monitoring.

**Expected:** the higher policy floor can make the SKU a candidate. Its
proposal/checklist shows the policy-floor rule. If a human deliberately
picks a lower statistical target, the proposal is marked as an explicit
policy exception, not silently accepted.

---

## What happens when policy is violated — the full table

Not an endless loop. Every situation below terminates in a bounded, defined
outcome:

| Situation | What the system does |
|---|---|
| Stale stock | Stops/defers; no proposal |
| Missing data | Parks the SKU; asks for data |
| No eligible vendor | Blocks the case |
| Budget far over limit | Blocks the case |
| Budget within 5% tolerance | Flags EXCEPTION, still requires human approval |
| Policy evidence missing/fake | Blocks the case |
| Agent gives invalid structured output | Retries that agent once, then blocks |
| Human asks for changes | Re-runs evidence → planning → policy review once |
| Human changes supplier | Re-prices → policy review → approval again |
| Facts change after approval | Revalidates; first recoverable failure re-plans, second blocks |

**The bounded loops, precisely:**
- Agent repair: maximum 2 attempts (`config.max_model_attempts_per_agent`).
- Human revision: maximum 1 (`config.max_revision_cycles`).
- Supplier edits: maximum 3 (`config.max_human_edit_cycles`).
- Revalidation after data changes: one fresh planning bounce, then block.

---

## After approval and delivery — the honest current state

1. Gate-1 approval creates a `PENDING` internal purchase request and reserves budget.
2. If `VENDOR_EMAIL_ENABLED=true`, Gate 2 sends the PO to the vendor.
3. The monitor counts `PENDING` quantity as inbound/on-order, preventing duplicate orders.
4. The app does **not** receive supplier confirmation automatically.
5. The app does **not** automatically increase stock on the delivery date.
6. There is **no** normal UI action to mark a purchase request as received.

After physical delivery, someone must update the stock snapshot in Data
Console — normally by entering the new real `on_hand` quantity. A stock
receipt record only improves vendor-performance history; it does not add
inventory automatically.

There is a genuinely missing final lifecycle stage:

```
PO sent → supplier confirms → goods received → inventory increases → purchase request closed
```

The monitor handles everything before that boundary; supplier confirmation and
goods receipt remain outside this application's scope.
