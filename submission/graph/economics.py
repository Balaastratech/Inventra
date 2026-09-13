"""
Deterministic replenishment arithmetic: how much to order, from whom, and on
what basis one supplier beats another.

Nothing in this module is a judgment call and nothing in it involves a
model. It is its own module because three consumers need the *same* numbers
and must never disagree:

  * prompts/strategist.py  renders them as evidence for the agent
  * graph/nodes.py         enforces the verdict, so the agent cannot overrule it
  * ui.py                  shows them to the approver

That last point is the reason this exists at all. A live run produced this
approver-facing sentence:

    "The recommended option (FastShip Inc.) costs an additional 450.0 but
     provides an extra day of buffer ... a justified investment"

The computed extra cost was **1450.0**. The model dropped a digit while
narrating arithmetic it had been handed correctly, and then declared the
premium justified without comparing it to anything. Both failures have the
same root cause: numbers were being authored in prose. Here they are
computed once, in code, and the prose is only allowed to cite them.


WHY THE COMPARISON BASIS CHANGED (and what did NOT change)
----------------------------------------------------------
Order quantity is sized per supplier, from that supplier's own lead time:
``daily_velocity x (target_cover_days + lead_time_days) - available``. That is
correct and it stays. The business asked for N days of cover *once the goods
land*, so a supplier that takes an extra day in transit genuinely has to feed
an extra day of demand. Sizing every supplier to one shared end date would
"fix" the comparison by quietly giving the faster supplier 11 days of cover
against a 10-day requirement -- changing the requirement to make the
arithmetic tidier. Rejected.

What was wrong was the ranking, one line:

    cheapest = min(options, key=lambda o: o.total_cost)      # WRONG

Once quantities legitimately differ per supplier, ``total_cost`` ranks two
*different-sized baskets* by their price tags. Worked example (AC-004: 12
units available, 3/day, 10-day target):

    FastShip   lead 2d, fill 0.98, $500  ->  25 units, $12,500
    Standard   lead 3d, fill 0.94, $450  ->  29 units, $13,050

The old rule declared FastShip "cheaper overall" and the validation gate then
*forced* that pick. But Standard's 29 units are not 25 units plus $550 of
waste. Three of the extra units are one more day of demand FastShip never had
to cover, and about two are shrinkage grossed up for the lower fill rate.
Every one of those units gets sold. Per unit actually delivered the ranking
inverts:

    FastShip   500 / 0.98 = $510.20      Standard   450 / 0.94 = $478.72

So the fix is to normalise the *metric*, not the quantity. This module now
ranks on **all-in cost per day of cover**: what the order costs, divided by
the days of demand it funds, plus the two costs that a per-unit price hides.

    all_in_cost_per_day_of_cover
        = ( cover_purchase_cost + carrying_cost + expected_stockout_cost )
          / days_of_cover_funded

Three guards keep that metric honest:

  1. **Minimum-order overshoot earns no coverage credit.** A supplier with a
     200-unit minimum would otherwise post a beautiful per-day figure by
     handing you two months of stock nobody asked for. Only the units
     genuinely required count toward ``days_of_cover_funded``; the overshoot
     is charged its carrying cost over the much longer time it sits.

  2. **Carrying cost exists at all.** It previously did not, anywhere in the
     codebase. Total spend was the only thing discouraging a large order, and
     removing it as the ranking metric would have left nothing to push back
     on "order more from whoever is cheapest per unit". The extra units are
     not waste, but the capital in them is not free either.

  3. **Delivery risk is priced per option, not pairwise.** The old rule scored
     every option against whichever one happened to be cheapest, and valued a
     premium option's buffer using *that option's* lateness probability --
     when the risk the buffer insures against belongs to the option you would
     otherwise have picked. Each option now carries its own expected stockout
     cost, computed from its own on-time rate against its own slack, so the
     comparison works with three suppliers as well as two and has no
     privileged anchor.

``total_cost`` does not disappear. It stops being the ranking metric and
becomes what it always was: the cash committed, checked against the budget in
graph/nodes.py and graph/revalidation.py.


THE ASSUMPTIONS, STATED RATHER THAN BURIED
------------------------------------------
Four inputs the decision needs are not in this schema. Each is a declared,
configurable value emitted next to every figure it affects, never dressed up
as measured data:

  * ``assumed_gross_margin_rate`` -- ``products`` is (sku, name, category,
    active). There is no selling price anywhere, so contribution per unit is
    NOT derivable. An earlier version used ``velocity x unit_price`` and
    called it "exposure", which was worse than useless: that is procurement
    spend, not earnings, and naming it that way invited the model to reason
    about it as revenue.

  * ``assumed_annual_carrying_rate`` -- no warehousing or cost-of-capital
    figures exist in the schema.

  * ``assumed_late_days_when_late`` -- ``on_time_rate`` answers "how often",
    never "by how much", and there is no promised-vs-received PO history to
    derive it from. The previous model treated any late delivery as consuming
    the *entire* buffer, which inflated the value of buffer days and was the
    arithmetic behind that $1,450 recommendation.

  * ``vendor_billed_on_units_shipped`` -- billing terms are not in the
    schema, and at a 0.94 fill rate the two readings differ by ~$780 on this
    case. Defaults to the reading the code already assumed (billed on units
    ordered), which never understates committed cash.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Iterable, Optional

from submission.config import config

# Verdicts. Computed here, enforced in nodes._validate_recommendation.
VERDICT_BEST_VALUE = "best_value_option"
VERDICT_WITHIN_TOLERANCE = "within_value_tolerance"
VERDICT_WORSE_VALUE = "worse_value_option"

#: Verdicts a recommendation is allowed to carry. Anything else is refused by
#: the validation hook and sent back to the agent as a repair attempt.
ACCEPTABLE_VERDICTS = frozenset({VERDICT_BEST_VALUE, VERDICT_WITHIN_TOLERANCE})

# Names from the superseded pairwise-premium rule, kept as aliases so existing
# imports and regression tests keep resolving. The concepts collapsed when
# delivery risk moved inside the per-option score: there is no longer a
# "premium to justify" separate from the score itself, because the cost of
# arriving later is already in it.
VERDICT_CHEAPEST = VERDICT_BEST_VALUE
VERDICT_JUSTIFIED = VERDICT_WITHIN_TOLERANCE
VERDICT_FREE_UPGRADE = VERDICT_WITHIN_TOLERANCE
VERDICT_NOT_JUSTIFIED = VERDICT_WORSE_VALUE
VERDICT_NO_EXTRA_TIME = VERDICT_WORSE_VALUE

#: How options are ranked. Reported on the result so the UI and the prompt can
#: say which basis was used instead of assuming one.
BASIS_PER_DAY = "all_in_cost_per_day_of_cover"
BASIS_ABSOLUTE = "all_in_cost"


@dataclass(frozen=True)
class EconomicsInputs:
    """Optional measured inputs. Missing facts retain the legacy config fallback."""
    contribution_per_unit: float | None
    margin_basis: str
    carrying_rate_per_day: float
    storage_cost_per_unit_per_day: float = 0.0
    carrying_basis: str = "assumed"
    lateness_by_vendor: dict = field(default_factory=dict)
    lateness_basis_by_vendor: dict[str, str] = field(default_factory=dict)
    billing_basis_by_vendor: dict[str, str] = field(default_factory=dict)


def required_quantity(
    available_units: int,
    daily_velocity: float,
    target_cover_days: int,
    lead_time_days: int,
    fill_rate: float | None = None,
) -> int:
    """Units genuinely needed from this supplier, *before* its minimum order
    is applied.

    Separated from size_order_quantity so the gap between "what we need" and
    "what the supplier will sell us" is a single computed number rather than
    something each caller re-derives. The approval screen previously
    recomputed it by hand and drifted out of step the moment lead-time demand
    was added to the sizing -- producing a minimum-order warning on orders
    that were in fact sized exactly right.
    """
    target_position = daily_velocity * (target_cover_days + lead_time_days)
    needed = math.ceil(target_position - available_units)
    if needed <= 0:
        return 0
    if fill_rate and 0 < fill_rate < 1:
        needed = math.ceil(needed / fill_rate)
    return needed


def size_order_quantity(
    available_units: int,
    daily_velocity: float,
    target_cover_days: int,
    moq: int,
    lead_time_days: int,
    fill_rate: float | None = None,
) -> int:
    """How many units to order from one specific supplier.

    Three corrections over the naive formula, in order of how much damage
    they were doing:

    1. **Lead-time demand.** The provided build_vendor_options() sizes orders
       as ``max(moq, available_units * 0.5)`` -- keyed to how much stock
       already exists, so more stock on hand produced a *bigger* reorder.
       Our first correction replaced that with ``target_cover x velocity -
       available``, which fixed the incoherence but still sized for cover
       starting *today*. The goods only start covering demand when they
       land, so every order under-delivered its own stated target by exactly
       ``lead_time x velocity``. Measured on AC-004/DEL-01 (velocity 2.9,
       available 12, order 29): a 2-day lead time yielded 12.1 days of cover
       against a 14-day target, a 5-day lead time yielded 9.1 days and went
       *negative* before arrival. Standard practice is to size to cover
       demand during the lead time plus the target period, which is what the
       ``target_cover_days + lead_time_days`` term below does.

    2. **Expected short shipment.** ``fill_rate`` was being fetched, passed
       into the prompt and used for nothing. A 0.90 fill rate means ordering
       29 units gets you about 26 -- so the ask is grossed up by it.

    3. **MOQ as a floor, not a target.** Unchanged, but note the floor can
       exceed the need by a lot; callers surface that to the approver rather
       than absorbing it silently (see ui._approval_notes), and
       evaluate_options() refuses to credit the overshoot as coverage.

    The quantity legitimately differs per supplier: a slower supplier needs
    more units, because more stock drains before its delivery lands and the
    target is N days of cover *from arrival*, not from today. That is the
    requirement, not an artefact -- which is precisely why evaluate_options()
    must not rank suppliers on total spend. See this module's docstring.
    """
    needed = required_quantity(
        available_units, daily_velocity, target_cover_days, lead_time_days, fill_rate
    )
    # needed == 0 means nothing is genuinely required and the supplier's
    # minimum is the only reason to order at all. Callers only reach here for
    # at-risk cases, and ui._approval_notes surfaces the overshoot.
    return max(moq, needed)


@dataclass(frozen=True)
class OptionEconomics:
    offer_id: str
    vendor_name: str
    quantity: int
    unit_price: float
    total_cost: float
    lead_time_days: int
    fill_rate: Optional[float]

    # --- what the order actually delivers ---
    required_quantity: int
    moq_overbuy_units: int
    expected_delivered_units: float
    effective_cost_per_delivered_unit: float
    days_of_cover_funded: Optional[float]

    # --- the three components of the comparable figure ---
    cover_purchase_cost: float
    carrying_cost: float
    expected_stockout_cost: Optional[float]
    all_in_cost: float
    all_in_cost_per_day_of_cover: Optional[float]

    # --- risk inputs ---
    buffer_days_before_stockout: Optional[float]
    arrives_before_stockout: bool
    on_time_rate: Optional[float]
    reliability_assumed: bool
    probability_delivery_is_late: Optional[float]
    expected_days_short_if_late: float
    daily_contribution_at_risk: Optional[float]

    # --- comparison against the winner and against the cash-cheapest ---
    extra_cost_per_day_vs_best_value: Optional[float]
    extra_cost_per_day_rate_vs_best_value: Optional[float]
    extra_cost_vs_cheapest: float
    extra_buffer_days_vs_cheapest: Optional[float]

    verdict: str
    verdict_explanation: str
    margin_basis: str = "assumed"
    carrying_basis: str = "assumed"
    lateness_basis: str = "assumed"
    billing_basis: str = "assumed"

    def as_evidence(self) -> dict:
        return {
            "offer_id": self.offer_id,
            "vendor_name": self.vendor_name,
            "quantity": self.quantity,
            "unit_price": self.unit_price,
            "total_cost": self.total_cost,
            "lead_time_days": self.lead_time_days,
            "fill_rate": self.fill_rate,
            "units_actually_needed": self.required_quantity,
            "extra_units_forced_by_supplier_minimum": self.moq_overbuy_units,
            "expected_units_delivered": self.expected_delivered_units,
            "effective_cost_per_delivered_unit": self.effective_cost_per_delivered_unit,
            "days_of_cover_funded_by_this_order": self.days_of_cover_funded,
            "cover_purchase_cost": self.cover_purchase_cost,
            "carrying_cost": self.carrying_cost,
            "expected_stockout_cost": self.expected_stockout_cost,
            "all_in_cost": self.all_in_cost,
            "all_in_cost_per_day_of_cover": self.all_in_cost_per_day_of_cover,
            "buffer_days_before_stockout": self.buffer_days_before_stockout,
            "arrives_before_stockout": self.arrives_before_stockout,
            "on_time_rate": self.on_time_rate,
            "on_time_rate_is_assumed": self.reliability_assumed,
            "probability_delivery_is_late": self.probability_delivery_is_late,
            "expected_days_short_if_late": self.expected_days_short_if_late,
            "daily_contribution_at_risk": self.daily_contribution_at_risk,
            "extra_cost_per_day_vs_best_value": self.extra_cost_per_day_vs_best_value,
            "extra_cost_per_day_rate_vs_best_value": self.extra_cost_per_day_rate_vs_best_value,
            "extra_total_cash_vs_cheapest_total": self.extra_cost_vs_cheapest,
            "extra_buffer_days_vs_cheapest_total": self.extra_buffer_days_vs_cheapest,
            "verdict": self.verdict,
            "verdict_explanation": self.verdict_explanation,
            "margin_basis": self.margin_basis,
            "carrying_basis": self.carrying_basis,
            "lateness_basis": self.lateness_basis,
            "billing_basis": self.billing_basis,
        }


@dataclass(frozen=True)
class OptionsEconomics:
    #: Winner on all-in cost per day of cover. This is the one that governs.
    best_value_offer_id: str
    #: Winner on raw cash out the door. Informational only -- it is NOT the
    #: decision, because order quantities differ per supplier by design. Kept
    #: because "this is not the cheapest invoice" is still something an
    #: approver and the budget check need to know.
    cheapest_offer_id: str
    ranking_basis: str
    all_options_arrive_before_stockout: bool
    assumed_gross_margin_rate: float
    assumed_annual_carrying_rate: float
    assumed_late_days_when_late: float
    value_tolerance_rate: float
    billed_on_units_shipped: bool
    decision_rule: str
    caveats: list[str]
    options: list[OptionEconomics] = field(default_factory=list)

    def by_offer(self, offer_id: str) -> OptionEconomics | None:
        return next((o for o in self.options if o.offer_id == offer_id), None)

    def by_offer_for_proposal(self, proposal) -> OptionEconomics | None:
        """ReplenishmentProposal doesn't carry offer_id (it is built from the
        provided ReplenishmentProposal model, which we don't extend), so match
        on the fields it does carry."""
        return next(
            (
                o
                for o in self.options
                if o.quantity == proposal.quantity
                and abs(o.unit_price - proposal.unit_price) < 0.005
                and o.vendor_name == proposal.recommended_vendor_name
            ),
            None,
        )

    def acceptable_offer_ids(self) -> set[str]:
        return {o.offer_id for o in self.options if o.verdict in ACCEPTABLE_VERDICTS}

    def as_evidence(self) -> dict:
        return {
            "decision_rule": self.decision_rule,
            "ranking_basis": self.ranking_basis,
            "best_value_offer_id": self.best_value_offer_id,
            "cheapest_total_cash_offer_id": self.cheapest_offer_id,
            "all_options_arrive_before_projected_stockout": self.all_options_arrive_before_stockout,
            "assumed_gross_margin_rate": self.assumed_gross_margin_rate,
            "assumed_annual_carrying_rate": self.assumed_annual_carrying_rate,
            "assumed_late_days_when_late": self.assumed_late_days_when_late,
            "value_tolerance_rate": self.value_tolerance_rate,
            "billed_on_units_shipped": self.billed_on_units_shipped,
            "caveats": self.caveats,
            "options": [o.as_evidence() for o in self.options],
        }


DECISION_RULE = (
    "Rank on all_in_cost_per_day_of_cover, NOT on total_cost. Order quantities differ between "
    "suppliers on purpose -- the target is N days of cover once the goods land, so a slower "
    "supplier has to fund more days of demand and legitimately needs more units. Comparing raw "
    "total_cost across different-sized orders therefore compares a smaller basket with a bigger "
    "one and calls the smaller one cheaper. all_in_cost_per_day_of_cover divides each order's cost "
    "by the days of demand it actually funds, excludes any minimum-order overshoot from that "
    "coverage credit, and already includes both inventory carrying cost and each supplier's own "
    "expected stockout cost from its own on-time rate. Because delivery risk is already priced in, "
    "there is no separate 'is the premium worth it' question left to answer: the option with the "
    "lowest all_in_cost_per_day_of_cover wins. The single exception is an option within "
    "value_tolerance_rate of the winner that also arrives earlier -- verdict "
    "'within_value_tolerance' -- which you may prefer on a near-tie. The verdict field states which "
    "case each option falls into; it is computed in code and is not yours to overrule."
)


def _round(value: float | None, places: int = 2) -> float | None:
    return None if value is None else round(value, places)


def evaluate_options(risk, options: Iterable, vendor_performance=None, inputs: EconomicsInputs | None = None) -> OptionsEconomics:
    """Score every eligible option on all-in cost per day of cover.

    `risk` is a StockRisk, `options` are VendorOption records already sized
    and priced by deterministic code, `vendor_performance` is the
    VendorPerformanceList so each option's real on_time_rate and fill_rate can
    be used rather than the blended pass/fail flag.
    """
    options = list(options)
    if not options:
        raise ValueError("evaluate_options requires at least one option")

    margin_rate = config.assumed_gross_margin_rate
    carrying_rate_per_day = inputs.carrying_rate_per_day if inputs else config.assumed_annual_carrying_rate / 365.0
    late_days = config.assumed_late_days_when_late
    tolerance = config.vendor_value_tolerance_rate
    billed_on_shipped = config.vendor_billed_on_units_shipped

    performance = getattr(vendor_performance, "vendors", None) or []
    on_time_by_vendor = {v.vendor_id: v.on_time_rate for v in performance}
    fill_by_vendor = {v.vendor_id: v.fill_rate for v in performance}

    velocity = risk.daily_velocity or 0.0

    def buffer_days(option) -> float | None:
        if not risk.projected_stockout_date or not option.expected_arrival:
            return None
        return (risk.projected_stockout_date - option.expected_arrival).total_seconds() / 86400

    # Contribution per unit is a property of the PRODUCT, not of whichever
    # supplier we happen to buy from: the money lost to an empty shelf is the
    # same either way. So the cost basis is fixed once, from the lowest unit
    # price available, and every option is valued against that same figure.
    # (Deriving it per-option from that option's own price made a dearer
    # supplier appear to protect more value, which is backwards -- it would
    # have let an expensive option partly justify itself.)
    def landed_cost(option) -> float:
        return option.unit_price + (getattr(option, "freight_per_unit", None) or 0) + (getattr(option, "freight_flat", None) or 0) / max(option.quantity, 1)

    cost_basis = min(landed_cost(option) for option in options)
    contribution = inputs.contribution_per_unit if inputs and inputs.contribution_per_unit is not None else cost_basis * margin_rate
    daily_contribution = round(velocity * contribution, 2) if velocity else None

    # Retained for the approval screen and the budget conversation only. Not
    # the ranking basis -- see the module docstring for why that was a bug.
    cheapest_cash = min(options, key=lambda o: o.total_cost)
    cheapest_cash_buffer = buffer_days(cheapest_cash)

    computed: list[dict] = []
    for option in options:
        option_landed_cost = landed_cost(option)
        late_distribution = inputs.lateness_by_vendor.get(option.vendor_id) if inputs else None
        option_late_days = late_distribution.mean_late_days if late_distribution else late_days
        option_billed_on_shipped = (inputs.billing_basis_by_vendor.get(option.vendor_id) == "SHIPPED") if inputs and option.vendor_id in inputs.billing_basis_by_vendor else billed_on_shipped
        fill = fill_by_vendor.get(option.vendor_id)
        effective_fill = fill if (fill and 0 < fill <= 1) else 1.0

        needed = required_quantity(
            risk.available_units,
            risk.daily_velocity,
            risk.target_cover_days,
            option.lead_time_days,
            fill,
        )
        overbuy = max(0, option.quantity - needed)
        cover_units_ordered = option.quantity - overbuy

        expected_delivered = round(option.quantity * effective_fill, 2)
        # Units that actually fund the coverage target. The minimum-order
        # overshoot is deliberately excluded: crediting it would let a
        # supplier with a 200-unit minimum win by handing us two months of
        # stock nobody asked for.
        cover_units_delivered = cover_units_ordered * effective_fill
        days_funded = (cover_units_delivered / velocity) if velocity > 0 else None

        # What is invoiced. Units shipped vs units ordered is a declared
        # assumption (config.vendor_billed_on_units_shipped) because the
        # schema carries no billing terms; at a 0.94 fill rate the two
        # readings differ by hundreds of dollars on a single order.
        billed_cover_units = cover_units_delivered if option_billed_on_shipped else cover_units_ordered
        billed_overbuy_units = overbuy * effective_fill if option_billed_on_shipped else overbuy
        cover_purchase_cost = round(billed_cover_units * option_landed_cost, 2)

        # Carrying cost. Linear depletion, so the cover portion is held for
        # half the days it funds. The overshoot sits through that whole period
        # AND half of its own consumption run on top, which is what stops a
        # large minimum order from looking free once its price is excluded
        # from the coverage numerator.
        avg_days_held = (days_funded / 2) if days_funded else 0.0
        storage_rate = inputs.storage_cost_per_unit_per_day if inputs else 0.0
        cover_carrying = billed_cover_units * (option_landed_cost * carrying_rate_per_day + storage_rate) * avg_days_held
        overbuy_days_held = (
            (days_funded or 0.0) + (overbuy / velocity / 2 if velocity > 0 else 0.0)
        )
        overbuy_carrying = (
            billed_overbuy_units * (option_landed_cost * carrying_rate_per_day + storage_rate) * overbuy_days_held
        )
        carrying_cost = round(cover_carrying + overbuy_carrying, 2)

        # Expected stockout cost, per option, from that option's own record.
        # A missing on-time figure falls back to the eligibility floor the
        # option had to clear to get here -- conservative, and flagged rather
        # than silently treated as perfect.
        measured_on_time = on_time_by_vendor.get(option.vendor_id)
        reliability_assumed = measured_on_time is None
        on_time = config.vendor_reliability_min if reliability_assumed else measured_on_time
        p_late = round(max(0.0, 1.0 - on_time), 4)
        buf = buffer_days(option)
        slack = max(0.0, buf) if buf is not None else 0.0
        days_short = max(0.0, option_late_days - slack)
        expected_stockout_cost = (
            round(p_late * days_short * velocity * contribution, 2)
            if velocity
            else None
        )

        all_in = round(cover_purchase_cost + carrying_cost + (expected_stockout_cost or 0.0), 2)
        per_day = round(all_in / days_funded, 2) if days_funded and days_funded > 0 else None

        computed.append(
            {
                "option": option,
                "fill": fill,
                "needed": needed,
                "overbuy": overbuy,
                "expected_delivered": expected_delivered,
                "effective_unit_cost": round(option_landed_cost / effective_fill, 2),
                "days_funded": _round(days_funded),
                "cover_purchase_cost": cover_purchase_cost,
                "carrying_cost": carrying_cost,
                "expected_stockout_cost": expected_stockout_cost,
                "all_in": all_in,
                "per_day": per_day,
                "buf": buf,
                "on_time": measured_on_time,
                "reliability_assumed": reliability_assumed,
                "p_late": p_late,
                "days_short": round(days_short, 2),
                "margin_basis": inputs.margin_basis if inputs and inputs.contribution_per_unit is not None else "assumed",
                "carrying_basis": inputs.carrying_basis if inputs else "assumed",
                "lateness_basis": inputs.lateness_basis_by_vendor.get(option.vendor_id, "assumed") if inputs else "assumed",
                "billing_basis": "measured" if inputs and option.vendor_id in inputs.billing_basis_by_vendor else "assumed",
            }
        )

    # Rank per day of cover when every option funds a measurable number of
    # days. It degrades to absolute all-in cost only in the degenerate case
    # where an order funds no coverage at all (a pure minimum-order buy, or a
    # zero-velocity product) -- reported on the result rather than assumed, so
    # the prompt and the UI can say which basis was used.
    per_day_available = all(c["per_day"] is not None for c in computed)
    ranking_basis = BASIS_PER_DAY if per_day_available else BASIS_ABSOLUTE
    score_key = "per_day" if per_day_available else "all_in"
    best = min(computed, key=lambda c: c[score_key])
    best_score = best[score_key]
    best_option = best["option"]

    def arrives_earlier_than_best(option) -> bool:
        if option.expected_arrival and best_option.expected_arrival:
            return option.expected_arrival < best_option.expected_arrival
        return option.lead_time_days < best_option.lead_time_days

    scored: list[OptionEconomics] = []
    for c in computed:
        option = c["option"]
        gap = round(c[score_key] - best_score, 2)
        gap_rate = round(gap / best_score, 4) if best_score else None
        buf = c["buf"]
        extra_cash = round(option.total_cost - cheapest_cash.total_cost, 2)
        extra_buffer_vs_cash = (
            None if buf is None or cheapest_cash_buffer is None else buf - cheapest_cash_buffer
        )
        per_day_text = (
            f"${c['per_day']:,.2f} per day of cover"
            if c["per_day"] is not None
            else f"${c['all_in']:,.2f} all-in"
        )

        if option.offer_id == best_option.offer_id:
            verdict = VERDICT_BEST_VALUE
            days_text = (
                f"{c['days_funded']:.1f} day(s)" if c["days_funded"] is not None else "no days"
            )
            explanation = (
                f"Best value: {per_day_text}, the lowest of the eligible options. "
                f"{option.quantity} units at ${option.unit_price:,.2f} funds {days_text} of "
                f"demand (${c['effective_unit_cost']:,.2f} per unit actually delivered, after a "
                f"{(c['fill'] or 1.0):.0%} fill rate)."
            )
        elif gap <= 0.005:
            # Exact tie on the ranking metric. Not the designated winner, but
            # nothing separates them, so refusing it would be arbitrary.
            verdict = VERDICT_WITHIN_TOLERANCE
            explanation = (
                f"Ties the best option at {per_day_text}. Nothing separates them on cost, so "
                f"either is a defensible choice."
            )
        elif gap_rate is not None and gap_rate <= tolerance and arrives_earlier_than_best(option):
            verdict = VERDICT_WITHIN_TOLERANCE
            explanation = (
                f"{per_day_text}, ${gap:,.2f} ({gap_rate:.1%}) above the best option -- within the "
                f"{tolerance:.0%} tolerance -- and it arrives earlier "
                f"({option.lead_time_days}d vs {best_option.lead_time_days}d lead time). Close "
                f"enough on cost that the earlier arrival is a reasonable preference."
            )
        else:
            verdict = VERDICT_WORSE_VALUE
            earlier = arrives_earlier_than_best(option)
            timing = (
                f"It does arrive earlier ({option.lead_time_days}d vs "
                f"{best_option.lead_time_days}d), but that is worth less than the gap: the "
                f"expected cost of a late delivery is already counted in both figures "
                f"(${c['expected_stockout_cost']:,.2f} here"
                if earlier and c["expected_stockout_cost"] is not None
                else "It arrives no earlier than the best option"
            )
            explanation = (
                f"{per_day_text} against {best_option.vendor_name}'s "
                f"${best_score:,.2f}"
                + (f" -- ${gap:,.2f} ({gap_rate:.1%}) worse" if gap_rate is not None else "")
                + ". "
                + timing
                + (")." if earlier and c["expected_stockout_cost"] is not None else ".")
                + " Delivery risk is already inside these numbers, so there is no premium left to"
                " justify."
            )

        scored.append(
            OptionEconomics(
                offer_id=option.offer_id,
                vendor_name=option.vendor_name,
                quantity=option.quantity,
                unit_price=option.unit_price,
                total_cost=option.total_cost,
                lead_time_days=option.lead_time_days,
                fill_rate=c["fill"],
                required_quantity=c["needed"],
                moq_overbuy_units=c["overbuy"],
                expected_delivered_units=c["expected_delivered"],
                effective_cost_per_delivered_unit=c["effective_unit_cost"],
                days_of_cover_funded=c["days_funded"],
                cover_purchase_cost=c["cover_purchase_cost"],
                carrying_cost=c["carrying_cost"],
                expected_stockout_cost=c["expected_stockout_cost"],
                all_in_cost=c["all_in"],
                all_in_cost_per_day_of_cover=c["per_day"],
                buffer_days_before_stockout=_round(buf),
                arrives_before_stockout=bool(buf is not None and buf >= 0),
                on_time_rate=c["on_time"],
                reliability_assumed=c["reliability_assumed"],
                probability_delivery_is_late=c["p_late"],
                expected_days_short_if_late=c["days_short"],
                daily_contribution_at_risk=daily_contribution,
                extra_cost_per_day_vs_best_value=(None if gap <= 0 else gap),
                extra_cost_per_day_rate_vs_best_value=(
                    None if gap <= 0 or gap_rate is None else gap_rate
                ),
                extra_cost_vs_cheapest=extra_cash,
                extra_buffer_days_vs_cheapest=_round(extra_buffer_vs_cash),
                verdict=verdict,
                verdict_explanation=explanation,
                margin_basis=c["margin_basis"], carrying_basis=c["carrying_basis"], lateness_basis=c["lateness_basis"], billing_basis=c["billing_basis"],
            )
        )

    caveats = []
    if not inputs or any(c["margin_basis"] == "assumed" for c in computed):
        caveats.append(f"Contribution per unit uses the {margin_rate:.0%} configured margin fallback where selling-price data is unavailable.")
    if not inputs or any(c["carrying_basis"] == "assumed" for c in computed):
        caveats.append(f"Carrying cost uses the {config.assumed_annual_carrying_rate:.0%} annual configured fallback where finance or storage data is unavailable.")
    if not inputs or any(c["lateness_basis"] == "assumed" for c in computed):
        caveats.append(f"Delivery risk uses the configured {late_days:g}-day lateness fallback where receipt history is insufficient.")
    if not inputs or any(c["billing_basis"] == "assumed" for c in computed):
        caveats.append(f"Suppliers are assumed to invoice for units {'shipped' if billed_on_shipped else 'ordered'} where billing terms are unavailable.")
    if any(c["reliability_assumed"] for c in computed):
        caveats.append(
            f"At least one supplier has no on-time record; the "
            f"{config.vendor_reliability_min:.0%} eligibility floor was used in its place."
        )

    return OptionsEconomics(
        best_value_offer_id=best_option.offer_id,
        cheapest_offer_id=cheapest_cash.offer_id,
        ranking_basis=ranking_basis,
        all_options_arrive_before_stockout=all(o.arrives_before_stockout for o in scored),
        assumed_gross_margin_rate=margin_rate,
        assumed_annual_carrying_rate=config.assumed_annual_carrying_rate,
        assumed_late_days_when_late=late_days,
        value_tolerance_rate=tolerance,
        billed_on_units_shipped=billed_on_shipped,
        decision_rule=DECISION_RULE,
        caveats=caveats,
        options=scored,
    )
