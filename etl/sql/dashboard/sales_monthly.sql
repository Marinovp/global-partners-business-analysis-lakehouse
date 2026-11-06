-- Dashboard: Sales Trends → monthly revenue and orders (orders come from order_pricing, one row per order,
-- so they aren't double counted across categories).
WITH revenue AS (
  SELECT date_trunc('month', order_date) AS month, sum(revenue) AS revenue
  FROM gp_gold.sales_daily GROUP BY 1
),
orders AS (
  SELECT date_trunc('month', order_date) AS month, count(*) AS orders, count(DISTINCT user_id) AS customers
  FROM gp_gold.order_pricing GROUP BY 1
)
SELECT r.month, r.revenue, o.orders, o.customers, round(r.revenue / o.orders, 2) AS avg_order_value
FROM revenue r JOIN orders o ON r.month = o.month
ORDER BY r.month
