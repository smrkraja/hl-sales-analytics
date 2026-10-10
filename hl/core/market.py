"""Buyer's vs seller's market classification from Redfin supply/demand signals."""
import pandas as pd

# Standard industry rule of thumb (NAR): under ~4 months of supply favors sellers,
# over ~6 favors buyers. Sale-to-list breaks ties inside the balanced band.
SELLER_MAX_SUPPLY = 4.0
BUYER_MIN_SUPPLY = 6.0
HOT_SALE_TO_LIST = 1.0
SOFT_SALE_TO_LIST = 0.96


def classify_regime(months_of_supply: float | None, sale_to_list: float | None) -> str | None:
    if months_of_supply is None or pd.isna(months_of_supply):
        return None
    if months_of_supply < SELLER_MAX_SUPPLY:
        return "Seller's market"
    if months_of_supply > BUYER_MIN_SUPPLY:
        return "Buyer's market"
    if sale_to_list is not None and not pd.isna(sale_to_list):
        if sale_to_list >= HOT_SALE_TO_LIST:
            return "Seller's market"
        if sale_to_list <= SOFT_SALE_TO_LIST:
            return "Buyer's market"
    return "Balanced"


def with_regime(market: pd.DataFrame) -> pd.DataFrame:
    market = market.copy()
    market["regime"] = [classify_regime(supply, ratio)
                        for supply, ratio in zip(market["months_of_supply"], market["sale_to_list"])]
    return market


def regime_shift(series: pd.DataFrame, lookback_months: int = 12) -> dict | None:
    """Compare the latest regime with the one ~lookback_months earlier for a single region."""
    series = with_regime(series.dropna(subset=["months_of_supply"])).sort_values("period_end")
    if series.empty:
        return None
    latest = series.iloc[-1]
    cutoff = latest["period_end"] - pd.DateOffset(months=lookback_months)
    earlier = series[series["period_end"] <= cutoff]
    previous = earlier.iloc[-1] if not earlier.empty else series.iloc[0]
    return {
        "current": latest["regime"],
        "previous": previous["regime"],
        "changed": latest["regime"] != previous["regime"],
        "months_of_supply": float(latest["months_of_supply"]),
        "months_of_supply_prev": float(previous["months_of_supply"]),
        "sale_to_list": float(latest["sale_to_list"]) if pd.notna(latest["sale_to_list"]) else None,
        "median_sale_price_yoy": float(latest["median_sale_price_yoy"]) if pd.notna(latest["median_sale_price_yoy"]) else None,
        "inventory_yoy": float(latest["inventory_yoy"]) if pd.notna(latest["inventory_yoy"]) else None,
        "as_of": latest["period_end"],
    }


def rate_context(rates: pd.DataFrame) -> dict:
    """Latest 30y rate and its change over the past year."""
    rates = rates.sort_values("date")
    latest = rates.iloc[-1]
    year_ago = rates[rates["date"] <= latest["date"] - pd.DateOffset(years=1)]
    previous = year_ago.iloc[-1] if not year_ago.empty else rates.iloc[0]
    return {
        "rate": float(latest["rate_30y"]),
        "rate_year_ago": float(previous["rate_30y"]),
        "change": float(latest["rate_30y"] - previous["rate_30y"]),
        "as_of": latest["date"],
    }
