-- Dashboard: Churn Risk → valuable customers who recently went quiet (re-engagement list).
-- Inactive for 46-180 days (recent enough to win back), ranked by lifetime value.
SELECT user_id, clv_tier, rfm_segment, lifetime_value, total_orders,
       days_since_last_order, avg_days_between_orders, spend_last_90d, spend_prev_90d, spend_change_pct,
       is_loyalty_member, last_order_date
FROM gp_gold.customer_profile
WHERE churn_status = 'At Risk' AND days_since_last_order <= 180
ORDER BY lifetime_value DESC
LIMIT 100
