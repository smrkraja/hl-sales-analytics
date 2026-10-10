"""HMDA (CFPB) loan data: state/county aggregates and on-demand loan-level detail.

Only originated loans (action_taken=1) count as "sales". Aggregates come from the
Data Browser aggregation API (one call per geography per year, cached on disk so
reruns are cheap). Loan-level rows come from the county CSV export.
"""
import io
import json
from concurrent.futures import ThreadPoolExecutor, as_completed

import pandas as pd

from hl.config import DATA_DIR, HMDA_API, LOANS_DIR, PURPOSE_TO_PRODUCT, RAW_DIR, STATES
from hl.etl.http import get_with_retry

PURPOSE_CODES = ",".join(str(code) for code in PURPOSE_TO_PRODUCT)
LOAN_COLUMNS = {
    "activity_year": "year",
    "lei": "lender_lei",
    "derived_msa-md": "metro_code",
    "census_tract": "tract",
    "county_code": "county_fips",
    "loan_purpose": "loan_purpose",
    "open-end_line_of_credit": "open_end",
    "loan_amount": "loan_amount",
    "interest_rate": "interest_rate",
    "property_value": "property_value",
    "loan_to_value_ratio": "ltv",
    "income": "income_k",
    "debt_to_income_ratio": "dti",
    "loan_term": "loan_term_months",
    "occupancy_type": "occupancy",
    "derived_loan_product_type": "loan_type",
    "lien_status": "lien",
    "tract_to_msa_income_percentage": "tract_income_pct",
    "tract_minority_population_percent": "tract_minority_pct",
}
OCCUPANCY = {1: "Primary residence", 2: "Second home", 3: "Investment"}


def _aggregate(geo_param: str, geo_value: str, year: int) -> list[dict]:
    cache_file = RAW_DIR / "hmda_agg" / str(year) / f"{geo_param}_{geo_value}.json"
    if cache_file.exists():
        return json.loads(cache_file.read_text())
    params = {"years": year, geo_param: geo_value, "actions_taken": 1, "loan_purposes": PURPOSE_CODES}
    rows = get_with_retry(f"{HMDA_API}/aggregations", params).json()["aggregations"]
    cache_file.parent.mkdir(parents=True, exist_ok=True)
    cache_file.write_text(json.dumps(rows))
    return rows


def to_product_rows(raw_rows: list[dict], **keys) -> list[dict]:
    """Map API rows (one per loan_purpose) to product rows; Home Equity merges two purposes."""
    totals: dict[str, dict] = {}
    for row in raw_rows:
        product = PURPOSE_TO_PRODUCT.get(int(row["loan_purposes"]))
        if product is None:
            continue
        bucket = totals.setdefault(product, {"loans": 0, "volume": 0.0})
        bucket["loans"] += int(row["count"])
        bucket["volume"] += float(row["sum"])
    return [{**keys, "product": product, **values} for product, values in totals.items()]


def _collect(jobs: list[tuple[str, str, int, dict]], label: str) -> pd.DataFrame:
    records: list[dict] = []
    failures = 0
    # Modest concurrency: the API is public and shared, and results are cached.
    with ThreadPoolExecutor(max_workers=6) as pool:
        futures = {pool.submit(_aggregate, param, value, year): keys for param, value, year, keys in jobs}
        for done_count, future in enumerate(as_completed(futures), start=1):
            try:
                records.extend(to_product_rows(future.result(), **futures[future]))
            except Exception as error:  # one bad geography shouldn't sink the whole load
                failures += 1
                print(f"  {label}: skipped {futures[future]} ({error})")
            if done_count % 500 == 0:
                print(f"  {label}: {done_count}/{len(jobs)}")
    if failures:
        print(f"  {label}: {failures} failures - rerun to retry (successes are cached)")
    return pd.DataFrame.from_records(records)


def build_state_aggregates(years: list[int], states: list[str]) -> pd.DataFrame:
    jobs = [("states", abbr, year, {"state": abbr, "year": year}) for year in years for abbr in states]
    return _collect(jobs, "state aggregates")


def build_county_aggregates(years: list[int], counties: pd.DataFrame) -> pd.DataFrame:
    jobs = [("counties", fips, year, {"county_fips": fips, "year": year})
            for year in years for fips in counties["county_fips"]]
    return _collect(jobs, "county aggregates")


def clean_loans(raw: pd.DataFrame) -> pd.DataFrame:
    loans = raw[list(LOAN_COLUMNS)].rename(columns=LOAN_COLUMNS)
    loans["tract"] = loans["tract"].astype("string").str.zfill(11)
    loans["county_fips"] = loans["county_fips"].astype("string").str.zfill(5)
    loans["loan_purpose"] = pd.to_numeric(loans["loan_purpose"], errors="coerce")
    loans["product"] = loans["loan_purpose"].map(PURPOSE_TO_PRODUCT)
    loans = loans[loans["product"].notna()].copy()
    # HMDA uses "Exempt"/"NA" strings in numeric columns; treat them as missing.
    numeric_columns = ["loan_amount", "interest_rate", "property_value", "ltv", "income_k", "loan_term_months",
                       "lien", "tract_income_pct", "tract_minority_pct"]
    for column in numeric_columns:
        loans[column] = pd.to_numeric(loans[column], errors="coerce")
    loans["open_end"] = pd.to_numeric(loans["open_end"], errors="coerce").eq(1)
    loans["occupancy"] = pd.to_numeric(loans["occupancy"], errors="coerce").map(OCCUPANCY)
    loans["metro_code"] = loans["metro_code"].astype("string")
    loans["year"] = pd.to_numeric(loans["year"]).astype(int)
    loans["loan_id"] = loans["county_fips"] + "-" + loans["year"].astype(str) + "-" + pd.RangeIndex(len(loans)).astype(str)
    return loans.reset_index(drop=True)


def fetch_county_loans(county_fips: str, year: int) -> pd.DataFrame:
    """Loan-level originations for one county-year, cached as parquet."""
    cache_file = LOANS_DIR / str(year) / f"{county_fips}.parquet"
    if cache_file.exists():
        return pd.read_parquet(cache_file)
    params = {"years": year, "counties": county_fips, "actions_taken": 1}
    response = get_with_retry(f"{HMDA_API}/csv", params, timeout=300)
    loans = clean_loans(pd.read_csv(io.BytesIO(response.content), dtype=str, low_memory=False))
    cache_file.parent.mkdir(parents=True, exist_ok=True)
    loans.to_parquet(cache_file, index=False)
    return loans


def fetch_lenders(years: list[int]) -> pd.DataFrame:
    """LEI -> institution name for every HMDA filer in the given years."""
    frames = []
    for year in years:
        institutions = get_with_retry(f"{HMDA_API}/filers", {"years": year}).json()["institutions"]
        frames.append(pd.DataFrame(institutions)[["lei", "name"]])
    return pd.concat(frames).drop_duplicates("lei", keep="last").rename(columns={"lei": "lender_lei", "name": "lender"})


def run(years: list[int], states: list[str], include_counties: bool = True) -> None:
    print("hmda: lender names")
    fetch_lenders(years).to_parquet(DATA_DIR / "lenders.parquet", index=False)
    # State totals are cheap (~150 calls), so always load all of them; `states` only limits the
    # slow per-county step. Keeps the national overview complete on a quick partial load.
    print(f"hmda: state aggregates for {len(ALL_STATE_ABBRS)} states x {len(years)} years")
    build_state_aggregates(years, ALL_STATE_ABBRS).to_parquet(DATA_DIR / "state_products.parquet", index=False)
    if include_counties:
        counties = pd.read_parquet(DATA_DIR / "counties.parquet")
        counties = counties[counties["state"].isin(states)]
        print(f"hmda: county aggregates for {len(counties)} counties x {len(years)} years")
        build_county_aggregates(years, counties).to_parquet(DATA_DIR / "county_products.parquet", index=False)


ALL_STATE_ABBRS = list(STATES.values())
