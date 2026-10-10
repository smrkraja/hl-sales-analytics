"""Census geography: county names, and census tract -> city mapping.

HMDA reports census tract but not city, so we derive city from the Census 2020
Block Assignment Files: each tract is assigned to the place (city/CDP) that
contains the most of its blocks.
"""
import io
import re
import zipfile
from concurrent.futures import ThreadPoolExecutor

import pandas as pd

from hl.config import DATA_DIR, STATES
from hl.etl.http import get_with_retry

COUNTY_URL = "https://www2.census.gov/geo/docs/reference/codes2020/national_county2020.txt"
PLACE_URL = "https://www2.census.gov/geo/docs/reference/codes2020/national_place2020.txt"
BAF_URL = "https://www2.census.gov/geo/docs/maps-data/data/baf2020/BlockAssign_ST{fips}_{abbr}.zip"
COUNTY_GEOJSON_URL = "https://raw.githubusercontent.com/plotly/datasets/master/geojson-counties-fips.json"

# A tract counts as "in" a city only if most of its blocks are; otherwise it is
# unincorporated county land and gets labeled that way.
CITY_MAJORITY_SHARE = 0.5
PLACE_SUFFIX = re.compile(
    r"\s+(city|town|village|CDP|borough|municipality|city and borough|"
    r"consolidated government.*|metropolitan government.*|unified government.*|urban county)$",
    re.IGNORECASE,
)


def clean_place_name(raw_name: str) -> str:
    """'Austin city' -> 'Austin'; 'Nashville-Davidson metropolitan government (balance)' -> 'Nashville-Davidson'."""
    name = re.sub(r"\s*\(balance\)$", "", raw_name)
    return PLACE_SUFFIX.sub("", name).strip()


def load_counties() -> pd.DataFrame:
    text = get_with_retry(COUNTY_URL).text
    counties = pd.read_csv(io.StringIO(text), sep="|", dtype=str)
    counties = counties[counties["STATEFP"].isin(STATES)]
    return pd.DataFrame({
        "county_fips": counties["STATEFP"] + counties["COUNTYFP"],
        "state": counties["STATE"],
        "county_name": counties["COUNTYNAME"],
    }).reset_index(drop=True)


def load_places() -> pd.DataFrame:
    text = get_with_retry(PLACE_URL).text
    places = pd.read_csv(io.StringIO(text), sep="|", dtype=str)
    return pd.DataFrame({
        "place_key": places["STATEFP"] + places["PLACEFP"],
        "city": places["PLACENAME"].map(clean_place_name),
    })


def assign_tracts_to_places(blocks: pd.DataFrame) -> pd.DataFrame:
    """Majority-of-blocks assignment. `blocks` has BLOCKID (15 chars) and PLACEFP (may be blank)."""
    frame = pd.DataFrame({
        "tract": blocks["BLOCKID"].str[:11],
        "place_fp": blocks["PLACEFP"].fillna("").str.strip(),
    })
    totals = frame.groupby("tract").size().rename("total_blocks")
    counts = frame[frame["place_fp"] != ""].groupby(["tract", "place_fp"]).size().rename("blocks").reset_index()
    top = counts.sort_values("blocks", ascending=False).drop_duplicates("tract")
    result = totals.reset_index().merge(top, on="tract", how="left")
    in_city = result["blocks"].fillna(0) / result["total_blocks"] >= CITY_MAJORITY_SHARE
    result["place_fp"] = result["place_fp"].where(in_city, None)
    return result[["tract", "place_fp"]]


def _state_tracts(state_fips: str, abbr: str) -> pd.DataFrame:
    payload = get_with_retry(BAF_URL.format(fips=state_fips, abbr=abbr), timeout=120).content
    with zipfile.ZipFile(io.BytesIO(payload)) as archive:
        member = next(name for name in archive.namelist() if "INCPLACE_CDP" in name)
        blocks = pd.read_csv(archive.open(member), sep="|", dtype=str)
    return assign_tracts_to_places(blocks)


def build_tract_city(counties: pd.DataFrame, places: pd.DataFrame) -> pd.DataFrame:
    with ThreadPoolExecutor(max_workers=6) as pool:
        frames = list(pool.map(lambda item: _state_tracts(*item), STATES.items()))
    tracts = pd.concat(frames, ignore_index=True)
    tracts["county_fips"] = tracts["tract"].str[:5]
    tracts["place_key"] = tracts["tract"].str[:2] + tracts["place_fp"].fillna("")
    tracts = tracts.merge(places, on="place_key", how="left").merge(counties, on="county_fips", how="left")
    unincorporated = "Unincorporated " + tracts["county_name"].fillna("")
    tracts["city"] = tracts["city"].where(tracts["place_fp"].notna(), unincorporated)
    return tracts[["tract", "county_fips", "state", "city"]]


def run() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    print("geo: counties and places")
    counties = load_counties()
    counties.to_parquet(DATA_DIR / "counties.parquet", index=False)
    places = load_places()
    print("geo: tract -> city (51 block assignment files)")
    build_tract_city(counties, places).to_parquet(DATA_DIR / "tract_city.parquet", index=False)
    print("geo: county boundaries")
    (DATA_DIR / "counties.geojson").write_bytes(get_with_retry(COUNTY_GEOJSON_URL).content)
