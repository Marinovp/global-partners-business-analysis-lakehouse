"""Job 2 - Gold: build the business tables in gp_gold from the silver Iceberg tables.

Every table is fully rebuilt and swapped in atomically, so a failed run leaves the previous
gold tables intact and queryable.

Tables (one per business question; see docs/solution-design.md for definitions):
  customer_ltv_daily    lifetime value per customer per order day (primary goal)
  customer_profile      one row per customer: CLV tier, RFM segment, churn indicators, loyalty
  date_dim              calendar with weekends and US federal holidays
  sales_daily           revenue by day, hour, location, app and category
  location_performance  revenue, orders and retention per location, ranked
  order_pricing         one row per order: actual vs usual-price revenue (implied discounts)
"""

import sys
from datetime import date, timedelta

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

RFM_MONTHS = 12  # "last N months" window for frequency and monetary
CHURN_DAYS = 45  # no order for more than this many days = "At Risk"
SPEND_PERIOD_DAYS = 90  # spend trend compares the last 90 days with the 90 days before
DISCOUNT_THRESHOLD = 0.9  # a line sold below 90% of its usual price counts as discounted


def write_gold(df: DataFrame, table: str) -> None:
    target = f"glue_catalog.gp_gold.{table}"
    df.writeTo(target).using("iceberg").tableProperty(
        "format-version", "2"
    ).createOrReplace()
    print(f"{target}: {spark.table(target).count()} rows")


def check_equal(name: str, expected, actual) -> None:
    print(f"{name}: expected {expected}, got {actual}")
    if expected != actual:
        raise RuntimeError(f"{name} mismatch: expected {expected}, got {actual}")


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
        .withColumn("options_revenue", F.coalesce(F.col("options_revenue"), F.lit(0)))
        .withColumn("line_revenue", F.col("item_price") + F.col("options_revenue"))
        .withColumn("order_date", F.to_date("creation_time_utc"))
        .withColumn("order_hour", F.hour("creation_time_utc"))  # UTC: store time zones are unknown
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


def customer_profile(lines: DataFrame) -> DataFrame:
    """One row per customer: lifetime value, order history and CLV tier.
    Tiers: High = top 20% by lifetime value, Medium = middle 60%, Low = bottom 20%."""
    customers = (
        lines.filter("user_id IS NOT NULL")
        .groupBy("user_id")
        .agg(
            F.sum("line_revenue").alias("lifetime_value"),
            F.countDistinct("order_id").alias("total_orders"),
            F.countDistinct("order_date").alias("order_days"),
            F.min("order_date").alias("first_order_date"),
            F.max("order_date").alias("last_order_date"),
            F.max("is_loyalty").alias(
                "is_loyalty_member"
            ),  # a member if any of their orders was a loyalty order
        )
    )
    # No partitionBy: every customer is ranked against all the others (fine for ~20k rows).
    by_value = Window.orderBy(F.col("lifetime_value").desc())
    return customers.withColumn("clv_bucket", F.ntile(5).over(by_value)).withColumn(
        "clv_tier",
        F.when(F.col("clv_bucket") == 1, "High")
        .when(F.col("clv_bucket") == 5, "Low")
        .otherwise("Medium"),
    )


def add_rfm(profile: DataFrame, lines: DataFrame, as_of: date) -> DataFrame:
    """Add Recency / Frequency / Monetary, 1-5 scores and a segment to each customer.

    Time is measured from the last day in the data (as_of_date), not from today: the data
    ends on 2024-02-21, so measuring from today would make every customer look inactive.
    Scores use fixed thresholds rather than percentiles: about half the customers have zero
    orders in the window, and percentile ranks can't split that many identical values fairly.
    The thresholds are assumptions for the SME to confirm.
    """
    window_start = F.add_months(F.lit(as_of), -RFM_MONTHS)
    recent = (
        lines.filter("user_id IS NOT NULL")
        .filter(F.col("order_date") > window_start)
        .groupBy("user_id")
        .agg(
            F.countDistinct("order_id").alias("frequency_12m"),
            F.sum("line_revenue").alias("monetary_12m"),
        )
    )
    rfm = (
        profile.join(recent, "user_id", "left")
        .fillna(0, ["frequency_12m", "monetary_12m"])  # no orders in the window
        .withColumn("as_of_date", F.lit(as_of))
        .withColumn("recency_days", F.datediff(F.col("as_of_date"), F.col("last_order_date")))
    )

    r, f, m = F.col("recency_days"), F.col("frequency_12m"), F.col("monetary_12m")
    rfm = (
        rfm.withColumn("r_score", F.when(r <= 30, 5).when(r <= 90, 4).when(r <= 180, 3).when(r <= 365, 2).otherwise(1))
        .withColumn("f_score", F.when(f >= 12, 5).when(f >= 6, 4).when(f >= 3, 3).when(f >= 1, 2).otherwise(1))
        .withColumn("m_score", F.when(m >= 500, 5).when(m >= 200, 4).when(m >= 75, 3).when(m > 0, 2).otherwise(1))
    )
    rs, fs, ms = F.col("r_score"), F.col("f_score"), F.col("m_score")
    segment = (
        F.when((rs >= 4) & (fs >= 4) & (ms >= 4), "VIP")
        .when((rs >= 4) & (fs <= 2), "New")
        .when((rs <= 2) & (fs <= 2), "Churn Risk")
        .otherwise("Regular")
    )
    return rfm.withColumn("rfm_segment", segment)


def add_churn_indicators(profile: DataFrame, lines: DataFrame, as_of: date) -> DataFrame:
    """Activity profile for retention work (descriptive, no prediction): days since last order,
    average gap between order days, and spend in the last 90 days vs the 90 days before."""
    days_back = F.datediff(F.lit(as_of), F.col("order_date"))
    spend = (
        lines.filter("user_id IS NOT NULL")
        .groupBy("user_id")
        .agg(
            F.sum(F.when(days_back < SPEND_PERIOD_DAYS, F.col("line_revenue")).otherwise(0)).alias("spend_last_90d"),
            F.sum(
                F.when(
                    (days_back >= SPEND_PERIOD_DAYS) & (days_back < 2 * SPEND_PERIOD_DAYS),
                    F.col("line_revenue"),
                ).otherwise(0)
            ).alias("spend_prev_90d"),
        )
    )
    return (
        profile.join(spend, "user_id", "left")
        .withColumn("days_since_last_order", F.col("recency_days"))
        .withColumn(
            "avg_days_between_orders",  # NULL for customers who ordered on one day only
            F.when(
                F.col("order_days") > 1,
                F.round(F.datediff("last_order_date", "first_order_date") / (F.col("order_days") - 1), 1),
            ),
        )
        .withColumn(
            "spend_change_pct",  # NULL when there was no spend in the earlier period
            F.when(
                F.col("spend_prev_90d") > 0,
                F.round((F.col("spend_last_90d") - F.col("spend_prev_90d")) / F.col("spend_prev_90d") * 100, 1),
            ),
        )
        .withColumn(
            "churn_status",
            F.when(F.col("recency_days") > CHURN_DAYS, "At Risk").otherwise("Active"),
        )
    )


def us_federal_holidays(first_year: int, last_year: int) -> list[tuple[date, str]]:
    """US federal holidays on their calendar dates (observed-day shifts are not applied).
    The company's own holiday list was not available; this list is an assumption to confirm."""

    def nth_weekday(year: int, month: int, weekday: int, n: int) -> date:
        first = date(year, month, 1)
        return first + timedelta(days=(weekday - first.weekday()) % 7 + 7 * (n - 1))

    def last_weekday(year: int, month: int, weekday: int) -> date:
        last = date(year + (month == 12), month % 12 + 1, 1) - timedelta(days=1)
        return last - timedelta(days=(last.weekday() - weekday) % 7)

    mon, thu = 0, 3
    holidays = []
    for y in range(first_year, last_year + 1):
        holidays += [
            (date(y, 1, 1), "New Year's Day"),
            (nth_weekday(y, 1, mon, 3), "Martin Luther King Jr. Day"),
            (nth_weekday(y, 2, mon, 3), "Presidents' Day"),
            (last_weekday(y, 5, mon), "Memorial Day"),
            (date(y, 7, 4), "Independence Day"),
            (nth_weekday(y, 9, mon, 1), "Labor Day"),
            (nth_weekday(y, 10, mon, 2), "Columbus Day"),
            (date(y, 11, 11), "Veterans Day"),
            (nth_weekday(y, 11, thu, 4), "Thanksgiving Day"),
            (date(y, 12, 25), "Christmas Day"),
        ]
        if y >= 2021:  # Juneteenth became a federal holiday in 2021
            holidays.append((date(y, 6, 19), "Juneteenth"))
    return holidays


def date_dim(first: date, last: date) -> DataFrame:
    """One row per calendar day for every full year the data touches."""
    days = spark.sql(
        f"SELECT explode(sequence(DATE'{first.year}-01-01', DATE'{last.year}-12-31')) AS date_key"
    )
    holidays = spark.createDataFrame(
        us_federal_holidays(first.year, last.year), "date_key date, holiday_name string"
    )
    return (
        days.join(holidays, "date_key", "left")
        .withColumn("day_of_week", F.date_format("date_key", "EEEE"))
        .withColumn("week", F.weekofyear("date_key"))
        .withColumn("month", F.date_format("date_key", "MMMM"))
        .withColumn("month_number", F.month("date_key"))
        .withColumn("quarter", F.quarter("date_key"))
        .withColumn("year", F.year("date_key"))
        .withColumn("is_weekend", F.dayofweek("date_key").isin(1, 7))  # Sunday = 1, Saturday = 7
        .withColumn("is_holiday", F.col("holiday_name").isNotNull())
        .select(
            "date_key", "day_of_week", "week", "month", "month_number", "quarter", "year",
            "is_weekend", "is_holiday", "holiday_name",
        )
    )


def sales_daily(lines: DataFrame) -> DataFrame:
    """Revenue by day, hour (UTC), location, app and item category. `orders` counts orders that
    contain the category, so sum revenue freely but don't add up `orders` across categories."""
    return lines.groupBy(
        "order_date", "order_hour", "restaurant_id", "app_name", "item_category"
    ).agg(
        F.sum("line_revenue").alias("revenue"),
        F.count("*").alias("line_items"),
        F.countDistinct("order_id").alias("orders"),
    )


def location_performance(lines: DataFrame) -> DataFrame:
    """One row per location: revenue, order volume, average order value, customer retention, rank."""
    orders = lines.groupBy("restaurant_id", "order_id", "user_id", "order_date").agg(
        F.sum("line_revenue").alias("order_revenue")
    )
    # Retention: share of the location's identified customers who ordered there more than once.
    customers = (
        orders.filter("user_id IS NOT NULL")
        .groupBy("restaurant_id", "user_id")
        .agg(F.count("*").alias("orders"))
        .groupBy("restaurant_id")
        .agg(
            F.count("*").alias("unique_customers"),
            F.round(F.avg(F.when(F.col("orders") > 1, 1).otherwise(0)) * 100, 1).alias("repeat_customer_pct"),
        )
    )
    per_location = orders.groupBy("restaurant_id").agg(
        F.sum("order_revenue").alias("total_revenue"),
        F.count("*").alias("total_orders"),
        F.round(F.avg("order_revenue"), 2).alias("avg_order_value"),
        F.countDistinct("order_date").alias("active_days"),
        F.min("order_date").alias("first_order_date"),
        F.max("order_date").alias("last_order_date"),
    )
    weeks_open = (F.datediff("last_order_date", "first_order_date") + 1) / 7
    return (
        per_location.join(customers, "restaurant_id", "left")
        .withColumn("orders_per_active_day", F.round(F.col("total_orders") / F.col("active_days"), 1))
        .withColumn("orders_per_week", F.round(F.col("total_orders") / F.greatest(weeks_open, F.lit(1)), 1))
        .withColumn("revenue_rank", F.rank().over(Window.orderBy(F.col("total_revenue").desc())))
    )


def order_pricing(lines: DataFrame) -> DataFrame:
    """One row per order, comparing what was charged with the item's usual price.

    The source has no discount fields (no negative option prices), so discounts are ESTIMATED:
    a line counts as discounted when its unit price is below 90% of the median unit price of
    the same item at the same location in the same year. Mid-year price increases can also
    show up as "discounts", so treat the result as an estimate, not accounting truth.
    """
    priced = lines.withColumn("unit_price", F.col("item_price") / F.col("item_quantity")).withColumn(
        "year", F.year("order_date")
    )
    usual = priced.groupBy("restaurant_id", "item_name", "year").agg(
        F.percentile_approx("unit_price", 0.5).alias("usual_unit_price")
    )
    with_usual = (
        priced.join(usual, ["restaurant_id", "item_name", "year"])
        .withColumn("is_discounted", F.col("unit_price") < F.col("usual_unit_price") * DISCOUNT_THRESHOLD)
        .withColumn(  # what the line would have cost at the usual price
            "gross_line_revenue",
            F.when(
                F.col("is_discounted"),
                (F.col("usual_unit_price") * F.col("item_quantity") + F.col("options_revenue")).cast("decimal(12,2)"),
            ).otherwise(F.col("line_revenue")),
        )
    )
    return (
        with_usual.groupBy("order_id", "order_date", "restaurant_id", "user_id", "is_loyalty")
        .agg(
            F.sum("line_revenue").alias("net_revenue"),
            F.sum("gross_line_revenue").alias("gross_revenue"),
            F.max("is_discounted").alias("has_discount"),
            F.sum(F.col("is_discounted").cast("int")).alias("discounted_lines"),
            F.count("*").alias("line_items"),
        )
        .withColumn("implied_discount", F.col("gross_revenue") - F.col("net_revenue"))
    )


lines = order_lines().cache()
as_of = lines.agg(F.max("order_date")).first()[0]
first_day = lines.agg(F.min("order_date")).first()[0]
total_revenue = lines.agg(F.sum("line_revenue")).first()[0]
customer_revenue = lines.filter("user_id IS NOT NULL").agg(F.sum("line_revenue")).first()[0]
print(f"as_of_date: {as_of}  first order: {first_day}  total revenue: {total_revenue}")

ltv = customer_ltv_daily(lines).cache()
check_equal("customer revenue in customer_ltv_daily", customer_revenue, ltv.agg(F.sum("daily_revenue")).first()[0])
write_gold(ltv, "customer_ltv_daily")

profile = add_churn_indicators(add_rfm(customer_profile(lines), lines, as_of), lines, as_of).cache()
check_equal("customers in customer_profile", ltv.select("user_id").distinct().count(), profile.count())
for column in ["clv_tier", "rfm_segment", "churn_status"]:
    print(f"{column}:", {r[column]: r["count"] for r in profile.groupBy(column).count().collect()})
write_gold(profile, "customer_profile")

calendar = date_dim(first_day, as_of).cache()
check_equal(
    "order dates missing from date_dim",
    0,
    lines.select(F.col("order_date").alias("date_key")).distinct().join(calendar, "date_key", "left_anti").count(),
)
print("holidays:", calendar.filter("is_holiday").count())
write_gold(calendar, "date_dim")

sales = sales_daily(lines)
check_equal("revenue in sales_daily", total_revenue, sales.agg(F.sum("revenue")).first()[0])
write_gold(sales, "sales_daily")

locations = location_performance(lines)
check_equal("revenue in location_performance", total_revenue, locations.agg(F.sum("total_revenue")).first()[0])
write_gold(locations, "location_performance")

pricing = order_pricing(lines).cache()
check_equal("revenue in order_pricing", total_revenue, pricing.agg(F.sum("net_revenue")).first()[0])
print("orders with an implied discount:", pricing.filter("has_discount").count(), "of", pricing.count())
write_gold(pricing, "order_pricing")
