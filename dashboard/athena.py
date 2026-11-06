"""Run the dashboard's SQL files (etl/sql/dashboard/*.sql) on Athena and return pandas DataFrames.

Uses your local AWS credentials (the same ones Terraform uses). Settings can be overridden with
environment variables: AWS_REGION, ATHENA_WORKGROUP, ATHENA_DATABASE.
"""

import os
import re
import time
from decimal import Decimal
from pathlib import Path
from string import Template

import boto3
import pandas as pd
import streamlit as st

SQL_DIR = Path(__file__).resolve().parents[1] / "etl" / "sql" / "dashboard"
REGION = os.environ.get("AWS_REGION", "us-west-2")
WORKGROUP = os.environ.get("ATHENA_WORKGROUP", "gp-lakehouse-dev-wg")
DATABASE = os.environ.get("ATHENA_DATABASE", "gp_gold")
USER_ID = re.compile(r"^[0-9a-f]{24}$")  # customer ids in this data are 24-character hex strings

# Athena returns every value as text; convert by the column type it reports.
_CASTS = {
    "boolean": lambda v: v == "true",
    "tinyint": int, "smallint": int, "integer": int, "bigint": int,
    "double": float, "float": float, "real": float,
    "decimal": Decimal,
    "date": lambda v: pd.Timestamp(v).date(),
    "timestamp": pd.Timestamp,
}


def _run(sql: str) -> pd.DataFrame:
    athena = boto3.client("athena", region_name=REGION)
    qid = athena.start_query_execution(
        QueryString=sql, QueryExecutionContext={"Database": DATABASE}, WorkGroup=WORKGROUP
    )["QueryExecutionId"]
    while True:
        status = athena.get_query_execution(QueryExecutionId=qid)["QueryExecution"]["Status"]
        if status["State"] in ("SUCCEEDED", "FAILED", "CANCELLED"):
            break
        time.sleep(0.5)
    if status["State"] != "SUCCEEDED":
        raise RuntimeError(f"Athena query {status['State']}: {status.get('StateChangeReason')}")

    columns, types, rows = [], [], []
    for page in athena.get_paginator("get_query_results").paginate(QueryExecutionId=qid):
        if not columns:
            meta = page["ResultSet"]["ResultSetMetadata"]["ColumnInfo"]
            columns = [c["Name"] for c in meta]
            types = [_CASTS.get(c["Type"].split("(")[0], str) for c in meta]
            data = page["ResultSet"]["Rows"][1:]  # the first row of the first page is the header
        else:
            data = page["ResultSet"]["Rows"]
        for row in data:
            values = [cell.get("VarCharValue") for cell in row["Data"]]
            rows.append([None if v is None else cast(v) for cast, v in zip(types, values)])
    df = pd.DataFrame(rows, columns=columns)
    # Decimals keep money exact in Athena; floats are easier for charts.
    for col, cast in zip(columns, types):
        if cast is Decimal:
            df[col] = df[col].astype(float)
    return df


@st.cache_data(ttl=3600, show_spinner="Querying Athena…")
def query(name: str, **params: str) -> pd.DataFrame:
    """Run etl/sql/dashboard/<name>.sql. Parameters replace $placeholders; only user_id is used,
    and it is validated here so nothing else can be injected into the SQL."""
    if "user_id" in params and not USER_ID.match(params["user_id"]):
        raise ValueError("Invalid customer id")
    sql = Template((SQL_DIR / f"{name}.sql").read_text()).substitute(params)
    return _run(sql)
