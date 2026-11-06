-- Dashboard: Customer Lifetime Value → average LTV by months since first order, per first-order year.
-- Shows how LTV accumulates over a customer's life (each customer's latest LTV in each month of life).
WITH firsts AS (SELECT user_id, first_order_date FROM gp_gold.customer_profile),
monthly AS (
  SELECT l.user_id, year(f.first_order_date) AS cohort_year,
         date_diff('month', f.first_order_date, l.order_date) AS months_since_first,
         max(l.ltv_to_date) AS ltv
  FROM gp_gold.customer_ltv_daily l JOIN firsts f ON l.user_id = f.user_id
  GROUP BY 1, 2, 3
)
SELECT cohort_year, months_since_first, round(avg(ltv), 2) AS avg_ltv_of_active, count(*) AS customers_ordering
FROM monthly
WHERE months_since_first <= 24
GROUP BY cohort_year, months_since_first
ORDER BY cohort_year, months_since_first
