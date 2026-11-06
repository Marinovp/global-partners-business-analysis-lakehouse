-- Mirrors location_performance() in etl/jobs/gold.py → gp_gold.location_performance.
-- One row per location (restaurant_id; location names aren't in the data), ranked by revenue.
-- repeat_customer_pct = share of the location's identified customers who ordered there more than once.

WITH options AS (
  SELECT order_id, lineitem_id, sum(option_price * option_quantity) AS options_revenue
  FROM gp_silver.order_item_options
  GROUP BY order_id, lineitem_id
),
lines AS (
  SELECT i.restaurant_id, i.order_id, i.user_id,
         CAST(i.creation_time_utc AS date) AS order_date,
         i.item_price + coalesce(o.options_revenue, 0) AS line_revenue
  FROM gp_silver.order_items i
  LEFT JOIN options o ON i.order_id = o.order_id AND i.lineitem_id = o.lineitem_id
),
orders AS (
  SELECT restaurant_id, order_id, user_id, order_date, sum(line_revenue) AS order_revenue
  FROM lines
  GROUP BY restaurant_id, order_id, user_id, order_date
),
customers AS (
  SELECT restaurant_id,
         count(*) AS unique_customers,
         round(avg(CASE WHEN orders > 1 THEN 1.0 ELSE 0 END) * 100, 1) AS repeat_customer_pct
  FROM (SELECT restaurant_id, user_id, count(*) AS orders
        FROM orders WHERE user_id IS NOT NULL GROUP BY restaurant_id, user_id)
  GROUP BY restaurant_id
),
per_location AS (
  SELECT restaurant_id,
         sum(order_revenue)                AS total_revenue,
         count(*)                          AS total_orders,
         round(avg(order_revenue), 2)      AS avg_order_value,
         count(DISTINCT order_date)        AS active_days,
         min(order_date)                   AS first_order_date,
         max(order_date)                   AS last_order_date
  FROM orders
  GROUP BY restaurant_id
)
SELECT p.*, c.unique_customers, c.repeat_customer_pct,
       round(CAST(total_orders AS double) / active_days, 1)                                        AS orders_per_active_day,
       round(total_orders / greatest((date_diff('day', first_order_date, last_order_date) + 1) / 7.0, 1), 1) AS orders_per_week,
       rank() OVER (ORDER BY total_revenue DESC)                                                    AS revenue_rank
FROM per_location p
LEFT JOIN customers c ON p.restaurant_id = c.restaurant_id;
