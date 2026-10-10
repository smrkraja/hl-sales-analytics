"""FRED 30-year fixed mortgage rate (Freddie Mac PMMS), weekly."""
import io

import pandas as pd

from hl.config import DATA_DIR
from hl.etl.http import get_with_retry

FRED_CSV = "https://fred.stlouisfed.org/graph/fredgraph.csv?id=MORTGAGE30US"


def run() -> None:
    print("fred: 30-year mortgage rate")
    rates = pd.read_csv(io.StringIO(get_with_retry(FRED_CSV).text))
    rates.columns = ["date", "rate_30y"]
    rates["date"] = pd.to_datetime(rates["date"])
    rates["rate_30y"] = pd.to_numeric(rates["rate_30y"], errors="coerce")
    rates.dropna().to_parquet(DATA_DIR / "mortgage_rates.parquet", index=False)
