-- Dashboard: Customer Segmentation → RFM segment × loyalty status.
SELECT rfm_segment, is_loyalty_member,
       count(*)                        AS customers,
       sum(lifetime_value)             AS lifetime_revenue,
       round(avg(lifetime_value), 2)   AS avg_ltv,
       round(avg(recency_days), 0)     AS avg_recency_days,
       round(avg(frequency_12m), 1)    AS avg_orders_12m,
       round(avg(monetary_12m), 2)     AS avg_spend_12m
FROM gp_gold.customer_profile
GROUP BY rfm_segment, is_loyalty_member
ORDER BY rfm_segment, is_loyalty_member
