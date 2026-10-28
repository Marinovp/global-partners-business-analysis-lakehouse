"""Job 1 - Silver: merge the latest raw extract into Apache Iceberg tables in gp_silver.

MERGE on the business key makes re-runs and overlapping extracts safe: no duplicates.
"""

import sys

import boto3
from awsglue.utils import getResolvedOptions
from pyspark.sql import DataFrame, SparkSession

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


def quarantine(rejects: DataFrame, table: str, reason: str, run: str) -> None:
    """Keep rejected rows instead of silently dropping them: quarantine/<table>/<run>/reason=<reason>/."""
    path = f"s3://{args['bucket']}/quarantine/{table}/{run}/reason={reason}/"
    # overwrite is safe here: the same raw run always produces the same rejects.
    rejects.write.mode("overwrite").parquet(path)
    print(f"{table}: {rejects.count()} rows quarantined ({reason})")


def merge_into_silver(
    table: str,
    keys: list[str],
    parent: str | None = None,
    parent_keys: list[str] | None = None,
) -> None:
    run_path = latest_run_path(table)
    run = run_path.rstrip("/").split("/")[-1]  # "run_id=..."
    raw = spark.read.parquet(run_path)
    raw = raw.toDF(
        *[c.lower() for c in raw.columns]
    )  # silver uses lowercase column names

    # Rows missing any key part can't be merged (NULL = NULL is not true).
    has_keys = " AND ".join(f"{k} IS NOT NULL" for k in keys)
    quarantine(raw.filter(f"NOT ({has_keys})"), table, "missing_key", run)
    updates = raw.filter(has_keys).dropDuplicates(
        keys
    )  # MERGE needs one source row per key

    # Child rows whose parent doesn't exist in silver (e.g. an option without its line item).
    if parent:
        parents = spark.table(f"glue_catalog.gp_silver.{parent}").select(*parent_keys)
        quarantine(
            updates.join(parents, parent_keys, "left_anti"), table, "orphan", run
        )
        updates = updates.join(
            parents, parent_keys, "left_semi"
        )  # keep only rows that HAVE a parent

    updates.createOrReplaceTempView("updates")

    target = f"glue_catalog.gp_silver.{table}"
    spark.sql(
        f"CREATE TABLE IF NOT EXISTS {target} USING iceberg "
        f"TBLPROPERTIES ('format-version'='2') "
        f"AS SELECT * FROM updates LIMIT 0"
    )
    on = " AND ".join(f"t.{k} = s.{k}" for k in keys)  # one "t.<key> = s.<key>" per key
    spark.sql(f"""
        MERGE INTO {target} t
        USING updates s
        ON {on}
        WHEN MATCHED THEN UPDATE SET *
        WHEN NOT MATCHED THEN INSERT *
    """)
    print(f"{target}: {spark.table(target).count()} rows after merge")


merge_into_silver("order_items", ["lineitem_id"])
merge_into_silver(
    "order_item_options",
    ["order_id", "lineitem_id", "option_group_name", "option_name"],
    parent="order_items",
    parent_keys=["order_id", "lineitem_id"],
)
