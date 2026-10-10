import pandas as pd
import pytest

from hl.core import insights, market, metrics, news
from hl.etl import geo, hmda


def make_aggregate(rows):
    return pd.DataFrame(rows, columns=["area", "year", "product", "loans", "volume"])


# --- metrics -----------------------------------------------------------------

def test_mix_shares_fills_missing_products_with_zero():
    frame = make_aggregate([("A", 2024, "Purchase", 75, 1.0), ("A", 2024, "Refinance", 25, 1.0)])
    shares = metrics.mix_shares(frame)
    assert shares == {"Purchase": 0.75, "Refinance": 0.25, "Cash-out Refi": 0.0, "Home Equity": 0.0}


def test_yoy_change_handles_missing_prior_year():
    frame = make_aggregate([
        ("A", 2023, "Purchase", 100, 1.0), ("A", 2024, "Purchase", 130, 1.0),
        ("A", 2024, "Refinance", 10, 1.0),
    ])
    changes = metrics.yoy_change(frame, 2024)
    assert changes["Purchase"] == pytest.approx(0.30)
    assert changes["Refinance"] is None


def test_product_mix_shares_sum_to_one_per_group():
    frame = make_aggregate([
        ("A", 2024, "Purchase", 60, 6.0), ("A", 2024, "Refinance", 40, 4.0),
        ("B", 2024, "Purchase", 10, 1.0),
    ])
    mix = metrics.product_mix(frame, ["area"])
    assert mix.groupby("area")["share"].sum().tolist() == pytest.approx([1.0, 1.0])
    assert mix.loc[mix["product"] == "Purchase", "avg_loan"].iloc[0] == pytest.approx(0.1)


# --- market ------------------------------------------------------------------

@pytest.mark.parametrize("supply, ratio, expected", [
    (2.5, 0.99, "Seller's market"),
    (7.0, 1.01, "Buyer's market"),
    (5.0, 1.01, "Seller's market"),
    (5.0, 0.95, "Buyer's market"),
    (5.0, 0.98, "Balanced"),
    (None, 1.0, None),
])
def test_classify_regime(supply, ratio, expected):
    assert market.classify_regime(supply, ratio) == expected


def test_regime_shift_detects_change_over_a_year():
    series = pd.DataFrame({
        "period_end": pd.to_datetime(["2025-01-31", "2025-06-30", "2026-01-31"]),
        "months_of_supply": [3.0, 5.0, 7.0],
        "sale_to_list": [1.01, 0.98, 0.96],
        "median_sale_price_yoy": [0.05, 0.0, -0.03],
        "inventory_yoy": [0.1, 0.2, 0.3],
    })
    shift = market.regime_shift(series)
    assert shift["previous"] == "Seller's market"
    assert shift["current"] == "Buyer's market"
    assert shift["changed"] is True


# --- news --------------------------------------------------------------------

@pytest.mark.parametrize("title, expected", [
    ("Oracle moves headquarters to Nashville", "Inflow"),
    ("Samsung to hire 2,000 at new Taylor plant", "Inflow"),
    ("Blue Origin Announces Massive Hutto Expansion, More Than 2,000 New Jobs", "Inflow"),
    ("Tesla Austin expansion rolls on with new Mustang Ridge distribution center", "Inflow"),
    ("NHL exploring Texas expansion opportunities in Houston, Austin", "Other"),
    ("Texas secures 650 acres for future state park expansion", "Other"),
    ("City of Austin Announces 2026 Fair Chance Hiring Job and Resource Fair", "Other"),
    ("Tesla announces layoffs at Austin gigafactory", "Outflow"),
    ("Plant closing will cut 400 jobs", "Outflow"),
    ("Austin home prices fall for third month", "Housing"),
    ("Local team wins championship", "Other"),
])
def test_classify_headline(title, expected):
    assert news.classify_headline(title) == expected


# --- insights ----------------------------------------------------------------

def test_mix_insights_flags_large_gaps_with_drivers():
    area = {"Purchase": 0.70, "Refinance": 0.10, "Cash-out Refi": 0.10, "Home Equity": 0.10}
    bench = {"Purchase": 0.55, "Refinance": 0.12, "Cash-out Refi": 0.13, "Home Equity": 0.20}
    context = {
        "regime": {"current": "Seller's market", "months_of_supply": 2.5, "median_sale_price_yoy": 0.02},
        "rates": {"rate": 6.8, "change": 0.1},
        "news": {"Inflow": 3, "Outflow": 0},
    }
    found = insights.mix_insights("Austin", area, "Texas", bench, context)
    by_product = {item.product: item for item in found}
    assert set(by_product) == {"Purchase", "Home Equity"}  # refi/cash-out gaps are under 5 pts
    assert by_product["Purchase"].kind == "opportunity"
    assert any("Seller's market" in driver for driver in by_product["Purchase"].drivers)
    assert any("headlines" in driver for driver in by_product["Purchase"].drivers)
    assert by_product["Home Equity"].kind == "watch"


def test_rate_insight_points_to_refi_when_rates_fall():
    result = insights.rate_insight({"rate": 5.9, "rate_year_ago": 6.9, "change": -1.0})
    assert result.product == "Refinance" and result.kind == "opportunity"


def test_compare_cities_names_leader_and_laggard():
    shares = {
        "Austin": {"Purchase": 0.65, "Refinance": 0.10, "Cash-out Refi": 0.12, "Home Equity": 0.13},
        "Houston": {"Purchase": 0.50, "Refinance": 0.20, "Cash-out Refi": 0.15, "Home Equity": 0.15},
    }
    profiles = {
        "Austin": {"investor_share": 0.12, "median_income_k": 150, "median_property_value": 550000},
        "Houston": {"investor_share": 0.08, "median_income_k": 100, "median_property_value": 300000},
    }
    found = {item.product: item for item in insights.compare_cities(shares, profiles)}
    assert found["Purchase"].area == "Austin vs Houston"
    assert found["Refinance"].area == "Houston vs Austin"
    assert any("investor" in driver for driver in found["Purchase"].drivers)


def test_regime_insight_reports_flip():
    shift = {"current": "Buyer's market", "previous": "Seller's market", "changed": True,
             "months_of_supply": 6.5, "months_of_supply_prev": 3.0}
    result = insights.regime_insight("Travis County", shift)
    assert result.kind == "watch" and "moved from" in result.title


def test_regime_insight_treats_hairline_flip_as_context():
    shift = {"current": "Balanced", "previous": "Seller's market", "changed": True,
             "months_of_supply": 4.0, "months_of_supply_prev": 3.9}
    result = insights.regime_insight("Harris County", shift)
    assert result.kind == "info" and "edged" in result.title


# --- etl helpers -------------------------------------------------------------

def test_to_product_rows_merges_home_equity_purposes():
    raw = [
        {"loan_purposes": "1", "count": 10, "sum": 100.0},
        {"loan_purposes": "2", "count": 3, "sum": 30.0},
        {"loan_purposes": "4", "count": 2, "sum": 20.0},
    ]
    rows = {row["product"]: row for row in hmda.to_product_rows(raw, state="TX", year=2024)}
    assert rows["Home Equity"]["loans"] == 5 and rows["Home Equity"]["volume"] == 50.0
    assert rows["Purchase"]["state"] == "TX"


def test_assign_tracts_uses_block_majority():
    blocks = pd.DataFrame({
        "BLOCKID": ["480010001001000", "480010001001001", "480010001001002",
                    "480010002001000", "480010002001001", "480010002001002"],
        "PLACEFP": ["05000", "05000", None, "05000", None, None],
    })
    result = geo.assign_tracts_to_places(blocks).set_index("tract")["place_fp"]
    assert result["48001000100"] == "05000"
    assert pd.isna(result["48001000200"])  # only 1 of 3 blocks in a city -> unincorporated


@pytest.mark.parametrize("raw, expected", [
    ("Austin city", "Austin"),
    ("Wells Branch CDP", "Wells Branch"),
    ("Nashville-Davidson metropolitan government (balance)", "Nashville-Davidson"),
])
def test_clean_place_name(raw, expected):
    assert geo.clean_place_name(raw) == expected


def test_texas_home_equity_gap_cites_state_law():
    area = {"Purchase": 0.73, "Refinance": 0.08, "Cash-out Refi": 0.10, "Home Equity": 0.09}
    bench = {"Purchase": 0.57, "Refinance": 0.09, "Cash-out Refi": 0.15, "Home Equity": 0.19}
    found = {item.product: item for item in insights.mix_insights("TX", area, "United States", bench, {"state": "TX"})}
    assert any("50(a)(6)" in driver for driver in found["Home Equity"].drivers)


def test_compare_cities_uses_relative_gap_for_small_products():
    shares = {
        "Austin": {"Purchase": 0.715, "Refinance": 0.071, "Cash-out Refi": 0.111, "Home Equity": 0.103},
        "Houston": {"Purchase": 0.746, "Refinance": 0.075, "Cash-out Refi": 0.087, "Home Equity": 0.092},
    }
    found = {item.product for item in insights.compare_cities(shares, {})}
    assert found == {"Cash-out Refi"}  # purchase gap is only 4% relative; home equity is 1.1 pts


def test_clean_loans_types_year_and_flags():
    raw = pd.DataFrame([{
        "activity_year": "2024", "lei": "X", "derived_msa-md": "12420", "census_tract": "48453000100",
        "county_code": "48453", "loan_purpose": "1", "open-end_line_of_credit": "2", "loan_amount": "305000",
        "interest_rate": "Exempt", "property_value": "400000", "loan_to_value_ratio": "76", "income": "120",
        "debt_to_income_ratio": "36%-<40%", "loan_term": "360", "occupancy_type": "1",
        "derived_loan_product_type": "Conventional:First Lien", "lien_status": "1",
        "tract_to_msa_income_percentage": "75", "tract_minority_population_percent": "55.2",
    }])
    loans = hmda.clean_loans(raw)
    assert loans["year"].iloc[0] == 2024 and loans["product"].iloc[0] == "Purchase"
    assert pd.isna(loans["interest_rate"].iloc[0]) and loans["open_end"].iloc[0] == False  # noqa: E712
    assert loans["tract_income_pct"].iloc[0] == 75
