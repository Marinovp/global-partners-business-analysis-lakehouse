-- Optional: make the raw Parquet extracts queryable in Athena, e.g. to inspect one run.
-- The pipeline doesn't need these tables (job 1 reads raw files directly).
-- Each extract run is a folder raw/<table>/run_id=<UTC timestamp>/, which becomes a partition.
-- Bucket name is the dev stack's (terraform output bucket_name).

CREATE EXTERNAL TABLE IF NOT EXISTS gp_raw.order_items (
  app_name            string,
  restaurant_id       string,
  creation_time_utc   timestamp,
  order_id            string,
  user_id             string,
  printed_card_number string,
  is_loyalty          boolean,
  currency            string,
  lineitem_id         string,
  item_category       string,
  item_name           string,
  item_price          decimal(10, 2),
  item_quantity       int
)
PARTITIONED BY (run_id string)
STORED AS PARQUET
LOCATION 's3://gp-lakehouse-dev-884747583198/raw/order_items/';

CREATE EXTERNAL TABLE IF NOT EXISTS gp_raw.order_item_options (
  order_id          string,
  lineitem_id       string,
  option_group_name string,
  option_name       string,
  option_price      decimal(10, 2),
  option_quantity   int
)
PARTITIONED BY (run_id string)
STORED AS PARQUET
LOCATION 's3://gp-lakehouse-dev-884747583198/raw/order_item_options/';

-- Register the run_id folders that exist (run again after new extracts).
MSCK REPAIR TABLE gp_raw.order_items;
MSCK REPAIR TABLE gp_raw.order_item_options;

-- Example: row count per extract run.
-- SELECT run_id, count(*) FROM gp_raw.order_items GROUP BY run_id ORDER BY run_id;
