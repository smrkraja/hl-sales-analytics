import plotly.express as px
import streamlit as st

import common
from hl.config import REGIME_COLORS
from hl.core import insights, market, news

common.require_data()
st.title("Market movement & news")
st.caption("Is the market tilting toward buyers or sellers, and are employers moving in or out?")

all_counties = common.counties()
states = sorted(all_counties["state"].unique())
left, middle, right = st.columns(3)
state = left.selectbox("State", states, index=states.index("TX"), key="mn_state")
state_counties = all_counties[all_counties["state"] == state].sort_values("county_name")
fips_list = state_counties["county_fips"].tolist()
county_fips = middle.selectbox("County", fips_list, index=fips_list.index("48453") if "48453" in fips_list else 0,
                               format_func=state_counties.set_index("county_fips")["county_name"].get, key="mn_county")
# Offer the county's cities ranked by number of census tracts (a proxy for size).
cities = (common.tract_city().query("county_fips == @county_fips and not city.str.startswith('Unincorporated')")
          ["city"].value_counts().index.tolist())
city = right.selectbox("City (for news)", cities or ["(none)"], key="mn_city")

# --- market regime -------------------------------------------------------------
st.subheader("Buyer's vs seller's market")
county_market = common.market_county()
series = county_market[county_market["county_fips"] == county_fips] if county_market is not None else None
shift = market.regime_shift(series) if series is not None and not series.empty else None
if shift is None:
    st.info("No Redfin market data for this county (small markets are often not covered).")
else:
    columns = st.columns(4)
    columns[0].markdown(common.regime_badge(shift["current"]), unsafe_allow_html=True)
    columns[0].caption(f"was {shift['previous']} a year ago" if shift["changed"] else "unchanged from a year ago")
    columns[1].metric("Months of supply", f"{shift['months_of_supply']:.1f}",
                      f"{shift['months_of_supply'] - shift['months_of_supply_prev']:+.1f} YoY", delta_color="off")
    if shift["sale_to_list"]:
        columns[2].metric("Sale-to-list", f"{shift['sale_to_list']:.1%}")
    if shift["median_sale_price_yoy"] is not None:
        columns[3].metric("Median price YoY", f"{shift['median_sale_price_yoy']:+.1%}")

    history = market.with_regime(series)
    figure = px.line(history, x="period_end", y="months_of_supply", title="Months of supply (rolling 90 days)")
    figure.update_traces(line=dict(width=2, color="#2a78d6"),
                         hovertemplate="%{x|%b %Y}: %{y:.1f} months<extra></extra>")
    # Reference bands: under 4 months favors sellers, over 6 favors buyers.
    figure.add_hrect(y0=0, y1=market.SELLER_MAX_SUPPLY, fillcolor=REGIME_COLORS["Seller's market"], opacity=0.07,
                     line_width=0, annotation_text="Seller's market", annotation_position="bottom left")
    figure.add_hrect(y0=market.BUYER_MIN_SUPPLY, y1=max(history["months_of_supply"].max(), 8) + 0.5,
                     fillcolor=REGIME_COLORS["Buyer's market"], opacity=0.07, line_width=0,
                     annotation_text="Buyer's market", annotation_position="top left")
    figure.update_yaxes(title=None, rangemode="tozero")
    figure.update_xaxes(title=None)
    chart_left, chart_right = st.columns(2)
    chart_left.plotly_chart(common.style(figure, 340), width="stretch")

    prices = px.line(history, x="period_end", y="median_sale_price", title="Median sale price")
    prices.update_traces(line=dict(width=2, color="#2a78d6"),
                         hovertemplate="%{x|%b %Y}: $%{y:,.0f}<extra></extra>")
    prices.update_yaxes(title=None, tickprefix="$")
    prices.update_xaxes(title=None)
    chart_right.plotly_chart(common.style(prices, 340), width="stretch")

# --- news ----------------------------------------------------------------------
st.subheader(f"Market news: {city}")
if city == "(none)":
    st.stop()
with st.spinner("Fetching headlines..."):
    result = news.fetch_city_news(city, state)
for error in result["errors"]:
    st.caption(f"⚠️ {error}")
counts = news.signal_counts(result["articles"])
columns = st.columns(4)
columns[0].metric("🟢 Inflow (relocations, hiring)", counts["Inflow"])
columns[1].metric("🟠 Outflow (layoffs, closures)", counts["Outflow"])
columns[2].metric("🏠 Housing market", counts["Housing"])
columns[3].metric("Other", counts["Other"])

samples = {signal: [a["title"] for a in result["articles"] if a["signal"] == signal] for signal in counts}
found = insights.news_insight(city, counts, samples)
if shift:
    found += [item for item in [insights.regime_insight(common.county_label(county_fips), shift)] if item]
common.render_insights(found, "No strong employer inflow/outflow signal in recent headlines.")

signal_filter = st.segmented_control("Show", ["Inflow", "Outflow", "Housing", "Other"],
                                     selection_mode="multi", default=["Inflow", "Outflow", "Housing"], key="mn_filter")
icons = {"Inflow": "🟢", "Outflow": "🟠", "Housing": "🏠", "Other": "▫️"}
shown = [article for article in result["articles"] if article["signal"] in (signal_filter or [])]
for article in shown[:40]:
    st.markdown(f"{icons[article['signal']]} **{article['signal']}** · [{article['title']}]({article['link']})  \n"
                f"<span style='color:#898781;font-size:0.85em'>{article['source']} · {article['published']}</span>",
                unsafe_allow_html=True)
if not shown:
    st.caption("No headlines for the selected signals.")
st.caption("Signals are keyword-tagged headlines - treat them as leads to investigate, not forecasts.")
