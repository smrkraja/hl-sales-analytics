import pandas as pd
import pytest

from hl.core import insights, territory


def make_loans(rows):
    columns = ["lender_lei", "product", "loan_amount", "interest_rate", "lien", "open_end",
               "loan_term_months", "tract_income_pct", "tract_minority_pct"]
    loans = pd.DataFrame(rows, columns=columns)
    loans["loan_id"] = [f"L{index}" for index in range(len(loans))]
    return loans


def test_market_share_ranks_by_loan_count_and_names_lenders():
    loans = make_loans([
        ("A", "Purchase", 100, 7, 1, False, 360, 90, 20),
        ("B", "Purchase", 900, 7, 1, False, 360, 90, 20),
        ("B", "Purchase", 900, 7, 1, False, 360, 90, 20),
    ])
    table = territory.market_share(loans, pd.DataFrame({"lender_lei": ["B"], "lender": ["Big Bank"]}))
    assert table["lender"].tolist() == ["Big Bank", "A"]  # unnamed LEI falls back to the code
    assert table["share"].tolist() == pytest.approx([2 / 3, 1 / 3])
    assert table["rank"].tolist() == [1, 2]


def test_bank_position_reports_missing_products_as_zero_share():
    loans = make_loans([
        ("A", "Purchase", 100, 7, 1, False, 360, 90, 20),
        ("B", "Refinance", 100, 7, 1, False, 360, 90, 20),
    ])
    positions = territory.bank_position(loans, "A").set_index("product")
    assert positions.loc["All products", "share"] == 0.5
    assert positions.loc["Purchase", "rank"] == 1
    assert positions.loc["Refinance", "share"] == 0.0 and pd.isna(positions.loc["Refinance", "rank"])


def test_monthly_payment_matches_standard_formula():
    # $300k, 6%, 30 years -> $1,798.65
    assert float(territory.monthly_payment(300_000, 6.0, 360)) == pytest.approx(1798.65, abs=0.01)


def test_refi_pool_applies_incentive_and_excludes_ineligible_loans():
    loans = make_loans([
        ("A", "Purchase", 400_000, 7.80, 1, False, 360, 90, 20),   # 0.8 above 7.0 -> in
        ("A", "Purchase", 400_000, 7.50, 1, False, 360, 90, 20),   # only 0.5 above -> out
        ("A", "Home Equity", 50_000, 9.00, 2, True, 360, 90, 20),  # HELOC / 2nd lien -> out
        ("A", "Refinance", 200_000, 8.50, 1, False, 120, 90, 20),  # short term -> out
        ("A", "Cash-out Refi", 300_000, None, 1, False, 360, 90, 20),  # no rate -> out
    ])
    pool = territory.refi_pool(loans, market_rate=7.0)
    assert len(pool) == 1
    assert pool["monthly_savings"].iloc[0] > 0
    assert pool["rate_gap"].iloc[0] == pytest.approx(0.8)


def test_fair_lending_coverage_flags_bank_below_peers():
    loans = make_loans(
        [("BANK", "Purchase", 1, 7, 1, False, 360, 120, 10)] * 9      # bank: 10% in LMI/minority tracts
        + [("BANK", "Purchase", 1, 7, 1, False, 360, 60, 70)]
        + [("PEER", "Purchase", 1, 7, 1, False, 360, 60, 70)] * 4     # peers: 40%
        + [("PEER", "Purchase", 1, 7, 1, False, 360, 120, 10)] * 6
    )
    coverage = territory.fair_lending_coverage(loans, "BANK").set_index("segment")
    assert coverage.loc["LMI tracts", "bank_share"] == pytest.approx(0.1)
    assert coverage.loc["LMI tracts", "peer_share"] == pytest.approx(0.4)
    assert bool(coverage.loc["LMI tracts", "needs_review"]) is True
    finding = insights.fair_lending_insight("Bank", coverage.reset_index().to_dict("records"))
    assert finding.kind == "watch" and "Compliance" in finding.action


def test_fair_lending_coverage_without_bank_reports_market_only():
    loans = make_loans([("A", "Purchase", 1, 7, 1, False, 360, 60, 70)])
    coverage = territory.fair_lending_coverage(loans, None)
    assert coverage["bank_share"].isna().all() and not coverage["needs_review"].any()


def test_share_gap_insight_picks_weakest_product():
    positions = [
        {"product": "All products", "share": 0.04, "rank": 5, "lenders": 300, "leader_share": 0.1, "market_loans": 10000},
        {"product": "Purchase", "share": 0.05, "rank": 4, "lenders": 250, "leader_share": 0.1, "market_loans": 7000},
        {"product": "Home Equity", "share": 0.01, "rank": 40, "lenders": 120, "leader_share": 0.2, "market_loans": 900},
    ]
    finding = insights.share_gap_insight("Our Bank", positions)
    assert finding.product == "Home Equity" and finding.action


def test_every_mix_insight_carries_an_action():
    area = {"Purchase": 0.40, "Refinance": 0.25, "Cash-out Refi": 0.20, "Home Equity": 0.15}
    bench = {"Purchase": 0.57, "Refinance": 0.09, "Cash-out Refi": 0.15, "Home Equity": 0.19}
    found = insights.mix_insights("X", area, "Y", bench, {})
    assert found and all(item.action for item in found)
