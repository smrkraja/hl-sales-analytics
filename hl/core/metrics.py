"""Pure pandas metrics over product-level loan aggregates and loan records."""
import pandas as pd

from hl.config import PRODUCTS


def product_mix(frame: pd.DataFrame, group_cols: list[str]) -> pd.DataFrame:
    """Loans, volume and share-of-loans per product within each group.

    `frame` needs columns: *group_cols, product, loans, volume.
    """
    mix = frame.groupby([*group_cols, "product"], as_index=False)[["loans", "volume"]].sum()
    totals = mix.groupby(group_cols)["loans"].transform("sum") if group_cols else mix["loans"].sum()
    mix["share"] = mix["loans"] / totals
    mix["avg_loan"] = mix["volume"] / mix["loans"]
    return mix


def mix_shares(frame: pd.DataFrame) -> dict[str, float]:
    """Share of loans per product for one area, with every product present."""
    totals = frame.groupby("product")["loans"].sum()
    grand_total = totals.sum()
    return {product: float(totals.get(product, 0) / grand_total) if grand_total else 0.0 for product in PRODUCTS}


def yoy_change(frame: pd.DataFrame, year: int) -> dict[str, float | None]:
    """Year-over-year change in loan count per product (None when last year had no loans)."""
    by_year = frame.groupby(["year", "product"])["loans"].sum()
    changes: dict[str, float | None] = {}
    for product in PRODUCTS:
        current = by_year.get((year, product), 0)
        previous = by_year.get((year - 1, product), 0)
        changes[product] = (current - previous) / previous if previous else None
    return changes


def loans_to_aggregate(loans: pd.DataFrame, group_cols: list[str]) -> pd.DataFrame:
    """Collapse loan records into the same shape as the HMDA aggregates."""
    return (loans.groupby([*group_cols, "product"], as_index=False)
            .agg(loans=("loan_id", "count"), volume=("loan_amount", "sum")))


def city_profile(loans: pd.DataFrame) -> pd.DataFrame:
    """Borrower/property context per city - used to explain product mix differences."""
    return loans.groupby("city").agg(
        loans=("loan_id", "count"),
        median_income_k=("income_k", "median"),
        median_property_value=("property_value", "median"),
        median_rate=("interest_rate", "median"),
        investor_share=("occupancy", lambda values: (values == "Investment").mean()),
        heloc_share=("open_end", "mean"),
    ).reset_index()


def attach_city(loans: pd.DataFrame, tract_city: pd.DataFrame) -> pd.DataFrame:
    merged = loans.merge(tract_city[["tract", "city"]], on="tract", how="left")
    merged["city"] = merged["city"].fillna("Unknown tract")
    return merged
