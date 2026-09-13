from datetime import date

from submission.config import config


def assess_maturity(first_sale_date: date | None, as_of: date, nonzero_observations: int) -> tuple[str, float]:
    if first_sale_date is None or first_sale_date > as_of:
        return "INSUFFICIENT", 0.0
    months = (as_of.year - first_sale_date.year) * 12 + as_of.month - first_sale_date.month
    tier = "INSUFFICIENT" if months < 3 else "PROVISIONAL" if months < 12 else "ESTABLISHED"
    confidence = min(1.0, max(0, nonzero_observations) / config.maturity_confidence_full_at_observations)
    return tier, confidence
