-- Mirrors customer_ltv_daily() in etl/jobs/gold.py → gp_gold.customer_ltv_daily (PRIMARY GOAL).
-- One row per customer per day they ordered; ltv_to_date = lifetime value up to and including that day.
-- Days without an order have no row: the customer's LTV on such a day is the latest row before it.

WITH options AS (
  SELECT order_id, lineitem_id, sum(option_price * option_quantity) AS options_revenue
  FROM gp_silver.order_item_options
  GROUP BY order_id, lineitem_id
),
lines AS (  -- revenue per line = item_price (already a line total) + its options
  SELECT i.user_id, i.order_id,
         CAST(i.creation_time_utc AS date) AS order_date,
         i.item_price + coalesce(o.options_revenue, 0) AS line_revenue
  FROM gp_silver.order_items i
  LEFT JOIN options o ON i.order_id = o.order_id AND i.lineitem_id = o.lineitem_id
),
daily AS (
  SELECT user_id, order_date,
         sum(line_revenue)        AS daily_revenue,
         count(DISTINCT order_id) AS daily_orders
  FROM lines
  WHERE user_id IS NOT NULL  -- rows with no customer can't count toward anyone's LTV
  GROUP BY user_id, order_date
)
SELECT user_id, order_date, daily_revenue, daily_orders,
       sum(daily_revenue) OVER (PARTITION BY user_id ORDER BY order_date) AS ltv_to_date
FROM daily;

-- Example (dashboard / review): one customer's LTV curve.
-- SELECT order_date, daily_revenue, ltv_to_date FROM gp_gold.customer_ltv_daily
-- WHERE user_id = '5f21b43d37ab46bd0d7b241e' ORDER BY order_date;
