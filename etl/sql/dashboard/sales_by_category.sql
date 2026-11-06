-- Dashboard: Sales Trends → revenue by item category and year.
SELECT year(order_date) AS year, item_category, sum(revenue) AS revenue, sum(line_items) AS line_items
FROM gp_gold.sales_daily
GROUP BY 1, 2
ORDER BY 1, revenue DESC
