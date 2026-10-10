"""ETL entry point.

    python -m hl.etl.run                       # everything (first run ~20-40 min)
    python -m hl.etl.run --states TX,FL        # quicker partial load
    python -m hl.etl.run --only fred,redfin    # refresh selected sources
"""
import argparse

from hl.config import HMDA_YEARS, LATEST_YEAR, SAMPLE_COUNTIES
from hl.etl import fred, geo, hmda, redfin

STEPS = ["geo", "hmda", "redfin", "fred", "samples"]


def main() -> None:
    parser = argparse.ArgumentParser(description="Load public home lending data into ./data")
    parser.add_argument("--states", help="Comma-separated state abbreviations (default: all)")
    parser.add_argument("--years", help=f"Comma-separated HMDA years (default: {HMDA_YEARS})")
    parser.add_argument("--only", help=f"Comma-separated steps from {STEPS}")
    parser.add_argument("--skip-counties", action="store_true", help="Skip per-county HMDA aggregates")
    parser.add_argument("--city-market", action="store_true", help="Also load Redfin city tracker (~1 GB)")
    args = parser.parse_args()

    states = args.states.upper().split(",") if args.states else hmda.ALL_STATE_ABBRS
    years = [int(year) for year in args.years.split(",")] if args.years else HMDA_YEARS
    steps = args.only.split(",") if args.only else STEPS

    def load_samples() -> None:
        for county_fips in SAMPLE_COUNTIES:
            print(f"loans: {county_fips} {LATEST_YEAR}", flush=True)
            hmda.fetch_county_loans(county_fips, LATEST_YEAR)

    runners = {
        "geo": geo.run,
        "hmda": lambda: hmda.run(years, states, include_counties=not args.skip_counties),
        "redfin": lambda: redfin.run(include_city=args.city_market),
        "fred": fred.run,
        "samples": load_samples,
    }
    failed = []
    for step in STEPS:
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
