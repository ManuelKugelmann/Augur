"""Horizon date computation and section labels."""

from __future__ import annotations

from datetime import datetime, timedelta
from dateutil.relativedelta import relativedelta


def compute_fictive_date(horizon: str, anchor: datetime | None = None) -> str:
    """Compute the fictive prediction date for a given horizon."""
    d = anchor or datetime.utcnow()
    if horizon == "tomorrow":
        d += timedelta(days=1)
    elif horizon == "soon":
        d += relativedelta(months=1)
    elif horizon == "future":
        d += relativedelta(years=1)
    return d.strftime("%Y-%m-%d")


def today_key() -> str:
    return datetime.utcnow().strftime("%Y-%m-%d")


SECTION_LABELS = {
    "en": {
        "signal": "The Signal",
        "extrapolation": "The Extrapolation",
        "in_the_works": "In The Works",
        "sources": "Sources",
        "sentiment": "The Augur's Sentiment",
        "foreseen_for": "Foreseen for",
        "divined": "Divined",
    },
    "de": {
        "signal": "Das Signal",
        "extrapolation": "Die Extrapolation",
        "in_the_works": "In Arbeit",
        "sources": "Quellen",
        "sentiment": "Die Einschätzung des Augur",
        "foreseen_for": "Vorhergesagt für",
        "divined": "Erstellt",
    },
}
