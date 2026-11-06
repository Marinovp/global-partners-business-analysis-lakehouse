-- Dashboard: Pricing & Discounts → monthly orders and revenue, discounted vs full price.
SELECT date_trunc('month', order_date) AS month, has_discount,
       count(*) AS orders, sum(net_revenue) AS net_revenue, sum(implied_discount) AS implied_discount
FROM gp_gold.order_pricing
GROUP BY 1, 2
ORDER BY 1, 2
