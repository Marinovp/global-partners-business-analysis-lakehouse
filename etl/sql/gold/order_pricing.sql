-- Mirrors order_pricing() in etl/jobs/gold.py → gp_gold.order_pricing: one row per order.
--
-- The source has NO discount fields (no negative option prices), so discounts are ESTIMATED:
-- a line counts as discounted when its unit price is below 90% of the median unit price of the
-- same item at the same location in the same year. Mid-year price increases can also look like
-- discounts, so treat implied_discount as an estimate, not accounting truth.
--   net_revenue   = what was actually charged
--   gross_revenue = what the order would have cost at usual prices
-- Profit can't be computed: the data has no cost information.

WITH options AS (
  SELECT order_id, lineitem_id, sum(option_price * option_quantity) AS options_revenue
  FROM gp_silver.order_item_options
  GROUP BY order_id, lineitem_id
),
lines AS (
  SELECT i.*,
         CAST(i.creation_time_utc AS date)              AS order_date,
         year(i.creation_time_utc)                      AS year,
         coalesce(o.options_revenue, 0)                 AS options_revenue,
         i.item_price + coalesce(o.options_revenue, 0)  AS line_revenue,
         i.item_price / i.item_quantity                 AS unit_price
  FROM gp_silver.order_items i
  LEFT JOIN options o ON i.order_id = o.order_id AND i.lineitem_id = o.lineitem_id
),
usual AS (
  SELECT restaurant_id, item_name, year, approx_percentile(unit_price, 0.5) AS usual_unit_price
  FROM lines
  GROUP BY restaurant_id, item_name, year
),
priced AS (
  SELECT l.*, u.usual_unit_price,
         l.unit_price < u.usual_unit_price * 0.9 AS is_discounted
  FROM lines l
  JOIN usual u ON l.restaurant_id = u.restaurant_id AND l.item_name = u.item_name AND l.year = u.year
)
SELECT order_id, order_date, restaurant_id, user_id, is_loyalty,
       sum(line_revenue)                                                      AS net_revenue,
       sum(CASE WHEN is_discounted
                THEN CAST(usual_unit_price * item_quantity + options_revenue AS decimal(12, 2))
                ELSE line_revenue END)                                       AS gross_revenue,
       bool_or(is_discounted)                                                 AS has_discount,
       count_if(is_discounted)                                                AS discounted_lines,
       count(*)                                                               AS line_items,
       sum(CASE WHEN is_discounted
                THEN CAST(usual_unit_price * item_quantity + options_revenue AS decimal(12, 2))
                ELSE line_revenue END) - sum(line_revenue)                   AS implied_discount
FROM priced
GROUP BY order_id, order_date, restaurant_id, user_id, is_loyalty;
