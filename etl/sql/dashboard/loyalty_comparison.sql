-- Dashboard: Loyalty Program Impact → members vs non-members (a member = any loyalty order).
WITH customers AS (
  SELECT is_loyalty_member,
         count(*)                                                     AS customers,
         round(avg(lifetime_value), 2)                                AS avg_ltv,
         round(avg(total_orders), 2)                                  AS avg_orders,
         round(100.0 * avg(CASE WHEN total_orders > 1 THEN 1 ELSE 0 END), 1) AS repeat_customer_pct,
         sum(lifetime_value)                                          AS lifetime_revenue
  FROM gp_gold.customer_profile
  GROUP BY 1
),
orders AS (
  SELECT p.is_loyalty_member, round(avg(o.net_revenue), 2) AS avg_order_value
  FROM gp_gold.order_pricing o JOIN gp_gold.customer_profile p ON o.user_id = p.user_id
  GROUP BY 1
)
SELECT c.*, o.avg_order_value
FROM customers c JOIN orders o ON c.is_loyalty_member = o.is_loyalty_member
