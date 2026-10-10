import pandas as pd
import plotly.express as px
import streamlit as st

import common
from hl.config import HMDA_YEARS, LATEST_YEAR, PRODUCTS
from hl.core import insights, market, metrics

common.require_data()
st.title("Drill-down: state → county → city → loan")

states = common.state_products()
county_agg = common.county_products()
rates = common.mortgage_rates()
rate_ctx = market.rate_context(rates) if rates is not None else None

# --- selection ---------------------------------------------------------------
with st.sidebar:
    st.header("Drill path")
    state = st.selectbox("State", sorted(states["state"].unique()), key="dd_state",
                         index=sorted(states["state"].unique()).index("TX") if "TX" in set(states["state"]) else 0)
    state_counties = common.counties()[common.counties()["state"] == state].sort_values("county_name")
    county_options = ["All counties"] + state_counties["county_fips"].tolist()
    county_fips = st.selectbox("County", county_options, key="dd_county",
                               format_func=lambda fips: fips if fips == "All counties"
                               else state_counties.set_index("county_fips").loc[fips, "county_name"])
    county_fips = None if county_fips == "All counties" else county_fips

    city = None
    loans = None
    if county_fips:
        loans = common.load_county_loans_with_feedback(county_fips, common.county_label(county_fips))
        if loans is not None:
            city_counts = loans["city"].value_counts()
            city = st.selectbox("City", ["All cities"] + city_counts.index.tolist(), key="dd_city",
                                format_func=lambda name: name if name == "All cities" else f"{name} ({city_counts[name]:,})")
            city = None if city == "All cities" else city
    st.caption(f"Loan-level detail uses HMDA {LATEST_YEAR}.")

crumbs = ["United States", state]
if county_fips:
    crumbs.append(common.county_label(county_fips).split(",")[0])
if city:
    crumbs.append(city)
st.markdown(" › ".join(f"**{crumb}**" if index == len(crumbs) - 1 else crumb for index, crumb in enumerate(crumbs)))

national_shares = metrics.mix_shares(states[states["year"] == LATEST_YEAR])
state_rows = states[states["state"] == state]
state_shares = metrics.mix_shares(state_rows[state_rows["year"] == LATEST_YEAR])


def kpi_row(frame: pd.DataFrame, has_years: bool = True) -> None:
    current = frame[frame["year"] == LATEST_YEAR] if has_years else frame
    columns = st.columns(4)
    loans_now, volume_now = current["loans"].sum(), current["volume"].sum()
    loans_delta = volume_delta = None
    if has_years:
        prior = frame[frame["year"] == LATEST_YEAR - 1]
        if prior["loans"].sum():
            loans_delta = loans_now / prior["loans"].sum() - 1
            volume_delta = volume_now / prior["volume"].sum() - 1
    columns[0].metric(f"Originations {LATEST_YEAR}", common.number(loans_now), common.delta_pct(loans_delta))
    columns[1].metric("Volume", common.money(volume_now), common.delta_pct(volume_delta))
    columns[2].metric("Avg loan", common.money(volume_now / loans_now) if loans_now else "-")
    shares = metrics.mix_shares(current)
    top = max(shares, key=shares.get)
    columns[3].metric("Top product", f"{top} ({shares[top]:.0%})")


def comparison_mix(rows: dict[str, dict]) -> pd.DataFrame:
    """Build a mix frame from {area_label: shares} so areas can be stacked side by side."""
    return pd.DataFrame([{"area": label, "product": product, "share": share, "loans": 0, "volume": 0}
                         for label, shares in rows.items() for product, share in shares.items()])


def regime_for_county(fips: str) -> dict | None:
    county_market = common.market_county()
    if county_market is None:
        return None
    return market.regime_shift(county_market[county_market["county_fips"] == fips])


def regime_for_state(abbr: str) -> dict | None:
    state_market = common.market_state()
    if state_market is None:
        return None
    return market.regime_shift(state_market[state_market["state"] == abbr])


# --- STATE level ---------------------------------------------------------------
if not county_fips:
    kpi_row(state_rows)
    regime = regime_for_state(state)
    st.markdown(common.regime_badge(regime and regime["current"]), unsafe_allow_html=True)

    left, right = st.columns([2, 3])
    with left:
        st.plotly_chart(common.mix_bar(comparison_mix({state: state_shares, "United States": national_shares}),
                                       "area", title="Product mix vs national"), width="stretch")
        trend = metrics.product_mix(state_rows, ["year"])
        trend["year"] = trend["year"].astype(str)
        st.plotly_chart(common.mix_bar(trend, "year", value="loans", orientation="v",
                                       title="Originations by year", height=300), width="stretch")
    with right:
        if county_agg is None:
            st.info("County aggregates are still loading - rerun the ETL to see the county map.")
        else:
            product = st.radio("Map product", PRODUCTS, horizontal=True, key="dd_state_product")
            county_now = county_agg[(county_agg["state"] == state) & (county_agg["year"] == LATEST_YEAR)]
            county_mix = metrics.product_mix(county_now, ["county_fips", "county_name"])
            figure = common.choropleth_sequential(
                data_frame=county_mix[county_mix["product"] == product], geojson=common.county_geojson(),
                locations="county_fips", color="share", hover_name="county_name",
                hover_data={"share": ":.1%", "loans": ":,", "county_fips": False},
                title=f"{product} share of loans by county",
            )
            figure.update_geos(fitbounds="locations", visible=False)
            figure.update_layout(coloraxis_colorbar=dict(tickformat=".0%"))
            st.plotly_chart(figure, width="stretch")

    if county_agg is not None:
        st.subheader("Counties")
        table = (county_agg[(county_agg["state"] == state) & (county_agg["year"] == LATEST_YEAR)]
                 .pivot_table(index="county_name", columns="product", values="loans", aggfunc="sum", fill_value=0))
        table = table.reindex(columns=[p for p in PRODUCTS if p in table.columns])
        table["Total"] = table.sum(axis=1)
        st.dataframe(table.sort_values("Total", ascending=False), width="stretch", height=320)

    st.subheader("Insights")
    context = {"regime": regime, "rates": rate_ctx, "state": state}
    found = insights.mix_insights(state, state_shares, "United States", national_shares, context)
    found += insights.yoy_insights(state, metrics.yoy_change(state_rows, LATEST_YEAR), LATEST_YEAR)
    found += [item for item in [insights.regime_insight(state, regime)] if item]
    common.render_insights(found)

# --- COUNTY level --------------------------------------------------------------
elif not city:
    label = common.county_label(county_fips)
    county_rows = county_agg[county_agg["county_fips"] == county_fips] if county_agg is not None else None
    if county_rows is not None and not county_rows.empty:
        kpi_row(county_rows)
        county_shares = metrics.mix_shares(county_rows[county_rows["year"] == LATEST_YEAR])
    elif loans is not None:
        kpi_row(metrics.loans_to_aggregate(loans, ["year"]))
        county_shares = metrics.mix_shares(metrics.loans_to_aggregate(loans, []))
    else:
        st.stop()
    regime = regime_for_county(county_fips)
    st.markdown(common.regime_badge(regime and regime["current"]), unsafe_allow_html=True)

    left, right = st.columns([2, 3])
    with left:
        st.plotly_chart(common.mix_bar(comparison_mix({label.split(",")[0]: county_shares, state: state_shares}),
                                       "area", title="Product mix vs state"), width="stretch")
        if county_rows is not None and not county_rows.empty:
            trend = metrics.product_mix(county_rows, ["year"])
            trend["year"] = trend["year"].astype(str)
            st.plotly_chart(common.mix_bar(trend, "year", value="loans", orientation="v",
                                           title="Originations by year", height=300), width="stretch")
    with right:
        if loans is not None:
            city_mix = metrics.product_mix(metrics.loans_to_aggregate(loans, ["city"]), ["city"])
            top_cities = loans["city"].value_counts().head(15).index
            city_mix = city_mix[city_mix["city"].isin(top_cities)]
            order = (city_mix[city_mix["product"] == "Purchase"].sort_values("share")["city"].tolist())
            st.plotly_chart(common.mix_bar(city_mix, "city", title="Product mix by city (top 15 by loans)")
                            .update_yaxes(categoryorder="array", categoryarray=order), width="stretch")

    if loans is not None:
        st.subheader("Cities")
        profile = metrics.city_profile(loans).sort_values("loans", ascending=False)
        st.dataframe(profile, width="stretch", hide_index=True, height=300, column_config={
            "median_income_k": st.column_config.NumberColumn("Median income ($k)", format="%.0f"),
            "median_property_value": st.column_config.NumberColumn("Median property value", format="$%.0f"),
            "median_rate": st.column_config.NumberColumn("Median rate", format="%.2f%%"),
            "investor_share": st.column_config.NumberColumn("Investor share", format="percent"),
            "heloc_share": st.column_config.NumberColumn("Open-end (HELOC) share", format="percent"),
        })

    st.subheader("Insights")
    context = {"regime": regime, "rates": rate_ctx, "state": state}
    found = insights.mix_insights(label, county_shares, state, state_shares, context)
    if county_rows is not None and not county_rows.empty:
        found += insights.yoy_insights(label, metrics.yoy_change(county_rows, LATEST_YEAR), LATEST_YEAR)
    found += [item for item in [insights.regime_insight(label, regime)] if item]
    common.render_insights(found)

# --- CITY level ----------------------------------------------------------------
else:
    label = common.county_label(county_fips)
    city_loans = loans[loans["city"] == city]
    county_shares = metrics.mix_shares(metrics.loans_to_aggregate(loans, []))
    city_agg = metrics.loans_to_aggregate(city_loans, ["year"])
    city_shares = metrics.mix_shares(city_agg)
    kpi_row(city_agg, has_years=False)

    city_market = common.market_city()
    regime = None
    if city_market is not None:
        regime = market.regime_shift(city_market[(city_market["city"] == city) & (city_market["state"] == state)])
    regime = regime or regime_for_county(county_fips)
    st.markdown(common.regime_badge(regime and regime["current"]), unsafe_allow_html=True)

    left, right = st.columns(2)
    with left:
        st.plotly_chart(common.mix_bar(comparison_mix({city: city_shares, label.split(",")[0]: county_shares,
                                                       state: state_shares}), "area",
                                       title="Product mix vs county and state"), width="stretch")
    with right:
        amounts = px.box(city_loans, x="product", y="loan_amount", color="product", points=False,
                         category_orders={"product": PRODUCTS}, color_discrete_map=common.PRODUCT_COLORS,
                         title="Loan amount by product")
        amounts.update_yaxes(type="log", title=None, tickprefix="$")
        amounts.update_xaxes(title=None)
        amounts.update_layout(showlegend=False)
        st.plotly_chart(common.style(amounts), width="stretch")

    st.subheader("Census tracts")
    tract_mix = metrics.loans_to_aggregate(city_loans, ["tract"])
    tract_table = tract_mix.pivot_table(index="tract", columns="product", values="loans", fill_value=0)
    tract_table["Total"] = tract_table.sum(axis=1)
    st.dataframe(tract_table.sort_values("Total", ascending=False), width="stretch", height=260)

    st.subheader("Loan records")
    st.caption("Deepest level available from public data: individual anonymized HMDA originations. "
               "HMDA does not publish borrower names or street addresses.")
    chosen = st.multiselect("Products", PRODUCTS, default=PRODUCTS, key="dd_loan_products")
    records = city_loans[city_loans["product"].isin(chosen)][[
        "loan_id", "product", "tract", "loan_amount", "property_value", "interest_rate", "ltv",
        "income_k", "dti", "loan_term_months", "occupancy", "open_end", "loan_type", "lender_lei",
    ]]
    st.dataframe(records, width="stretch", hide_index=True, height=360, column_config={
        "loan_amount": st.column_config.NumberColumn("Loan amount", format="$%.0f"),
        "property_value": st.column_config.NumberColumn("Property value", format="$%.0f"),
        "interest_rate": st.column_config.NumberColumn("Rate", format="%.3f%%"),
        "income_k": st.column_config.NumberColumn("Income ($k)", format="%.0f"),
        "open_end": st.column_config.CheckboxColumn("Open-end (HELOC)"),
    })
    st.download_button("Download these records (CSV)", records.to_csv(index=False).encode(),
                       file_name=f"hmda_{city.replace(' ', '_')}_{LATEST_YEAR}.csv", mime="text/csv")

    st.subheader("Insights")
    context = {"regime": regime, "rates": rate_ctx, "state": state}
    common.render_insights(insights.mix_insights(city, city_shares, label.split(",")[0], county_shares, context))

common.data_footnote()
