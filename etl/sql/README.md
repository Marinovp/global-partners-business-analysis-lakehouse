# SQL versions of the pipeline logic

The pipeline itself runs in PySpark (a requirement: "all logic in PySpark"). These files express
the **same logic in SQL** so it can be reviewed, explained and spot-checked without reading Spark
code. Each file names the PySpark function it mirrors.

| Folder | Dialect | What it mirrors |
|---|---|---|
| `source/` | SQL Server (T-SQL) | The queries job 0 (`etl/jobs/extract.py`) sends to the source database |
| `raw/` | Athena | Optional DDL to make the raw Parquet extracts queryable (the pipeline itself doesn't need it) |
| `silver/` | Athena (Iceberg) | Job 1 (`etl/jobs/silver.py`): quarantine rules and the MERGE into silver |
| `gold/` | Athena | Job 2 (`etl/jobs/gold.py`): one `SELECT` per gold table |
| `dq/` | Athena | Job 3 (`etl/jobs/dq.py`): the data-quality checks |
| `dashboard/` | Athena | The queries the Streamlit dashboard runs (the app loads these files directly) |

## Running them

- Athena console → workgroup **`gp-lakehouse-dev-wg`** (results are encrypted and scans are capped at 1 GB).
- The `gold/` and `dq/` files are plain `SELECT`s: running them is read-only and safe. To compare with
  the PySpark output, wrap one in `SELECT count(*), sum(<money column>) FROM (<query>)` and compare
  with the same aggregate on the `gp_gold` table.
- The `silver/*_merge.sql` files **write** to silver; run them only against a dev stack.

## Known differences from the PySpark results

| Topic | Why results can differ slightly |
|---|---|
| CLV tiers for tied customers | `ntile()` splits customers with the same lifetime value arbitrarily; tier **counts** match, but which tied customer lands in which tier can differ |
| Implied discounts | Spark `percentile_approx` and Athena `approx_percentile` are both approximate medians and can disagree on a few items, which shifts a few orders in or out of "discounted" (measured: 15,219 orders in SQL vs 14,953 in PySpark, about 2%) |
| Everything else | Same results (verified: row counts and revenue totals match the gold tables) |

## Shared assumptions (also in `docs/solution-design.md`)

- **Revenue per line = `item_price` + sum(`option_price` × `option_quantity`).** `item_price` behaves as a
  line total in this data (it rises with quantity), so it is not multiplied by `item_quantity`.
- **Dates are UTC** (`creation_time_utc`); store time zones are not in the data.
- **`as_of_date` = the last order date in the data (2024-02-21)**, not today, for recency, RFM and churn.
- Rows with no `user_id` count toward sales and location revenue, but not toward any customer metric.
