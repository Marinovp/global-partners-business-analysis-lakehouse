-- Dashboard: Customer Segmentation → customers per Recency × Frequency score (1 = worst, 5 = best).
SELECT 
        r_score, f_score, count(*) AS customers, 
        round(avg(monetary_12m), 2) AS avg_spend_12m
FROM 
    gp_gold.customer_profile
GROUP BY 
    r_score, f_score
ORDER BY 
    r_score, f_score
