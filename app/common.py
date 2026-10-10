"""Cached data access and shared chart helpers for the Streamlit pages."""
import json
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from hl.config import (DATA_DIR, LATEST_YEAR, PRODUCT_COLORS, PRODUCTS,  # noqa: E402
                       REGIME_COLORS, SEQUENTIAL_BLUE)
from hl.core import metrics  # noqa: E402
from hl.core.insights import Insight  # noqa: E402
from hl.etl import hmda  # noqa: E402

REQUIRED_FILES = ["counties.parquet", "tract_city.parquet", "state_products.parquet"]


def require_data() -> None:
    missing = [name for name in REQUIRED_FILES if not (DATA_DIR / name).exists()]
    if missing:
        st.error(f"Data not loaded yet (missing {', '.join(missing)}). Run `python -m hl.etl.run` first.")
        st.stop()


def _read_optional(name: str) -> pd.DataFrame | None:
    path = DATA_DIR / name
    return pd.read_parquet(path) if path.exists() else None


@st.cache_data(show_spinner=False)
def counties() -> pd.DataFrame:
    return pd.read_parquet(DATA_DIR / "counties.parquet")


@st.cache_data(show_spinner=False)
def tract_city() -> pd.DataFrame:
    return pd.read_parquet(DATA_DIR / "tract_city.parquet")


@st.cache_data(show_spinner=False)
def state_products() -> pd.DataFrame:
    return pd.read_parquet(DATA_DIR / "state_products.parquet")


@st.cache_data(show_spinner=False)
def county_products() -> pd.DataFrame | None:
    frame = _read_optional("county_products.parquet")
    return frame.merge(counties(), on="county_fips", how="left") if frame is not None else None


@st.cache_data(show_spinner=False)
def market_state() -> pd.DataFrame | None:
    return _read_optional("market_state.parquet")


@st.cache_data(show_spinner=False)
def market_county() -> pd.DataFrame | None:
    return _read_optional("market_county.parquet")


@st.cache_data(show_spinner=False)
def market_city() -> pd.DataFrame | None:
    return _read_optional("market_city.parquet")


@st.cache_data(show_spinner=False)
def mortgage_rates() -> pd.DataFrame | None:
    return _read_optional("mortgage_rates.parquet")


@st.cache_data(show_spinner=False)
def county_geojson() -> dict | None:
    path = DATA_DIR / "counties.geojson"
    return json.loads(path.read_text()) if path.exists() else None


@st.cache_data(show_spinner=False)
def county_loans(county_fips: str, year: int = LATEST_YEAR) -> pd.DataFrame:
    """Loan-level rows with city attached; downloads from HMDA on first use."""
    loans = hmda.fetch_county_loans(county_fips, year)
    loans["year"] = loans["year"].astype(int)
    return metrics.attach_city(loans, tract_city())


@st.cache_data(show_spinner=False)
def metros() -> pd.DataFrame | None:
    return _read_optional("metros.parquet")


@st.cache_data(show_spinner=False)
def lenders() -> pd.DataFrame | None:
    return _read_optional("lenders.parquet")


@st.cache_data(show_spinner=False)
def territory_loans(county_fips_list: tuple[str, ...], years: tuple[int, ...]) -> pd.DataFrame:
    """Loan records for every county-year in a territory, downloaded in parallel on first use."""
    jobs = [(fips, year) for year in years for fips in county_fips_list]
    with ThreadPoolExecutor(max_workers=4) as pool:
        frames = list(pool.map(lambda job: hmda.fetch_county_loans(*job), jobs))
    loans = pd.concat(frames, ignore_index=True)
    loans["year"] = loans["year"].astype(int)  # caches written before the int fix store text
    return metrics.attach_city(loans, tract_city())


def data_as_of() -> str:
    """One-line freshness stamp so advisers know how current each source is."""
    parts = [f"HMDA loans: {LATEST_YEAR} (published annually, ~1 year lag)"]
    county_market = market_county()
    if county_market is not None:
        parts.append(f"Redfin market: {county_market['period_end'].max():%b %Y}")
    rates = mortgage_rates()
    if rates is not None:
        parts.append(f"30y rate: {rates['date'].max():%b %d, %Y}")
    return " · ".join(parts)


def load_county_loans_with_feedback(county_fips: str, county_label: str) -> pd.DataFrame | None:
    try:
        with st.spinner(f"Loading loan-level HMDA records for {county_label} (first time only)..."):
            return county_loans(county_fips)
    except Exception as error:
        st.warning(f"Could not download loan records for {county_label}: {error}")
        return None


def county_label(county_fips: str) -> str:
    row = counties().set_index("county_fips").loc[county_fips]
    return f"{row['county_name']}, {row['state']}"


# --- formatting --------------------------------------------------------------

def money(value: float) -> str:
    for threshold, suffix in [(1e12, "T"), (1e9, "B"), (1e6, "M"), (1e3, "K")]:
        if abs(value) >= threshold:
            return f"${value / threshold:,.1f}{suffix}"
    return f"${value:,.0f}"


def number(value: float) -> str:
    return f"{value:,.0f}"


def delta_pct(change: float | None) -> str | None:
    return None if change is None else f"{change * 100:+.1f}% YoY"


# --- charts ------------------------------------------------------------------

def style(figure: go.Figure, height: int = 380) -> go.Figure:
    has_title = bool(figure.layout.title.text)
    has_legend = len(figure.data) > 1 and figure.layout.showlegend is not False
    top_margin = (56 if has_title else 8) + (48 if has_legend else 0)
    figure.update_layout(
        height=height, margin=dict(l=8, r=8, t=top_margin, b=8),
        # Title pinned to the top of the canvas, legend in its own row beneath it.
        title=dict(yref="container", y=0.98, yanchor="top", x=0, xanchor="left", pad=dict(l=4)),
        legend=dict(orientation="h", yanchor="bottom", y=1.01, xanchor="left", x=0, title=None),
        font=dict(family="system-ui, -apple-system, Segoe UI, sans-serif"),
        bargap=0.25,
    )
    figure.update_xaxes(showgrid=False)
    figure.update_yaxes(gridcolor="rgba(137,135,129,0.25)", zeroline=False)
    return figure


def mix_bar(mix: pd.DataFrame, category: str, value: str = "share", title: str = "",
            orientation: str = "h", height: int | None = None) -> go.Figure:
    """Stacked product-mix bars; colors are fixed per product, never by rank."""
    is_share = value == "share"
    axis = dict(x=value, y=category) if orientation == "h" else dict(x=category, y=value)
    figure = px.bar(
        mix, **axis, color="product", orientation=orientation, title=title,
        category_orders={"product": PRODUCTS}, color_discrete_map=PRODUCT_COLORS,
        custom_data=["product", "loans", "volume", "share"],
    )
    figure.update_traces(
        marker_line_width=1, marker_line_color="rgba(252,252,251,0.9)",  # 2px surface gap between fills
        hovertemplate="<b>%{customdata[0]}</b><br>Loans: %{customdata[1]:,}<br>"
                      "Volume: $%{customdata[2]:,.0f}<br>Share: %{customdata[3]:.1%}<extra></extra>",
    )
    value_axis = dict(tickformat=".0%" if is_share else "~s", title=None)
    if orientation == "h":
        figure.update_xaxes(**value_axis)
        figure.update_yaxes(title=None)
    else:
        figure.update_yaxes(**value_axis)
        figure.update_xaxes(title=None)
    rows = mix[category].nunique()
    return style(figure, height or max(260, 32 * rows + 90))


# Cities use palette slots 5-8 so they never borrow a product's color.
# Slot 5 (magenta) is low-contrast on light backgrounds, so bars carry direct labels.
CITY_COLORS = ["#e87ba4", "#008300", "#4a3aa7", "#e34948"]


def grouped_product_bar(mix: pd.DataFrame, category: str, value: str, title: str) -> go.Figure:
    is_share = value == "share"
    if not is_share:
        # Plotly's SI format prints billions as "G"; plot in $ millions instead.
        mix = mix.assign(**{value: mix[value] / 1e6})
    figure = px.bar(mix, x="product", y=value, color=category, barmode="group", title=title,
                    category_orders={"product": PRODUCTS}, color_discrete_sequence=CITY_COLORS,
                    text=value)
    figure.update_traces(texttemplate="%{text:.0%}" if is_share else "$%{text:,.0f}M", textposition="outside",
                         cliponaxis=False)
    figure.update_yaxes(title=None, **({"tickformat": ".0%"} if is_share else {"tickprefix": "$", "ticksuffix": "M"}))
    figure.update_xaxes(title=None)
    return style(figure)


def choropleth_sequential(**kwargs) -> go.Figure:
    figure = px.choropleth(color_continuous_scale=SEQUENTIAL_BLUE, **kwargs)
    figure.update_layout(coloraxis_colorbar=dict(title=None, thickness=12))
    figure.update_geos(bgcolor="rgba(0,0,0,0)", lakecolor="rgba(0,0,0,0)", showlakes=False)
    return style(figure, 460)


def regime_badge(regime: str | None) -> str:
    if not regime:
        return "Market regime: n/a"
    icon = {"Seller's market": "▲", "Buyer's market": "▼", "Balanced": "◆"}[regime]
    color = REGIME_COLORS[regime]
    return f"<span style='color:{color};font-weight:600'>{icon}</span> **{regime}**"


KIND_ICONS = {"opportunity": "🟢", "watch": "🟠", "info": "🔵"}
KIND_LABELS = {"opportunity": "Opportunity", "watch": "Watch", "info": "Context"}


def render_insights(items: list[Insight], empty_message: str = "No notable signals for this selection.") -> None:
    if not items:
        st.caption(empty_message)
        return
    for item in items:
        with st.container(border=True):
            st.markdown(f"{KIND_ICONS[item.kind]} **{KIND_LABELS[item.kind]}** · {item.area}")
            st.markdown(f"**{item.title}**")
            st.write(item.detail)
            if item.drivers:
                st.markdown("**Why:**\n" + "\n".join(f"- {driver}" for driver in item.drivers))
            if item.action:
                st.markdown(f"👉 **What to do:** {item.action}")


def data_footnote() -> None:
    st.caption(
        "Sources: CFPB HMDA originations (action_taken=1); Census 2020 block assignment files for tract→city; "
        "Redfin Data Center market tracker; FRED MORTGAGE30US; Google News / GDELT headlines. "
        "Home Equity = HMDA loan purposes 'home improvement' + 'other', where most HELOCs are reported. "
        "Loan records are anonymized - HMDA publishes no borrower names or addresses."
    )
