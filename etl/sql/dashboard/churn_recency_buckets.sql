-- Dashboard: Churn Risk → how long customers have been inactive, with their value.
SELECT CASE WHEN days_since_last_order <= 45  THEN '1: 0-45 days'
            WHEN days_since_last_order <= 90  THEN '2: 46-90 days'
            WHEN days_since_last_order <= 180 THEN '3: 91-180 days'
            WHEN days_since_last_order <= 365 THEN '4: 181-365 days'
            ELSE '5: over 365 days' END       AS inactivity,
       clv_tier,
       count(*)                               AS customers,
       sum(lifetime_value)                    AS lifetime_revenue
FROM gp_gold.customer_profile
GROUP BY 1, 2
ORDER BY 1, 2
