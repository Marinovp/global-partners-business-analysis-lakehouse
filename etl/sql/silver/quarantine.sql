-- Mirrors quarantine() and merge_into_silver() in etl/jobs/silver.py: which rows are REJECTED.
-- Rejected rows are written to quarantine/<table>/run_id=<run>/reason=<reason>/ instead of silver.
-- Uses the optional gp_raw tables from raw/raw_tables.sql; "latest run" = max(run_id).

-- reason=missing_key: rows that can't be merged because part of the key is NULL
-- (NULL = NULL is not true in SQL, so MERGE would insert them again on every run).
SELECT *
FROM gp_raw.order_items
WHERE run_id = (SELECT max(run_id) FROM gp_raw.order_items)
  AND lineitem_id IS NULL;

SELECT *
FROM gp_raw.order_item_options
WHERE run_id = (SELECT max(run_id) FROM gp_raw.order_item_options)
  AND NOT (order_id IS NOT NULL AND lineitem_id IS NOT NULL
           AND option_group_name IS NOT NULL AND option_name IS NOT NULL);

-- reason=orphan: options whose parent line item doesn't exist in silver.
SELECT DISTINCT o.*
FROM gp_raw.order_item_options o
WHERE o.run_id = (SELECT max(run_id) FROM gp_raw.order_item_options)
  AND NOT EXISTS (
    SELECT 1 FROM gp_silver.order_items i
    WHERE i.order_id = o.order_id AND i.lineitem_id = o.lineitem_id
  );
