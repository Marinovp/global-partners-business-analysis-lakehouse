"""Global Partners business insights dashboard (Streamlit).

Run from the repo root:  streamlit run dashboard/app.py
Reads the gold tables through Athena with your AWS credentials. Every query lives in
etl/sql/dashboard/<name>.sql, so the SQL can be reviewed separately from this file.
"""

import altair as alt
import pandas as pd
import streamlit as st

from athena import USER_ID, query

st.set_page_config(page_title="Global Partners Insights", layout="wide")

PAGES = [
    "Customer Lifetime Value",
    "Customer Segmentation",
    "Churn Risk",
    "Sales Trends & Seasonality",
    "Loyalty Program Impact",
    "Location Performance",
    "Pricing & Discounts",
    "Data Quality",
]
page = st.sidebar.radio("Dashboard", PAGES)
st.sidebar.caption(
    "Data: Jan 2020 – Feb 21, 2024 (as-of date for recency and churn). "
    "Revenue = item price + options. Times are UTC."
)


def money(value) -> str:
    return f"${float(value):,.0f}"


def bar(df: pd.DataFrame, x: str, y: str, color: str | None = None, sort=None, horizontal=False):
    enc = {"x": alt.X(x, sort=sort), "y": alt.Y(y)} if not horizontal else {"y": alt.Y(x, sort=sort), "x": alt.X(y)}
    chart = alt.Chart(df).mark_bar().encode(**enc, tooltip=list(df.columns))
    if color:
        chart = chart.encode(color=color)
    st.altair_chart(chart, width="stretch")


# ----------------------------------------------------------------------------------------------
if page == "Customer Lifetime Value":
    st.title("Customer Lifetime Value")
    st.caption("Lifetime value = total revenue from a customer so far. Tiers: High = top 20%, Medium = middle 60%, Low = bottom 20%.")
    tiers = query("clv_tiers")
    cols = st.columns(len(tiers))
    for col, row in zip(cols, tiers.itertuples()):
        col.metric(f"{row.clv_tier} value customers", f"{row.customers:,}", f"{row.revenue_share_pct}% of revenue", delta_color="off")
    st.dataframe(tiers, hide_index=True, width="stretch")

    st.subheader("How LTV builds up over a customer's life")
    cohort = query("ltv_cohort_curve")
    cohort["cohort_year"] = cohort["cohort_year"].astype(str)
    st.altair_chart(
        alt.Chart(cohort).mark_line(point=True).encode(
            x=alt.X("months_since_first:Q", title="Months since first order"),
            y=alt.Y("avg_ltv_of_active:Q", title="Average LTV of customers ordering that month"),
            color=alt.Color("cohort_year:N", title="First order year"),
            tooltip=list(cohort.columns),
        ),
        width="stretch",
    )

    st.subheader("One customer's LTV, day by day")
    top = query("top_customers")
    choice = st.selectbox(
        "Customer (top 200 by lifetime value)",
        top["user_id"],
        format_func=lambda u: f"{u} · {money(top.set_index('user_id').loc[u, 'lifetime_value'])}",
    )
    typed = st.text_input("…or paste any customer id")
    user = typed.strip() or choice
    if not USER_ID.match(user):
        st.error("A customer id is 24 lowercase hex characters.")
    else:
        curve = query("customer_ltv_curve", user_id=user)
        if curve.empty:
            st.info("No orders for this customer.")
        else:
            st.altair_chart(
                alt.Chart(curve).mark_line(interpolate="step-after", point=True).encode(
                    x="order_date:T", y=alt.Y("ltv_to_date:Q", title="LTV to date ($)"), tooltip=list(curve.columns)
                ),
                width="stretch",
            )
            st.dataframe(curve, hide_index=True, width="stretch")
    with st.expander("Top 200 customers"):
        st.dataframe(top, hide_index=True, width="stretch")

# ----------------------------------------------------------------------------------------------
elif page == "Customer Segmentation":
    st.title("Customer Segmentation (RFM)")
    st.caption(
        "Recency, frequency and spend over the last 12 months before Feb 21, 2024. "
        "VIP: R, F, M ≥ 4 · New: recent (R ≥ 4) with few orders (F ≤ 2) · Churn Risk: R ≤ 2 and F ≤ 2 · else Regular."
    )
    seg = query("segments")
    seg["member"] = seg["is_loyalty_member"].map({True: "Loyalty member", False: "Non-member"})
    totals = seg.groupby("rfm_segment", as_index=False)[["customers", "lifetime_revenue"]].sum()
    cols = st.columns(len(totals))
    for col, row in zip(cols, totals.itertuples()):
        col.metric(row.rfm_segment, f"{row.customers:,} customers", money(row.lifetime_revenue), delta_color="off")
    left, right = st.columns(2)
    with left:
        st.subheader("Customers per segment, by loyalty")
        bar(seg, "rfm_segment", "customers", color="member")
    with right:
        st.subheader("Average lifetime value per segment")
        bar(seg, "rfm_segment", "avg_ltv", color="member")
    st.subheader("Recency × Frequency grid (customers)")
    grid = query("rfm_grid")
    st.altair_chart(
        alt.Chart(grid).mark_rect().encode(
            x=alt.X("f_score:O", title="Frequency score (5 = most orders)"),
            y=alt.Y("r_score:O", title="Recency score (5 = most recent)", sort="descending"),
            color=alt.Color("customers:Q", scale=alt.Scale(scheme="blues")),
            tooltip=list(grid.columns),
        ),
        width="stretch",
    )
    st.dataframe(seg.drop(columns="member"), hide_index=True, width="stretch")

# ----------------------------------------------------------------------------------------------
elif page == "Churn Risk":
    st.title("Churn Risk Indicators")
    summary = query("churn_summary")
    as_of = summary["as_of_date"].max()
    st.caption(f"At Risk = no order for more than 45 days before {as_of}. Descriptive indicators, not a prediction.")
    cols = st.columns(len(summary))
    for col, row in zip(cols, summary.itertuples()):
        col.metric(row.churn_status, f"{row.customers:,} customers", f"avg {row.avg_days_since_last_order:.0f} days since last order", delta_color="off")
    st.dataframe(summary.drop(columns="as_of_date"), hide_index=True, width="stretch")
    st.subheader("How long customers have been inactive")
    buckets = query("churn_recency_buckets")
    bar(buckets, "inactivity", "customers", color="clv_tier")
    st.subheader("Re-engagement list: valuable customers who went quiet 46–180 days ago")
    st.dataframe(query("churn_watchlist"), hide_index=True, width="stretch")

# ----------------------------------------------------------------------------------------------
elif page == "Sales Trends & Seasonality":
    st.title("Sales Trends & Seasonality")
    monthly = query("sales_monthly")
    st.subheader("Monthly revenue")
    st.altair_chart(
        alt.Chart(monthly).mark_line(point=True).encode(x="month:T", y="revenue:Q", tooltip=list(monthly.columns)),
        width="stretch",
    )
    left, right = st.columns(2)
    with left:
        st.subheader("Monthly orders")
        st.altair_chart(alt.Chart(monthly).mark_bar().encode(x="month:T", y="orders:Q", tooltip=list(monthly.columns)), width="stretch")
    with right:
        st.subheader("Holidays vs weekends vs weekdays")
        hol = query("sales_holidays")
        bar(hol, "day_type", "avg_daily_revenue", sort="-y")
    st.subheader("Revenue by category")
    cats = query("sales_by_category")
    years = sorted(cats["year"].unique())
    year = st.select_slider("Year", options=years, value=years[-1])
    bar(cats[cats["year"] == year].head(15), "item_category", "revenue", sort="-x", horizontal=True)
    st.subheader("Revenue by day of week and hour (UTC)")
    wh = query("sales_weekday_hour")
    st.altair_chart(
        alt.Chart(wh).mark_rect().encode(
            x=alt.X("order_hour:O", title="Hour (UTC)"),
            y=alt.Y("day_of_week:N", sort=alt.EncodingSortField("weekday_number")),
            color=alt.Color("revenue:Q", scale=alt.Scale(scheme="greens")),
            tooltip=list(wh.columns),
        ),
        width="stretch",
    )
    st.subheader("Monthly revenue by location")
    loc = query("sales_by_location_month")
    picks = st.multiselect("Locations", sorted(loc["restaurant_id"].unique()), default=sorted(loc["restaurant_id"].unique())[:5])
    st.altair_chart(
        alt.Chart(loc[loc["restaurant_id"].isin(picks)]).mark_line().encode(x="month:T", y="revenue:Q", color="restaurant_id:N"),
        width="stretch",
    )

# ----------------------------------------------------------------------------------------------
elif page == "Loyalty Program Impact":
    st.title("Loyalty Program Impact")
    st.caption("A customer counts as a member if any of their orders was a loyalty order.")
    comp = query("loyalty_comparison")
    comp["group"] = comp["is_loyalty_member"].map({True: "Loyalty members", False: "Non-members"})
    cols = st.columns(len(comp))
    for col, row in zip(cols, comp.itertuples()):
        col.metric(row.group, f"{money(row.avg_ltv)} avg LTV", f"{row.repeat_customer_pct}% repeat · {money(row.avg_order_value)} AOV", delta_color="off")
    metrics = comp.melt(id_vars="group", value_vars=["avg_ltv", "avg_orders", "repeat_customer_pct", "avg_order_value"])
    st.altair_chart(
        alt.Chart(metrics).mark_bar().encode(
            x=alt.X("group:N", title=None), y=alt.Y("value:Q", title=None), color="group:N", column=alt.Column("variable:N", title=None)
        ).resolve_scale(y="independent"),
    )
    st.dataframe(comp.drop(columns="group"), hide_index=True, width="stretch")
    st.subheader("Loyalty membership by CLV tier")
    tiers = query("loyalty_by_tier")
    tiers["member"] = tiers["is_loyalty_member"].map({True: "Loyalty member", False: "Non-member"})
    bar(tiers, "clv_tier", "customers", color="member")

# ----------------------------------------------------------------------------------------------
elif page == "Location Performance":
    st.title("Location Performance")
    st.caption("Locations are identified by restaurant_id (names aren't in the data). Retention = share of a location's customers who ordered there more than once.")
    locs = query("locations")
    best, worst = locs.iloc[0], locs.iloc[-1]
    c1, c2, c3 = st.columns(3)
    c1.metric("Top location", best.restaurant_id, money(best.total_revenue), delta_color="off")
    c2.metric("Lowest location", worst.restaurant_id, money(worst.total_revenue), delta_color="off")
    c3.metric("Locations", len(locs))
    bar(locs, "restaurant_id", "total_revenue", sort="-x", horizontal=True)
    st.subheader("What distinguishes top performers")
    st.altair_chart(
        alt.Chart(locs).mark_circle(size=120).encode(
            x=alt.X("avg_order_value:Q", title="Average order value ($)"),
            y=alt.Y("repeat_customer_pct:Q", title="Repeat customers (%)"),
            size="total_revenue:Q",
            color=alt.Color("revenue_rank:Q", scale=alt.Scale(scheme="viridis", reverse=True)),
            tooltip=list(locs.columns),
        ),
        width="stretch",
    )
    st.dataframe(locs, hide_index=True, width="stretch")

# ----------------------------------------------------------------------------------------------
elif page == "Pricing & Discounts":
    st.title("Pricing & Discount Effectiveness")
    st.warning(
        "The source data contains **no discount fields** (no negative option prices). Discounts here are an "
        "**estimate**: a line sold below 90% of the same item's median price at the same location in the same year. "
        "Mid-year price increases can also look like discounts. Profit can't be shown: there is no cost data."
    )
    summary = query("pricing_summary")
    summary["orders_type"] = summary["has_discount"].map({True: "With implied discount", False: "Full price"})
    cols = st.columns(len(summary))
    for col, row in zip(cols, summary.itertuples()):
        col.metric(row.orders_type, f"{row.orders:,} orders", f"net {money(row.net_revenue)} · avg {money(row.avg_order_net)}", delta_color="off")
    total_discount = summary["implied_discount"].sum()
    gross = summary["gross_revenue"].sum()
    st.metric("Estimated revenue given away (gross − net)", money(total_discount), f"{100 * float(total_discount) / float(gross):.1f}% of gross", delta_color="off")
    st.dataframe(summary.drop(columns="orders_type"), hide_index=True, width="stretch")
    st.subheader("Monthly orders: discounted vs full price")
    monthly = query("pricing_monthly")
    monthly["orders_type"] = monthly["has_discount"].map({True: "With implied discount", False: "Full price"})
    st.altair_chart(
        alt.Chart(monthly).mark_area(opacity=0.7).encode(x="month:T", y=alt.Y("orders:Q", stack=True), color="orders_type:N", tooltip=list(monthly.columns)),
        width="stretch",
    )

# ----------------------------------------------------------------------------------------------
elif page == "Data Quality":
    st.title("Data Quality Gate")
    st.caption("Results of the latest pipeline run's DQ job. A failed CRITICAL check fails the pipeline and sends an alert.")
    dq = query("dq_latest")
    if dq.empty:
        st.info("No DQ results yet. Run the pipeline first.")
    else:
        st.write(f"Run at {dq['run_ts'].max()} UTC")
        failed = dq[(dq["severity"] == "CRITICAL") & (~dq["passed"])]
        (st.error if len(failed) else st.success)(f"{len(failed)} critical failures")
        st.dataframe(dq, hide_index=True, width="stretch")
