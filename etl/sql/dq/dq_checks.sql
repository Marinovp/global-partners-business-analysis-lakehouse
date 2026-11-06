-- Mirrors the CHECKS in etl/jobs/dq.py (job 3, the DQ gate). Read-only.
-- CRITICAL checks must pass or the pipeline run fails (and alerts); WARNING checks are recorded only.
-- Each row: check_name, severity, value, passed. Results of every pipeline run are kept in gp_gold.dq_results.

WITH options AS (
  SELECT order_id, lineitem_id, sum(option_price * option_quantity) AS options_revenue
  FROM gp_silver.order_item_options GROUP BY order_id, lineitem_id
),
silver_revenue AS (
  SELECT sum(i.item_price + coalesce(o.options_revenue, 0)) AS revenue
  FROM gp_silver.order_items i
  LEFT JOIN options o ON i.order_id = o.order_id AND i.lineitem_id = o.lineitem_id
),
checks (check_name, severity, value, passed) AS (
  SELECT 'silver order_items is not empty', 'CRITICAL', CAST(count(*) AS varchar), count(*) > 0
  FROM gp_silver.order_items
  UNION ALL
  SELECT 'silver order_item_options is not empty', 'CRITICAL', CAST(count(*) AS varchar), count(*) > 0
  FROM gp_silver.order_item_options
  UNION ALL
  SELECT 'silver order_items: lineitem_id is unique', 'CRITICAL',
         CAST(count(*) - count(DISTINCT lineitem_id) AS varchar), count(*) = count(DISTINCT lineitem_id)
  FROM gp_silver.order_items
  UNION ALL
  SELECT 'silver order_item_options: composite key is unique', 'CRITICAL',
         CAST(count(*) - count(DISTINCT (order_id, lineitem_id, option_group_name, option_name)) AS varchar),
         count(*) = count(DISTINCT (order_id, lineitem_id, option_group_name, option_name))
  FROM gp_silver.order_item_options
  UNION ALL
  SELECT 'silver: no rows with missing keys', 'CRITICAL', CAST(n AS varchar), n = 0
  FROM (SELECT (SELECT count(*) FROM gp_silver.order_items WHERE lineitem_id IS NULL)
             + (SELECT count(*) FROM gp_silver.order_item_options
                WHERE order_id IS NULL OR lineitem_id IS NULL OR option_group_name IS NULL OR option_name IS NULL) AS n)
  UNION ALL
  SELECT 'silver: no orphan options', 'CRITICAL', CAST(count(*) AS varchar), count(*) = 0
  FROM gp_silver.order_item_options o
  WHERE NOT EXISTS (SELECT 1 FROM gp_silver.order_items i
                    WHERE i.order_id = o.order_id AND i.lineitem_id = o.lineitem_id)
  UNION ALL
  SELECT 'gold sales_daily revenue = silver revenue', 'CRITICAL', CAST(diff AS varchar), diff = 0
  FROM (SELECT (SELECT sum(revenue) FROM gp_gold.sales_daily) - (SELECT revenue FROM silver_revenue) AS diff)
  UNION ALL
  SELECT 'gold location_performance revenue = silver revenue', 'CRITICAL', CAST(diff AS varchar), diff = 0
  FROM (SELECT (SELECT sum(total_revenue) FROM gp_gold.location_performance) - (SELECT revenue FROM silver_revenue) AS diff)
  UNION ALL
  SELECT 'gold order_pricing net revenue = silver revenue', 'CRITICAL', CAST(diff AS varchar), diff = 0
  FROM (SELECT (SELECT sum(net_revenue) FROM gp_gold.order_pricing) - (SELECT revenue FROM silver_revenue) AS diff)
  UNION ALL
  SELECT 'gold customer_profile LTV = customer_ltv_daily revenue', 'CRITICAL', CAST(diff AS varchar), diff = 0
  FROM (SELECT (SELECT sum(lifetime_value) FROM gp_gold.customer_profile)
             - (SELECT sum(daily_revenue) FROM gp_gold.customer_ltv_daily) AS diff)
  UNION ALL
  SELECT 'gold: final ltv_to_date = lifetime_value for every customer', 'CRITICAL', CAST(count(*) AS varchar), count(*) = 0
  FROM gp_gold.customer_profile p
  JOIN (SELECT user_id, max(ltv_to_date) AS final_ltv FROM gp_gold.customer_ltv_daily GROUP BY user_id) l
    ON p.user_id = l.user_id
  WHERE p.lifetime_value <> l.final_ltv
  UNION ALL
  SELECT 'gold: High CLV tier is 20% of customers (±1 point)', 'CRITICAL', CAST(pct AS varchar), pct BETWEEN 19 AND 21
  FROM (SELECT round(avg(CASE WHEN clv_tier = 'High' THEN 100.0 ELSE 0 END), 2) AS pct FROM gp_gold.customer_profile)
  UNION ALL
  SELECT 'gold: Low CLV tier is 20% of customers (±1 point)', 'CRITICAL', CAST(pct AS varchar), pct BETWEEN 19 AND 21
  FROM (SELECT round(avg(CASE WHEN clv_tier = 'Low' THEN 100.0 ELSE 0 END), 2) AS pct FROM gp_gold.customer_profile)
  UNION ALL
  SELECT 'gold: date_dim covers every sales date', 'CRITICAL', CAST(count(DISTINCT s.order_date) AS varchar),
         count(DISTINCT s.order_date) = 0
  FROM gp_gold.sales_daily s
  WHERE NOT EXISTS (SELECT 1 FROM gp_gold.date_dim d WHERE d.date_key = s.order_date)
  UNION ALL
  SELECT 'gold is as fresh as silver (same last order date)', 'CRITICAL', CAST(d AS varchar), d = 0
  FROM (SELECT date_diff('day', (SELECT max(order_date) FROM gp_gold.sales_daily),
                                (SELECT max(CAST(creation_time_utc AS date)) FROM gp_silver.order_items)) AS d)
  UNION ALL
  SELECT 'test rows in silver (item_name = ''Test'')', 'WARNING', CAST(count(*) AS varchar), count(*) = 0
  FROM gp_silver.order_items WHERE lower(item_name) = 'test'
  UNION ALL
  SELECT 'customers with $0 lifetime value', 'WARNING', CAST(count(*) AS varchar), count(*) = 0
  FROM gp_gold.customer_profile WHERE lifetime_value = 0
  UNION ALL
  SELECT 'customers with LTV over $5,000 (possible business accounts)', 'WARNING', CAST(count(*) AS varchar), count(*) = 0
  FROM gp_gold.customer_profile WHERE lifetime_value > 5000
  UNION ALL
  SELECT 'rows with no customer (NULL user_id), % of lines', 'WARNING', CAST(pct AS varchar), pct <= 10
  FROM (SELECT round(avg(CASE WHEN user_id IS NULL THEN 100.0 ELSE 0 END), 2) AS pct FROM gp_silver.order_items)
)
SELECT * FROM checks ORDER BY severity, passed, check_name;

-- History of the gate (written by job 3 on every run):
-- SELECT run_ts, check_name, severity, value, passed FROM gp_gold.dq_results ORDER BY run_ts DESC, severity;
