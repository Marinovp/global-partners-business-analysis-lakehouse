# Building It by Hand in the AWS Console

The same stack Terraform builds, created click by click. Useful to learn what Terraform does for you.
Follow the steps **in order**: later objects need earlier ones.

- Region: **US West (Oregon) us-west-2** (top right, every page).
- Replace `<acct>` with your 12-digit account ID.
- ⚠️ marks places where the console's default differs from our design.
- When finished, tear it down with [section 13](#13-tear-down) (or Terraform will conflict with the same names).

## 1. KMS key

**KMS → Customer managed keys → Create key**
1. Symmetric · Encrypt and decrypt → Next.
2. Alias: `gp-lakehouse-dev`.
3. Key administrators and users: select your own user → Finish.
4. Open the key → **Key rotation** tab → enable automatic rotation (yearly).

## 2. S3 data bucket

**S3 → Create bucket**
1. Name: `gp-lakehouse-dev-<acct>`.
2. Block **all** public access: keep on.
3. Default encryption: **SSE-KMS** → choose `alias/gp-lakehouse-dev` → **Bucket Key: Enable**.
4. Create. Then **Permissions → Bucket policy** → paste (HTTPS only):
```json
{"Version":"2012-10-17","Statement":[{"Sid":"DenyNonTLS","Effect":"Deny","Principal":"*","Action":"s3:*",
 "Resource":["arn:aws:s3:::gp-lakehouse-dev-<acct>","arn:aws:s3:::gp-lakehouse-dev-<acct>/*"],
 "Condition":{"Bool":{"aws:SecureTransport":"false"}}}]}
```

## 3. Network (VPC)

**VPC → Your VPCs → Create VPC**
1. ⚠️ Choose **"VPC only"**, not "VPC and more" (that wizard adds public subnets, an internet gateway and possibly a NAT gateway).
2. Name `gp-lakehouse-dev-vpc`, CIDR `10.20.0.0/16` → Create.
3. **Actions → Edit VPC settings** → enable **DNS hostnames** (needed for private endpoint DNS).

**Subnets → Create subnet** (in that VPC), two of them:

| Name | AZ | CIDR |
|---|---|---|
| `gp-lakehouse-dev-private-us-west-2a` | us-west-2a | `10.20.0.0/24` |
| `gp-lakehouse-dev-private-us-west-2b` | us-west-2b | `10.20.1.0/24` |

**Route tables → Create route table** `gp-lakehouse-dev-private-rt` (this VPC) → **Subnet associations** → add both subnets.
Add no other routes: no internet route keeps everything private.

**Security groups → Create security group** (this VPC), three:

| Name | Inbound rule |
|---|---|
| `gp-lakehouse-dev-glue-sg` | All TCP, source = **this same group** (save first, then edit to add the self-reference) |
| `gp-lakehouse-dev-rds-sg` | MSSQL / TCP 1433, source = `glue-sg` |
| `gp-lakehouse-dev-endpoints-sg` | HTTPS / TCP 443, source = `glue-sg` |

⚠️ The console gives every group an "allow all outbound" rule. Keep it on `glue-sg`. On the other two it's harmless, but Terraform has none: they only answer, never start connections.

**Endpoints → Create endpoint**
1. Gateway: service `com.amazonaws.us-west-2.s3` (type Gateway) → this VPC → route table `private-rt`. Name `gp-lakehouse-dev-s3-endpoint`.
2. Interface, once for each of `secretsmanager`, `glue`, `logs`, `kms` (`com.amazonaws.us-west-2.<name>`):
   VPC → subnet **us-west-2a only** → security group `endpoints-sg` → **Enable private DNS name** on.
   Name `gp-lakehouse-dev-<name>-endpoint`. (These cost ~$0.01/hour each.)

## 4. RDS SQL Server

**RDS → Parameter groups → Create**: family `sqlserver-ex-16.0`, name `gp-lakehouse-dev-sqlserver` → open it → edit `rds.force_ssl` = `1`.

**RDS → Subnet groups → Create**: name `gp-lakehouse-dev-db-subnets`, this VPC, both AZs and subnets.

**RDS → Create database**
1. Standard create · **Microsoft SQL Server** · Edition **SQL Server Express** · version 16.00.x.
2. Identifier `gp-lakehouse-dev-sqlserver` · master username `dbadmin` · **Managed in AWS Secrets Manager**.
3. Instance `db.t3.micro` · storage 20 GiB.
4. Connectivity: this VPC · subnet group `db-subnets` · **Public access: No** · security group: `rds-sg` only (⚠️ remove `default`).
5. Additional configuration: parameter group `gp-lakehouse-dev-sqlserver` · backups at the minimum offered · encryption with `alias/gp-lakehouse-dev` · deletion protection **off**.
6. Create and wait ~15 minutes for **Available**. Secrets Manager now has a secret `rds!db-…` with the password.

## 5. IAM role for Glue

**IAM → Roles → Create role**
1. Trusted entity: AWS service → **Glue**.
2. Attach `AWSGlueServiceRole`. Name `gp-lakehouse-dev-glue-role` → Create.
3. Open the role → **Add permissions → Create inline policy → JSON** (name `gp-lakehouse-dev-glue-access`):
```json
{"Version":"2012-10-17","Statement":[
 {"Effect":"Allow","Action":"s3:ListBucket","Resource":"arn:aws:s3:::gp-lakehouse-dev-<acct>"},
 {"Effect":"Allow","Action":["s3:GetObject","s3:PutObject","s3:DeleteObject"],"Resource":"arn:aws:s3:::gp-lakehouse-dev-<acct>/*"},
 {"Effect":"Allow","Action":["kms:Decrypt","kms:GenerateDataKey"],"Resource":"<KMS key ARN from step 1>"},
 {"Effect":"Allow","Action":"secretsmanager:GetSecretValue","Resource":"<rds!db-… secret ARN from step 4>"}]}
```

## 6. Catalog and Athena

1. **Glue → Data Catalog → Databases → Add database**, three times: `gp_raw`, `gp_silver`, `gp_gold`.
2. **Athena → Workgroups → Create workgroup** `gp-lakehouse-dev-wg`:
   query result location `s3://gp-lakehouse-dev-<acct>/athena-results/` · encrypt results **SSE_KMS** with the project key ·
   **Per query data usage control: 1 GB** · override client-side settings: on.

## 7. Upload files

In the bucket (**S3 → bucket → Upload**):
- `data/order_items.csv`, `data/order_item_options.csv` → folder `seed/`
- `etl/jobs/*.py` (5 scripts) → folder `artifacts/jobs/`

## 8. Glue connection

**Glue → Data connections → Create connection → Microsoft SQL Server**
1. Host: the RDS endpoint (RDS → database → Connectivity), port 1433, database `globalpartners`.
2. Credentials: **AWS Secrets Manager** → the `rds!db-…` secret.
3. Network: this VPC · subnet **us-west-2a** · security group `glue-sg`.
4. Name `gp-lakehouse-dev-sqlserver` → Create.

## 9. Glue jobs

For each job: **Glue → ETL jobs → Script editor → Spark → Upload script** (pick the file), then **Job details**:
- Name (below) · IAM role `gp-lakehouse-dev-glue-role` · **Glue 4.0** · worker **G.1X**, **2** workers · retries **0** · timeout **30** minutes.
- Script path: `s3://gp-lakehouse-dev-<acct>/artifacts/jobs/<script>` · Temporary path: `s3://…/artifacts/tmp/`.
- **Advanced → Job parameters** (key = value, keys include `--`):

| Job name | Script | Connection | Job parameters |
|---|---|---|---|
| `gp-lakehouse-dev-seed-rds` | `seed_rds.py` | `…-sqlserver` | `--bucket`, `--db_host`, `--db_port`=1433, `--db_name`=globalpartners, `--secret_arn`, `--aws_region`=us-west-2 |
| `gp-lakehouse-dev-extract` | `extract.py` | `…-sqlserver` | same as seed + `--datalake-formats`=iceberg, `--lookback_days`=2 |
| `gp-lakehouse-dev-silver` | `silver.py` | none | `--bucket`, `--datalake-formats`=iceberg |
| `gp-lakehouse-dev-gold` | `gold.py` | none | `--bucket`, `--datalake-formats`=iceberg |
| `gp-lakehouse-dev-dq` | `dq.py` | none | `--bucket`, `--datalake-formats`=iceberg |

`--bucket` = `gp-lakehouse-dev-<acct>` · `--db_host` = the RDS endpoint · `--secret_arn` = the `rds!db-…` secret ARN.

Then **run `seed-rds` once** (Run → wait for *Succeeded*): it creates the database and loads the CSVs.

## 10. Workflow

**Glue → Workflows → Add workflow** `gp-lakehouse-dev-pipeline`, max concurrency **1**. Open it → graph:
1. **Add trigger** `gp-lakehouse-dev-start`: type **Schedule**, daily, 06:00 UTC → add node: job `extract`.
2. Click `extract` → **Add trigger** `…-after-extract`: type **Event**, watch `extract` = **SUCCEEDED** → add `silver`.
3. Same from `silver` → `…-after-silver` → `gold`, and from `gold` → `…-after-gold` → `dq`.

⚠️ New triggers can be created "deactivated". Check each trigger is **Activated** (Glue → Triggers).

## 11. Failure alerts

1. **SNS → Topics → Create topic**: Standard, `gp-lakehouse-dev-pipeline-alerts` → **Create subscription**: Email → your address → confirm the email AWS sends.
2. **EventBridge → Rules → Create rule** `gp-lakehouse-dev-job-failed` → event pattern (custom JSON):
```json
{"source":["aws.glue"],"detail-type":["Glue Job State Change"],
 "detail":{"state":["FAILED","TIMEOUT","ERROR"],
  "jobName":["gp-lakehouse-dev-extract","gp-lakehouse-dev-silver","gp-lakehouse-dev-gold","gp-lakehouse-dev-dq"]}}
```
   Target: SNS topic `…-pipeline-alerts`. (The console adds the topic permission for you.)

## 12. Run and check

1. **Glue → Workflows → pipeline → Run workflow** → **History** shows extract → silver → gold → dq.
2. **Athena** (workgroup `gp-lakehouse-dev-wg`):
```sql
SELECT count(*) FROM gp_silver.order_items;        -- 203,518
SELECT clv_tier, count(*) FROM gp_gold.customer_profile GROUP BY 1;   -- 4,035 / 12,105 / 4,034
SELECT * FROM gp_gold.dq_results ORDER BY run_ts DESC LIMIT 20;       -- 0 critical failures
```

## 13. Tear down

Delete in this order (each one blocks the next while it exists):
1. Workflow, then its 4 triggers · the 5 Glue jobs · the Glue connection.
2. EventBridge rule · SNS topic.
3. RDS database (⚠️ uncheck "final snapshot"; the secret goes with it) → then its parameter group and subnet group.
4. The 5 VPC endpoints.
5. Security groups: `rds-sg` and `endpoints-sg` first (they reference `glue-sg`), then `glue-sg`.
6. Route table · subnets · VPC.
7. Athena workgroup (delete with its contents) · Glue databases (with their tables).
8. S3 bucket: **Empty** first, then delete.
9. KMS key: **Schedule deletion** (7 days minimum) · IAM role `gp-lakehouse-dev-glue-role`.

With Terraform, all of this is `make destroy ENV=dev`.
