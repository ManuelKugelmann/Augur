"""MCP Signals Store — MongoDB-backed profile/snapshot store.

Profiles: MongoDB collections ``profiles_{kind}`` (one per kind).
  Shared across all users. Text + geo indexes for fast search.

Snapshots: Per-kind timeseries collections with geo support:
  snap_{kind}  — recent data, 1-year TTL, hours granularity
  arch_{kind}  — long-term archive, no TTL, days granularity
  events       — cross-kind signal events, 1-year TTL

All snapshot/event docs share: ts (datetime), meta (entity, kind, region,
type, source), data (payload), location (optional GeoJSON Point).

When running behind LibreChat via streamable-http, X-User-ID / X-User-Email
headers are injected per request and stored in snapshot/event meta.
"""
from fastmcp import FastMCP
from pymongo import MongoClient
from pathlib import Path
from collections import defaultdict
from datetime import datetime, timezone, timedelta
import json
import logging
import os
import re

log = logging.getLogger("augur.store")

try:
    from bson import ObjectId
except ImportError:
    ObjectId = None  # type: ignore[misc,assignment]

from dotenv import load_dotenv
load_dotenv()

mcp = FastMCP("signals-store", instructions="MongoDB-backed profile/snapshot store")

_client = None
_cols_ready = set()

VALID_KINDS = frozenset({
    "countries", "stocks", "etfs", "crypto", "indices", "sources",
    "commodities", "crops", "materials", "products", "companies",
    "regions",
})

VALID_REGIONS = frozenset({
    "north_america", "latin_america", "europe", "mena",
    "sub_saharan_africa", "south_asia", "east_asia",
    "southeast_asia", "central_asia", "oceania",
    "arctic", "antarctic", "global",
})

SNAPSHOTS_TTL = 365 * 86400         # 1 year

_SAFE_ID = re.compile(r'^[A-Za-z0-9_-]+$')
_SAFE_FIELD = re.compile(r'^[A-Za-z0-9_][A-Za-z0-9_.]*$')

# ── Post-hooks for snapshot and event insertion ──────
# Lazy-loaded to avoid hard dependency on alerts module in tests.

_hooks_loaded = False


def _load_hooks():
    """Import threshold checker and impact mapper if available."""
    global _hooks_loaded
    if _hooks_loaded:
        return
    _hooks_loaded = True
    try:
        import sys
        alerts_path = str(Path(__file__).resolve().parent.parent / "alerts")
        if alerts_path not in sys.path:
            sys.path.insert(0, alerts_path)
        from threshold_checker import check_thresholds, get_thresholds_from_profile, max_severity
        from impact_mapper import propagate_event_impact, should_propagate
        globals()["_threshold_checker"] = {
            "check": check_thresholds,
            "get_thresholds": get_thresholds_from_profile,
            "max_severity": max_severity,
        }
        globals()["_impact_mapper"] = {
            "propagate": propagate_event_impact,
            "should_propagate": should_propagate,
        }
    except ImportError:
        pass  # alerts module not available — hooks disabled


def _run_snapshot_threshold_hook(kind: str, entity: str, data: dict):
    """Check entity profile thresholds after snapshot insertion."""
    _load_hooks()
    tc = globals().get("_threshold_checker")
    if not tc:
        return
    try:
        profile = get_profile(kind, entity)
        if "error" in profile:
            return
        thresholds = tc["get_thresholds"](profile)
        if not thresholds:
            return
        breaches = tc["check"](data, thresholds)
        if not breaches:
            return
        severity = tc["max_severity"](breaches)
        labels = [b["label"] for b in breaches]
        event(
            subtype="threshold_breach",
            summary=f"{entity}: {', '.join(labels)}",
            data={"entity": entity, "kind": kind, "breaches": breaches},
            severity=severity,
            entities=[entity],
            source="threshold_checker",
        )
    except Exception as e:
        import logging
        logging.getLogger("augur.store").warning(
            "threshold hook error %s/%s: %s", kind, entity, e)


def _run_event_impact_hook(event_meta: dict, event_summary: str,
                           event_data: dict, event_id: str):
    """Propagate impact to exposed profiles after event insertion."""
    _load_hooks()
    im = globals().get("_impact_mapper")
    if not im:
        return
    if not im["should_propagate"](event_meta.get("severity", "medium")):
        return
    try:
        im["propagate"](
            event_meta, event_summary, event_data,
            search_profiles_fn=search_profiles,
            snapshot_fn=snapshot,
            event_id=event_id,
        )
    except Exception as e:
        import logging
        logging.getLogger("augur.store").warning(
            "impact hook error: %s", e)


# ── User context helper ──────────────────────────


def _get_user_id() -> str:
    """Return the LibreChat user ID from HTTP headers (streamable-http)
    or LIBRECHAT_USER_ID env var (stdio fallback). Empty string if unavailable."""
    try:
        from fastmcp.server.dependencies import get_http_headers
        headers = get_http_headers()
        uid = headers.get("x-user-id", "")
        if uid:
            return uid
    except (RuntimeError, ImportError):
        pass
    return os.environ.get("LIBRECHAT_USER_ID", "")


# ── MongoDB helpers ───────────────────────────────


def _db():
    global _client
    if not _client:
        uri = os.environ.get("MONGO_URI_SIGNALS") or os.environ.get("MONGO_URI", "")
        if not uri:
            raise RuntimeError(
                "MONGO_URI_SIGNALS not set — set it in .env or environment. "
                "Do NOT reuse LibreChat's MONGO_URI (different database).")
        try:
            _client = MongoClient(uri, serverSelectionTimeoutMS=5000)
        except Exception as e:
            raise RuntimeError(f"MongoDB connection failed: {e}") from e
    # Use database name from URI path if present, otherwise default to 'signals'
    try:
        return _client.get_default_database()
    except Exception:
        return _client.signals


def _ensure_ts(name: str, ttl: int | None = None, granularity: str = "hours"):
    """Auto-create a timeseries collection if it doesn't exist."""
    global _cols_ready
    if name in _cols_ready:
        return
    db = _db()
    if name not in db.list_collection_names():
        opts: dict = {
            "timeseries": {
                "timeField": "ts",
                "metaField": "meta",
                "granularity": granularity,
            },
        }
        if ttl is not None:
            opts["expireAfterSeconds"] = ttl
        db.create_collection(name, **opts)
    _cols_ready.add(name)


def _profiles_col(kind: str):
    """Return the profiles collection for a kind. Auto-creates indexes."""
    name = f"profiles_{kind}"
    if name not in _cols_ready:
        col = _db()[name]
        try:
            col.create_index("_id_str", unique=True, background=True)
            col.create_index([("location", "2dsphere")],
                             background=True, sparse=True)
            col.create_index([
                ("name", "text"),
                ("tags", "text"),
                ("sector", "text"),
            ], background=True, default_language="english")
            col.create_index("region", background=True)
            col.create_index("tags", background=True)
        except Exception as e:
            log.debug("index creation skipped for %s: %s", name, e)
        _cols_ready.add(name)
        return col
    return _db()[name]


def _snap_col(kind: str):
    """Return the snapshots collection for a kind (1-year TTL)."""
    name = f"snap_{kind}"
    _ensure_ts(name, ttl=SNAPSHOTS_TTL)
    col = _db()[name]
    if f"{name}_geo" not in _cols_ready:
        try:
            col.create_index([("location", "2dsphere")], background=True)
        except Exception as e:
            log.debug("geo index skipped for %s: %s", name, e)
        _cols_ready.add(f"{name}_geo")
    return col


def _arch_col(kind: str):
    """Return the archive collection for a kind (no TTL)."""
    name = f"arch_{kind}"
    _ensure_ts(name, granularity="hours")
    return _db()[name]


def _events_col():
    """Return the cross-kind events collection."""
    _ensure_ts("events", ttl=SNAPSHOTS_TTL)
    col = _db().events
    if "events_geo" not in _cols_ready:
        try:
            col.create_index([("location", "2dsphere")], background=True)
        except Exception as e:
            log.debug("geo index skipped for events: %s", e)
        _cols_ready.add("events_geo")
    return col


def _ser(doc: dict) -> dict:
    doc["_id"] = str(doc.get("_id", ""))
    for k in ("ts",):
        if isinstance(doc.get(k), datetime):
            doc[k] = doc[k].isoformat()
    if "meta" in doc:
        meta = doc.pop("meta")
        for k, v in meta.items():
            if k not in doc:
                doc[k] = v
    return doc


def _parse_ts(iso_str: str) -> datetime | None:
    """Parse ISO date string safely. Returns None on invalid input."""
    try:
        return datetime.fromisoformat(iso_str)
    except (ValueError, TypeError):
        return None


# ── Profile validation helpers ────────────────────


def _validate_profile_args(kind: str, id: str, region: str = "") -> dict | None:
    """Validate kind/id/region. Returns error dict or None if valid."""
    if not _SAFE_ID.match(id):
        return {"error": f"invalid id: {id} (only A-Z, a-z, 0-9, _, -)"}
    if kind not in VALID_KINDS:
        return {"error": f"unknown kind: {kind}, valid: {sorted(VALID_KINDS)}"}
    if region and not _SAFE_ID.match(region):
        return {"error": f"invalid region: {region}"}
    return None


# ── Seed helper (install-time only) ──────────────


def seed_profiles(profiles_dir: str, clear: bool = False) -> dict:
    """Bulk-load profile JSON files from a directory into MongoDB.

    Used during install to populate profiles_{kind} collections.
    Uses upsert so existing data is never overwritten (only new profiles added).
    The source directory can be cleaned up after seeding.

    Args:
        profiles_dir: Path to directory with {region}/{kind}/{id}.json layout.
        clear: If True, drop collections first (reinit).

    Returns: {kind: {seeded: N, skipped: N}} summary.
    """
    pdir = Path(profiles_dir)
    if not pdir.exists():
        return {"error": f"profiles directory not found: {pdir}"}

    results: dict = {}
    errors: list[str] = []
    for kind in sorted(VALID_KINDS):
        seeded = 0
        skipped = 0
        col = _profiles_col(kind)

        if clear:
            col.drop()
            _cols_ready.discard(f"profiles_{kind}")
            col = _profiles_col(kind)

        for region_dir in sorted(pdir.iterdir()):
            if not region_dir.is_dir() or region_dir.name not in VALID_REGIONS:
                continue
            kind_dir = region_dir / kind
            if not kind_dir.is_dir():
                continue
            for fpath in sorted(kind_dir.glob("*.json")):
                if fpath.stem.startswith("_"):
                    continue
                try:
                    data = json.loads(fpath.read_text())
                    profile_id = fpath.stem
                    if not _SAFE_ID.match(profile_id):
                        errors.append(f"{fpath.name}: invalid ID '{profile_id}'")
                        continue
                    doc = {
                        "_id_str": profile_id,
                        "kind": kind,
                        "region": region_dir.name,
                        **data,
                    }
                    if clear:
                        col.insert_one(doc)
                        seeded += 1
                    else:
                        r = col.update_one(
                            {"_id_str": profile_id},
                            {"$setOnInsert": doc},
                            upsert=True,
                        )
                        if r.upserted_id:
                            seeded += 1
                        else:
                            skipped += 1
                except Exception as exc:
                    errors.append(f"{fpath.name}: {exc}")
        if seeded or skipped:
            results[kind] = {"seeded": seeded, "skipped": skipped}
    if errors:
        results["_errors"] = errors
    return results


# ── Schema + lint helpers ─────────────────────────

# Minimal required fields: just identifiers. Extra fields (including freeform 'notes') always allowed.
_REQUIRED_FIELDS: dict[str, list[str]] = {k: ["id", "name"] for k in VALID_KINDS}


def _lint_one(kind: str, id: str, data: dict) -> list[str]:
    """Lint a single profile against required fields. Returns list of issue strings."""
    required = _REQUIRED_FIELDS.get(kind, [])
    return [f"missing required field: {f}" for f in required if f not in data]


# ── Profile tools ─────────────────────────────────
# Profiles stored in MongoDB: profiles_{kind} collections.
# API: kind + id identify a profile. region optional for reads, default global for writes.
# Geo: optional location field with 2dsphere index.


def _strip_mongo_id(doc: dict) -> dict:
    """Remove MongoDB _id and rename _id_str→id for clean output."""
    doc.pop("_id", None)
    if "_id_str" in doc:
        doc["id"] = doc.pop("_id_str")
    return doc


@mcp.tool()
def get_profile(kind: str, id: str, region: str = "") -> dict:
    """Read a profile by kind and id. Optionally filter by region."""
    err = _validate_profile_args(kind, id, region)
    if err:
        return err
    q: dict = {"_id_str": id}
    if region:
        q["region"] = region
    doc = _profiles_col(kind).find_one(q)
    if not doc:
        return {"error": f"not found: {kind}/{id}"}
    return _strip_mongo_id(doc)


@mcp.tool()
def put_profile(kind: str, id: str, data: dict,
                region: str = "global",
                lon: float | None = None,
                lat: float | None = None) -> dict:
    """Create or merge a profile. Shallow-merges with existing data.

    Required: id, name. All other fields optional. Recommended structure per kind:

    countries: iso2, region, currency, capital, population,
        trade{top_exports, top_partners, major_ports, chokepoint_exposure},
        exposure{commodities_import, energy_mix, risk_factors},
        ratings{credit, democracy_index}, tags
    stocks: type="stock", exchange, sector, industry, country,
        fundamentals{founded, employees},
        exposure{countries, commodities, supply_chain, risk_factors}, tags
    etfs: type="etf", exchange, issuer, strategy,
        exposure{countries, sectors, commodities, risk_factors}, tags
    crypto: type="crypto", network, consensus, max_supply,
        exposure{countries, risk_factors}, tags
    indices: type="index", country, exchange, components, methodology,
        exposure{sectors, countries, risk_factors}, tags
    commodities: category (energy|metals|agriculture|livestock), unit, benchmark,
        producers[], consumers[], chokepoints[], seasonality,
        exposure{countries, risk_factors}, tags
    crops: category (grains|oilseeds|fibers|sugar|fruits|vegetables),
        growing_season, producers[], exporters[], water_intensity,
        exposure{countries, commodities, risk_factors}, tags
    materials: category (metals|minerals|chemicals|forestry|textiles),
        producers[], reserves[], processing[], end_uses[], substitutes[],
        exposure{countries, risk_factors}, tags
    products: category (electronics|energy|pharma|automotive|industrial|consumer),
        hs_codes[], manufacturers[], inputs[], trade_volume,
        exposure{countries, materials, commodities, risk_factors}, tags
    companies: country, sector, industry, revenue, employees,
        publicly_traded, ticker, subsidiaries[],
        exposure{countries, products, materials, risk_factors}, tags
    sources: mcp, tool, api_base, auth (none|api_key|token),
        refresh{frequency, snapshot_type, default_params}, ttl_days

    Use 'notes' field for freeform data. Use 'tags' for categorization.
    """
    err = _validate_profile_args(kind, id, region)
    if err:
        return err
    col = _profiles_col(kind)
    existing = col.find_one({"_id_str": id})
    if existing:
        # Merge: update in-place, keep existing region (skip lint — partial update)
        actual_region = existing.get("region", region)
        update_data = {**data}
        update_data["_updated"] = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        if lon is not None and lat is not None:
            update_data["location"] = {"type": "Point", "coordinates": [lon, lat]}
        col.update_one({"_id_str": id}, {"$set": update_data})
        return {"id": id, "region": actual_region, "status": "ok"}
    else:
        # New profile — lint required fields
        full = {"id": id, "kind": kind, "region": region, **data}
        issues = _lint_one(kind, id, full)
        if issues:
            return {"error": f"validation failed for {kind}/{id}",
                    "issues": issues}
        doc = {
            "_id_str": id,
            "kind": kind,
            "region": region,
            **data,
            "_updated": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        }
        if lon is not None and lat is not None:
            doc["location"] = {"type": "Point", "coordinates": [lon, lat]}
        col.insert_one(doc)
        return {"id": id, "region": region, "status": "ok"}


@mcp.tool()
def list_profiles(kind: str, region: str = "",
                  limit: int = 500) -> list[dict]:
    """List profiles for a kind, optionally filtered by region."""
    if kind not in VALID_KINDS:
        return []
    limit = min(limit, 2000)
    q: dict = {}
    if region:
        q["region"] = region
    col = _profiles_col(kind)
    projection = {"_id": 0, "_id_str": 1, "name": 1, "region": 1}
    docs = col.find(q, projection).sort("_id_str", 1).limit(limit)
    return [{"id": d["_id_str"], "name": d.get("name", d["_id_str"]),
             "region": d.get("region", "")} for d in docs]


@mcp.tool()
def find_profile(query: str, region: str = "",
                 limit: int = 100) -> list[dict]:
    """Cross-kind search by name, ID, or tag. Uses MongoDB text index + regex fallback."""
    results: list[dict] = []
    for kind in sorted(VALID_KINDS):
        col = _profiles_col(kind)
        # Try text search first
        q: dict = {"$text": {"$search": query}}
        if region:
            q["region"] = region
        projection = {"_id": 0, "_id_str": 1, "kind": 1, "name": 1,
                       "region": 1, "tags": 1, "sector": 1}
        try:
            docs = list(col.find(q, projection).limit(limit))
        except Exception:
            docs = []
        # Regex fallback for ID and name partial match
        regex = re.compile(re.escape(query), re.IGNORECASE)
        id_q: dict = {"_id_str": regex}
        if region:
            id_q["region"] = region
        id_docs = list(col.find(id_q, projection).limit(limit))
        name_q: dict = {"name": regex}
        if region:
            name_q["region"] = region
        name_docs = list(col.find(name_q, projection).limit(limit))
        id_docs.extend(name_docs)
        # Merge deduplicated
        seen = {d["_id_str"] for d in docs}
        for d in id_docs:
            if d["_id_str"] not in seen:
                docs.append(d)
                seen.add(d["_id_str"])
        for d in docs:
            d["id"] = d.pop("_id_str")
            if "kind" not in d:
                d["kind"] = kind
            results.append(d)
    return results[:limit]


@mcp.tool()
def search_profiles(kind: str, field: str, value: str,
                    region: str = "") -> list[dict]:
    """Search by dot-path field value (e.g. field='exposure.countries', value='USA').
    Uses MongoDB dot notation queries."""
    err = _validate_profile_args(kind, "x")  # just validate kind
    if err:
        return []
    if not _SAFE_FIELD.match(field):
        return [{"error": f"invalid field name: {field}"}]
    col = _profiles_col(kind)
    # Try exact match, then regex for string fields
    q: dict = {field: value}
    if region:
        q["region"] = region
    docs = list(col.find(q, {"_id": 0}).limit(100))
    if not docs:
        # Regex fallback for partial string match
        q[field] = re.compile(re.escape(value), re.IGNORECASE)
        docs = list(col.find(q, {"_id": 0}).limit(100))
    # Normalize _id_str → id so callers get a consistent shape
    for d in docs:
        if "_id_str" in d and "id" not in d:
            d["id"] = d.pop("_id_str")
    return docs


@mcp.tool()
def region_links(id: str = "", link_type: str = "") -> dict:
    """Query region neighbors, links, and the global interconnection graph.

    - id only → neighbors + links for that region
    - id + link_type → filtered links (trade, alliance, dependency, rivalry, corridor, overlap)
    - no args → return the global graph (clusters, corridors, rivalry axes, dependency chains)
    """
    if not id:
        # Return graph from MongoDB (stored as a special profile)
        doc = _profiles_col("regions").find_one({"_id_str": "_graph"})
        if doc:
            return _strip_mongo_id(doc)
        return {"error": "region graph not found — create it with put_profile('regions', '_graph', data)"}
    prof = get_profile("regions", id)
    if "error" in prof:
        return prof
    result: dict = {"id": id, "name": prof.get("name", id)}
    result["neighbors"] = prof.get("neighbors", [])
    links = prof.get("links", [])
    if link_type:
        links = [lk for lk in links if lk.get("type") == link_type]
    result["links"] = links
    return result


@mcp.tool()
def country_links(id: str = "", link_type: str = "") -> dict:
    """Query country neighbors, links, and cross-border relationships.

    - id only → neighbors + links for that country
    - id + link_type → filtered links (trade, alliance, dependency, rivalry, corridor, sanctions)
    - no args → return all country link data across regions
    """
    if not id:
        # Aggregate links from all country profiles via MongoDB
        all_links: list[dict] = []
        col = _profiles_col("countries")
        for doc in col.find({"links": {"$exists": True, "$ne": []}},
                            {"_id": 0, "_id_str": 1, "name": 1, "links": 1}):
            all_links.append({
                "id": doc.get("_id_str", ""),
                "name": doc.get("name", ""),
                "links": doc.get("links", []),
            })
        return {"countries_with_links": all_links}
    prof = get_profile("countries", id)
    if "error" in prof:
        return prof
    result: dict = {"id": id, "name": prof.get("name", id)}
    result["neighbors"] = prof.get("neighbors", [])
    links = prof.get("links", [])
    if link_type:
        links = [lk for lk in links if lk.get("type") == link_type]
    result["links"] = links
    return result


@mcp.tool()
def list_regions() -> list[dict]:
    """List geographic regions and the profile kinds they contain."""
    result: dict[str, set] = {}
    for kind in sorted(VALID_KINDS):
        col = _profiles_col(kind)
        regions = col.distinct("region")
        for r in regions:
            if r:
                result.setdefault(r, set()).add(kind)
    return [{"region": r, "kinds": sorted(ks)} for r, ks in sorted(result.items())]


@mcp.tool()
def nearby_profiles(kind: str, lon: float, lat: float,
                    max_km: float = 500, limit: int = 50) -> list[dict]:
    """Geo proximity search for profiles with location data."""
    if kind not in VALID_KINDS:
        return [{"error": f"unknown kind: {kind}"}]
    pipeline: list[dict] = [
        {"$geoNear": {
            "near": {"type": "Point", "coordinates": [lon, lat]},
            "distanceField": "_dist_m",
            "maxDistance": max_km * 1000,
            "spherical": True,
        }},
        {"$limit": limit},
        {"$project": {"_id": 0}},
    ]
    col = _profiles_col(kind)
    return [_strip_mongo_id(d) for d in col.aggregate(pipeline)]


@mcp.tool()
def lint_profiles(kind: str | None = None, id: str | None = None) -> dict:
    """Validate profiles against schema. Scope: kind+id, kind only, or all."""
    results: dict = {"ok": [], "issues": {}}
    targets: list[tuple[str, str]] = []
    if kind and id:
        targets.append((kind, id))
    elif kind:
        for entry in list_profiles(kind):
            targets.append((kind, entry["id"]))
    else:
        for k in VALID_KINDS:
            for entry in list_profiles(k):
                targets.append((k, entry["id"]))
    for k, pid in targets:
        prof = get_profile(k, pid)
        if "error" in prof:
            results["issues"][f"{k}/{pid}"] = [prof["error"]]
            continue
        issues = _lint_one(k, pid, prof)
        key = f"{k}/{pid}"
        if issues:
            results["issues"][key] = issues
        else:
            results["ok"].append(key)
    return results


# ── Snapshot tools ────────────────────────────────
# Mirror profile tools API: kind, id (entity), region — plus time fields.
# Each kind has its own MongoDB timeseries collection (snap_{kind} / arch_{kind}).


def _insert_snapshot(kind: str, entity: str, type: str, data: dict,
                     region: str, source: str, ts: str,
                     lon: float | None, lat: float | None,
                     archive: bool = False) -> dict:
    """Shared insert logic for snapshot() and archive_snapshot()."""
    if kind not in VALID_KINDS:
        return {"error": f"unknown kind: {kind}"}
    now = datetime.now(timezone.utc)
    meta = {"entity": entity, "kind": kind, "region": region,
            "type": type, "source": source}
    uid = _get_user_id()
    if uid:
        meta["user_id"] = uid
    parsed_ts = _parse_ts(ts) if ts else now
    if ts and parsed_ts is None:
        return {"error": f"invalid ISO date: {ts}"}
    doc = {"ts": parsed_ts, "meta": meta, "data": data}
    if lon is not None and lat is not None:
        doc["location"] = {"type": "Point", "coordinates": [lon, lat]}
    col = _arch_col(kind) if archive else _snap_col(kind)
    prefix = "arch" if archive else "snap"
    r = col.insert_one(doc)
    return {"id": str(r.inserted_id), "collection": f"{prefix}_{kind}", "status": "ok"}


def _query_history(kind: str, entity: str, type: str, region: str,
                   after: str, before: str, limit: int,
                   archive: bool = False) -> list[dict]:
    """Shared query logic for history() and archive_history()."""
    if kind not in VALID_KINDS:
        return [{"error": f"unknown kind: {kind}"}]
    q: dict = {"meta.entity": entity}
    if type:
        q["meta.type"] = type
    if region:
        q["meta.region"] = region
    if after or before:
        q["ts"] = {}
        if after:
            parsed = _parse_ts(after)
            if not parsed:
                return [{"error": f"invalid after date: {after}"}]
            q["ts"]["$gte"] = parsed
        if before:
            parsed = _parse_ts(before)
            if not parsed:
                return [{"error": f"invalid before date: {before}"}]
            q["ts"]["$lt"] = parsed
    col = _arch_col(kind) if archive else _snap_col(kind)
    rows = col.find(q).sort("ts", -1).limit(limit)
    return [_ser(r) for r in rows]


@mcp.tool()
def snapshot(kind: str, entity: str, type: str, data: dict,
             region: str = "", source: str = "", ts: str = "",
             lon: float | None = None, lat: float | None = None) -> dict:
    """Store a timestamped data point. type: indicators, price, fundamentals, etc."""
    result = _insert_snapshot(kind, entity, type, data, region, source, ts, lon, lat)
    if result.get("status") == "ok" and source != "threshold_checker":
        _run_snapshot_threshold_hook(kind, entity, data)
    return result


@mcp.tool()
def event(subtype: str, summary: str, data: dict,
          severity: str = "medium", countries: list[str] | None = None,
          entities: list[str] | None = None, region: str = "",
          source: str = "", ts: str = "",
          lon: float | None = None, lat: float | None = None) -> dict:
    """Log a signal event. severity: low/medium/high/critical."""
    now = datetime.now(timezone.utc)
    meta = {
        "type": "event",
        "subtype": subtype,
        "severity": severity,
        "region": region,
        "countries": countries or [],
        "entities": entities or [],
        "source": source,
    }
    uid = _get_user_id()
    if uid:
        meta["user_id"] = uid
    parsed_ts = _parse_ts(ts) if ts else now
    if ts and parsed_ts is None:
        return {"error": f"invalid ISO date: {ts}"}
    doc = {
        "ts": parsed_ts,
        "meta": meta,
        "summary": summary,
        "data": data,
    }
    if lon is not None and lat is not None:
        doc["location"] = {"type": "Point", "coordinates": [lon, lat]}
    r = _events_col().insert_one(doc)
    result = {"id": str(r.inserted_id), "status": "ok"}
    if source != "impact_mapper":
        _run_event_impact_hook(meta, summary, data, str(r.inserted_id))
    return result


@mcp.tool()
def history(kind: str, entity: str, type: str = "",
            region: str = "", after: str = "", before: str = "",
            limit: int = 100) -> list[dict]:
    """Snapshot history for an entity. Newest first. after/before: ISO dates."""
    return _query_history(kind, entity, type, region, after, before, min(limit, 5000))


@mcp.tool()
def recent_events(subtype: str = "", severity: str = "",
                  region: str = "", countries: list[str] | None = None,
                  days: int = 30, limit: int = 50) -> list[dict]:
    """Recent signal events, filtered by subtype/severity/region."""
    limit = min(limit, 1000)
    q: dict = {
        "ts": {"$gte": datetime.now(timezone.utc) - timedelta(days=days)},
    }
    if subtype:
        q["meta.subtype"] = subtype
    if severity:
        q["meta.severity"] = severity
    if region:
        q["meta.region"] = region
    if countries:
        q["meta.countries"] = {"$in": countries}
    rows = _events_col().find(q).sort("ts", -1).limit(limit)
    return [_ser(r) for r in rows]


@mcp.tool()
def nearby(kind: str, lon: float, lat: float,
           max_km: float = 500, type: str = "",
           limit: int = 50) -> list[dict]:
    """Geo proximity search. kind: profile kind or 'events'."""
    geo_near: dict = {
        "near": {"type": "Point", "coordinates": [lon, lat]},
        "distanceField": "_dist_m",
        "maxDistance": max_km * 1000,
        "spherical": True,
        "key": "location",
    }
    if type:
        geo_near["query"] = {"meta.type": type}
    if kind == "events":
        col = _events_col()
    elif kind in VALID_KINDS:
        col = _snap_col(kind)
    else:
        return [{"error": f"unknown kind: {kind}"}]
    pipeline: list[dict] = [
        {"$geoNear": geo_near},
        {"$limit": limit},
    ]
    return [_ser(r) for r in col.aggregate(pipeline)]


@mcp.tool()
def trend(kind: str, entity: str, type: str, field: str,
          periods: int = 12) -> list[dict]:
    """Extract a field's trend over time (e.g. field='gdp_growth_pct')."""
    if kind not in VALID_KINDS:
        return [{"error": f"unknown kind: {kind}"}]
    if not _SAFE_FIELD.match(field):
        return [{"error": f"invalid field name: {field}"}]
    pipeline = [
        {"$match": {"meta.entity": entity, "meta.type": type}},
        {"$sort": {"ts": -1}},
        {"$limit": periods},
        {"$project": {"ts": 1, "value": f"$data.{field}", "_id": 0}},
        {"$sort": {"ts": 1}},
    ]
    return list(_snap_col(kind).aggregate(pipeline))


_BLOCKED_STAGES = frozenset({
    "$out", "$merge", "$unionWith", "$collStats", "$currentOp",
    "$listSessions", "$planCacheStats",
})


def _has_blocked_stage(obj) -> bool:
    """Recursively check for blocked aggregation stages in nested pipelines."""
    if isinstance(obj, dict):
        for key, val in obj.items():
            if key in _BLOCKED_STAGES:
                return True
            if _has_blocked_stage(val):
                return True
    elif isinstance(obj, list):
        for item in obj:
            if _has_blocked_stage(item):
                return True
    return False


@mcp.tool()
def aggregate(kind: str, pipeline: list[dict],
              archive: bool = False) -> list[dict]:
    """Read-only MongoDB aggregation. kind: profile kind or 'events'."""
    if _has_blocked_stage(pipeline):
        return [{"error": "pipeline contains a blocked stage ($out, $merge, etc.)"}]
    if kind == "events":
        col = _events_col()
    elif kind in VALID_KINDS:
        col = _arch_col(kind) if archive else _snap_col(kind)
    else:
        return [{"error": f"unknown kind: {kind}"}]
    return [_ser(r) for r in col.aggregate(pipeline)]


# ── Charts ────────────────────────────────────────

_CHART_HTML = """<!DOCTYPE html>
<html><head><meta charset="utf-8">
<script src="https://cdn.plot.ly/plotly-2.35.2.min.js"></script>
<style>body{{margin:0;font-family:system-ui}}#c{{width:100%;height:100vh}}</style>
</head><body><div id="c"></div><script>
Plotly.newPlot('c',{traces},{layout},{{responsive:true}});
</script></body></html>"""


@mcp.tool()
def chart(kind: str, entity: str, type: str, fields: list[str],
          periods: int = 24, archive: bool = False,
          chart_type: str = "line", title: str = "") -> str:
    """Plotly HTML chart from timeseries. chart_type: line/bar/scatter. Output HTML directly as artifact."""
    if kind not in VALID_KINDS:
        return f"Unknown kind: {kind}"
    for field in fields:
        if not _SAFE_FIELD.match(field):
            return f"Invalid field name: {field}"
    col = _arch_col(kind) if archive else _snap_col(kind)

    traces = []
    for field in fields:
        pipeline = [
            {"$match": {"meta.entity": entity, "meta.type": type}},
            {"$sort": {"ts": -1}},
            {"$limit": periods},
            {"$project": {"ts": 1, "value": f"$data.{field}", "_id": 0}},
            {"$sort": {"ts": 1}},
        ]
        points = list(col.aggregate(pipeline))
        if not points:
            continue
        x = [p["ts"].isoformat() if isinstance(p["ts"], datetime) else p["ts"]
             for p in points]
        y = [p.get("value") for p in points]
        mode = ("lines+markers" if chart_type == "line"
                else "markers" if chart_type == "scatter" else "")
        trace: dict = {"x": x, "y": y, "name": field}
        if chart_type in ("line", "scatter"):
            trace["type"] = "scatter"
            trace["mode"] = mode
        else:
            trace["type"] = "bar"
        traces.append(trace)

    if not traces:
        return f"No data found for {kind}/{entity}/{type} fields={fields}"

    chart_title = title or f"{entity} — {type}"
    layout = json.dumps({
        "title": chart_title,
        "xaxis": {"title": "Date"},
        "template": "plotly_white",
        "margin": {"t": 40, "r": 20, "b": 40, "l": 60},
    })
    return _CHART_HTML.format(traces=json.dumps(traces), layout=layout)


# ── Archive ───────────────────────────────────────


@mcp.tool()
def archive_snapshot(kind: str, entity: str, type: str, data: dict,
                     region: str = "", source: str = "", ts: str = "") -> dict:
    """Long-term archive snapshot (no TTL). For historical/yearly data."""
    return _insert_snapshot(kind, entity, type, data, region, source, ts,
                            None, None, archive=True)


@mcp.tool()
def archive_history(kind: str, entity: str, type: str = "",
                    region: str = "", after: str = "", before: str = "",
                    limit: int = 200) -> list[dict]:
    """Query long-term archive for an entity."""
    return _query_history(kind, entity, type, region, after, before, limit,
                          archive=True)


@mcp.tool()
def compact(kind: str, entity: str, type: str, older_than_days: int = 90,
            bucket: str = "month") -> dict:
    """Downsample old snapshots to archive. bucket: week/month/quarter."""
    if kind not in VALID_KINDS:
        return {"error": f"unknown kind: {kind}"}

    date_trunc = {
        "week": {"$dateTrunc": {"date": "$ts", "unit": "week"}},
        "month": {"$dateTrunc": {"date": "$ts", "unit": "month"}},
        "quarter": {"$dateTrunc": {"date": "$ts", "unit": "quarter"}},
    }
    if bucket not in date_trunc:
        return {"error": f"invalid bucket: {bucket}, use week/month/quarter"}

    cutoff = datetime.now(timezone.utc) - timedelta(days=older_than_days)
    snap = _snap_col(kind)
    sample = snap.find_one(
        {"meta.entity": entity, "meta.type": type, "ts": {"$lt": cutoff}}
    )
    if not sample:
        return {"status": "nothing_to_compact", "entity": entity, "type": type}

    sample_data = sample.get("data", {})
    data_keys = [k for k in sample_data.keys() if _SAFE_FIELD.match(k)]

    group_accumulators = {}
    for k in data_keys:
        safe_k = k.replace(".", "_")
        val = sample_data[k]
        if isinstance(val, (int, float)):
            group_accumulators[safe_k] = {"$avg": f"$data.{k}"}
        else:
            group_accumulators[safe_k] = {"$first": f"$data.{k}"}
    group_accumulators["_source"] = {"$first": "$meta.source"}
    group_accumulators["_region"] = {"$first": "$meta.region"}
    group_accumulators["_count"] = {"$sum": 1}

    pipeline = [
        {"$match": {
            "meta.entity": entity, "meta.type": type, "ts": {"$lt": cutoff},
        }},
        {"$group": {
            "_id": date_trunc[bucket],
            **group_accumulators,
        }},
        {"$sort": {"_id": 1}},
    ]

    buckets_result = list(snap.aggregate(pipeline))
    if not buckets_result:
        return {"status": "nothing_to_compact", "entity": entity, "type": type}

    archive_docs = []
    for b in buckets_result:
        d = {}
        for k in data_keys:
            safe_k = k.replace(".", "_")
            val = b.get(safe_k)
            if val is not None:
                d[k] = round(val, 6) if isinstance(val, float) else val
        d["_samples"] = b["_count"]
        archive_docs.append({
            "ts": b["_id"],
            "meta": {
                "entity": entity,
                "kind": kind,
                "region": b.get("_region", ""),
                "type": type,
                "source": b.get("_source", ""),
            },
            "data": d,
        })

    arch_result = _arch_col(kind).insert_many(archive_docs)
    if len(arch_result.inserted_ids) != len(archive_docs):
        return {"error": "partial archive insert — snapshots preserved",
                "archived": len(arch_result.inserted_ids),
                "expected": len(archive_docs)}

    result = snap.delete_many(
        {"meta.entity": entity, "meta.type": type, "ts": {"$lt": cutoff}}
    )

    return {
        "status": "ok",
        "collection": f"snap_{kind}",
        "buckets_created": len(archive_docs),
        "snapshots_deleted": result.deleted_count,
        "bucket_size": bucket,
        "oldest": archive_docs[0]["ts"].isoformat(),
        "newest": archive_docs[-1]["ts"].isoformat(),
    }


# ── Per-user notes / plans ────────────────────────
# Stored in MongoDB "user_notes" collection, keyed by user_id.
# user_id comes from X-User-ID header (streamable-http) or env var.

_VALID_NOTE_KINDS = frozenset({"note", "plan", "watchlist", "journal"})
_VALID_RESEARCH_KINDS = frozenset({"research", "report", "briefing", "alert"})


def _notes_col():
    """Return the user_notes collection."""
    return _db().user_notes


@mcp.tool()
def save_note(title: str, content: str, tags: list[str] | None = None,
              kind: str = "note") -> dict:
    """Save a personal note/plan/watchlist/journal (per-user)."""
    if kind not in _VALID_NOTE_KINDS:
        return {"error": f"invalid note kind: {kind} (use: {', '.join(sorted(_VALID_NOTE_KINDS))})"}
    uid = _get_user_id()
    if not uid:
        return {"error": "user not identified (X-User-ID header missing)"}
    now = datetime.now(timezone.utc)
    doc = {
        "user_id": uid,
        "kind": kind,
        "title": title,
        "content": content,
        "tags": tags or [],
        "created": now,
        "updated": now,
    }
    r = _notes_col().insert_one(doc)
    return {"id": str(r.inserted_id), "status": "ok"}


@mcp.tool()
def get_notes(kind: str = "", tag: str = "", limit: int = 50) -> list[dict]:
    """List your notes. Filter by kind or tag."""
    uid = _get_user_id()
    if not uid:
        return [{"error": "user not identified"}]
    q: dict = {"user_id": uid}
    if kind:
        q["kind"] = kind
    if tag:
        q["tags"] = tag
    rows = _notes_col().find(q).sort("updated", -1).limit(limit)
    result = []
    for r in rows:
        r["_id"] = str(r["_id"])
        for k in ("created", "updated"):
            if isinstance(r.get(k), datetime):
                r[k] = r[k].isoformat()
        result.append(r)
    return result


@mcp.tool()
def update_note(note_id: str, content: str = "", title: str = "",
                tags: list[str] | None = None) -> dict:
    """Update a note (owner only)."""
    uid = _get_user_id()
    if not uid:
        return {"error": "user not identified"}
    try:
        oid = ObjectId(note_id)
    except Exception:
        return {"error": f"invalid note_id format: {note_id}"}
    update: dict = {"updated": datetime.now(timezone.utc)}
    if content:
        update["content"] = content
    if title:
        update["title"] = title
    if tags is not None:
        update["tags"] = tags
    r = _notes_col().update_one(
        {"_id": oid, "user_id": uid},
        {"$set": update}
    )
    if r.matched_count == 0:
        return {"error": "note not found or not owned by you"}
    return {"status": "ok"}


@mcp.tool()
def delete_note(note_id: str) -> dict:
    """Delete a note (owner only)."""
    uid = _get_user_id()
    if not uid:
        return {"error": "user not identified"}
    try:
        oid = ObjectId(note_id)
    except Exception:
        return {"error": f"invalid note_id format: {note_id}"}
    r = _notes_col().delete_one({"_id": oid, "user_id": uid})
    if r.deleted_count == 0:
        return {"error": "note not found or not owned by you"}
    return {"status": "ok"}



# ── Shared research notes ────────────────────────
# Research findings produced by analyzing agents — shared across all users.
# Stored in "shared_notes" collection. No user tracking — any agent can
# read, write, update, or delete. Title is unique (upsert).


def _shared_notes_col():
    """Return the shared_notes collection."""
    return _db().shared_notes


@mcp.tool()
def save_research(title: str, content: str,
                  tags: list[str] | None = None,
                  kind: str = "research") -> dict:
    """Save a shared research note. Overwrites if title exists.

    kind: research | report | briefing | alert (default: research)
    """
    if kind not in _VALID_RESEARCH_KINDS:
        return {"error": f"invalid research kind: {kind} (use: {', '.join(sorted(_VALID_RESEARCH_KINDS))})"}
    now = datetime.now(timezone.utc)
    col = _shared_notes_col()
    r = col.update_one(
        {"title": title},
        {"$set": {
            "content": content,
            "kind": kind,
            "tags": tags or [],
            "updated": now,
        }, "$setOnInsert": {
            "title": title,
            "created": now,
        }},
        upsert=True,
    )
    action = "updated" if r.matched_count else "created"
    return {"title": title, "status": action}


@mcp.tool()
def get_research(title: str = "", tag: str = "", kind: str = "",
                 limit: int = 50) -> list[dict]:
    """List shared research notes. Filter by title, tag, or kind."""
    q: dict = {}
    if title:
        q["title"] = title
    if tag:
        q["tags"] = tag
    if kind:
        q["kind"] = kind
    rows = _shared_notes_col().find(q).sort("updated", -1).limit(limit)
    result = []
    for r in rows:
        r["_id"] = str(r["_id"])
        for k in ("created", "updated"):
            if isinstance(r.get(k), datetime):
                r[k] = r[k].isoformat()
        result.append(r)
    return result


@mcp.tool()
def update_research(title: str, content: str = "",
                    tags: list[str] | None = None) -> dict:
    """Update a shared research note by title."""
    update: dict = {"updated": datetime.now(timezone.utc)}
    if content:
        update["content"] = content
    if tags is not None:
        update["tags"] = tags
    r = _shared_notes_col().update_one(
        {"title": title},
        {"$set": update}
    )
    if r.matched_count == 0:
        return {"error": "research note not found"}
    return {"title": title, "status": "updated"}


@mcp.tool()
def delete_research(title: str) -> dict:
    """Delete a shared research note by title."""
    r = _shared_notes_col().delete_one({"title": title})
    if r.deleted_count == 0:
        return {"error": "research note not found"}
    return {"title": title, "status": "deleted"}


# ── Per-user trading keys ─────────────────────────
# Users provide their own API keys via LibreChat customUserVars.
# Keys arrive as HTTP headers (e.g. X-Broker-Key) and are NOT stored server-side.


def _get_user_key(header_name: str) -> str:
    """Read a per-user API key from HTTP headers. Empty string if unavailable."""
    try:
        from fastmcp.server.dependencies import get_http_headers
        headers = get_http_headers()
        return headers.get(header_name.lower(), "")
    except (RuntimeError, ImportError):
        return ""


# ── Risk gate ─────────────────────────────────────
# All external trading actions (order placement, etc.) must pass through
# this gate before executing. Settings come from:
#   1. Per-user HTTP headers (set via LibreChat customUserVars UI):
#      X-Risk-Daily-Limit, X-Risk-Live-Trading
#   2. Server-wide env var fallbacks: RISK_DAILY_LIMIT (default 50)
#
# Enforces:
#   - user must be identified
#   - live trading must be explicitly enabled by user (default: dry_run)
#   - per-user daily action limit (in-memory counter, resets on restart)


_user_action_counts: dict[str, int] = defaultdict(int)
_action_count_date: str = ""  # YYYY-MM-DD — resets counter daily
_DAILY_ACTION_LIMIT_DEFAULT = int(os.environ.get("RISK_DAILY_LIMIT", "50"))


def _get_user_risk_settings() -> dict:
    """Read per-user risk settings from HTTP headers (customUserVars).
    Falls back to server-wide defaults."""
    limit_str = _get_user_key("x-risk-daily-limit")
    live_str = _get_user_key("x-risk-live-trading")
    try:
        limit = int(limit_str) if limit_str else _DAILY_ACTION_LIMIT_DEFAULT
    except ValueError:
        limit = _DAILY_ACTION_LIMIT_DEFAULT
    live_trading = live_str.lower() in ("yes", "true", "1") if live_str else False
    return {"daily_limit": limit, "live_trading": live_trading}


def _risk_check(action: str, params: dict,
                dry_run: bool = True) -> dict | None:
    """Validate a trading action before execution.
    Returns None if approved, or an error dict if blocked.
    User can override dry_run default via RISK_LIVE_TRADING customUserVar."""
    global _action_count_date
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    if _action_count_date != today:
        _user_action_counts.clear()
        _action_count_date = today
    uid = _get_user_id()
    if not uid:
        return {"error": "user not identified — cannot execute trading actions"}
    settings = _get_user_risk_settings()
    # If user enabled live trading via UI, use that; else respect dry_run param
    effective_dry_run = dry_run and not settings["live_trading"]
    if effective_dry_run:
        return {"blocked": "dry_run",
                "action": action, "params": params,
                "message": "Set dry_run=False or enable live trading in Settings > Plugins"}
    limit = settings["daily_limit"]
    if _user_action_counts[uid] >= limit:
        return {"error": f"daily action limit ({limit}) reached",
                "user_id": uid, "action": action}
    _user_action_counts[uid] += 1
    return None


@mcp.tool()
def risk_status() -> dict:
    """Risk gate status: live trading, actions used today, daily limit."""
    uid = _get_user_id()
    if not uid:
        return {"error": "user not identified"}
    settings = _get_user_risk_settings()
    broker = _get_user_key("x-broker-name")
    has_key = bool(_get_user_key("x-broker-key"))
    return {
        "user_id": uid,
        "broker": broker or "(not set)",
        "broker_key_set": has_key,
        "live_trading": settings["live_trading"],
        "actions_today": _user_action_counts[uid],
        "daily_limit": settings["daily_limit"],
        "remaining": max(0, settings["daily_limit"] - _user_action_counts[uid]),
    }


# ── Notifications (ntfy) ──────────────────────────
# Per-user push notifications via ntfy.sh.
# User sets their ntfy topic via X-Ntfy-Topic header (customUserVars).
# Server-wide fallback: NTFY_TOPIC env var.
# NTFY_BASE_URL defaults to https://ntfy.sh


_NTFY_BASE = os.environ.get("NTFY_BASE_URL", "https://ntfy.sh")
_NTFY_TOPIC_DEFAULT = os.environ.get("NTFY_TOPIC", "")


def _get_ntfy_topic() -> str:
    """Get the ntfy topic for the current user (header > env default)."""
    topic = _get_user_key("x-ntfy-topic")
    return topic or _NTFY_TOPIC_DEFAULT


def _sanitize_header(v: str) -> str:
    """Strip CRLF to prevent header injection."""
    return v.replace("\r", "").replace("\n", " ")


@mcp.tool()
async def notify(title: str, message: str, priority: str = "default",
                 tags: str = "") -> dict:
    """Send a push notification via ntfy (per-user topic).

    priority: min | low | default | high | urgent
    tags: comma-separated emoji tags (e.g. "warning,chart_with_upwards_trend")
    """
    topic = _get_ntfy_topic()
    if not topic:
        return {"error": "no ntfy topic configured — set X-Ntfy-Topic in Settings > Plugins or NTFY_TOPIC env var"}
    import httpx
    headers = {"Title": _sanitize_header(title), "Priority": priority}
    if tags:
        headers["Tags"] = _sanitize_header(tags)
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.post(f"{_NTFY_BASE}/{topic}", content=message,
                                  headers=headers)
            r.raise_for_status()
        return {"status": "sent", "topic": topic}
    except Exception as e:
        return {"error": f"ntfy send failed: {e}"}


if __name__ == "__main__":
    mcp.run(transport="stdio")
