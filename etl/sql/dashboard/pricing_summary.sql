-- Dashboard: Pricing & Discounts → orders with vs without an implied discount.
-- ESTIMATE: the source has no discount fields; see etl/sql/gold/order_pricing.sql for the rule.
SELECT has_discount,
       count(*)                          AS orders,
       sum(net_revenue)                  AS net_revenue,
       sum(gross_revenue)                AS gross_revenue,
       sum(implied_discount)             AS implied_discount,
       round(avg(net_revenue), 2)        AS avg_order_net,
       round(avg(line_items), 2)         AS avg_items_per_order
FROM gp_gold.order_pricing
GROUP BY has_discount
