-- Dashboard: Loyalty Program Impact → share of each CLV tier that are loyalty members.
SELECT clv_tier, is_loyalty_member, count(*) AS customers, round(avg(lifetime_value), 2) AS avg_ltv
FROM gp_gold.customer_profile
GROUP BY 1, 2
ORDER BY 1, 2
