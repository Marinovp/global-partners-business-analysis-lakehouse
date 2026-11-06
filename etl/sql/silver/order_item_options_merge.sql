-- Mirrors merge_into_silver("order_item_options", [4 keys], parent="order_items") in etl/jobs/silver.py.
-- WRITES to silver: run only against a dev stack, after order_items_merge.sql.
-- Composite key: (order_id, lineitem_id, option_group_name, option_name).
-- Orphans (no parent line item in silver) are left out here; quarantine.sql lists them.

MERGE INTO gp_silver.order_item_options t
USING (
  SELECT order_id, lineitem_id, option_group_name, option_name, option_price, option_quantity
  FROM (
    SELECT r.*,
           row_number() OVER (PARTITION BY order_id, lineitem_id, option_group_name, option_name
                              ORDER BY option_price) AS rn
    FROM gp_raw.order_item_options r
    WHERE run_id = (SELECT max(run_id) FROM gp_raw.order_item_options)
      AND order_id IS NOT NULL AND lineitem_id IS NOT NULL
      AND option_group_name IS NOT NULL AND option_name IS NOT NULL
      AND EXISTS (SELECT 1 FROM gp_silver.order_items i
                  WHERE i.order_id = r.order_id AND i.lineitem_id = r.lineitem_id)
  )
  WHERE rn = 1
) s
ON  t.order_id = s.order_id
AND t.lineitem_id = s.lineitem_id
AND t.option_group_name = s.option_group_name
AND t.option_name = s.option_name
WHEN MATCHED THEN UPDATE SET
  option_price = s.option_price, option_quantity = s.option_quantity
WHEN NOT MATCHED THEN INSERT
  (order_id, lineitem_id, option_group_name, option_name, option_price, option_quantity)
VALUES
  (s.order_id, s.lineitem_id, s.option_group_name, s.option_name, s.option_price, s.option_quantity);
