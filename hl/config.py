"""Shared paths, constants and product definitions."""
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
RAW_DIR = DATA_DIR / "raw"
# Per-county loan-level parquet, fetched on demand. Bump the version when the
# kept columns change so stale caches are re-downloaded instead of misread.
LOANS_DIR = DATA_DIR / "loans" / "v2"
NEWS_CACHE_DIR = DATA_DIR / "news_cache"

HMDA_YEARS = [2022, 2023, 2024]
LATEST_YEAR = HMDA_YEARS[-1]
# Vintages scanned for refinance opportunities - the high-rate years.
REFI_VINTAGES = [2023, 2024]
HMDA_API = "https://ffiec.cfpb.gov/v2/data-browser-api/view"

# HMDA loan_purpose codes -> dashboard product. HMDA has no "HELOC" purpose;
# HELOCs are mostly reported as home improvement (2) or other (4), so those
# roll up into Home Equity. Loan-level views also show the open-end flag.
PURPOSE_TO_PRODUCT = {
    1: "Purchase",
    31: "Refinance",
    32: "Cash-out Refi",
    2: "Home Equity",
    4: "Home Equity",
}
PRODUCTS = ["Purchase", "Refinance", "Cash-out Refi", "Home Equity"]

# Validated categorical palette (dataviz reference instance), fixed order so a
# product keeps its color no matter which subset is shown.
PRODUCT_COLORS = {
    "Purchase": "#2a78d6",
    "Refinance": "#eb6834",
    "Cash-out Refi": "#1baf7a",
    "Home Equity": "#eda100",
}
SEQUENTIAL_BLUE = ["#cde2fb", "#9ec5f4", "#6da7ec", "#3987e5", "#256abf", "#184f95", "#0d366b"]

# Status palette - reserved for market regime; always paired with a text label.
REGIME_COLORS = {
    "Seller's market": "#d03b3b",
    "Balanced": "#fab219",
    "Buyer's market": "#0ca30c",
}

STATES = {
    "01": "AL", "02": "AK", "04": "AZ", "05": "AR", "06": "CA", "08": "CO", "09": "CT",
    "10": "DE", "11": "DC", "12": "FL", "13": "GA", "15": "HI", "16": "ID", "17": "IL",
    "18": "IN", "19": "IA", "20": "KS", "21": "KY", "22": "LA", "23": "ME", "24": "MD",
    "25": "MA", "26": "MI", "27": "MN", "28": "MS", "29": "MO", "30": "MT", "31": "NE",
    "32": "NV", "33": "NH", "34": "NJ", "35": "NM", "36": "NY", "37": "NC", "38": "ND",
    "39": "OH", "40": "OK", "41": "OR", "42": "PA", "44": "RI", "45": "SC", "46": "SD",
    "47": "TN", "48": "TX", "49": "UT", "50": "VT", "51": "VA", "53": "WA", "54": "WV",
    "55": "WI", "56": "WY",
}

# Loan-level detail preloaded so the drill-down works offline out of the box.
# Covers the PRD's examples (Austin, Houston) plus other large metros.
SAMPLE_COUNTIES = [
    "48453",  # Travis, TX (Austin)
    "48491",  # Williamson, TX (Austin suburbs)
    "48209",  # Hays, TX (Austin metro)
    "48021",  # Bastrop, TX (Austin metro)
    "48055",  # Caldwell, TX (Austin metro)
    "48201",  # Harris, TX (Houston)
    "48113",  # Dallas, TX
    "04013",  # Maricopa, AZ (Phoenix)
    "12086",  # Miami-Dade, FL
    "37119",  # Mecklenburg, NC (Charlotte)
    "47037",  # Davidson, TN (Nashville)
]

DEFAULT_METRO = "12420"  # Austin-Round Rock-San Marcos, TX
