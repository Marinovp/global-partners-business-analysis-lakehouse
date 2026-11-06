-- Dashboard: Sales Trends → average daily revenue on holidays, weekends and regular weekdays.
WITH days AS (
  SELECT s.order_date, d.is_holiday, d.is_weekend, d.holiday_name, sum(s.revenue) AS revenue
  FROM gp_gold.sales_daily s JOIN gp_gold.date_dim d ON s.order_date = d.date_key
  GROUP BY 1, 2, 3, 4
)
SELECT CASE WHEN is_holiday THEN 'Holiday' WHEN is_weekend THEN 'Weekend' ELSE 'Weekday' END AS day_type,
       count(*) AS days, round(avg(revenue), 2) AS avg_daily_revenue
FROM days
GROUP BY 1
UNION ALL
SELECT holiday_name, count(*), round(avg(revenue), 2)
FROM days WHERE is_holiday
GROUP BY 1
