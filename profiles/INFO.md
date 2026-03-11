# Profiles Directory

Profiles describe anything tradeable or trade-relevant. Organized by
**geographic region** then **kind**, with per-kind indexes at the top level.
Stored in MongoDB (`profiles_{kind}` collections). Seed JSON files on disk
are loaded via `seed_profiles`.

## Structure

```
profiles/
├── INFO.md                        ← this file
├── INDEX_{kind}.json              ← per-kind indexes (auto-generated)
│
├── north_america/                 ← seed data by region
│   ├── countries/USA.json
│   ├── stocks/AAPL.json
│   └── companies/...
├── latin_america/
├── europe/
│   ├── countries/DEU.json
│   └── stocks/SAP.json
├── mena/                          ← Middle East & North Africa
├── sub_saharan_africa/
├── south_asia/
├── east_asia/
├── southeast_asia/
├── central_asia/
├── oceania/
├── arctic/                        ← interest regions
├── antarctic/
└── global/                        ← non-geographic (ETFs, indices, commodities, ...)
    ├── etfs/VWO.json
    ├── indices/
    ├── commodities/
    ├── crops/
    ├── materials/
    └── sources/faostat.json
```

## Regions

| Region | Description |
|--------|-------------|
| `north_america` | USA, Canada, Mexico |
| `latin_america` | Central America, Caribbean, South America |
| `europe` | EU + non-EU European countries |
| `mena` | Middle East & North Africa |
| `sub_saharan_africa` | Sub-Saharan Africa |
| `south_asia` | India, Pakistan, Bangladesh, etc. |
| `east_asia` | China, Japan, Korea, Taiwan, Mongolia |
| `southeast_asia` | ASEAN countries |
| `central_asia` | Kazakhstan, Uzbekistan, etc. |
| `oceania` | Australia, New Zealand, Pacific Islands |
| `arctic` | Arctic region (climate, resources, shipping) |
| `antarctic` | Antarctic region (climate, research) |
| `global` | Non-geographic: ETFs, indices, commodities, crops, materials, sources |

## Kinds

| Kind | ID Convention | Example IDs | Required |
|------|---------------|-------------|----------|
| countries | ISO3 uppercase | DEU, USA, CHN | id, name |
| stocks | Ticker uppercase | AAPL, NVDA, SAP | id, name |
| etfs | Ticker uppercase | VWO, SPY, QQQ | id, name |
| crypto | Symbol uppercase | BTC, ETH, SOL | id, name |
| indices | Symbol uppercase | SPX, NDX, DJI | id, name |
| commodities | lowercase slug | crude_oil, gold | id, name |
| crops | lowercase slug | corn, wheat | id, name |
| materials | lowercase slug | lithium, copper | id, name |
| products | lowercase slug | semiconductors | id, name |
| companies | lowercase slug | tsmc, aramco | id, name |
| sources | lowercase slug | faostat, usgs | id, name |

All extra fields are allowed. Use `notes` for freeform data.

## Index Files

Top-level `INDEX_{kind}.json` per kind — array of `{id, kind, name, region, tags?, sector?}`.

- Auto-updated on `put_profile()` calls
- Full rebuild via `rebuild_index(kind?)`
- `find_profile(query, region?)` merges all indexes for cross-kind search
- Region key always present for geographic filtering

## MongoDB Collections

Per-kind timeseries collections mirror the profile structure:

| Collection | TTL | Use |
|------------|-----|-----|
| `snap_{kind}` | 365 days | Recent snapshots (hours granularity) |
| `arch_{kind}` | none | Long-term archive (days granularity) |
| `events` | 365 days | Cross-kind signal events |

All docs include `meta.region` matching the profile's geographic region.
Optional `location` GeoJSON Point field for spatial queries via `nearby()`.

## Tools

### Profile tools (MongoDB-backed)

| Tool | Purpose |
|------|---------|
| `get_profile(kind, id, region?)` | Read a profile (scans all regions if omitted) |
| `put_profile(kind, id, data, region?)` | Create/merge profile (default: global) |
| `list_profiles(kind, region?)` | List profiles, optionally by region |
| `find_profile(query, region?)` | Cross-kind search by name/ID/tag |
| `search_profiles(kind, field, value, region?)` | Field-level search |
| `list_regions()` | List regions and their kinds |
| `rebuild_index(kind?)` | Rebuild indexes from disk |
| `lint_profiles(kind?, id?)` | Validate required fields |

### Snapshot tools (MongoDB, same API + time fields)

| Tool | Purpose |
|------|---------|
| `snapshot(kind, entity, type, data, region?, ...)` | Store timestamped data |
| `history(kind, entity, type?, region?, after?, before?)` | Query history |
| `trend(kind, entity, type, field, periods?)` | Extract field trend |
| `nearby(kind, lon, lat, max_km?, type?)` | Geo proximity search |
| `event(subtype, summary, data, region?, ...)` | Log signal event |
| `recent_events(subtype?, severity?, region?, ...)` | Query recent events |
| `archive_snapshot(kind, entity, type, data, region?)` | Long-term storage |
| `archive_history(kind, entity, type?, region?, ...)` | Query archive |
| `compact(kind, entity, type, older_than_days?)` | Downsample to archive |
| `aggregate(kind, pipeline, archive?)` | Raw aggregation pipeline |
| `chart(kind, entity, type, fields, ...)` | Generate Plotly chart |
