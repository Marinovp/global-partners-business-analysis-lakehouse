# Global Partners Business Insights Lakehouse: Solution Design

**Status:** built and running in a dev environment; awaiting SME review of the assumptions in section 9.
**Diagram:** [`architecture/global_partners_lakehouse.drawio`](architecture/global_partners_lakehouse.drawio)

## 1. Goal

A single view of customer behaviour, spending and business performance across all locations and
ordering apps, refreshed daily:

- **Primary:** Customer Lifetime Value (CLV), how it evolves **daily** for every customer, and High / Medium / Low value tiers.
- **Secondary:** RFM segmentation, churn indicators, sales trends and seasonality, loyalty program impact,
  location performance, and pricing/discount effectiveness.
- An interactive dashboard (Streamlit) for marketing, operations and leadership.

**Constraints from the requirements:** SQL Server as the source · AWS services only · no new licences ·
no Snowflake/dbt or other external tools · all logic in PySpark · scheduling, encryption and a failure
reload mechanism · CI/CD on GitHub.

## 2. Architecture

```
 Source CSVs ──(one-time, per environment)──► RDS SQL Server Express (simulated source system)
                                                   │ JDBC over TLS · private subnet · password in Secrets Manager
 ┌──────────────── Glue Workflow (daily 06:00 UTC, or on demand) ────────────────────────────────┐
 │ Job 0  extract  SQL Server → S3 raw/<table>/run_id=<ts>/  (Parquet, immutable)                 │
 │          │ on SUCCEEDED                                                                          │
 │ Job 1  silver   raw → Iceberg gp_silver (clean, dedupe, MERGE) · rejects → S3 quarantine/      │
 │          │ on SUCCEEDED                                                                          │
 │ Job 2  gold     silver → Iceberg gp_gold (7 business tables, atomic rebuild)                   │
 │          │ on SUCCEEDED                                                                          │
 │ Job 3  dq       19 checks on silver + gold → gp_gold.dq_results; fails the run on any CRITICAL │
 └───────────────────────────────────────────────────────────────────────────────────────────────┘
        any job FAILED / TIMEOUT / ERROR ──► EventBridge rule ──► SNS ──► email
 Glue Data Catalog (gp_raw · gp_silver · gp_gold) ──► Athena (workgroup, KMS-encrypted results, 1 GB scan cap)
                                                          ──► Streamlit dashboard (8 pages)
 Infrastructure: Terraform · CI/CD: GitHub Actions with OIDC (no stored AWS keys)
```

### Why each technology

| Choice | Why | Considered instead |
|---|---|---|
| **RDS for SQL Server Express** | Managed SQL Server with **no licence fee** (Express is licence-included), which meets "source = SQL Server" and "no new licences" | SQL Server on EC2 (more to manage); Standard edition (licence cost) |
| **AWS Glue (PySpark)** for every step | Serverless Spark billed per second; satisfies "all logic in PySpark" end to end with one engine; reads SQL Server over JDBC, so no CDC or source changes are needed | **DMS** (Express has no CDC, plus a second tool), EMR (more setup), Lambda (not PySpark) |
| **Amazon S3** | Durable, cheap, encrypted storage for every layer | — |
| **Apache Iceberg** (silver, gold) | `MERGE` makes re-runs and overlapping extracts safe (idempotent); atomic table replacement keeps gold readable if a run fails; time travel; read natively by Athena | Plain Parquet (no MERGE, no atomic swap) |
| **Glue Data Catalog + Athena** | Serverless SQL priced per data scanned; no cluster to run; easy to query from Streamlit | Redshift (not needed at this size, always-on cost) |
| **Glue Workflow** (orchestration) | Native scheduling and job chaining; every task is already a Glue job, so no extra service or IAM role | Step Functions + EventBridge Scheduler (more pieces for the same chain), MWAA (always-on cost) |
| **EventBridge + SNS** | Glue Workflows can't send alerts themselves; an EventBridge rule on job failures forwards them to email at no running cost | CloudWatch alarms per job |
| **Terraform** | Whole platform reproducible from code; the dev stack is destroyed and recreated regularly to save cost | Console setup (not repeatable), CloudFormation |
| **GitHub Actions + OIDC** | Required CI/CD on GitHub; OIDC gives each run short-lived AWS credentials, so no AWS keys are stored in GitHub | Long-lived access keys as secrets |
| **Streamlit** | Required by the brief; Python only; reads gold through Athena | QuickSight (extra licence) |

## 3. Ingestion (job 0, `etl/jobs/extract.py`)

- **Incremental:** pulls `order_items` created after a **watermark** = newest `creation_time_utc` already in silver
  **minus a 2-day lookback**, up to the moment the run started. The overlap catches late-arriving rows; silver's
  MERGE makes the overlap harmless.
- `order_item_options` has no timestamp, so it is pulled by **joining to its parent line items** in the same window.
- **First run** (no silver yet): full, unfiltered copy, which also brings orphan options so silver can quarantine them.
- Every run writes to a **new** `raw/<table>/run_id=<UTC timestamp>/` folder (`errorifexists`): raw is an
  immutable history, so silver can always be rebuilt without touching the source.
- Row counts read from SQL Server are compared with the rows written; a mismatch fails the job.

## 4. Silver (job 1, `etl/jobs/silver.py`)

| Table | Key | Rule |
|---|---|---|
| `gp_silver.order_items` | `lineitem_id` | lower-case columns, one row per key, MERGE |
| `gp_silver.order_item_options` | `order_id, lineitem_id, option_group_name, option_name` | exact duplicates removed (2,299), orphans quarantined (28), MERGE |

- **Quarantine instead of silent drops:** rows with a missing key (`NULL = NULL` is not true, so MERGE would
  re-insert them on every run) and orphan options go to `quarantine/<table>/run_id=<run>/reason=<reason>/`.
- Every source row is accounted for: 203,519 = 203,518 in silver + 1 quarantined; 193,017 = 190,690 + 2,299 duplicates + 28 orphans.
- Tables are Iceberg **format v2** (row-level DELETE/UPDATE from Athena).

## 5. Gold data model (job 2, `etl/jobs/gold.py`)

**Revenue of a line = `item_price` + Σ(`option_price` × `option_quantity`).** In this data `item_price` is
already a line total (the average price rises with quantity), so it is not multiplied by quantity.
Total revenue: **$1,863,974.28**, of which $1,690,600.00 is from identified customers.

| Table | Grain | Answers |
|---|---|---|
| `customer_ltv_daily` | customer × day with an order | **How LTV evolves daily** (primary goal): `daily_revenue`, `daily_orders`, `ltv_to_date` (running total). Days without orders have no row; the LTV on such a day is the latest row before it. |
| `customer_profile` | customer | CLV (`lifetime_value`, `clv_tier`), RFM (`recency_days`, `frequency_12m`, `monetary_12m`, scores, `rfm_segment`), churn (`days_since_last_order`, `avg_days_between_orders`, `spend_change_pct`, `churn_status`), `is_loyalty_member` |
| `date_dim` | calendar day, 2020–2024 | day of week, ISO week, month, quarter, year, weekend, US federal holidays |
| `sales_daily` | day × hour (UTC) × location × app × category | revenue, line items, orders (orders containing the category) |
| `location_performance` | location | revenue, orders, average order value, unique customers, repeat-customer %, orders per active day / week, revenue rank |
| `order_pricing` | order | net (charged) vs gross (usual-price) revenue, implied discount, discounted lines |
| `dq_results` | check × run | data-quality history (job 3) |

`customer_ltv_daily` is **sparse** (100,084 rows) rather than one row per customer per calendar day, which
would be millions of rows that repeat the same value.

## 6. Metric definitions

| Metric | Definition |
|---|---|
| **CLV** | Total revenue from the customer to date (historical; the brief's method). |
| **CLV tier** | Rank customers by lifetime value: **High** = top 20%, **Medium** = middle 60%, **Low** = bottom 20% (`ntile(5)`). Result: 4,035 / 12,105 / 4,034; High customers bring **76.8%** of revenue. |
| **as_of_date** | The last order date in the data, **2024-02-21**. Recency and churn are measured from it, not from today; otherwise every customer would look inactive. |
| **RFM** | R = days since last order; F = orders in the 12 months before as_of; M = spend in those 12 months. Scores 1–5 by fixed thresholds (R ≤30/90/180/365 days; F ≥12/6/3/1 orders; M ≥$500/200/75/>0). **VIP**: R, F, M ≥ 4 · **New**: R ≥ 4, F ≤ 2 · **Churn Risk**: R ≤ 2, F ≤ 2 · else **Regular**. Fixed thresholds instead of percentiles because ~9,700 customers have zero orders in the window and percentiles can't split identical values fairly. |
| **Churn indicators** | Days since last order; average days between order days; spend in the last 90 days vs the 90 before (%). **At Risk** = no order for more than 45 days. Descriptive, not predictive. |
| **Sales trends** | Daily / weekly / monthly revenue from `sales_daily`, joined to `date_dim` for weekends and holidays; by location, category, app and hour (UTC). |
| **Loyalty impact** | A customer is a **member** if any of their orders was a loyalty order (2,783 customers have both flags). Members vs non-members: average LTV ($159.40 vs $53.08), orders (11.7 vs 3.5), repeat rate, average order value. |
| **Location performance** | Per `restaurant_id` (names aren't in the data): revenue, orders, AOV, orders per day/week, retention; ranked by revenue. |
| **Discounts (estimate)** | The data has **no discount fields** (no negative `option_price`). A line is treated as discounted when its unit price is below **90% of the median** unit price of the same item at the same location in the same year (14,953 of 131,328 orders; ~$25.7k). Profit can't be computed: there is no cost data. |

## 7. Data quality (job 3, `etl/jobs/dq.py`)

15 **CRITICAL** checks (fail the pipeline and alert): silver not empty; keys unique; no missing keys; no orphans;
gold revenue reconciles to silver in `sales_daily`, `location_performance` and `order_pricing`; customer LTV
reconciles between `customer_profile` and `customer_ltv_daily`; final `ltv_to_date` = `lifetime_value` per
customer; High and Low tiers are 20% (±1 point); `date_dim` covers every sales date; gold is as fresh as silver.

4 **WARNING** checks (recorded only), currently flagging: 1 test row (`item_name = 'Test'`), 2 customers with
$0 lifetime value, 15 customers over $5,000 (possible business accounts), and 8.75% of lines without a customer.

## 8. Operations

- **Schedule:** daily at 06:00 UTC while the stack exists; `make pipeline ENV=dev` runs it on demand.
- **Failure reload:** each job starts only when the previous one SUCCEEDED, so a failure stops the chain before bad data spreads, and the failure alert fires. Every step is safe to re-run: raw runs never overwrite each other, silver MERGE is idempotent, and gold tables are replaced atomically (the previous gold stays readable until a new version is complete). To recover, fix the cause and resume the workflow run from the failed job in the Glue console, or start a new run.
- **Security and encryption:** customer-managed KMS key for S3 (SSE-KMS with bucket key), RDS storage and Athena results; HTTPS-only bucket policy; RDS requires TLS (`rds.force_ssl=1`); RDS and Glue in private subnets with no internet route; S3 gateway endpoint and interface endpoints for Secrets Manager, Glue, CloudWatch Logs and KMS; DB password generated and stored by RDS in Secrets Manager; least-privilege security groups; Glue and CI use IAM roles (temporary credentials, no stored keys).
- **Cost control:** the dev stack is destroyed when not in use (`make destroy ENV=dev`) and recreated with `make apply`; RDS and the interface endpoints are the only hourly costs.

## 9. Assumptions for SME sign-off

1. `item_price` is a **line total**, not a unit price (the data contradicts the brief's description).
2. Revenue includes option prices × option quantity.
3. RFM window of **12 months**, the score thresholds in section 6, and the segment rules.
4. Churn threshold of **45 days**; spend trend over **90-day** periods.
5. Loyalty membership = **any** loyalty order.
6. **US federal holidays** stand in for the company holiday list (`date_dim` was not provided).
7. The **discount estimate** (90% of the item's median price, per location and year) in place of real discount data.
8. Times are **UTC**; store time zones aren't in the data.
9. The 15 customers over $5,000 and the "Test" row are kept in the metrics until the SME decides whether to exclude them.

## 10. Known limitations and next steps

- RDS certificate trust: the JDBC connection is encrypted but uses `trustServerCertificate=true`; trust the RDS CA bundle instead.
- Glue job blocks repeat the same settings; refactor to one `for_each` over a map.
- Tighten the Glue security group's egress from all destinations to only RDS, the endpoints and the S3 prefix list.
- Add a KMS-encrypted Glue security configuration for job logs.
- Guard `make destroy` against `ENV=prod`; give prod its own AWS account (the catalog database names are per account).
- Replace the discount estimate once real promotion data is available.
