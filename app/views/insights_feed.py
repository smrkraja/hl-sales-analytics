import streamlit as st

import common
from hl.config import LATEST_YEAR, PRODUCTS
from hl.core import insights, market, metrics, narrative

common.require_data()
st.title("Proactive insights")
st.caption("Rule-based signals across a state's largest counties - each one says what changed and why.")

states_frame = common.state_products()
county_agg = common.county_products()
county_market = common.market_county()
state_market = common.market_state()
rates = common.mortgage_rates()
rate_ctx = market.rate_context(rates) if rates is not None else None

state_list = sorted(states_frame["state"].unique())
left, middle, right = st.columns([1, 1, 2])
state = left.selectbox("State", state_list, index=state_list.index("TX") if "TX" in state_list else 0, key="if_state")
top_n = middle.slider("Largest counties", 5, 40, 15, key="if_topn")
kinds = right.segmented_control("Show", ["opportunity", "watch", "info"], selection_mode="multi",
                                default=["opportunity", "watch"], format_func=common.KIND_LABELS.get, key="if_kinds")
products = st.multiselect("Products", PRODUCTS, default=PRODUCTS, key="if_products")

state_rows = states_frame[states_frame["state"] == state]
state_shares = metrics.mix_shares(state_rows[state_rows["year"] == LATEST_YEAR])
national_shares = metrics.mix_shares(states_frame[states_frame["year"] == LATEST_YEAR])
state_regime = market.regime_shift(state_market[state_market["state"] == state]) if state_market is not None else None

found: list[insights.Insight] = []
if rate_ctx:
    found.append(insights.rate_insight(rate_ctx))
state_context = {"regime": state_regime, "rates": rate_ctx, "state": state}
found += insights.mix_insights(state, state_shares, "United States", national_shares, state_context)
found += [item for item in [insights.regime_insight(state, state_regime)] if item]

if county_agg is None:
    st.info("County aggregates not loaded yet - showing state-level insights only.")
else:
    in_state = county_agg[county_agg["state"] == state]
    latest = in_state[in_state["year"] == LATEST_YEAR]
    largest = latest.groupby("county_fips")["volume"].sum().nlargest(top_n).index
    for fips in largest:
        rows = in_state[in_state["county_fips"] == fips]
        label = f"{rows['county_name'].iloc[0]}, {state}"
        regime = None
        if county_market is not None:
            regime = market.regime_shift(county_market[county_market["county_fips"] == fips])
        context = {"regime": regime, "rates": rate_ctx, "state": state}
        found += insights.mix_insights(label, metrics.mix_shares(rows[rows["year"] == LATEST_YEAR]), state,
                                       state_shares, context)
        found += insights.yoy_insights(label, metrics.yoy_change(rows, LATEST_YEAR), LATEST_YEAR)
        if regime and regime["changed"]:
            found.append(insights.regime_insight(label, regime))

shown = [item for item in found
         if item.kind in (kinds or []) and (item.product is None or item.product in products)]
st.markdown(f"**{len(shown)} insights** for {state}")

if narrative.is_enabled():
    if st.button("✨ Write an adviser briefing with Claude", key="if_brief"):
        with st.spinner("Claude is writing the briefing..."):
            st.session_state["if_briefing"] = narrative.write_briefing(state, shown[:60])
    if st.session_state.get("if_briefing"):
        with st.container(border=True):
            st.markdown(st.session_state["if_briefing"])
            st.caption("AI-generated from the insights below - verify before acting.")
else:
    st.caption("Set ANTHROPIC_API_KEY in .env to enable an AI-written adviser briefing.")

common.render_insights(shown)
common.data_footnote()
