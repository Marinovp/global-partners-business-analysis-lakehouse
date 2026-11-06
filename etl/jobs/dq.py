"""Job 3 - DQ gate: check silver and gold after every pipeline run.

Each check is recorded in gp_gold.dq_results (kept as history, one batch of rows per run).
If any CRITICAL check fails, the job fails: the workflow shows the run as failed and the
failure alert fires. WARNING checks are recorded but never fail the run.
"""

import sys
from datetime import datetime, timezone

from awsglue.utils import getResolvedOptions
from pyspark.sql import SparkSession
from pyspark.sql.utils import AnalysisException

args = getResolvedOptions(sys.argv, ["bucket"])

spark = (
    SparkSession.builder.config(
        "spark.sql.extensions",
        "org.apache.iceberg.spark.extensions.IcebergSparkSessionExtensions",
    )
    .config("spark.sql.catalog.glue_catalog", "org.apache.iceberg.spark.SparkCatalog")
    .config("spark.sql.catalog.glue_catalog.catalog-impl", "org.apache.iceberg.aws.glue.GlueCatalog")
    .config("spark.sql.catalog.glue_catalog.io-impl", "org.apache.iceberg.aws.s3.S3FileIO")
    .config("spark.sql.catalog.glue_catalog.warehouse", f"s3://{args['bucket']}/gold/")
    .getOrCreate()
)
spark.conf.set("spark.sql.session.timeZone", "UTC")

S = "glue_catalog.gp_silver"
G = "glue_catalog.gp_gold"
LINE_REVENUE = f"""
    (SELECT i.*, i.item_price + coalesce(o.options_revenue, 0) AS line_revenue
     FROM {S}.order_items i
     LEFT JOIN (SELECT order_id, lineitem_id, sum(option_price * option_quantity) AS options_revenue
                FROM {S}.order_item_options GROUP BY order_id, lineitem_id) o
       ON i.order_id = o.order_id AND i.lineitem_id = o.lineitem_id)
"""

# (name, severity, SQL returning one value, rule the value must satisfy)
CHECKS = [
    ("silver order_items is not empty", "CRITICAL", f"SELECT count(*) FROM {S}.order_items", lambda v: v > 0),
    ("silver order_item_options is not empty", "CRITICAL", f"SELECT count(*) FROM {S}.order_item_options", lambda v: v > 0),
    ("silver order_items: lineitem_id is unique", "CRITICAL",
     f"SELECT count(*) - count(DISTINCT lineitem_id) FROM {S}.order_items", lambda v: v == 0),
    ("silver order_item_options: composite key is unique", "CRITICAL",
     f"""SELECT count(*) - count(DISTINCT concat_ws('|', order_id, lineitem_id, option_group_name, option_name))
         FROM {S}.order_item_options""", lambda v: v == 0),
    ("silver: no rows with missing keys", "CRITICAL",
     f"""SELECT (SELECT count(*) FROM {S}.order_items WHERE lineitem_id IS NULL)
              + (SELECT count(*) FROM {S}.order_item_options
                 WHERE order_id IS NULL OR lineitem_id IS NULL OR option_group_name IS NULL OR option_name IS NULL)""",
     lambda v: v == 0),
    ("silver: no orphan options", "CRITICAL",
     f"""SELECT count(*) FROM {S}.order_item_options o
         LEFT ANTI JOIN {S}.order_items i ON o.order_id = i.order_id AND o.lineitem_id = i.lineitem_id""",
     lambda v: v == 0),
    ("gold sales_daily revenue = silver revenue", "CRITICAL",
     f"SELECT (SELECT sum(revenue) FROM {G}.sales_daily) - (SELECT sum(line_revenue) FROM {LINE_REVENUE})",
     lambda v: v == 0),
    ("gold location_performance revenue = silver revenue", "CRITICAL",
     f"SELECT (SELECT sum(total_revenue) FROM {G}.location_performance) - (SELECT sum(line_revenue) FROM {LINE_REVENUE})",
     lambda v: v == 0),
    ("gold order_pricing net revenue = silver revenue", "CRITICAL",
     f"SELECT (SELECT sum(net_revenue) FROM {G}.order_pricing) - (SELECT sum(line_revenue) FROM {LINE_REVENUE})",
     lambda v: v == 0),
    ("gold customer_profile LTV = customer_ltv_daily revenue", "CRITICAL",
     f"SELECT (SELECT sum(lifetime_value) FROM {G}.customer_profile) - (SELECT sum(daily_revenue) FROM {G}.customer_ltv_daily)",
     lambda v: v == 0),
    ("gold: final ltv_to_date = lifetime_value for every customer", "CRITICAL",
     f"""SELECT count(*) FROM {G}.customer_profile p
         JOIN (SELECT user_id, max(ltv_to_date) AS final_ltv FROM {G}.customer_ltv_daily GROUP BY user_id) l
           ON p.user_id = l.user_id
         WHERE p.lifetime_value <> l.final_ltv""", lambda v: v == 0),
    ("gold: High CLV tier is 20% of customers (±1 point)", "CRITICAL",
     f"SELECT round(avg(CASE WHEN clv_tier = 'High' THEN 100.0 ELSE 0 END), 2) FROM {G}.customer_profile",
     lambda v: 19 <= v <= 21),
    ("gold: Low CLV tier is 20% of customers (±1 point)", "CRITICAL",
     f"SELECT round(avg(CASE WHEN clv_tier = 'Low' THEN 100.0 ELSE 0 END), 2) FROM {G}.customer_profile",
     lambda v: 19 <= v <= 21),
    ("gold: date_dim covers every sales date", "CRITICAL",
     f"""SELECT count(DISTINCT s.order_date) FROM {G}.sales_daily s
         LEFT ANTI JOIN {G}.date_dim d ON s.order_date = d.date_key""", lambda v: v == 0),
    ("gold is as fresh as silver (same last order date)", "CRITICAL",
     f"""SELECT datediff((SELECT max(to_date(creation_time_utc)) FROM {S}.order_items),
                         (SELECT max(order_date) FROM {G}.sales_daily))""", lambda v: v == 0),
    ("test rows in silver (item_name = 'Test')", "WARNING",
     f"SELECT count(*) FROM {S}.order_items WHERE lower(item_name) = 'test'", lambda v: v == 0),
    ("customers with $0 lifetime value", "WARNING",
     f"SELECT count(*) FROM {G}.customer_profile WHERE lifetime_value = 0", lambda v: v == 0),
    ("customers with LTV over $5,000 (possible business accounts)", "WARNING",
     f"SELECT count(*) FROM {G}.customer_profile WHERE lifetime_value > 5000", lambda v: v == 0),
    ("rows with no customer (NULL user_id), % of lines", "WARNING",
     f"SELECT round(avg(CASE WHEN user_id IS NULL THEN 100.0 ELSE 0 END), 2) FROM {S}.order_items",
     lambda v: v <= 10),
]

run_ts = datetime.now(timezone.utc)
results = []
for name, severity, sql, rule in CHECKS:
    value = spark.sql(sql).first()[0]
    passed = value is not None and bool(rule(value))
    results.append((run_ts, name, severity, str(value), passed))
    print(f"[{'PASS' if passed else 'FAIL'}] {severity:<8} {name}: {value}")

df = spark.createDataFrame(
    results, "run_ts timestamp, check_name string, severity string, value string, passed boolean"
)
try:
    spark.table(f"{G}.dq_results")
    df.writeTo(f"{G}.dq_results").append()  # keep the history of every run
except AnalysisException:
    df.writeTo(f"{G}.dq_results").using("iceberg").tableProperty("format-version", "2").create()

failed = [r[1] for r in results if r[2] == "CRITICAL" and not r[4]]
warnings = [r[1] for r in results if r[2] == "WARNING" and not r[4]]
print(f"DQ summary: {len(results)} checks, {len(failed)} critical failures, {len(warnings)} warnings")
if failed:
    raise RuntimeError(f"DQ gate failed: {failed}")
