import pandas as pd
import plotly.express as px
import streamlit as st

import common
from hl.config import HMDA_YEARS, PRODUCTS
from hl.core import insights, market, metrics

common.require_data()
st.title("Home lending sales - national overview")

states = common.state_products()
year = st.segmented_control("HMDA year", HMDA_YEARS, default=HMDA_YEARS[-1], key="overview_year") or HMDA_YEARS[-1]
current = states[states["year"] == year]
previous = states[states["year"] == year - 1]

# KPI row
total_loans, total_volume = current["loans"].sum(), current["volume"].sum()
columns = st.columns(5)
columns[0].metric("Originations", common.number(total_loans),
                  common.delta_pct((total_loans / previous["loans"].sum() - 1) if not previous.empty else None))
columns[1].metric("Volume", common.money(total_volume),
                  common.delta_pct((total_volume / previous["volume"].sum() - 1) if not previous.empty else None))
national_shares = metrics.mix_shares(current)
columns[2].metric("Purchase share", f"{national_shares['Purchase']:.0%}")
columns[3].metric("Refi + cash-out share", f"{national_shares['Refinance'] + national_shares['Cash-out Refi']:.0%}")
rates = common.mortgage_rates()
rate_ctx = market.rate_context(rates) if rates is not None else None
if rate_ctx:
    columns[4].metric("30y mortgage rate", f"{rate_ctx['rate']:.2f}%", f"{rate_ctx['change']:+.2f} pts YoY",
                      delta_color="inverse")

# Map
st.subheader("Where each product sells")
map_left, map_right = st.columns([1, 3])
product = map_left.radio("Product", PRODUCTS, key="overview_product")
measure = map_left.radio("Measure", ["Share of state's loans", "Loan count", "Dollar volume"], key="overview_measure")
mix = metrics.product_mix(current, ["state"])
selected = mix[mix["product"] == product]
value_column = {"Share of state's loans": "share", "Loan count": "loans", "Dollar volume": "volume"}[measure]
figure = common.choropleth_sequential(
    data_frame=selected, locations="state", locationmode="USA-states", scope="usa", color=value_column,
    hover_name="state", hover_data={"share": ":.1%", "loans": ":,", "volume": ":$,.0f", "state": False},
)
if value_column == "share":
    figure.update_layout(coloraxis_colorbar=dict(tickformat=".0%"))
map_right.plotly_chart(figure, width="stretch")
map_left.caption("Tip: open **Drill-down** to go from a state to its counties, cities and individual loans.")

# Mix by state
st.subheader("Product mix by state")
sort_product = st.selectbox("Sort states by share of", PRODUCTS, key="overview_sort")
order = (mix[mix["product"] == sort_product].sort_values("share")["state"].tolist())
st.plotly_chart(
    common.mix_bar(mix, "state", title=f"Share of originations by product, {year}")
    .update_yaxes(categoryorder="array", categoryarray=order),
    width="stretch",
)

# Rates + headline insights
left, right = st.columns([3, 2])
if rates is not None:
    recent = rates[rates["date"] >= rates["date"].max() - pd.DateOffset(years=5)]
    rate_figure = px.line(recent, x="date", y="rate_30y", title="30-year fixed mortgage rate (Freddie Mac PMMS)")
    rate_figure.update_traces(line=dict(width=2, color="#2a78d6"),
                              hovertemplate="%{x|%b %d, %Y}: %{y:.2f}%<extra></extra>")
    rate_figure.update_layout(hovermode="x unified")
    rate_figure.update_yaxes(ticksuffix="%", title=None)
    rate_figure.update_xaxes(title=None)
    left.plotly_chart(common.style(rate_figure, 320), width="stretch")
with right:
    st.markdown("**National signals**")
    national = [item for item in [insights.rate_insight(rate_ctx) if rate_ctx else None] if item]
    national += insights.yoy_insights("United States", metrics.yoy_change(states, year), year)
    common.render_insights(national)

common.data_footnote()
