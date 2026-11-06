-- Dashboard: Customer Lifetime Value → highest-value customers (also feeds the customer picker).
SELECT 
        user_id, 
        lifetime_value, 
        total_orders, 
        clv_tier, rfm_segment,
        churn_status,
       is_loyalty_member, 
       first_order_date, 
       last_order_date
FROM 
    gp_gold.customer_profile
ORDER BY 
    lifetime_value DESC
LIMIT 200
