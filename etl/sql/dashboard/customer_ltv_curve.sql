-- Dashboard: Customer Lifetime Value → how one customer's LTV evolved day by day (primary goal).
-- $user_id is filled in by the app (validated as a 24-character hex id before use).
SELECT order_date, daily_revenue, daily_orders, ltv_to_date
FROM gp_gold.customer_ltv_daily
WHERE user_id = '$user_id'
ORDER BY order_date
