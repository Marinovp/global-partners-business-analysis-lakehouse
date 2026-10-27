"""Seed job: load the source CSVs from S3 into RDS SQL Server, the simulated source system.

Run after each `make apply` + `make seed`. Safe to re-run: tables are overwritten.
Fails if the row count read back from SQL Server differs from the rows read from the CSV.
"""

import json
import sys

import boto3
from awsglue.utils import getResolvedOptions
from pyspark.sql import DataFrame, SparkSession
from pyspark.sql import functions as F

args = getResolvedOptions(
    sys.argv, ["bucket", "db_host", "db_port", "db_name", "secret_arn", "aws_region"]
)

spark = SparkSession.builder.getOrCreate()
# CSV timestamps are UTC ("...Z"); keep them UTC when written to SQL Server.
spark.conf.set("spark.sql.session.timeZone", "UTC")

secret = json.loads(
    boto3.client("secretsmanager", region_name=args["aws_region"])
    .get_secret_value(SecretId=args["secret_arn"])["SecretString"]
)
user, password = secret["username"], secret["password"]

# The instance enforces TLS (rds.force_ssl=1). trustServerCertificate=true encrypts the
# connection but skips certificate validation; hardening item: trust the RDS CA bundle instead.
base_url = f"jdbc:sqlserver://{args['db_host']}:{args['db_port']};encrypt=true;trustServerCertificate=true"
db_url = f"{base_url};databaseName={args['db_name']}"
jdbc_options = {"user": user, "password": password, "driver": "com.microsoft.sqlserver.jdbc.SQLServerDriver"}


# Source schema, created explicitly so SQL Server gets real types (Spark's JDBC writer would
# pick DATETIME, which rounds milliseconds, and NVARCHAR(MAX) for every string).
TABLE_DDL = {
    "order_items": """
        CREATE TABLE dbo.order_items (
            APP_NAME            NVARCHAR(100),
            RESTAURANT_ID       VARCHAR(24),
            CREATION_TIME_UTC   DATETIME2(3),
            ORDER_ID            VARCHAR(24),
            USER_ID             VARCHAR(24),
            PRINTED_CARD_NUMBER VARCHAR(32),
            IS_LOYALTY          BIT,
            CURRENCY            CHAR(3),
            LINEITEM_ID         VARCHAR(24),
            ITEM_CATEGORY       NVARCHAR(200),
            ITEM_NAME           NVARCHAR(200),
            ITEM_PRICE          DECIMAL(10, 2),
            ITEM_QUANTITY       INT
        )""",
    "order_item_options": """
        CREATE TABLE dbo.order_item_options (
            ORDER_ID          VARCHAR(24),
            LINEITEM_ID       VARCHAR(24),
            OPTION_GROUP_NAME NVARCHAR(100),
            OPTION_NAME       NVARCHAR(200),
            OPTION_PRICE      DECIMAL(10, 2),
            OPTION_QUANTITY   INT
        )""",
}


def run_sql(database: str, statement: str) -> None:
    """Run one DDL statement directly on SQL Server (Spark's JDBC API only reads and writes rows)."""
    jvm = spark.sparkContext._gateway.jvm
    conn = jvm.java.sql.DriverManager.getConnection(f"{base_url};databaseName={database}", user, password)
    try:
        conn.createStatement().executeUpdate(statement)
    finally:
        conn.close()


def read_csv(name: str) -> DataFrame:
    return (
        spark.read.option("header", True)
        .option("multiLine", True)  # some item names contain line breaks inside quotes
        .option("escape", '"')
        .csv(f"s3://{args['bucket']}/seed/{name}.csv")
    )


def load_table(df: DataFrame, table: str) -> None:
    df = df.cache()
    expected = df.count()

    run_sql(args["db_name"], f"IF OBJECT_ID('dbo.{table}') IS NULL {TABLE_DDL[table]}")
    # truncate=true: overwrite empties the existing table instead of dropping it, keeping our types.
    (
        df.write.format("jdbc")
        .options(url=db_url, dbtable=f"dbo.{table}", truncate="true", **jdbc_options)
        .mode("overwrite")
        .save()
    )

    actual = (
        spark.read.format("jdbc")
        .options(url=db_url, query=f"SELECT COUNT(*) AS n FROM dbo.{table}", **jdbc_options)
        .load()
        .first()["n"]
    )
    print(f"{table}: {expected} rows read from CSV, {actual} rows in SQL Server")
    if actual != expected:
        raise RuntimeError(f"{table}: row count mismatch ({expected} expected, {actual} loaded)")


# RDS SQL Server starts with system databases only, so create the source database first.
run_sql("master", f"IF DB_ID('{args['db_name']}') IS NULL CREATE DATABASE [{args['db_name']}]")

order_items = (
    read_csv("order_items")
    .withColumn("CREATION_TIME_UTC", F.to_timestamp("CREATION_TIME_UTC"))
    .withColumn("IS_LOYALTY", F.col("IS_LOYALTY").cast("boolean"))
    .withColumn("ITEM_PRICE", F.col("ITEM_PRICE").cast("decimal(10,2)"))
    .withColumn("ITEM_QUANTITY", F.col("ITEM_QUANTITY").cast("int"))
)
load_table(order_items, "order_items")

order_item_options = (
    read_csv("order_item_options")
    .withColumn("OPTION_PRICE", F.col("OPTION_PRICE").cast("decimal(10,2)"))
    .withColumn("OPTION_QUANTITY", F.col("OPTION_QUANTITY").cast("int"))
)
load_table(order_item_options, "order_item_options")
