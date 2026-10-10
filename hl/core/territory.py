"""Territory analytics on loan-level HMDA records: lender market share, the
refinance in-the-money pool, and fair-lending coverage checks."""
import numpy as np
import pandas as pd

from hl.config import PRODUCTS

# Industry rule of thumb: a refinance pays off once the borrower can cut their
# rate by roughly 0.75 points (closing costs recovered in ~2-3 years).
REFI_INCENTIVE = 0.75
REFI_PRODUCTS = ["Purchase", "Refinance", "Cash-out Refi"]
MIN_REFI_TERM_MONTHS = 180  # skip short balloon/bridge loans

# FFIEC definitions: low/moderate income tract = median family income below 80%
# of the metro median; majority-minority = minority population above 50%.
LMI_INCOME_PCT = 80
MAJORITY_MINORITY_PCT = 50
# Screening heuristic (not a regulatory bright line): a lender whose share of
# loans in a protected segment is under 80% of its peers' warrants review.
PEER_RATIO_REVIEW = 0.8


def market_share(loans: pd.DataFrame, lenders: pd.DataFrame | None = None) -> pd.DataFrame:
    """Lender league table: loans, volume, shares and rank (by loan count)."""
    table = (loans.groupby("lender_lei", as_index=False)
             .agg(loans=("loan_id", "count"), volume=("loan_amount", "sum")))
    table["share"] = table["loans"] / table["loans"].sum()
    table["volume_share"] = table["volume"] / table["volume"].sum()
    table = table.sort_values(["loans", "volume"], ascending=False).reset_index(drop=True)
    table["rank"] = table.index + 1
    if lenders is not None:
        table = table.merge(lenders, on="lender_lei", how="left")
        table["lender"] = table["lender"].fillna(table["lender_lei"])
    else:
        table["lender"] = table["lender_lei"]
    return table


def bank_position(loans: pd.DataFrame, lender_lei: str) -> pd.DataFrame:
    """The bank's rank and share overall and per product, against the market leader."""
    rows = []
    for product in ["All products", *PRODUCTS]:
        subset = loans if product == "All products" else loans[loans["product"] == product]
        if subset.empty:
            continue
        table = market_share(subset)
        mine = table[table["lender_lei"] == lender_lei]
        rows.append({
            "product": product,
            "rank": int(mine["rank"].iloc[0]) if not mine.empty else None,
            "lenders": len(table),
            "loans": int(mine["loans"].iloc[0]) if not mine.empty else 0,
            "share": float(mine["share"].iloc[0]) if not mine.empty else 0.0,
            "leader_share": float(table["share"].iloc[0]),
            "market_loans": int(table["loans"].sum()),
        })
    return pd.DataFrame(rows)


def monthly_payment(principal, annual_rate_pct, months):
    """Standard amortizing payment; vectorised over pandas/numpy inputs."""
    monthly_rate = np.asarray(annual_rate_pct, dtype=float) / 100 / 12
    principal = np.asarray(principal, dtype=float)
    months = np.asarray(months, dtype=float)
    with np.errstate(divide="ignore", invalid="ignore"):
        payment = principal * monthly_rate / (1 - (1 + monthly_rate) ** -months)
    return np.where(monthly_rate == 0, principal / months, payment)


def refi_pool(loans: pd.DataFrame, market_rate: float, incentive: float = REFI_INCENTIVE) -> pd.DataFrame:
    """First-lien, closed-end loans whose note rate beats the market by `incentive`.

    Savings use the original amount and term - a slight overstatement for loans that
    have amortized, and the pool is an upper bound since HMDA doesn't track payoffs.
    """
    eligible = loans[
        loans["product"].isin(REFI_PRODUCTS)
        & (loans["lien"] == 1)
        & ~loans["open_end"]
        & loans["interest_rate"].notna()
        & (loans["loan_term_months"] >= MIN_REFI_TERM_MONTHS)
        & (loans["interest_rate"] >= market_rate + incentive)
    ].copy()
    current_payment = monthly_payment(eligible["loan_amount"], eligible["interest_rate"], eligible["loan_term_months"])
    new_payment = monthly_payment(eligible["loan_amount"], market_rate, eligible["loan_term_months"])
    eligible["monthly_savings"] = current_payment - new_payment
    eligible["rate_gap"] = eligible["interest_rate"] - market_rate
    return eligible.sort_values("monthly_savings", ascending=False)


def tract_segments(loans: pd.DataFrame) -> pd.DataFrame:
    """Boolean segment flags used for fair-lending coverage."""
    return pd.DataFrame({
        "LMI tracts": loans["tract_income_pct"] < LMI_INCOME_PCT,
        "Majority-minority tracts": loans["tract_minority_pct"] > MAJORITY_MINORITY_PCT,
    }, index=loans.index)


def fair_lending_coverage(loans: pd.DataFrame, lender_lei: str | None) -> pd.DataFrame:
    """Share of loans in LMI / majority-minority tracts: the bank vs all other lenders.

    This mirrors the peer comparison examiners use in redlining reviews. It flags a
    gap for review; it is not a legal conclusion.
    """
    segments = tract_segments(loans)
    is_bank = loans["lender_lei"] == lender_lei if lender_lei else pd.Series(False, index=loans.index)
    rows = []
    for segment in segments.columns:
        in_segment = segments[segment]
        market_share_in_segment = float(in_segment.mean())
        peer_share = float(in_segment[~is_bank].mean()) if (~is_bank).any() else None
        bank_share = float(in_segment[is_bank].mean()) if is_bank.any() else None
        ratio = bank_share / peer_share if bank_share is not None and peer_share else None
        rows.append({
            "segment": segment,
            "market_share": market_share_in_segment,
            "peer_share": peer_share,
            "bank_share": bank_share,
            "bank_to_peer": ratio,
            "needs_review": ratio is not None and ratio < PEER_RATIO_REVIEW,
        })
    return pd.DataFrame(rows)
