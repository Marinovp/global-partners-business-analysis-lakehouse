-- Dashboard: Customer Lifetime Value → tier summary. High = top 20%, Medium = middle 60%, Low = bottom 20%.
SELECT clv_tier,
       count(*)                                                        AS customers,
       sum(lifetime_value)                                             AS revenue,
       round(100.0 * sum(lifetime_value) / sum(sum(lifetime_value)) OVER (), 1) AS revenue_share_pct,
       round(avg(lifetime_value), 2)                                   AS avg_ltv,
       min(lifetime_value)                                             AS min_ltv,
       max(lifetime_value)                                             AS max_ltv
FROM gp_gold.customer_profile
GROUP BY clv_tier
ORDER BY max(lifetime_value) DESC
