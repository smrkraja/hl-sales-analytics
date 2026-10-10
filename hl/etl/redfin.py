"""Redfin Data Center market tracker: supply/demand signals per state, county, city."""
import pandas as pd

from hl.config import DATA_DIR, RAW_DIR
from hl.etl.http import get_with_retry

TRACKER_URL = "https://redfin-public-data.s3.us-west-2.amazonaws.com/redfin_market_tracker/{level}_market_tracker.tsv000.gz"
START_DATE = "2021-01-01"
COLUMNS = {
    "PERIOD_END": "period_end",
    "PERIOD_DURATION": "period_days",
    "REGION": "region",
    "STATE_CODE": "state",
    "PROPERTY_TYPE": "property_type",
    "IS_SEASONALLY_ADJUSTED": "seasonally_adjusted",
    "MEDIAN_SALE_PRICE": "median_sale_price",
    "MEDIAN_SALE_PRICE_YOY": "median_sale_price_yoy",
    "HOMES_SOLD": "homes_sold",
    "HOMES_SOLD_YOY": "homes_sold_yoy",
    "NEW_LISTINGS": "new_listings",
    "INVENTORY": "inventory",
    "INVENTORY_YOY": "inventory_yoy",
    "MONTHS_OF_SUPPLY": "months_of_supply",
    "MEDIAN_DOM": "median_dom",
    "AVG_SALE_TO_LIST": "sale_to_list",
    "SOLD_ABOVE_LIST": "sold_above_list",
    "PRICE_DROPS": "price_drops",
}


def _download(level: str) -> str:
    target = RAW_DIR / f"redfin_{level}.tsv.gz"
    if not target.exists():
        target.parent.mkdir(parents=True, exist_ok=True)
        response = get_with_retry(TRACKER_URL.format(level=level), timeout=900, stream=True)
        with open(target, "wb") as handle:
            for chunk in response.iter_content(chunk_size=1 << 20):
                handle.write(chunk)
    return str(target)


def load_tracker(level: str) -> pd.DataFrame:
    """Read the tracker in chunks, keeping only all-residential, non-adjusted, recent rows."""
    kept = []
    reader = pd.read_csv(_download(level), sep="\t", compression="gzip", usecols=list(COLUMNS),
                         chunksize=500_000, low_memory=False)
    for chunk in reader:
        chunk = chunk.rename(columns=COLUMNS)
        mask = (
            (chunk["property_type"] == "All Residential")
            & (chunk["seasonally_adjusted"].astype(str).str.lower() == "false")
            & (chunk["period_end"] >= START_DATE)
        )
        kept.append(chunk[mask])
    tracker = pd.concat(kept, ignore_index=True).drop(columns=["property_type", "seasonally_adjusted"])
    tracker["period_end"] = pd.to_datetime(tracker["period_end"])
    # County/city files are 90-day rolling windows; state files also carry monthly.
    # Keep the shortest window available so every level is a consistent series.
    shortest = tracker["period_days"].min()
    tracker = tracker[tracker["period_days"] == shortest].drop(columns="period_days")
    return tracker.sort_values(["region", "period_end"]).reset_index(drop=True)


def attach_county_fips(tracker: pd.DataFrame, counties: pd.DataFrame) -> pd.DataFrame:
    """Redfin labels counties as 'Travis County, TX'; join to FIPS via name + state."""
    lookup = counties.assign(region=counties["county_name"] + ", " + counties["state"])[["region", "county_fips"]]
    return tracker.merge(lookup, on="region", how="inner")


def run(include_city: bool = False) -> None:
    print("redfin: state market tracker")
    load_tracker("state").to_parquet(DATA_DIR / "market_state.parquet", index=False)
    print("redfin: county market tracker (~240 MB download)")
    counties = pd.read_parquet(DATA_DIR / "counties.parquet")
    attach_county_fips(load_tracker("county"), counties).to_parquet(DATA_DIR / "market_county.parquet", index=False)
    if include_city:
        print("redfin: city market tracker (~1 GB download)")
        city = load_tracker("city")
        city["city"] = city["region"].str.rsplit(",", n=1).str[0].str.strip()
        city.to_parquet(DATA_DIR / "market_city.parquet", index=False)
