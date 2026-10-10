import pandas as pd
import plotly.express as px
import streamlit as st

import common
from hl.config import DEFAULT_METRO, HMDA_YEARS, LATEST_YEAR, PRODUCTS, REFI_VINTAGES
from hl.core import insights, market, metrics, news, territory

common.require_data()
metros = common.metros()
if metros is None:
    st.error("Metro crosswalk missing. Run `python -m hl.etl.run --only metros,lenders`.")
    st.stop()
lender_names = common.lenders()

BANK_COLOR, PEER_COLOR = "#2a78d6", "#c3c2b7"
KIND_ORDER = {"watch": 0, "opportunity": 1, "info": 2}

# --- territory + bank selection (kept in the URL so advisers can bookmark/share) ---
metro_names = metros.drop_duplicates("metro_code").set_index("metro_code")["metro_name"].sort_values()
params = st.query_params
metro_code = params.get("metro", DEFAULT_METRO)
if metro_code not in metro_names.index:
    metro_code = DEFAULT_METRO

st.title("My territory")
pick_metro, pick_bank = st.columns([3, 2])
metro_code = pick_metro.selectbox("Metro area", metro_names.index.tolist(),
                                  index=metro_names.index.get_loc(metro_code), format_func=metro_names.get,
                                  key="t_metro")
metro_name = metro_names[metro_code]
territory_counties = tuple(sorted(metros.loc[metros["metro_code"] == metro_code, "county_fips"]))
st.caption(f"{len(territory_counties)} counties · {common.data_as_of()}")

try:
    with st.spinner(f"Loading loan records for {metro_name} (first visit downloads from HMDA)..."):
        latest = common.territory_loans(territory_counties, (LATEST_YEAR,))
except Exception as error:
    st.error(f"Could not load HMDA loan records: {error}")
    st.stop()
latest = latest[latest["metro_code"] == metro_code]  # county files can include loans outside the metro definition

lender_table = territory.market_share(latest, lender_names)
lender_labels = dict(zip(lender_table["lender_lei"], lender_table["lender"] + " (" + lender_table["loans"].map("{:,}".format) + ")"))
bank_options = ["(none)"] + lender_table["lender_lei"].tolist()
bank_param = params.get("bank", "(none)")
bank_lei = pick_bank.selectbox("Our bank", bank_options,
                               index=bank_options.index(bank_param) if bank_param in bank_options else 0,
                               format_func=lambda lei: "Not selected" if lei == "(none)" else lender_labels[lei],
                               key="t_bank", help="Pick your institution to see its share, rank and fair-lending coverage.")
bank_lei = None if bank_lei == "(none)" else bank_lei
bank_name = lender_table.set_index("lender_lei")["lender"].get(bank_lei) if bank_lei else None

st.query_params["metro"] = metro_code
if bank_lei:
    st.query_params["bank"] = bank_lei
elif "bank" in st.query_params:
    del st.query_params["bank"]

# --- shared context -------------------------------------------------------------
county_agg = common.county_products()
territory_agg = county_agg[county_agg["county_fips"].isin(territory_counties)] if county_agg is not None else None
rates = common.mortgage_rates()
rate_ctx = market.rate_context(rates) if rates is not None else None
current_rate = rate_ctx["rate"] if rate_ctx else 7.0

largest_county = latest["county_fips"].value_counts().index[0]
# Multi-state metros (e.g. New York) benchmark against the state of their largest county.
home_state = common.counties().set_index("county_fips")["state"].get(largest_county, "")
county_market = common.market_county()
regime = (market.regime_shift(county_market[county_market["county_fips"] == largest_county])
          if county_market is not None else None)

# --- KPIs --------------------------------------------------------------------
kpis = st.columns(4)
if territory_agg is not None and not territory_agg.empty:
    now = territory_agg[territory_agg["year"] == LATEST_YEAR]
    before = territory_agg[territory_agg["year"] == LATEST_YEAR - 1]
    change = now["loans"].sum() / before["loans"].sum() - 1 if before["loans"].sum() else None
    kpis[0].metric(f"Originations {LATEST_YEAR}", common.number(now["loans"].sum()), common.delta_pct(change))
    kpis[1].metric("Volume", common.money(now["volume"].sum()))
kpis[2].markdown(f"Market ({common.county_label(largest_county).split(',')[0]})")
kpis[2].markdown(common.regime_badge(regime and regime["current"]), unsafe_allow_html=True)
positions = territory.bank_position(latest, bank_lei) if bank_lei else None
if positions is not None:
    overall = positions.iloc[0]
    kpis[3].metric(f"{bank_name} share", f"{overall['share']:.1%}",
                   f"rank #{overall['rank']} of {overall['lenders']}" if overall["rank"] else "no loans", delta_color="off")
elif rate_ctx:
    kpis[3].metric("30y mortgage rate", f"{current_rate:.2f}%", f"{rate_ctx['change']:+.2f} pts YoY", delta_color="inverse")

# --- refi pool at today's rate (also feeds the action list) ---------------------
try:
    vintage_loans = common.territory_loans(territory_counties, tuple(REFI_VINTAGES))
    vintage_loans = vintage_loans[vintage_loans["metro_code"] == metro_code]
except Exception as error:
    vintage_loans = None
    st.warning(f"Refi vintages unavailable: {error}")
pool_today = territory.refi_pool(vintage_loans, current_rate) if vintage_loans is not None else None

# --- this week's actions -------------------------------------------------------
st.subheader("This week's actions")
actions: list[insights.Insight] = []
if rate_ctx:
    actions.append(insights.rate_insight(rate_ctx))
if pool_today is not None:
    actions.append(insights.refi_pool_insight(metro_name, len(pool_today), pool_today["loan_amount"].sum(),
                                              float(pool_today["monthly_savings"].median()) if len(pool_today) else 0,
                                              current_rate))
if territory_agg is not None and not territory_agg.empty:
    state_rows = common.state_products()
    state_rows = state_rows[(state_rows["state"] == home_state) & (state_rows["year"] == LATEST_YEAR)]
    context = {"regime": regime, "rates": rate_ctx, "state": home_state}
    actions += insights.mix_insights(metro_name, metrics.mix_shares(territory_agg[territory_agg["year"] == LATEST_YEAR]),
                                     home_state, metrics.mix_shares(state_rows), context)
    actions += insights.yoy_insights(metro_name, metrics.yoy_change(territory_agg, LATEST_YEAR), LATEST_YEAR)
regime_item = insights.regime_insight(common.county_label(largest_county), regime)
if regime_item:
    actions.append(regime_item)
principal_city = metro_name.split(",")[0].split("-")[0].strip()
try:
    headlines = news.fetch_city_news(principal_city, home_state)["articles"]
    samples = {signal: [a["title"] for a in headlines if a["signal"] == signal] for signal in ["Inflow", "Outflow"]}
    actions += insights.news_insight(principal_city, news.signal_counts(headlines), samples)
except Exception:
    pass  # news is a bonus signal; the action list stands without it
coverage = territory.fair_lending_coverage(latest, bank_lei)
if bank_lei:
    actions += [item for item in [insights.share_gap_insight(bank_name, positions.to_dict("records")),
                                  insights.fair_lending_insight(bank_name, coverage.to_dict("records"))] if item]
actions.sort(key=lambda item: KIND_ORDER[item.kind])
left, right = st.columns(2)
for index, item in enumerate(actions):
    with (left if index % 2 == 0 else right):
        common.render_insights([item])

# --- detail tabs ---------------------------------------------------------------
share_tab, refi_tab, fair_tab, county_tab = st.tabs(["Market share", "Refi opportunity", "Fair lending", "Counties"])

with share_tab:
    product = st.segmented_control("Product", ["All products", *PRODUCTS], default="All products",
                                   key="t_share_product") or "All products"
    subset = latest if product == "All products" else latest[latest["product"] == product]
    table = territory.market_share(subset, lender_names)
    top = table.head(15).copy()
    if bank_lei and bank_lei not in set(top["lender_lei"]) and bank_lei in set(table["lender_lei"]):
        top = pd.concat([top, table[table["lender_lei"] == bank_lei]])  # always show our bank
    top["who"] = (top["lender_lei"] == bank_lei).map({True: bank_name or "Our bank", False: "Other lenders"})
    top["label"] = "#" + top["rank"].astype(str) + " " + top["lender"].str.slice(0, 38)
    figure = px.bar(top, x="share", y="label", orientation="h", color="who", text="share",
                    color_discrete_map={bank_name or "Our bank": BANK_COLOR, "Other lenders": PEER_COLOR},
                    title=f"Top lenders by {product.lower()} loans, {metro_name} {LATEST_YEAR}",
                    custom_data=["lender", "loans", "volume"])
    figure.update_traces(texttemplate="%{text:.1%}", textposition="outside", cliponaxis=False,
                         hovertemplate="<b>%{customdata[0]}</b><br>Loans: %{customdata[1]:,}<br>"
                                       "Volume: $%{customdata[2]:,.0f}<br>Share: %{x:.1%}<extra></extra>")
    figure.update_yaxes(categoryorder="array", categoryarray=top["label"].tolist()[::-1], title=None)
    figure.update_xaxes(tickformat=".0%", title=None)
    figure.update_layout(showlegend=bool(bank_lei))
    st.plotly_chart(common.style(figure, 34 * len(top) + 140), width="stretch")
    if positions is not None:
        st.markdown(f"**{bank_name} by product**")
        st.dataframe(positions, hide_index=True, width="stretch", column_config={
            "share": st.column_config.NumberColumn("Our share", format="percent"),
            "leader_share": st.column_config.NumberColumn("Leader share", format="percent"),
            "market_loans": st.column_config.NumberColumn("Market loans", format="%d"),
        })
    with st.expander(f"Full lender table ({len(table):,} lenders)"):
        st.dataframe(table[["rank", "lender", "loans", "share", "volume", "volume_share"]], hide_index=True,
                     width="stretch", column_config={
                         "share": st.column_config.NumberColumn("Loan share", format="percent"),
                         "volume": st.column_config.NumberColumn("Volume", format="dollar"),
                         "volume_share": st.column_config.NumberColumn("Volume share", format="percent"),
                     })

with refi_tab:
    if vintage_loans is None:
        st.info("Refi vintages could not be loaded.")
    else:
        controls = st.columns([2, 2, 3])
        scenario_rate = controls[0].slider("Rate scenario (30y)", min_value=round(max(3.0, current_rate - 3), 2),
                                           max_value=round(current_rate, 2), value=round(current_rate, 2), step=0.125,
                                           format="%.3f%%", key="t_rate",
                                           help="Today's rate by default. Slide down to size the pool if rates fall.")
        vintages = controls[1].multiselect("Origination years", HMDA_YEARS, default=REFI_VINTAGES, key="t_vintages")
        audience_options = ["All lenders' loans"] + ([f"{bank_name} loans (retention)", "Other lenders' loans (acquisition)"]
                                                     if bank_lei else [])
        audience = controls[2].radio("Whose borrowers", audience_options, horizontal=True, key="t_audience")
        if set(vintages) - set(REFI_VINTAGES):
            extra = tuple(sorted(set(vintages) - set(REFI_VINTAGES)))
            with st.spinner("Loading additional vintages..."):
                more = common.territory_loans(territory_counties, extra)
            pool_source = pd.concat([vintage_loans, more[more["metro_code"] == metro_code]])
        else:
            pool_source = vintage_loans
        pool_source = pool_source[pool_source["year"].isin(vintages)]
        if audience.endswith("(retention)"):
            pool_source = pool_source[pool_source["lender_lei"] == bank_lei]
        elif audience.endswith("(acquisition)"):
            pool_source = pool_source[pool_source["lender_lei"] != bank_lei]
        pool = territory.refi_pool(pool_source, scenario_rate)

        stats = st.columns(4)
        stats[0].metric("Loans in the money", common.number(len(pool)))
        stats[1].metric("Balance", common.money(pool["loan_amount"].sum()))
        stats[2].metric("Median saving / month", common.money(pool["monthly_savings"].median()) if len(pool) else "-")
        stats[3].metric("Total saving / year", common.money(pool["monthly_savings"].sum() * 12) if len(pool) else "-")
        st.caption(f"In the money = note rate at least {territory.REFI_INCENTIVE:.2f} pts above "
                   f"{scenario_rate:.3f}% (first-lien, closed-end, 15+ year loans).")

        eligible = pool_source[pool_source["product"].isin(territory.REFI_PRODUCTS) & (pool_source["lien"] == 1)
                               & ~pool_source["open_end"] & pool_source["interest_rate"].between(2, 12)].copy()
        eligible["rate_bucket"] = (eligible["interest_rate"] * 4).round() / 4
        eligible["status"] = (eligible["interest_rate"] >= scenario_rate + territory.REFI_INCENTIVE).map(
            {True: "In the money", False: "Not yet"})
        histogram = eligible.groupby(["rate_bucket", "status"], as_index=False).size()
        figure = px.bar(histogram, x="rate_bucket", y="size", color="status",
                        color_discrete_map={"In the money": BANK_COLOR, "Not yet": PEER_COLOR},
                        title="Loans by note rate", labels={"rate_bucket": "Note rate", "size": "Loans"})
        figure.add_vline(x=scenario_rate + territory.REFI_INCENTIVE, line_dash="dot", line_color="#52514e",
                         annotation_text=f"{scenario_rate + territory.REFI_INCENTIVE:.2f}% threshold")
        figure.update_xaxes(ticksuffix="%", title=None)
        figure.update_yaxes(title=None)
        st.plotly_chart(common.style(figure, 320), width="stretch")

        if len(pool):
            by_city = (pool.groupby("city", as_index=False)
                       .agg(loans=("loan_id", "count"), balance=("loan_amount", "sum"),
                            median_saving=("monthly_savings", "median"))
                       .sort_values("loans", ascending=False))
            st.markdown("**Where they are**")
            st.dataframe(by_city, hide_index=True, width="stretch", height=260, column_config={
                "balance": st.column_config.NumberColumn("Balance", format="dollar"),
                "median_saving": st.column_config.NumberColumn("Median saving / month", format="dollar"),
            })
            outreach = pool.merge(lender_names, on="lender_lei", how="left") if lender_names is not None else pool
            columns = ["loan_id", "year", "city", "tract", "product", "loan_amount", "interest_rate", "rate_gap",
                       "monthly_savings", "loan_term_months", "lender" if "lender" in outreach else "lender_lei"]
            st.download_button("Download in-the-money list (CSV)", outreach[columns].to_csv(index=False).encode(),
                               file_name=f"refi_pool_{metro_code}_{scenario_rate:.3f}.csv", mime="text/csv")
        st.caption("Upper bound: HMDA doesn't record payoffs, so some of these loans have already refinanced or "
                   "been paid off. Records are anonymized - match to your own servicing/CRM data to contact borrowers. "
                   "Outreach should cover every eligible borrower in the territory, not selected neighbourhoods.")

with fair_tab:
    st.markdown(
        "Fair-lending laws (ECOA/Reg B, Fair Housing Act) prohibit treating neighbourhoods differently because of "
        "the race or ethnicity of their residents (**redlining**). Examiners compare a lender's share of loans in "
        "low/moderate-income (LMI) and majority-minority census tracts with its peers. This tab runs that same screen. "
        "It does **not** use race or ethnicity to target anyone."
    )
    display = coverage.copy()
    display["status"] = display.apply(
        lambda row: "⚠️ Review with Compliance" if row["needs_review"]
        else ("✅ In line with peers" if pd.notna(row["bank_to_peer"]) else "Select our bank to compare"), axis=1)
    st.dataframe(display[["segment", "market_share", "peer_share", "bank_share", "bank_to_peer", "status"]],
                 hide_index=True, width="stretch", column_config={
                     "market_share": st.column_config.NumberColumn("All lenders", format="percent"),
                     "peer_share": st.column_config.NumberColumn("Peers (excl. our bank)", format="percent"),
                     "bank_share": st.column_config.NumberColumn("Our bank", format="percent"),
                     "bank_to_peer": st.column_config.NumberColumn("Our bank ÷ peers", format="%.2f"),
                 })
    st.caption(f"Share of each group's {LATEST_YEAR} originations located in the segment. LMI = tract median family "
               f"income under {territory.LMI_INCOME_PCT}% of the metro median; majority-minority = minority "
               f"population over {territory.MAJORITY_MINORITY_PCT}%. Ratio under {territory.PEER_RATIO_REVIEW} is a "
               "screening threshold for review, not a legal finding.")
    if pool_today is not None and len(pool_today):
        pool_segments = territory.tract_segments(pool_today).mean()
        st.markdown(f"**Refi outreach list check:** {pool_segments['LMI tracts']:.0%} of today's in-the-money loans "
                    f"are in LMI tracts and {pool_segments['Majority-minority tracts']:.0%} in majority-minority "
                    "tracts. Campaigns should reach all of them - don't filter the list by neighbourhood.")
    st.markdown("**Guardrails built into this dashboard**\n"
                "- Race, ethnicity and sex fields are never loaded into targeting views.\n"
                "- Opportunity lists cover the whole territory; there is no filter by tract demographics.\n"
                "- Insight wording is generated by rules and should be reviewed by Compliance before campaigns.")

with county_tab:
    if territory_agg is None:
        st.info("County aggregates not loaded.")
    else:
        rows = []
        for fips in territory_counties:
            county_rows = territory_agg[territory_agg["county_fips"] == fips]
            if county_rows.empty:
                continue
            shares = metrics.mix_shares(county_rows[county_rows["year"] == LATEST_YEAR])
            change = metrics.yoy_change(county_rows, LATEST_YEAR)
            shift = (market.regime_shift(county_market[county_market["county_fips"] == fips])
                     if county_market is not None else None)
            current = county_rows[county_rows["year"] == LATEST_YEAR]
            rows.append({"county": common.county_label(fips), "loans": int(current["loans"].sum()),
                         "volume": current["volume"].sum(), **{f"{p} share": shares[p] for p in PRODUCTS},
                         "purchase YoY": change["Purchase"], "market": shift["current"] if shift else None})
        st.dataframe(pd.DataFrame(rows).sort_values("loans", ascending=False), hide_index=True, width="stretch",
                     column_config={
                         "volume": st.column_config.NumberColumn("Volume", format="dollar"),
                         **{f"{p} share": st.column_config.NumberColumn(f"{p} share", format="percent") for p in PRODUCTS},
                         "purchase YoY": st.column_config.NumberColumn("Purchase YoY", format="percent"),
                     })
        st.caption("Open **Deep Insights** for city- and loan-level detail in any county.")

common.data_footnote()
