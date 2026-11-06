-- Mirrors merge_into_silver("order_items", ["lineitem_id"]) in etl/jobs/silver.py.
-- WRITES to silver: run only against a dev stack. Athena supports MERGE on Iceberg tables.
-- Source = latest raw extract, without NULL keys, one row per key (MERGE needs that).
-- Re-running it changes nothing: matched rows are updated in place, so it is idempotent.

MERGE INTO gp_silver.order_items t
USING (
  SELECT app_name, restaurant_id, creation_time_utc, order_id, user_id, printed_card_number,
         is_loyalty, currency, lineitem_id, item_category, item_name, item_price, item_quantity
  FROM (
    SELECT r.*, row_number() OVER (PARTITION BY lineitem_id ORDER BY creation_time_utc) AS rn
    FROM gp_raw.order_items r
    WHERE run_id = (SELECT max(run_id) FROM gp_raw.order_items)
      AND lineitem_id IS NOT NULL
  )
  WHERE rn = 1
) s
ON t.lineitem_id = s.lineitem_id
WHEN MATCHED THEN UPDATE SET
  app_name = s.app_name, restaurant_id = s.restaurant_id, creation_time_utc = s.creation_time_utc,
  order_id = s.order_id, user_id = s.user_id, printed_card_number = s.printed_card_number,
  is_loyalty = s.is_loyalty, currency = s.currency, item_category = s.item_category,
  item_name = s.item_name, item_price = s.item_price, item_quantity = s.item_quantity
WHEN NOT MATCHED THEN INSERT
  (app_name, restaurant_id, creation_time_utc, order_id, user_id, printed_card_number,
   is_loyalty, currency, lineitem_id, item_category, item_name, item_price, item_quantity)
VALUES
  (s.app_name, s.restaurant_id, s.creation_time_utc, s.order_id, s.user_id, s.printed_card_number,
   s.is_loyalty, s.currency, s.lineitem_id, s.item_category, s.item_name, s.item_price, s.item_quantity);
