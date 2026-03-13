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

---

## Second Review — 2026-03-13

Deep review of the entire codebase for code quality gaps, security, test coverage,
and architectural issues. Builds on the first review; items already fixed above are
not repeated.

### CRITICAL

#### 24. Mutable Default Argument in `score_prediction`
**File:** `src/servers/augur_score.py:140`

```python
async def score_prediction(..., evidence: list[dict] = []) -> dict:
```
Classic Python footgun — the same list object is shared across all calls.
Should be `evidence: list[dict] | None = None` with `evidence = evidence or []`.

#### 25. `api_multi()` Runs Sequentially Despite Name
**File:** `src/servers/_http.py:34-46`

```python
async def api_multi(calls: dict) -> dict:
    for key, coro in calls.items():
        results[key] = await coro  # ← sequential, not concurrent
```
Used by `water_server`, `disasters_server`, `humanitarian_server`, `infra_server`
for aggregation tools. Each coroutine is `await`ed one-by-one. Should use
`asyncio.gather()` for parallel execution (current latency = sum of all calls;
should be max of all calls).

#### 26. ACLED Token Race Condition (async global state)
**File:** `src/servers/conflict_server.py:18-41`

Module-level `_acled_token` / `_acled_token_exp` globals modified by async
`_acled_auth()` without a lock. Two concurrent requests both see expired token,
both call the OAuth endpoint, waste quota. Fix: use `asyncio.Lock`.

#### 27. Risk Gate Daily Counter Never Resets
**File:** `src/store/server.py:1294`

```python
_user_action_counts: dict[str, int] = defaultdict(int)
```
In-memory counter resets only on process restart. No daily reset logic.
If the server runs for days without restart, users hit their daily limit
permanently. Needs a date-keyed counter or periodic reset.

---

### WARNING

#### 28. `indicators_server` Hard-Fails at Import
**File:** `src/servers/indicators_server.py:22-25`

```python
import pandas as pd
from ta.trend import SMAIndicator, EMAIndicator, MACD as TAmacd
```
Top-level imports with no `try/except`. If `ta` or `pandas` is not installed,
`combined_server.py` fails to start entirely (all 50+ tools down).
Tests auto-skip via conftest, but production has no graceful degradation.
Should wrap in try/except and disable the indicators namespace if unavailable.

#### 29. No Ticker Validation in `analyze_full`
**File:** `src/servers/indicators_server.py:94`

`ticker` parameter is passed directly to Yahoo Finance URL without validation.
While `httpx` handles URL encoding, malicious input like `../../` or very long
strings should be rejected early. Add regex: `^[A-Za-z0-9^._-]{1,20}$`.

#### 30. SPARQL Injection via `limit` Parameter
**File:** `src/servers/elections_server.py:68`

```python
}} ORDER BY DESC(?date) LIMIT {limit}"""
```
`limit` is an `int` parameter, so Python's type system provides some protection,
but MCP tool parameters arrive as JSON and could be strings. The `year` and
`country` inputs are validated; `limit` is not.

#### 31. FDA Drug Name Injection
**File:** `src/servers/health_server.py:65`

```python
search = f'patient.drug.medicinalproduct:"{drug}"'
```
User `drug` parameter interpolated into FDA API query with only double-quote
wrapping. A `drug` value containing `"` could break the query. Add input
sanitization or escape quotes.

#### 32. Plotly CDN Pinned to Old Version
**File:** `src/store/server.py:903`

```html
<script src="https://cdn.plot.ly/plotly-2.35.2.min.js"></script>
```
Hardcoded CDN URL. Not a security risk (loaded client-side in chart output),
but will miss bug fixes. Consider making configurable or documenting the pin.

#### 33. No Logging in Domain Servers
**Files:** All 12 `src/servers/*_server.py` (except `augur_publish.py`, `augur_score.py`)

None of the domain servers log API calls, errors, or rate limits. Only
`augur_publish.py` and `augur_score.py` use Python's `logging` module.
Makes production debugging difficult. Recommend adding `log = logging.getLogger()`
to each server and logging on API errors.

#### 34. `OAuthToken` Class Not Used for ACLED
**File:** `src/servers/_http.py:49-80` vs `src/servers/conflict_server.py:22-41`

`_http.py` provides a proper `OAuthToken` class with encapsulated caching, but
`conflict_server.py` implements its own ad-hoc global-state token caching.
Should refactor ACLED auth to use `OAuthToken` (fixes #26 race condition too).

#### 35. `push_site` Runs Git Commands Without Checking Exit Codes
**File:** `src/servers/augur_publish.py:584-591`

```python
await _run(["git", "add", "_posts/", "assets/", "_data/"])
# ← exit code not checked
rc, status_out, _ = await _run(["git", "status", "--porcelain"])
```
`git add` and `git commit` exit codes are ignored. A failed `git add` would
silently proceed to push stale content.

#### 36. `notify()` Uses Synchronous httpx
**File:** `src/store/server.py:1387`

```python
r = httpx.post(...)
```
All other HTTP calls in the codebase use `httpx.AsyncClient`. This synchronous
call blocks the event loop. Should use `async with httpx.AsyncClient`.

---

### LOW / STYLE

#### 37. `_parse_yaml_value` Skips Edge Cases
**File:** `src/servers/augur_common.py:213-230`

Custom YAML parser doesn't handle multiline strings, anchors, or escaped chars.
Fine for the limited front-matter use case, but could silently corrupt data
with unexpected YAML. Consider adding a comment documenting the subset supported.

#### 38. `water_server.py` Non-Portable Date Format
**File:** `src/servers/water_server.py:76`

`strftime("%-m/%-d/%Y")` — `%-m` (no-padding) is glibc-only. Fails on non-Linux
systems. Not a real issue (deployed only on Uberspace/Linux), but fragile.

#### 39. `compact()` Not Atomic
**File:** `src/store/server.py:1054-1062`

Archives snapshots then deletes originals in two separate operations. If the
process crashes between `insert_many` and `delete_many`, data is duplicated.
Low risk (idempotent on re-run, TTL cleans snapshots eventually), but worth
noting.

#### 40. `find_profile` Iterates All Kinds
**File:** `src/store/server.py:500-538`

Cross-kind search does MongoDB queries across all 12 `profiles_*` collections
sequentially. With small profile counts this is fine; at scale, consider a
unified search collection or MongoDB Atlas Search.

#### 41. `eu_parliament_meps` Uses 60s Timeout
**File:** `src/servers/elections_server.py:138`

While other endpoints use 15-30s, EU Parliament API gets 60s. This is intentionally
generous (their API is slow), but a hung connection ties up the event loop.
Consider documenting why.

---

### Test Coverage Gaps

#### T1. Risk Gate Under-Tested
**File:** `src/store/server.py:1311-1331`

`_risk_check()` has tests for basic dry_run and user identification, but:
- Daily counter increment and limit enforcement not tested
- Counter never-resets bug (#27) not covered
- `_get_user_risk_settings()` header parsing edge cases untested

#### T2. `compact()` Not Tested
**File:** `src/store/server.py:980-1072`

The entire compaction workflow (downsample snapshots to archive, delete originals)
has no test coverage. Complex aggregation pipeline + delete operation.

#### T3. `chart()` Not Tested
**File:** `src/store/server.py:910-957`

Plotly HTML chart generation has no tests. Could silently break without detection.

#### T4. Social Posting Partially Tested
**Files:** `src/servers/augur_publish.py:386-563`

Bluesky and Mastodon posting have basic tests, but:
- Image upload path (blob upload) not tested
- Facet/link computation byte-offset logic not tested
- `push_site` git operations not tested

#### T5. `api_multi` Error Isolation Not Tested
**File:** `src/servers/_http.py:34-46`

No test verifies that one failing coroutine doesn't prevent others from completing.

#### T6. Alert Hooks Lightly Tested
**Files:** `src/alerts/threshold_checker.py`, `src/alerts/impact_mapper.py`

Threshold checking and impact propagation have unit tests, but the integration
path (snapshot insert → threshold hook → event creation → impact propagation)
is not end-to-end tested.

---

## Summary

| Status | Count | Details |
|--------|-------|---------|
| **First review** | | |
| Fixed | 14 | #1-5, #7-13, #15, #19 |
| Mitigated | 1 | #6 (regex) |
| Accepted | 3 | #14, #16, #18 (not applicable) |
| Open | 2 | #17 (perf at scale), #23 (low priority) |
| **Second review** | | |
| Critical | 4 | #24-27 (mutable default, sequential api_multi, race condition, counter reset) |
| Warning | 9 | #28-36 (import crash, ticker validation, injection, logging, sync httpx) |
| Low/Style | 5 | #37-41 (yaml parser, date format, atomicity, iteration, timeout) |
| Test gaps | 6 | T1-T6 (risk gate, compact, chart, social, api_multi, alert hooks) |
