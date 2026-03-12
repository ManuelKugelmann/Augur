# Code Review — Augur

Full security and quality audit of the entire codebase. Date: 2026-03-06.
Updated: 2026-03-09 (14 of 19 fixed, all critical security issues resolved).

---

## CRITICAL Issues

### 1. ~~Path Traversal in Profile Tools~~ ✅ FIXED
**File:** `src/store/server.py`

`_safe_profile_path()` validates `id` with regex `^[A-Za-z0-9_-]+$` and checks resolved path stays within profiles directory.

### 2. ~~Raw MongoDB Aggregation Pipeline Exposed~~ ✅ FIXED
**File:** `src/store/server.py`

`_BLOCKED_STAGES` frozenset blocks `$out`, `$merge`, `$unionWith`, `$collStats`, `$currentOp`, `$listSessions`, `$planCacheStats`. Recursive check via `_has_blocked_stage()`.

### 3. ~~Mutable Default Arguments~~ ✅ FIXED
**File:** `src/store/server.py`

All `[]` defaults replaced with `None` + `or []` inside functions.

### 4. ~~Shell Injection in `trap`~~ ✅ FIXED
**Files:** `Augur.sh`, `bootstrap.sh`

All traps use single-quoted bodies: `trap 'rm -rf "${LC_TMP:-}"' EXIT`.

### 5. ~~Operator Precedence Bug in Git Update~~ ✅ FIXED
**File:** `Augur.sh`

Fallback commands grouped with braces: `... || { git ... fetch ... && git ... reset --hard ...; }`.

### 6. OData Injection in WHO API — MITIGATED
**File:** `health_server.py`

Regex validation `^[A-Za-z0-9_-]+$` added for `country` parameter. Injection blocked, though f-string interpolation remains (no parameterized OData alternative available).

---

## WARNING Issues

### 7. ~~Environment Variable Name Mismatches~~ ✅ FIXED
`.env.example` now matches code: `GOOGLE_API_KEY`, `AISSTREAM_API_KEY`, `CF_API_TOKEN`.

### 8. ~~`datetime.utcnow()` Deprecated~~ ✅ FIXED
**File:** `disasters_server.py` — uses `datetime.now(timezone.utc)`.

### 9. ~~No Timeout on Most HTTP Clients~~ ✅ FIXED
All 12 domain servers + store now have explicit `timeout=` on every `httpx.AsyncClient()` call (15–30s depending on API).

### 10. ~~No Error Handling on Domain Servers~~ ✅ FIXED
All 12 domain servers now wrap HTTP calls in `try/except httpx.HTTPError`, returning `{"error": ...}` instead of crashing.

### 11. ~~CI References Non-Existent `install.sh`~~ ✅ FIXED
Dead config removed from `.github/workflows/release.yml`.

### 12. ~~`nightly-git-commit.sh` Never Pushes~~ ✅ FIXED
Now includes `git push` with fallback message.

### 13. ~~Comtrade API Key Sent When Empty~~ ✅ FIXED
Now checks `if not COMTRADE_KEY` and returns clean error dict.

### 14. `type` Shadows Python Built-in — ACCEPTED
**File:** `src/store/server.py`

Used as parameter name in `snapshot()`, `event()`, etc. Shadows builtin within function scope. Low risk — accepted as trade-off for API clarity (`type` matches MongoDB field name).

### 15. ~~Index Creation at Module Load~~ ✅ FIXED
Index creation now happens on-demand in `_snap_col()`, `_arch_col()`, `_events_col()`.

### 16. Sequential HTTP in `space_weather()` — ACCEPTED
**File:** `weather_server.py`

3 sequential requests. Could use `asyncio.gather()` for 3x latency improvement, but current approach has better per-request error isolation.

### 17. `search_profiles` Reads Every File — OPEN
**File:** `src/store/server.py`

O(n) disk reads per query. Will degrade at scale. `search_profiles()` does field-level scans. Options: in-memory cache with TTL, or MongoDB text search.

### 18. Domain Server `.env` Not Loaded via LibreChat — NOT APPLICABLE
**File:** `augur-uberspace/config/librechat.yaml`

Domain servers run inside the combined trading server process (not as separate LibreChat-launched MCPs). The combined server is a systemd service that sources `.env`. API keys are available via the process environment.

### 19. ~~`deploy.conf` Variable Not Used by Ops Script~~ ✅ CLARIFIED
`Augur.sh` sets `GH_REPO` default before sourcing config — intentional for `curl|bash` one-liner where config doesn't exist yet. Comment added to explain.

---

## STYLE Issues

### 20. `_schema.json` Files Aren't JSON Schema
Descriptive, not machine-validatable. Full JSON Schema conversion tracked in TODO.md (P5).

### 21. `librechat.yaml` Uses `npx -y` Despite Bundled Packages
CI bundles `node_modules`, but yaml still uses `npx -y` for external MCPs (yahoo-finance, prediction-markets, etc.). These are external packages not included in the bundle — `npx -y` is correct.

### 22. Inconsistent ID Casing in Profiles — BY DESIGN
Countries: uppercase ISO3 (`DEU`). Sources/commodities: lowercase slug (`faostat`). This follows the naming conventions documented in CLAUDE.md and profiles/INFO.md.

### 23. CI Removes `package-lock.json` — OPEN (low priority)
Prevents reproducible builds. Each install fetches latest minor versions.

---

## Summary

| Status | Count | Details |
|--------|-------|---------|
| ✅ Fixed | 14 | #1-5, #7-13, #15, #19 |
| ⚠️ Mitigated | 1 | #6 (regex) |
| ℹ️ Accepted | 3 | #14, #16, #18 (not applicable) |
| 🔲 Open | 2 | #17 (perf at scale), #23 (low priority) |
