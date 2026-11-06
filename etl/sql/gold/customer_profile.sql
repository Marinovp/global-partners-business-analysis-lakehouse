-- Mirrors customer_profile() + add_rfm() + add_churn_indicators() in etl/jobs/gold.py
-- → gp_gold.customer_profile: one row per customer.
--
-- CLV tier: High = top 20% by lifetime value, Medium = middle 60%, Low = bottom 20%.
-- RFM, measured from as_of_date (last order date in the data, 2024-02-21), over the last 12 months:
--   r_score  days since last order:  ≤30 → 5, ≤90 → 4, ≤180 → 3, ≤365 → 2, else 1
--   f_score  orders in 12 months:    ≥12 → 5, ≥6 → 4,  ≥3 → 3,   ≥1 → 2,   0 → 1
--   m_score  spend in 12 months:     ≥$500 → 5, ≥$200 → 4, ≥$75 → 3, >$0 → 2, $0 → 1
--   segment  VIP: R,F,M ≥ 4 · New: R ≥ 4 and F ≤ 2 · Churn Risk: R ≤ 2 and F ≤ 2 · else Regular
-- Churn: At Risk = no order for more than 45 days; spend trend = last 90 days vs the 90 before.
-- Thresholds are assumptions for the SME to confirm.

WITH options AS (
  SELECT order_id, lineitem_id, sum(option_price * option_quantity) AS options_revenue
  FROM gp_silver.order_item_options
  GROUP BY order_id, lineitem_id
),
lines AS (
  SELECT i.user_id, i.order_id, i.is_loyalty,
         CAST(i.creation_time_utc AS date) AS order_date,
         i.item_price + coalesce(o.options_revenue, 0) AS line_revenue
  FROM gp_silver.order_items i
  LEFT JOIN options o ON i.order_id = o.order_id AND i.lineitem_id = o.lineitem_id
),
as_of AS (SELECT max(order_date) AS as_of_date FROM lines),
customers AS (
  SELECT l.user_id,
         sum(l.line_revenue)                                    AS lifetime_value,
         count(DISTINCT l.order_id)                             AS total_orders,
         count(DISTINCT l.order_date)                           AS order_days,
         min(l.order_date)                                      AS first_order_date,
         max(l.order_date)                                      AS last_order_date,
         bool_or(l.is_loyalty)                                  AS is_loyalty_member,  -- any loyalty order
         count(DISTINCT CASE WHEN l.order_date > date_add('month', -12, a.as_of_date)
                             THEN l.order_id END)               AS frequency_12m,
         coalesce(sum(CASE WHEN l.order_date > date_add('month', -12, a.as_of_date)
                           THEN l.line_revenue END), 0)         AS monetary_12m,
         coalesce(sum(CASE WHEN date_diff('day', l.order_date, a.as_of_date) < 90
                           THEN l.line_revenue END), 0)         AS spend_last_90d,
         coalesce(sum(CASE WHEN date_diff('day', l.order_date, a.as_of_date) BETWEEN 90 AND 179
                           THEN l.line_revenue END), 0)         AS spend_prev_90d,
         a.as_of_date
  FROM lines l CROSS JOIN as_of a
  WHERE l.user_id IS NOT NULL
  GROUP BY l.user_id, a.as_of_date
),
scored AS (
  SELECT c.*,
         ntile(5) OVER (ORDER BY lifetime_value DESC)        AS clv_bucket,
         date_diff('day', last_order_date, as_of_date)       AS recency_days
  FROM customers c
),
rfm AS (
  SELECT s.*,
         CASE WHEN recency_days <= 30 THEN 5 WHEN recency_days <= 90 THEN 4
              WHEN recency_days <= 180 THEN 3 WHEN recency_days <= 365 THEN 2 ELSE 1 END AS r_score,
         CASE WHEN frequency_12m >= 12 THEN 5 WHEN frequency_12m >= 6 THEN 4
              WHEN frequency_12m >= 3 THEN 3 WHEN frequency_12m >= 1 THEN 2 ELSE 1 END AS f_score,
         CASE WHEN monetary_12m >= 500 THEN 5 WHEN monetary_12m >= 200 THEN 4
              WHEN monetary_12m >= 75 THEN 3 WHEN monetary_12m > 0 THEN 2 ELSE 1 END AS m_score
  FROM scored s
)
SELECT user_id, lifetime_value, total_orders, order_days, first_order_date, last_order_date,
       is_loyalty_member,
       clv_bucket,
       CASE clv_bucket WHEN 1 THEN 'High' WHEN 5 THEN 'Low' ELSE 'Medium' END        AS clv_tier,
       frequency_12m, monetary_12m, as_of_date, recency_days, r_score, f_score, m_score,
       CASE WHEN r_score >= 4 AND f_score >= 4 AND m_score >= 4 THEN 'VIP'
            WHEN r_score >= 4 AND f_score <= 2 THEN 'New'
            WHEN r_score <= 2 AND f_score <= 2 THEN 'Churn Risk'
            ELSE 'Regular' END                                                       AS rfm_segment,
       spend_last_90d, spend_prev_90d,
       recency_days                                                                  AS days_since_last_order,
       CASE WHEN order_days > 1
            THEN round(date_diff('day', first_order_date, last_order_date) / CAST(order_days - 1 AS double), 1)
       END                                                                           AS avg_days_between_orders,
       CASE WHEN spend_prev_90d > 0
            THEN round(CAST(spend_last_90d - spend_prev_90d AS double) / CAST(spend_prev_90d AS double) * 100, 1)
       END                                                                           AS spend_change_pct,
       CASE WHEN recency_days > 45 THEN 'At Risk' ELSE 'Active' END                  AS churn_status
FROM rfm;
