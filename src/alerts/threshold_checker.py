"""Threshold checker — evaluate data against profile-defined thresholds.

Pure-function module with no side effects.  The caller (store hooks,
cron jobs, or ingest pipeline) decides what to do with breaches.

Threshold definitions live in profile ``signal.thresholds``:

    "signal": {
        "thresholds": [
            {"field": "rsi_14", "op": "<", "value": 30,
             "severity": "high", "label": "RSI oversold"},
            {"field": "close", "op": ">", "value": 200,
             "severity": "medium", "label": "Price above 200"},
        ]
    }

Supported operators: <, >, <=, >=, ==, !=, absent (field missing).
"""
from __future__ import annotations

import logging
import operator
from typing import Any

log = logging.getLogger("augur.alerts.threshold")

_OPS: dict[str, Any] = {
    "<": operator.lt,
    ">": operator.gt,
    "<=": operator.le,
    ">=": operator.ge,
    "==": operator.eq,
    "!=": operator.ne,
}

_VALID_SEVERITIES = frozenset({"low", "medium", "high", "critical"})


def _get_nested(data: dict, field: str) -> Any:
    """Resolve a dot-notation field path in nested dicts.

    Returns _MISSING sentinel if not found.
    """
    parts = field.split(".")
    current = data
    for part in parts:
        if isinstance(current, dict) and part in current:
            current = current[part]
        else:
            return _MISSING
    return current


class _MissingSentinel:
    """Sentinel for missing fields (distinct from None)."""
    def __repr__(self):
        return "<MISSING>"


_MISSING = _MissingSentinel()


def check_thresholds(
    data: dict,
    thresholds: list[dict],
) -> list[dict]:
    """Evaluate data against a list of threshold definitions.

    Args:
        data: The snapshot or event data payload.
        thresholds: List of threshold dicts, each with:
            field (str): Dot-notation path in data.
            op (str): Comparison operator (<, >, <=, >=, ==, !=, absent).
            value: The threshold value to compare against.
            severity (str): low/medium/high/critical.
            label (str): Human-readable description.

    Returns:
        List of breach dicts for thresholds that were triggered.
        Each breach contains: field, op, threshold, actual, severity, label.
    """
    breaches = []
    for t in thresholds:
        field = t.get("field", "")
        op_str = t.get("op", "")
        threshold_value = t.get("value")
        severity = t.get("severity", "medium")
        label = t.get("label", f"{field} {op_str} {threshold_value}")

        if not field:
            log.warning("threshold missing 'field': %s", t)
            continue

        actual = _get_nested(data, field)

        # Handle "absent" operator
        if op_str == "absent":
            if actual is _MISSING:
                breaches.append({
                    "field": field,
                    "op": "absent",
                    "threshold": None,
                    "actual": None,
                    "severity": severity,
                    "label": label,
                })
            continue

        # For all other ops, skip if field is missing
        if actual is _MISSING:
            continue

        # Resolve operator
        op_fn = _OPS.get(op_str)
        if op_fn is None:
            log.warning("unknown operator '%s' in threshold: %s", op_str, t)
            continue

        # Compare (handle type mismatches gracefully)
        try:
            if op_fn(actual, threshold_value):
                breaches.append({
                    "field": field,
                    "op": op_str,
                    "threshold": threshold_value,
                    "actual": actual,
                    "severity": severity,
                    "label": label,
                })
        except TypeError:
            log.warning("type mismatch comparing %s (%s) %s %s (%s)",
                        field, type(actual).__name__, op_str,
                        threshold_value, type(threshold_value).__name__)

    return breaches


def get_thresholds_from_profile(profile: dict) -> list[dict]:
    """Extract threshold definitions from a profile's signal.thresholds field."""
    return profile.get("signal", {}).get("thresholds", [])


def max_severity(breaches: list[dict]) -> str:
    """Return the highest severity from a list of breaches."""
    order = {"low": 0, "medium": 1, "high": 2, "critical": 3}
    if not breaches:
        return "low"
    return max(breaches, key=lambda b: order.get(b.get("severity", "low"), 0))["severity"]
