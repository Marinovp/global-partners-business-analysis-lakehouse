-- Mirrors etl/jobs/extract.py: the queries job 0 sends to SQL Server (database globalpartners).
-- Dialect: SQL Server (T-SQL).
--
-- :lower_bound = newest creation_time_utc already in gp_silver.order_items minus 2 days (lookback)
-- :upper_bound = the time the extract run started
-- When silver doesn't exist yet, job 0 runs the FULL queries instead.

-- 1. Full extract (first run). Unfiltered on purpose: it also brings orphan options, which
--    silver then quarantines.
SELECT * FROM dbo.order_items;
SELECT * FROM dbo.order_item_options;

-- 2. Incremental extract (every later run).
SELECT *
FROM dbo.order_items
WHERE CREATION_TIME_UTC >  :lower_bound
  AND CREATION_TIME_UTC <= :upper_bound;

-- Options have no timestamp, so they borrow the timestamp of their parent line item.
SELECT o.*
FROM dbo.order_item_options o
JOIN dbo.order_items i
  ON o.ORDER_ID = i.ORDER_ID
 AND o.LINEITEM_ID = i.LINEITEM_ID
WHERE i.CREATION_TIME_UTC >  :lower_bound
  AND i.CREATION_TIME_UTC <= :upper_bound;

-- 3. The watermark itself (run in Athena/Spark against silver, not in SQL Server):
--    SELECT date_add('day', -2, max(creation_time_utc)) FROM gp_silver.order_items;
