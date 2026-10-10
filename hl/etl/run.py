"""ETL entry point.

    python -m hl.etl.run                       # everything (first run ~20-40 min)
    python -m hl.etl.run --states TX,FL        # quicker partial load
    python -m hl.etl.run --only fred,redfin    # refresh selected sources
"""
import argparse

from hl.config import DATA_DIR, HMDA_YEARS, REFI_VINTAGES, SAMPLE_COUNTIES
from hl.etl import fred, geo, hmda, redfin

STEPS = ["geo", "hmda", "redfin", "fred", "samples"]
# Lightweight steps that can be refreshed on their own: --only metros,lenders
EXTRA_STEPS = ["metros", "lenders"]


def main() -> None:
    parser = argparse.ArgumentParser(description="Load public home lending data into ./data")
    parser.add_argument("--states", help="Limit county-level loads to these states, e.g. TX,FL (default: all)")
    parser.add_argument("--years", help=f"Comma-separated HMDA years (default: {HMDA_YEARS})")
    parser.add_argument("--only", help=f"Comma-separated steps from {STEPS + EXTRA_STEPS}")
    parser.add_argument("--skip-counties", action="store_true", help="Skip per-county HMDA aggregates")
    parser.add_argument("--city-market", action="store_true", help="Also load Redfin city tracker (~1 GB)")
    args = parser.parse_args()

    states = args.states.upper().split(",") if args.states else hmda.ALL_STATE_ABBRS
    years = [int(year) for year in args.years.split(",")] if args.years else HMDA_YEARS
    steps = args.only.split(",") if args.only else STEPS

    def load_samples() -> None:
        for year in REFI_VINTAGES:
            for county_fips in SAMPLE_COUNTIES:
                print(f"loans: {county_fips} {year}", flush=True)
                hmda.fetch_county_loans(county_fips, year)

    runners = {
        "geo": geo.run,
        "hmda": lambda: hmda.run(years, states, include_counties=not args.skip_counties),
        "redfin": lambda: redfin.run(include_city=args.city_market),
        "fred": fred.run,
        "samples": load_samples,
        "metros": geo.run_metros,
        "lenders": lambda: hmda.fetch_lenders(years).to_parquet(DATA_DIR / "lenders.parquet", index=False),
    }
    failed = []
    for step in STEPS + EXTRA_STEPS:
        if step not in steps:
            continue
        # Sources are independent - one outage shouldn't block the others.
        try:
            runners[step]()
        except Exception as error:
            failed.append(step)
            print(f"{step}: FAILED ({error}) - rerun with --only {step}", flush=True)
    print(f"done{' with failures: ' + ','.join(failed) if failed else ''}")


if __name__ == "__main__":
    main()
