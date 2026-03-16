# Code Review — Augur

Full security and quality audit of the entire codebase. Date: 2026-03-06.
Updated: 2026-03-16 (third review; all critical + warning issues fixed across first two reviews).

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

### 17. ~~`search_profiles` Reads Every File~~ ✅ NOT APPLICABLE
**File:** `src/store/server.py`

Originally flagged as O(n) disk reads. Since refactored: `search_profiles()` and `find_profile()` now use MongoDB queries (dot-notation, text index, regex fallback). No disk reads involved. See #52 for the remaining scaling concern with `find_profile()`.

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

#### 24. ~~Mutable Default Argument in `score_prediction`~~ ✅ FIXED
**File:** `src/servers/augur_score.py` — changed to `evidence: list[dict] | None = None` with `evidence = evidence or []`.

#### 25. ~~`api_multi()` Runs Sequentially Despite Name~~ ✅ FIXED
**File:** `src/servers/_http.py` — now uses `asyncio.gather()` for concurrent execution with per-key error capture.

#### 26. ~~ACLED Token Race Condition~~ ✅ FIXED
**File:** `src/servers/conflict_server.py` — added `asyncio.Lock` with double-check pattern to prevent concurrent token refreshes.

#### 27. ~~Risk Gate Daily Counter Never Resets~~ ✅ FIXED
**File:** `src/store/server.py` — added `_action_count_date` tracking; `_risk_check()` clears counters on date change.

---

### WARNING

#### 28. ~~`indicators_server` Hard-Fails at Import~~ ✅ FIXED
**File:** `src/servers/indicators_server.py` — `ta`/`pandas` imports wrapped in `try/except`; `_TA_AVAILABLE` flag gates tool execution. Server starts cleanly without these deps.

#### 29. ~~No Ticker Validation in `analyze_full`~~ ✅ FIXED
**File:** `src/servers/indicators_server.py` — added regex `^[A-Za-z0-9^._-]{1,20}$` validation before Yahoo Finance request.

#### 30. ~~SPARQL Injection via `limit` Parameter~~ ✅ FIXED
**File:** `src/servers/elections_server.py` — `limit` capped with `min(limit, 200)` in both SPARQL queries.

#### 31. ~~FDA Drug Name Injection~~ ✅ FIXED
**File:** `src/servers/health_server.py` — embedded quotes stripped from `drug` parameter before interpolation into FDA query.

#### 32. Plotly CDN Pinned to Old Version
**File:** `src/store/server.py:903`

```html
<script src="https://cdn.plot.ly/plotly-2.35.2.min.js"></script>
```
Hardcoded CDN URL. Not a security risk (loaded client-side in chart output),
but will miss bug fixes. Consider making configurable or documenting the pin.

#### 33. ~~No Logging in Domain Servers~~ ✅ FIXED
**Files:** All 12 `src/servers/*_server.py` now have `log = logging.getLogger("augur.{name}")`.

#### 34. ~~`OAuthToken` Class Not Used for ACLED~~ ✅ FIXED (via #26)
ACLED auth now uses `asyncio.Lock` for thread safety. Password grant doesn't fit `OAuthToken` (client_credentials only), but the race condition is resolved.

#### 35. ~~`push_site` Runs Git Commands Without Checking Exit Codes~~ ✅ FIXED
**File:** `src/servers/augur_publish.py` — `git add` and `git commit` exit codes now checked; returns error dict on failure.

#### 36. ~~`notify()` Uses Synchronous httpx~~ ✅ FIXED
**File:** `src/store/server.py` — `notify()` is now `async def` using `httpx.AsyncClient`.

---

#### 42. ~~CRLF Injection in ntfy Headers~~ ✅ FIXED
**Files:** `src/servers/augur_publish.py`, `src/store/server.py` — `_sanitize_header()` strips `\r` and `\n` from all user-supplied ntfy header values.

#### 43. ~~Charts Server Integer Parse Crash~~ ✅ FIXED
**File:** `src/store/charts.py` — `periods` parsing wrapped in `try/except` with default=24 fallback and clamped to `[1, 10000]`.

#### 44. ~~No Upper Bound on `limit` Parameters~~ ✅ FIXED
**File:** `src/store/server.py` — `list_profiles` capped at 2000, `history` at 5000, `recent_events` at 1000.

#### 45. ~~`seed_profiles` Skips ID Validation~~ ✅ FIXED
**File:** `src/store/server.py` — `_SAFE_ID` regex check added before inserting; invalid IDs logged to `_errors`.

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

#### T1. ~~Risk Gate Under-Tested~~ ✅ FIXED
Added tests: daily counter reset on date change, counter persistence same day, invalid `x-risk-daily-limit` header fallback, zero daily limit blocks all actions. See `tests/test_review_fixes.py`.

#### T2. `compact()` Not Tested — COVERED IN `test_store_mongo.py`
Already tested: `TestCompact` class with 5 tests (reject invalid kind, reject invalid bucket, nothing to compact, compact success, partial insert error). No gap.

#### T3. `chart()` Not Tested — COVERED IN `test_store_mongo.py`
Already tested: `TestChart` class with 6 tests (reject invalid kind, no data, generates HTML, archive, bar type, scatter type). No gap.

#### T4. Social Posting Partially Tested — OPEN
Image upload and byte-offset facet logic remain untested. Push_site exit codes now checked (#35).

#### T5. ~~`api_multi` Error Isolation Not Tested~~ ✅ FIXED
Added `test_api_multi_error_isolation` verifying one failing coroutine returns `{"error": ...}` while others succeed. See `tests/test_review_fixes.py`.

#### T6. Alert Hooks Lightly Tested — OPEN
End-to-end integration path (snapshot → threshold hook → event → impact) not tested. Unit tests for individual components are solid.

---

---

## Third Review — 2026-03-16

Fresh codebase review. All previous critical/warning issues remain fixed.
Focus: new code paths, overlooked patterns, scaling concerns.

### WARNING

#### 46. `OAuthToken.headers()` KeyError on Malformed Response — OPEN
**File:** `src/servers/_http.py:83`

If OAuth server returns HTTP 200 but response JSON is missing `access_token` key,
`data["access_token"]` raises `KeyError`. This is not caught by `except httpx.HTTPError`,
so it propagates and crashes the calling tool. Should catch `(KeyError, httpx.HTTPError)`.

#### 47. `_replace_field()` Regex Replacement Injection — OPEN
**File:** `src/servers/augur_score.py:182`

`value` is used directly in `re.sub()` replacement string: `pattern.sub(rf'\1 "{value}"', ...)`.
If `outcome_note` contains backslash sequences (`\1`, `\n`), they are interpreted as regex
backreferences/escapes, corrupting the front matter. Fix: use a lambda replacement or escape
the value with `value.replace("\\", "\\\\")`.

#### 48. Image Generation Polling Without Backoff — OPEN (low priority)
**File:** `src/servers/augur_publish.py:225-231`

Replicate image gen polls 60 times at 1-second intervals. No exponential backoff.
If the prediction times out, the Replicate job is not cancelled (orphaned, runs to completion
on their side). Low financial impact but poor practice.

#### 49. `price_ingest.py` Missing None Check for `close` Field — OPEN
**File:** `src/ingest/price_ingest.py:87`

`close` field uses `round(float(last_bar["close"]), 4)` without a None guard, while
`open`, `high`, `low`, and `volume` all check `is not None` first. If Yahoo Finance
returns a null close price, `float(None)` raises `TypeError` and crashes the ingest.
Fix: add the same `if ... is not None else None` pattern as the other fields.

#### 50. Signal Change Detection Order — OPEN (low priority)
**File:** `src/ingest/price_ingest.py:111-117`

Signal change detection fetches the previous composite signal *after* storing the new
snapshot. It then reads `history(limit=2)` and assumes `rows[1]` is the old signal.
In a concurrent scenario, another insert could shift the index. Low risk in current
single-process cron, but the old signal should be fetched *before* storing the new one.

#### 51. `indicator()` Catches Bare `Exception` — ACCEPTED
**File:** `src/servers/macro_server.py:142-163`

Provider routing (`fred → worldbank → imf`) wraps each call in `except Exception`.
The inner functions already return error dicts and don't raise, so these clauses only fire
on truly unexpected errors. Defensive but overly broad — accepted as-is since the routing
pattern benefits from resilience.

### LOW / STYLE

#### 52. `find_profile()` Does 36 MongoDB Queries Per Call — OPEN
**File:** `src/store/server.py:503-542`

Cross-kind search iterates 12 kinds × 3 queries each (text search, ID regex, name regex).
Fine at current scale (424 profiles). At 1000+ profiles, consider a unified search collection
or MongoDB Atlas Search. Supersedes old #17 as the real scaling concern.

---

### Test Coverage Gaps (continued)

T4 and T6 from second review remain open (social posting image upload, alert hooks e2e).

---

## Summary

| Status | Count | Details |
|--------|-------|---------|
| **First review** | | |
| Fixed | 15 | #1-5, #7-13, #15, #17 (not applicable), #19 |
| Mitigated | 1 | #6 (regex) |
| Accepted | 3 | #14, #16, #18 (not applicable) |
| Open | 1 | #23 (low priority) |
| **Second review** | | |
| Fixed | 17 | #24-31, #33-36, #42-45 |
| Accepted | 1 | #32 (Plotly CDN pin, document only) |
| Low/Style | 5 | #37-41 (yaml parser, date format, atomicity, iteration, timeout) |
| Test gaps fixed | 3 | T1 (risk gate), T5 (api_multi), T2/T3 (already covered) |
| Test gaps open | 2 | T4 (social image upload), T6 (alert e2e integration) |
| **Third review** | | |
| Open | 5 | #46 (OAuth KeyError), #47 (regex replacement), #48 (polling backoff), #49 (close None check), #50 (signal change order) |
| Accepted | 1 | #51 (bare Exception in indicator routing) |
| Low/Style | 1 | #52 (find_profile 36 queries, scaling concern) |
