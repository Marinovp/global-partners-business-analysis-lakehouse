-- Mirrors sales_daily() in etl/jobs/gold.py → gp_gold.sales_daily.
-- Revenue by day, hour (UTC), location, app and item category.
-- `orders` = orders containing that category: sum `revenue` freely, but don't add up `orders`
-- across categories (an order with a drink and a sandwich would be counted twice).

WITH options AS (
  SELECT order_id, lineitem_id, sum(option_price * option_quantity) AS options_revenue
  FROM gp_silver.order_item_options
  GROUP BY order_id, lineitem_id
),
lines AS (
  SELECT i.*,
         CAST(i.creation_time_utc AS date) AS order_date,
         hour(i.creation_time_utc)         AS order_hour,
         i.item_price + coalesce(o.options_revenue, 0) AS line_revenue
  FROM gp_silver.order_items i
  LEFT JOIN options o ON i.order_id = o.order_id AND i.lineitem_id = o.lineitem_id
)
SELECT order_date, order_hour, restaurant_id, app_name, item_category,
       sum(line_revenue)        AS revenue,
       count(*)                 AS line_items,
       count(DISTINCT order_id) AS orders
FROM lines
GROUP BY order_date, order_hour, restaurant_id, app_name, item_category;

-- Monthly revenue with seasonality context (joins the calendar):
-- SELECT d.year, d.month_number, d.month, sum(s.revenue) AS revenue,
--        sum(CASE WHEN d.is_holiday THEN s.revenue END) AS holiday_revenue
-- FROM gp_gold.sales_daily s JOIN gp_gold.date_dim d ON s.order_date = d.date_key
-- GROUP BY 1, 2, 3 ORDER BY 1, 2;
