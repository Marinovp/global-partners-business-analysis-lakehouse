"""Job 0 - Extract: copy the source table from SQL server to S3 raw/ as Parquet
Every run writes to a new folder raw/<table>/run_id=<id>/
and never overwrites an older run
"""

import json
import sys
from datetime import datetime, timezone
import boto3
from awsglue.utils import getResolvedOptions
from pyspark.sql import SparkSession

args = getResolvedOptions(
    sys.argv, ["bucket", "db_host", "db_port", "db_name", "secret_arn", "aws_region"]
)

spark = SparkSession.builder.getOrCreate()
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

run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def extract_table(table: str) -> None:
    df = (
        spark.read.format("jdbc")
        .options(url=db_url, dbtable=f"dbo.{table}", **jdbc_options)
        .load()
        .cache()
    )
    source_rows = df.count()

    path = f"s3://{args['bucket']}/raw/{table}/run_id={run_id}"
    df.write.mode("errorifexists").parquet(path)

    written_rows = spark.read.parquet(path).count()
    print(
        f"{table}: {source_rows} rows in SQL server, {written_rows} rows written to {path}"
    )
    if written_rows != source_rows:
        raise RuntimeError(f"{table}: row count mistmatch")


for table in ["order_items", "order_item_options"]:
    extract_table(table)
