-- Dashboard: Sales Trends → revenue by day of week and hour (hours are UTC; store time zones are unknown).
SELECT 
        d.day_of_week, day_of_week(s.order_date) AS weekday_number, 
        s.order_hour, sum(s.revenue) AS revenue
FROM 
    gp_gold.sales_daily s 
    JOIN gp_gold.date_dim d 
        ON s.order_date = d.date_key
GROUP BY 
    1, 2, 3
ORDER BY 
    2, 3
