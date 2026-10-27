"""Job 1 - Silver: merge the latest raw extract into Apache Iceberg tables in gp_silver.

MERGE on the business key makes re-runs and overlapping extracts safe: no duplicates.
"""

import sys

import boto3
from awsglue.utils import getResolvedOptions
from pyspark.sql import SparkSession

args = getResolvedOptions(sys.argv, ["bucket"])

# Register the Glue Data Catalog as an Iceberg catalog called "glue_catalog".
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


def latest_run_path(table: str) -> str:
    """raw/<table>/ holds one run_id=... folder per extract; return the newest one."""
    resp = boto3.client("s3").list_objects_v2(
        Bucket=args["bucket"], Prefix=f"raw/{table}/", Delimiter="/"
    )
    newest = max(
        p["Prefix"] for p in resp["CommonPrefixes"]
    )  # run_ids are timestamps, so max = newest
    return f"s3://{args['bucket']}/{newest}"


raw = spark.read.parquet(latest_run_path("order_items"))
raw = raw.toDF(*[c.lower() for c in raw.columns])  # silver uses lowercase column names
updates = raw.dropDuplicates(["lineitem_id"])  # MERGE needs one source row per key
updates.createOrReplaceTempView("updates")

table = "glue_catalog.gp_silver.order_items"
spark.sql(
    f"CREATE TABLE IF NOT EXISTS {table} USING iceberg AS SELECT * FROM updates LIMIT 0"
)
spark.sql(f"""
    MERGE INTO {table} t
    USING updates s
    ON t.lineitem_id = s.lineitem_id
    WHEN MATCHED THEN UPDATE SET *
    WHEN NOT MATCHED THEN INSERT *
""")
print(f"{table}: {spark.table(table).count()} rows after merge")
