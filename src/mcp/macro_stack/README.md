# macro-stack MCP

Unified BLS + BEA + Census Bureau macro-data MCP. Complements `fred` (which
wraps the St. Louis Fed's FRED aggregator) by hitting the underlying primary
sources directly. Used by `MacroCycleAgent` for cycle/regime composition that
needs metrics FRED does not republish (e.g., BEA NIPA detail tables, Census
EITS retail/housing time series).

## Endpoints

| Tool | Purpose |
| --- | --- |
| `get_bls_series(series_id, start_year, end_year)` | BLS public timeseries v2 (CPI, unemployment, payrolls). |
| `get_bea_table(dataset, table_name, frequency, year)` | BEA Data API tables (NIPA, FixedAssets, etc.). |
| `get_census_series(dataset, time_period, variables)` | Census Bureau time-series API (EITS — retail sales, housing starts). |

All endpoints return a dict that always carries `source` and `retrieved_at`.
On failure (404, bad id, connectivity, auth/quota) they return a
not-found-style sentinel rather than raising:
`{series_not_found: True | table_not_found: True | dataset_not_found: True, error_class: <str?>, ...}`.

## Data dictionaries

Commonly used series — these are the IDs `MacroCycleAgent` should reach for
first. Not exhaustive; each agency exposes thousands more.

### BLS series IDs

| Series ID | Description |
| --- | --- |
| `CUUR0000SA0` | CPI-U, U.S. city average, all items, NSA (headline CPI). |
| `CUSR0000SA0` | CPI-U, all items, SA. |
| `CUUR0000SA0L1E` | CPI-U, all items less food & energy (core CPI), NSA. |
| `LNS14000000` | Civilian unemployment rate, SA, 16+. |
| `CES0000000001` | Total nonfarm payroll employment, SA. |
| `CES0500000003` | Avg hourly earnings, total private, SA. |
| `LNS11300000` | Civilian labor force participation rate, SA. |
| `WPSFD4` | PPI, finished goods. |

### BEA tables

| Dataset | Table | Description |
| --- | --- | --- |
| `NIPA` | `T10101` | Percent change from preceding period in real GDP. |
| `NIPA` | `T10105` | Gross Domestic Product (level). |
| `NIPA` | `T20100` | Personal income and disposition of personal income. |
| `NIPA` | `T20305` | Personal consumption expenditures by major type. |
| `NIPA` | `T11400` | Gross value added by sector. |
| `FixedAssets` | `FAAt101` | Fixed assets and consumer durable goods (annual). |

Frequencies: `A` (annual), `Q` (quarterly), `M` (monthly — only some tables).

### Census time series (EITS = Economic Indicators Time Series)

| Dataset | Notes |
| --- | --- |
| `timeseries/eits/marts` | Monthly Retail Trade Survey (advance + revised). |
| `timeseries/eits/mrts` | Monthly Retail Trade — historical. |
| `timeseries/eits/resconst` | New residential construction (housing starts/completions). |
| `timeseries/eits/ressales` | New residential sales. |
| `timeseries/eits/advm3` | Advance monthly manufacturers' shipments / inventories / orders. |

Standard variables on EITS endpoints: `cell_value`, `data_type_code`,
`category_code`, `seasonally_adj`, `time_slot_id`, `error_data`,
`time` (returned automatically when `time=` query is used).

## API keys

Set in repo `.env`:

```
BLS_API_KEY=
BEA_API_KEY=
CENSUS_API_KEY=
```

Free registration:
- BLS: <https://data.bls.gov/registrationEngine/>
- BEA: <https://apps.bea.gov/API/signup/>
- Census: <https://api.census.gov/data/key_signup.html>

If a required key is missing, the relevant endpoint returns the not-found
sentinel with `error_class: "missing_api_key"` (it does NOT raise — fail soft
so MacroCycleAgent can degrade gracefully).
