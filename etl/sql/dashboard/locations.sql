-- Dashboard: Location Performance → every location, ranked by revenue.
SELECT revenue_rank, restaurant_id, total_revenue, total_orders, avg_order_value,
       unique_customers, repeat_customer_pct, orders_per_active_day, orders_per_week,
       active_days, first_order_date, last_order_date
FROM gp_gold.location_performance
ORDER BY revenue_rank
