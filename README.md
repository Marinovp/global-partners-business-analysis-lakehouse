# Global Partners Business Insights Lakehouse

An AWS lakehouse that turns restaurant order data into customer and business insights: **Customer Lifetime
Value (daily, with High/Medium/Low tiers)**, RFM segments, churn indicators, sales trends, loyalty impact,
location performance and pricing, served through a Streamlit dashboard.

```
SQL Server (RDS) → Glue PySpark: extract → silver (Iceberg) → gold (Iceberg) → DQ gate → Athena → Streamlit
                   orchestrated by a Glue Workflow · failures alert via EventBridge + SNS · built with Terraform
```

- **Design, data model, metric definitions, "why" of each technology, assumptions:** [docs/solution-design.md](docs/solution-design.md)
- **Architecture diagram:** [docs/architecture/global_partners_lakehouse.drawio](docs/architecture/global_partners_lakehouse.drawio)
- **SQL version of every query (for review):** [etl/sql/](etl/sql/README.md)

## Repository layout

```
infra/bootstrap/        Terraform state bucket + GitHub OIDC deploy role (permanent, applied once)
infra/lakehouse/        The platform: VPC, RDS, S3, KMS, Glue jobs + workflow, Athena, alerts
  env/dev.*             Environment settings (backend + variables), chosen at run time
etl/jobs/               PySpark Glue jobs: seed_rds, extract, silver, gold, dq
etl/sql/                The same logic in SQL (source, silver, gold, dq, dashboard queries)
dashboard/              Streamlit app (reads gold via Athena)
.github/workflows/      CI (checks + plan) and Deploy (manual apply/destroy)
data/                   Source CSVs (not in Git; see data/README.md)
Makefile                One-word commands for everything below
```

## Prerequisites

Terraform ≥ 1.10, AWS CLI v2 with credentials for the target account (region `us-west-2`), Python 3.10+,
`make`. The source CSVs in `data/` (`order_items.csv`, `order_item_options.csv`).

## Running it

**Once per account** — create the state bucket and the GitHub deploy role:
```
terraform -chdir=infra/bootstrap init && terraform -chdir=infra/bootstrap apply
```

**Bring the stack up** (about 15 minutes, mostly RDS):
```
export TF_VAR_alert_email=you@example.com   # optional: failure alerts (confirm the email AWS sends)
make plan ENV=dev
make apply ENV=dev
make seed ENV=dev        # upload data/*.csv to S3
make seed-rds ENV=dev    # load them into SQL Server; wait until the job SUCCEEDED (Glue console)
make pipeline ENV=dev    # extract → silver → gold → dq; also runs daily at 06:00 UTC
```

**Check and run single jobs:** `make check ENV=dev` (format, validate, Python syntax) · `make extract | silver | gold | dq ENV=dev`.

**Tear down when not in use** (everything except the bootstrap stack; data in S3 is deleted too):
```
make destroy ENV=dev
```

## Dashboard

Runs locally with your AWS credentials and queries Athena (workgroup `gp-lakehouse-dev-wg`):
```
python3 -m venv .venv && source .venv/bin/activate
pip install -r dashboard/requirements.txt
streamlit run dashboard/app.py
```
Pages: Customer Lifetime Value · Customer Segmentation · Churn Risk · Sales Trends & Seasonality ·
Loyalty Program Impact · Location Performance · Pricing & Discounts · Data Quality.

## CI/CD (GitHub Actions)

- **CI** (`.github/workflows/ci.yml`), on every PR and push to `main`: Terraform format and validation, Python
  syntax, then `terraform plan` against dev.
- **Deploy** (`.github/workflows/deploy.yml`), run by hand (Actions → Deploy → Run workflow): `apply` or `destroy`
  the dev stack. Manual on purpose, so a merge never brings the paid stack back up unannounced.

Setup after applying the bootstrap stack:
1. Repository → Settings → Secrets and variables → Actions → **Variables**: `AWS_ROLE_ARN` =
   `terraform -chdir=infra/bootstrap output -raw github_actions_role_arn`
2. Optional **secret** `ALERT_EMAIL` for failure alerts.
3. Optional: Settings → Environments → `dev` → required reviewers, so every deploy needs approval.

Authentication uses **OIDC**: each run gets temporary AWS credentials; no AWS keys are stored in GitHub.

## Data notes

Data covers 2020-04-21 → 2024-02-21 (203,519 order lines, 193,017 options, 20,174 customers, 28 locations).
Findings that shaped the design, all detailed in the solution design: `item_price` is a line total; there are
no discounts in the data (the dashboard shows a labelled estimate); 8.75% of lines have no customer;
`date_dim` was generated (US federal holidays); recency is measured from the last order date, not today.
