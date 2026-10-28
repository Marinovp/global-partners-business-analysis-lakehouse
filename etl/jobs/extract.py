"""Job 0 - Extract: copy the source tables from SQL Server to S3 raw/ as Parquet.

Incremental: only rows newer than the watermark (newest creation_time_utc already in silver,
minus a lookback for late-arriving rows). First run, when silver doesn't exist yet: full copy.
Every run writes to a new folder raw/<table>/run_id=<id>/ and never overwrites an older run.
"""

import json
import sys
from datetime import datetime, timezone

import boto3
from awsglue.utils import getResolvedOptions
from pyspark.sql import SparkSession
from pyspark.sql.utils import AnalysisException

args = getResolvedOptions(
    sys.argv,
    [
        "bucket",
        "db_host",
        "db_port",
        "db_name",
        "secret_arn",
        "aws_region",
        "lookback_days",
    ],
)

# Iceberg catalog config (same as silver.py) so this job can read the watermark from gp_silver.
spark = (
    SparkSession.builder.config(
        "spark.sql.extensions",
        "org.apache.iceberg.spark.extensions.IcebergSparkSessionExtensions",
    )
    .config("spark.sql.catalog.glue_catalog", "org.apache.iceberg.spark.SparkCatalog")
    .config(
        "spark.sql.catalog.glue_catalog.catalog-impl",
        "org.apache.iceberg.aws.glue.GlueCatalog",
    )
    .config(
        "spark.sql.catalog.glue_catalog.io-impl", "org.apache.iceberg.aws.s3.S3FileIO"
    )
    .config(
        "spark.sql.catalog.glue_catalog.warehouse", f"s3://{args['bucket']}/silver/"
    )
    .getOrCreate()
)
spark.conf.set("spark.sql.session.timeZone", "UTC")

secret = json.loads(
    boto3.client("secretsmanager", region_name=args["aws_region"]).get_secret_value(
        SecretId=args["secret_arn"]
    )["SecretString"]
)
user, password = secret["username"], secret["password"]

base_url = f"jdbc:sqlserver://{args['db_host']}:{args['db_port']};encrypt=true;trustServerCertificate=true"
db_url = f"{base_url};databaseName={args['db_name']}"
jdbc_options = {
    "user": user,
    "password": password,
    "driver": "com.microsoft.sqlserver.jdbc.SQLServerDriver",
}

run_start = datetime.now(timezone.utc)
run_id = run_start.strftime("%Y%m%dT%H%M%SZ")
upper_bound = run_start.strftime("%Y-%m-%d %H:%M:%S.%f")[
    :-3
]  # rows created after the run started wait for the next run


def watermark() -> str | None:
    """Newest creation_time_utc already in silver, minus the lookback. None means: no silver yet, do a full copy."""
    try:
        spark.table("glue_catalog.gp_silver.order_items").createOrReplaceTempView(
            "silver_items"
        )
    except AnalysisException:
        return None
    lookback = int(args["lookback_days"])
    return spark.sql(f"""
        SELECT date_format(max(creation_time_utc) - INTERVAL {lookback} DAYS, 'yyyy-MM-dd HH:mm:ss.SSS')
        FROM silver_items
    """).first()[0]  # also None if the table exists but is empty


def extract_table(table: str, query: str) -> None:
    df = (
        spark.read.format("jdbc")
        .options(url=db_url, query=query, **jdbc_options)
        .load()
        .cache()
    )
    source_rows = df.count()

    path = f"s3://{args['bucket']}/raw/{table}/run_id={run_id}"
    df.write.mode("errorifexists").parquet(path)

    written_rows = spark.read.parquet(path).count()
    print(
        f"{table}: {source_rows} rows in SQL Server, {written_rows} rows written to {path}"
    )
    if written_rows != source_rows:
        raise RuntimeError(f"{table}: row count mismatch")


lower_bound = watermark()
if lower_bound is None:
    # Full copy. Unfiltered on purpose: it also captures orphan options, so silver can quarantine them.
    print("No silver yet: full extract")
    queries = {
        "order_items": "SELECT * FROM dbo.order_items",
        "order_item_options": "SELECT * FROM dbo.order_item_options",
    }
else:
    print(
        f"Incremental extract: creation_time_utc > {lower_bound} and <= {upper_bound}"
    )

    def in_window(column: str) -> str:
        return f"{column} > '{lower_bound}' AND {column} <= '{upper_bound}'"

    queries = {
        "order_items": f"SELECT * FROM dbo.order_items WHERE {in_window('CREATION_TIME_UTC')}",
        # Options have no timestamp: take the options of the line items in the window.
        "order_item_options": f"""
            SELECT o.* FROM dbo.order_item_options o
            JOIN dbo.order_items i ON o.ORDER_ID = i.ORDER_ID AND o.LINEITEM_ID = i.LINEITEM_ID
            WHERE {in_window('i.CREATION_TIME_UTC')}
        """,
    }

for table, query in queries.items():
    extract_table(table, query)
