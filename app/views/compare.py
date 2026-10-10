import pandas as pd
import streamlit as st

import common
from hl.config import SAMPLE_COUNTIES
from hl.core import insights, market, metrics, news

common.require_data()
st.title("Compare cities")
st.caption("Which products lead in which city - and what explains the difference.")

all_counties = common.counties().assign(label=lambda frame: frame["county_name"] + ", " + frame["state"])
labels = all_counties.set_index("county_fips")["label"]
chosen_counties = st.multiselect(
    "Counties to pull cities from (loan data downloads on first use)",
    all_counties["county_fips"].tolist(), default=["48453", "48491", "48201"],
    format_func=labels.get, key="cmp_counties",
)
if not chosen_counties:
    st.stop()

frames = []
for fips in chosen_counties:
    loans = common.load_county_loans_with_feedback(fips, labels[fips])
    if loans is not None:
        frames.append(loans.assign(state=labels[fips].rsplit(", ", 1)[1], county_fips=fips))
if not frames:
    st.stop()
loans = pd.concat(frames, ignore_index=True)
# A city can span counties (Austin: Travis + Williamson) - aggregate by city + state.
loans["city"] = loans["city"] + ", " + loans["state"]

city_counts = loans["city"].value_counts()
defaults = [name for name in ["Austin, TX", "Houston, TX"] if name in city_counts.index] or city_counts.index[:2].tolist()
cities = st.multiselect("Cities (up to 4)", city_counts.index.tolist(), default=defaults, max_selections=4,
                        format_func=lambda name: f"{name} ({city_counts[name]:,} loans)", key="cmp_cities")
if len(cities) < 2:
    st.info("Pick at least two cities.")
    st.stop()

selected = loans[loans["city"].isin(cities)]
mix = metrics.product_mix(metrics.loans_to_aggregate(selected, ["city"]), ["city"])
# Fixed city order keeps each city's color stable as the selection changes.
mix["city"] = pd.Categorical(mix["city"], categories=cities, ordered=True)
mix = mix.sort_values("city")

left, right = st.columns(2)
left.plotly_chart(common.grouped_product_bar(mix, "city", "share", "Share of each city's loans"),
                  width="stretch")
right.plotly_chart(common.grouped_product_bar(mix, "city", "volume", "Dollar volume by product ($ millions)"),
                   width="stretch")

st.subheader("Borrower and property profile")
profile = metrics.city_profile(selected).set_index("city").loc[cities].reset_index()
st.dataframe(profile, width="stretch", hide_index=True, column_config={
    "median_income_k": st.column_config.NumberColumn("Median income ($k)", format="%.0f"),
    "median_property_value": st.column_config.NumberColumn("Median property value", format="$%.0f"),
    "median_rate": st.column_config.NumberColumn("Median rate", format="%.2f%%"),
    "investor_share": st.column_config.NumberColumn("Investor share", format="percent"),
    "heloc_share": st.column_config.NumberColumn("Open-end (HELOC) share", format="percent"),
})

# Market regime per city (Redfin city tracker if loaded, otherwise the city's main county)
st.subheader("Market regime")
city_market, county_market = common.market_city(), common.market_county()
regime_columns = st.columns(len(cities))
regimes = {}
for column, name in zip(regime_columns, cities):
    city_name, state = name.rsplit(", ", 1)
    shift = None
    if city_market is not None:
        shift = market.regime_shift(city_market[(city_market["city"] == city_name) & (city_market["state"] == state)])
    if shift is None and county_market is not None:
        main_county = selected[selected["city"] == name]["county_fips"].mode().iloc[0]
        shift = market.regime_shift(county_market[county_market["county_fips"] == main_county])
    regimes[name] = shift
    with column:
        st.markdown(f"**{name}**")
        st.markdown(common.regime_badge(shift and shift["current"]), unsafe_allow_html=True)
        if shift:
            caption = f"{shift['months_of_supply']:.1f} months of supply"
            if shift["sale_to_list"]:
                caption += f" · sale-to-list {shift['sale_to_list']:.1%}"
            st.caption(caption)

st.subheader("Why the mix differs")
shares = {name: metrics.mix_shares(metrics.loans_to_aggregate(selected[selected["city"] == name], [])) for name in cities}
profiles = profile.set_index("city").to_dict("index")
found = insights.compare_cities(shares, profiles)

include_news = st.toggle("Add market-news signals (fetches live headlines)", value=False, key="cmp_news")
if include_news:
    for name in cities:
        city_name, state = name.rsplit(", ", 1)
        with st.spinner(f"Fetching news for {name}..."):
            result = news.fetch_city_news(city_name, state)
        counts = news.signal_counts(result["articles"])
        samples = {signal: [a["title"] for a in result["articles"] if a["signal"] == signal] for signal in counts}
        found += insights.news_insight(name, counts, samples)
common.render_insights(found, "Product mix is similar across these cities - no gap of 2+ pts that is also 15%+ in relative terms.")

common.data_footnote()
