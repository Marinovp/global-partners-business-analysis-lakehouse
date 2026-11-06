# What Was Built

Every AWS object in the project, what it is for, and how it connects to the others.
All names start with **`gp-lakehouse-dev`** (the `dev` environment) unless noted. Region: **us-west-2**.
For the reasoning behind the design, see [solution-design.md](solution-design.md).

## The big picture

```
data/*.csv ─► S3 seed/ ─► [seed job] ─► RDS SQL Server ─► [extract] ─► S3 raw/ ─► [silver] ─► Iceberg silver
                                                                                    └─► S3 quarantine/
Iceberg silver ─► [gold] ─► Iceberg gold ─► [dq] ─► dq_results        Athena ◄── Streamlit dashboard
                     the 4 pipeline jobs run in order inside the Glue Workflow; failures email you
```

## 1. Permanent stack (`infra/bootstrap`) — survives every destroy

| Object | Name | What it does |
|---|---|---|
| S3 bucket | `gp-lakehouse-tfstate-<account>` | Stores Terraform state. Versioned, encrypted, private, protected from deletion. |
| IAM OIDC provider | `token.actions.githubusercontent.com` | Lets GitHub prove "this run comes from our repo" to AWS. |
| IAM role | `gp-lakehouse-github-actions` | Role GitHub Actions uses to plan/apply. Only this repository can assume it. Permissions: AWS `PowerUserAccess` + managing IAM roles named `gp-lakehouse-*`. |

## 2. Network

| Object | Name | What it does |
|---|---|---|
| VPC | `…-vpc` (10.20.0.0/16) | Private network for RDS and Glue. **No internet gateway, no NAT**: nothing in it can reach or be reached from the internet. |
| 2 private subnets | `…-private-us-west-2a` / `-2b` (10.20.0.0/24, 10.20.1.0/24) | RDS needs two zones; Glue and the endpoints use 2a. |
| Route table | `…-private-rt` | The subnets' only routes: inside the VPC, and S3 via the gateway endpoint. |
| S3 gateway endpoint | `…-s3-endpoint` | Private path to S3 (free). |
| 4 interface endpoints | `…-secretsmanager/-glue/-logs/-kms-endpoint` | Private paths to Secrets Manager (DB password), Glue API (catalog), CloudWatch Logs (job logs), KMS. Billed hourly. |

## 3. Security groups (firewalls)

| Group | Allows in | Used by |
|---|---|---|
| `…-glue-sg` | All TCP **from itself** (Spark nodes talk to each other); all traffic out | Glue jobs that run in the VPC |
| `…-rds-sg` | TCP **1433 from glue-sg** only | RDS |
| `…-endpoints-sg` | TCP **443 from glue-sg** only | Interface endpoints |

Replies are allowed automatically (security groups are stateful), so RDS and the endpoints need no outbound rules.

## 4. Encryption and storage

| Object | Name | What it does |
|---|---|---|
| KMS key + alias | `alias/gp-lakehouse-dev` | Encrypts S3 data, RDS storage and Athena results. Yearly rotation; 7-day deletion window. |
| S3 bucket | `gp-lakehouse-dev-<account>` | The data lake. Encrypted with the KMS key, private, **HTTPS-only** policy. Deleted with the stack. |

Folders (prefixes) in the data bucket:

| Prefix | Contents |
|---|---|
| `seed/` | The source CSVs (uploaded by `make seed`) |
| `artifacts/jobs/` | The 5 Glue job scripts (uploaded by Terraform) · `artifacts/tmp/` Glue temp files |
| `raw/<table>/run_id=<time>/` | One untouched Parquet copy per extract run |
| `silver/`, `gold/` | Iceberg table files |
| `quarantine/<table>/run_id=<run>/reason=<reason>/` | Rejected rows (missing key, orphan option) |
| `athena-results/` | Athena query results |

## 5. Source database (simulates the company's SQL Server)

| Object | Name | What it does |
|---|---|---|
| RDS instance | `…-sqlserver` | SQL Server 2022 **Express** (no licence fee), `db.t3.micro`, 20 GB. Private, KMS-encrypted, no backups (dev). Database `globalpartners` with `order_items` and `order_item_options`. |
| DB subnet group | `…-db-subnets` | Which subnets RDS may use (both). |
| Parameter group | `…-sqlserver` | `rds.force_ssl = 1`: refuses unencrypted connections. |
| Secret | `rds!db-…` | DB username/password, **created by RDS** in Secrets Manager. Nobody types or sees it. |

## 6. IAM role for Glue

**`gp-lakehouse-dev-glue-role`**, used by every Glue job.

| Part | Grants |
|---|---|
| Trust policy | Only the Glue service can use the role. |
| `AWSGlueServiceRole` (AWS managed) | Glue basics: logs, network interfaces in the VPC, Data Catalog. |
| `…-glue-access` (inline) | S3 list/read/write/delete on the data bucket only · KMS `Decrypt` + `GenerateDataKey` on the project key · read the DB secret. |

## 7. Glue: connection, jobs, workflow

**Glue connection `…-sqlserver`** (JDBC): puts a job's network interfaces in subnet 2a with `glue-sg`, and points it at the RDS database and secret. Only jobs that talk to RDS use it.

**Jobs** (all: Glue 4.0, 2 × G.1X workers, 30-minute timeout, no automatic retries; scripts in `etl/jobs/`):

| Job | Script | In VPC? | Reads → writes |
|---|---|---|---|
| `…-seed-rds` | `seed_rds.py` | yes | S3 `seed/*.csv` → SQL Server tables (setup only, run after each rebuild) |
| `…-extract` (job 0) | `extract.py` | yes | SQL Server → `raw/` Parquet. Full first time, then only new rows (watermark − 2 days). |
| `…-silver` (job 1) | `silver.py` | no | Latest `raw/` → `gp_silver` (MERGE, dedupe) + `quarantine/` |
| `…-gold` (job 2) | `gold.py` | no | `gp_silver` → 7 tables in `gp_gold` (rebuilt atomically) |
| `…-dq` (job 3) | `dq.py` | no | Checks silver + gold → `gp_gold.dq_results`; **fails** on any critical problem |

**Workflow `…-pipeline`** (one run at a time) and its triggers:

| Trigger | Type | Starts |
|---|---|---|
| `…-start` | Schedule, daily 06:00 UTC (or `make pipeline`) | extract |
| `…-after-extract` | When extract **SUCCEEDED** | silver |
| `…-after-silver` | When silver **SUCCEEDED** | gold |
| `…-after-gold` | When gold **SUCCEEDED** | dq |

A failed job stops the chain: nothing after it runs.

## 8. Catalog, query and alerts

| Object | Name | What it does |
|---|---|---|
| Glue databases | `gp_raw`, `gp_silver`, `gp_gold` | The table list Athena and Spark use (metadata only; data is in S3). |
| Athena workgroup | `…-wg` | Query settings: results to `athena-results/`, KMS-encrypted, queries over **1 GB** scanned are cancelled. |
| SNS topic | `…-pipeline-alerts` | Sends failure emails (if `alert_email` is set; confirm AWS's email first). |
| EventBridge rule | `…-job-failed` | Watches the 4 pipeline jobs; on FAILED / TIMEOUT / ERROR it sends a message to the SNS topic. |

## 9. Tables

| Table | One row per | Holds |
|---|---|---|
| `gp_silver.order_items` | order line | Cleaned source line items |
| `gp_silver.order_item_options` | option on a line | Cleaned add-ons (duplicates and orphans removed) |
| `gp_gold.customer_ltv_daily` | customer × order day | **Daily LTV** (running total) |
| `gp_gold.customer_profile` | customer | CLV tier, RFM segment, churn status, loyalty |
| `gp_gold.date_dim` | calendar day | Weekday, month, weekend, holiday |
| `gp_gold.sales_daily` | day × hour × location × app × category | Revenue and volumes |
| `gp_gold.location_performance` | location | Revenue, orders, AOV, retention, rank |
| `gp_gold.order_pricing` | order | Charged vs usual-price revenue (discount estimate) |
| `gp_gold.dq_results` | check × run | Data-quality history |

## 10. Outside AWS

| Item | Where | What it does |
|---|---|---|
| Streamlit dashboard | `dashboard/` | 8 pages; runs on your laptop and queries gold through Athena. |
| CI workflow | `.github/workflows/ci.yml` | On every PR/push: format, validate, Python syntax, then a Terraform plan. |
| Deploy workflow | `.github/workflows/deploy.yml` | Manual button: apply or destroy the dev stack. |
| Makefile | repo root | `plan`, `apply`, `destroy`, `seed`, `seed-rds`, `pipeline`, single jobs, `check`. |
| SQL versions | `etl/sql/` | The same logic as SQL, for review. |

## What costs money

| While the stack is up | About |
|---|---|
| RDS `db.t3.micro` + storage | $0.03/hour |
| 4 interface endpoints | $0.04/hour |
| KMS key | $1/month, prorated |
| Glue job runs | ~$0.05 per job run (billed per second) |
| Athena | $5 per TB scanned (these tables: fractions of a cent) |
| Everything else (VPC, S3 at this size, IAM, SNS, EventBridge, catalog) | ~$0 |

Run `make destroy ENV=dev` when you stop working; the permanent stack costs almost nothing.
