-- Dashboard: Churn Risk → Active vs At Risk (no order for more than 45 days before as_of_date).
SELECT churn_status,
       count(*)                                  AS customers,
       round(avg(days_since_last_order), 0)      AS avg_days_since_last_order,
       round(avg(avg_days_between_orders), 1)    AS avg_days_between_orders,
       round(avg(spend_change_pct), 1)           AS avg_spend_change_pct,
       sum(lifetime_value)                       AS lifetime_revenue,
       max(as_of_date)                           AS as_of_date
FROM gp_gold.customer_profile
GROUP BY churn_status
