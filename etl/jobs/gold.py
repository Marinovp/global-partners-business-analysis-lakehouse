"""Job 2 - Gold: build the business tables in gp_gold from the silver Iceberg tables.

Every table is fully rebuilt and swapped in atomically, so a failed run leaves the previous
gold tables intact and queryable.
"""

import sys

from awsglue.utils import getResolvedOptions
from pyspark.sql import DataFrame, SparkSession, Window
from pyspark.sql import functions as F

args = getResolvedOptions(sys.argv, ["bucket"])

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
    .config("spark.sql.catalog.glue_catalog.warehouse", f"s3://{args['bucket']}/gold/")
    .getOrCreate()
)
spark.conf.set("spark.sql.session.timeZone", "UTC")


def write_gold(df: DataFrame, table: str) -> None:
    target = f"glue_catalog.gp_gold.{table}"
    df.writeTo(target).using("iceberg").tableProperty(
        "format-version", "2"
    ).createOrReplace()
    print(f"{target}: {spark.table(target).count()} rows")


def order_lines() -> DataFrame:
    """One row per line item with its revenue. item_price behaves as a line total in the source
    (it rises with quantity), so it is not multiplied by item_quantity."""
    options = (
        spark.table("glue_catalog.gp_silver.order_item_options")
        .groupBy("order_id", "lineitem_id")
        .agg(
            F.sum(F.col("option_price") * F.col("option_quantity")).alias(
                "options_revenue"
            )
        )
    )
    return (
        spark.table("glue_catalog.gp_silver.order_items")
        .join(options, ["order_id", "lineitem_id"], "left")
        .withColumn(
            "line_revenue",
            F.col("item_price") + F.coalesce(F.col("options_revenue"), F.lit(0)),
        )
        .withColumn("order_date", F.to_date("creation_time_utc"))
    )


def customer_ltv_daily(lines: DataFrame) -> DataFrame:
    """One row per customer per day they ordered, with lifetime value so far. Days without an
    order are not stored because the running total can't change on those days."""
    daily = (
        lines.filter(
            "user_id IS NOT NULL"
        )  # rows with no customer can't count toward anyone's LTV
        .groupBy("user_id", "order_date")
        .agg(
            F.sum("line_revenue").alias("daily_revenue"),
            F.countDistinct("order_id").alias("daily_orders"),
        )
    )
    per_customer_over_time = Window.partitionBy("user_id").orderBy("order_date")
    return daily.withColumn(
        "ltv_to_date", F.sum("daily_revenue").over(per_customer_over_time)
    )


lines = order_lines().cache()
ltv = customer_ltv_daily(lines).cache()

# Every dollar from identified customers must land in the LTV table.
expected = lines.filter("user_id IS NOT NULL").agg(F.sum("line_revenue")).first()[0]
actual = ltv.agg(F.sum("daily_revenue")).first()[0]
print(f"customer revenue: {expected} in silver, {actual} in customer_ltv_daily")
if expected != actual:
    raise RuntimeError(
        f"Revenue mismatch: {expected} in silver, {actual} in customer_ltv_daily"
    )

write_gold(ltv, "customer_ltv_daily")
