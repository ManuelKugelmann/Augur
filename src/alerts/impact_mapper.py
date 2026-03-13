"""Event-to-profile impact mapper — auto-tag entities when events hit a country.

When a high/critical event with ``countries`` is stored, this module
queries profiles that have exposure to those countries and creates
impact snapshots linking the event to affected entities.

Pure-function design: receives store callables, no global state.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

log = logging.getLogger("augur.alerts.impact")

# Profile kinds that carry exposure.countries
_EXPOSURE_KINDS = ("stocks", "etfs", "crypto", "commodities", "crops",
                   "materials", "products", "companies")

# Only propagate impact for these severity levels
_PROPAGATE_SEVERITIES = frozenset({"high", "critical"})


def find_exposed_profiles(
    countries: list[str],
    search_profiles_fn,
    *,
    kinds: tuple[str, ...] = _EXPOSURE_KINDS,
) -> list[dict]:
    """Find profiles with exposure.countries matching any of the given countries.

    Args:
        countries: List of ISO3 country codes from the event.
        search_profiles_fn: Callable(kind, field, value) -> list[dict].
        kinds: Profile kinds to search across.

    Returns:
        List of dicts with keys: kind, id, name, matched_countries.
    """
    if not countries:
        return []

    exposed = []
    seen = set()

    for country in countries:
        for kind in kinds:
            try:
                matches = search_profiles_fn(kind, "exposure.countries", country)
            except Exception as e:
                log.warning("search failed kind=%s country=%s: %s", kind, country, e)
                continue

            for profile in matches:
                pid = profile.get("id", "")
                key = (kind, pid)
                if key in seen:
                    # Already found this profile — add the country to matched set
                    for ep in exposed:
                        if ep["kind"] == kind and ep["id"] == pid:
                            ep["matched_countries"].append(country)
                            break
                    continue
                seen.add(key)
                exposed.append({
                    "kind": kind,
                    "id": pid,
                    "name": profile.get("name", pid),
                    "matched_countries": [country],
                })

    return exposed


def propagate_event_impact(
    event_meta: dict,
    event_summary: str,
    event_data: dict,
    *,
    search_profiles_fn,
    snapshot_fn,
    event_id: str = "",
) -> list[dict]:
    """After an event is stored, create impact snapshots for exposed profiles.

    Only runs for high/critical severity events with country associations.

    Args:
        event_meta: The event's meta dict (subtype, severity, countries, etc.).
        event_summary: The event summary text.
        event_data: The event data payload.
        search_profiles_fn: store.search_profiles callable.
        snapshot_fn: store.snapshot callable.
        event_id: The stored event's MongoDB ID (for cross-reference).

    Returns:
        List of impact records created.
    """
    severity = event_meta.get("severity", "medium")
    if severity not in _PROPAGATE_SEVERITIES:
        return []

    countries = event_meta.get("countries", [])
    if not countries:
        return []

    exposed = find_exposed_profiles(countries, search_profiles_fn)
    if not exposed:
        return []

    impacts = []
    for profile in exposed:
        impact_data = {
            "event_id": event_id,
            "event_subtype": event_meta.get("subtype", ""),
            "event_severity": severity,
            "event_summary": event_summary[:500],
            "matched_countries": profile["matched_countries"],
            "entity_name": profile["name"],
        }

        try:
            snapshot_fn(
                kind=profile["kind"],
                entity=profile["id"],
                type="impact",
                data=impact_data,
                source="impact_mapper",
            )
            impacts.append({
                "kind": profile["kind"],
                "id": profile["id"],
                "name": profile["name"],
                "matched_countries": profile["matched_countries"],
            })
            log.info("impact: %s/%s exposed via %s",
                     profile["kind"], profile["id"],
                     profile["matched_countries"])
        except Exception as e:
            log.warning("failed to store impact for %s/%s: %s",
                        profile["kind"], profile["id"], e)

    return impacts


def should_propagate(severity: str) -> bool:
    """Check if an event severity warrants impact propagation."""
    return severity in _PROPAGATE_SEVERITIES
