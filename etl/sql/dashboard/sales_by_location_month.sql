-- Dashboard: Sales Trends → monthly revenue per location.
SELECT date_trunc('month', order_date) AS month, restaurant_id, sum(revenue) AS revenue
FROM gp_gold.sales_daily
GROUP BY 1, 2
ORDER BY 1, 2
