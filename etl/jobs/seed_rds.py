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


def create_database_if_missing() -> None:
    """RDS SQL Server starts with system databases only, so create the source database."""
    jvm = spark.sparkContext._gateway.jvm
    conn = jvm.java.sql.DriverManager.getConnection(f"{base_url};databaseName=master", user, password)
    try:
        conn.createStatement().executeUpdate(
            f"IF DB_ID('{args['db_name']}') IS NULL CREATE DATABASE [{args['db_name']}]"
        )
    finally:
        conn.close()


def read_csv(name: str) -> DataFrame:
    return (
        spark.read.option("header", True)
        .option("multiLine", True)  # some item names contain line breaks inside quotes
        .option("escape", '"')
        .csv(f"s3://{args['bucket']}/seed/{name}.csv")
    )


def load_table(df: DataFrame, table: str, column_types: str | None = None) -> None:
    df = df.cache()
    expected = df.count()

    writer = df.write.format("jdbc").options(url=db_url, dbtable=f"dbo.{table}", **jdbc_options).mode("overwrite")
    if column_types:
        writer = writer.option("createTableColumnTypes", column_types)
    writer.save()

    actual = (
        spark.read.format("jdbc")
        .options(url=db_url, query=f"SELECT COUNT(*) AS n FROM dbo.{table}", **jdbc_options)
        .load()
        .first()["n"]
    )
    print(f"{table}: {expected} rows read from CSV, {actual} rows in SQL Server")
    if actual != expected:
        raise RuntimeError(f"{table}: row count mismatch ({expected} expected, {actual} loaded)")


create_database_if_missing()

order_items = (
    read_csv("order_items")
    .withColumn("CREATION_TIME_UTC", F.to_timestamp("CREATION_TIME_UTC"))
    .withColumn("IS_LOYALTY", F.col("IS_LOYALTY").cast("boolean"))
    .withColumn("ITEM_PRICE", F.col("ITEM_PRICE").cast("decimal(10,2)"))
    .withColumn("ITEM_QUANTITY", F.col("ITEM_QUANTITY").cast("int"))
)
# DATETIME2(3) keeps the millisecond precision that SQL Server's default DATETIME would round.
load_table(order_items, "order_items", column_types="CREATION_TIME_UTC DATETIME2(3)")

order_item_options = (
    read_csv("order_item_options")
    .withColumn("OPTION_PRICE", F.col("OPTION_PRICE").cast("decimal(10,2)"))
    .withColumn("OPTION_QUANTITY", F.col("OPTION_QUANTITY").cast("int"))
)
load_table(order_item_options, "order_item_options")
