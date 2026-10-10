# Home Lending Sales Analytics

Streamlit dashboard for home lending advisers: where purchase, refinance, cash-out and home equity loans are sold, why the mix differs between places, and which market shifts (buyer/seller market, employers moving in or out) to act on. Requirements: [hl-dashboard-prd.md](hl-dashboard-prd.md).

## Quick start

```bash
uv venv .venv --python 3.12 && uv pip install --python .venv/bin/python -r requirements.txt
.venv/bin/python -m hl.etl.run          # first load ~20-40 min; reruns use cached downloads
.venv/bin/streamlit run app/Home.py
```

Optional: copy `.env.example` to `.env` and set `ANTHROPIC_API_KEY` to enable the Claude-written adviser briefing on the Insights page.

## Pages

| Page | What it answers |
|---|---|
| National overview | Volumes, product mix by state, choropleth map, mortgage-rate trend |
| Drill-down | State → county → city → individual (anonymized) loan records, with insights at each level |
| Compare cities | Product mix, volume and borrower profile side by side, plus why they differ |
| Market & news | Buyer's/seller's market from months of supply, price trend, tagged employer news |
| Insights | Rule-based signals across a state's largest counties, plus an optional AI briefing |

## Data sources (all public, no keys)

| Source | Used for |
|---|---|
| [CFPB HMDA](https://ffiec.cfpb.gov/data-browser/) 2022-2024 | Originated loans by product, state, county, census tract |
| [Census 2020 block assignment files](https://www.census.gov/geographies/reference-files/time-series/geo/block-assignment-files.html) | Census tract → city (majority of blocks) |
| [Redfin Data Center](https://www.redfin.com/news/data-center/) | Months of supply, sale-to-list, prices → market regime |
| [FRED MORTGAGE30US](https://fred.stlouisfed.org/series/MORTGAGE30US) | 30-year rate context for refi/HELOC economics |
| Google News RSS, GDELT | City headlines, keyword-tagged Inflow / Outflow / Housing |

## Known limits

- **No homeowner names or addresses.** HMDA is anonymized; the deepest level is the individual loan record (tract, amount, rate, income, property value, lender). Plug the bank's own CRM in at `hl/etl/hmda.py::fetch_county_loans` for borrower-level detail.
- **Home Equity** = HMDA purposes "home improvement" + "other", where most HELOCs are reported. Loan records also carry the open-end (HELOC) flag.
- HMDA lags about a year (2024 is the latest full year). Redfin county data is a rolling 90-day window.
- News signals are keyword-based leads, not forecasts. GDELT throttles heavily, so Google News is the main source.

## Layout

```
hl/etl/    download + clean: geo.py, hmda.py, redfin.py, fred.py, run.py
hl/core/   metrics.py, market.py (regime), insights.py (rules), news.py, narrative.py (Claude)
app/       Home.py (navigation), common.py (cached loaders, chart helpers), views/*.py
tests/     pytest unit tests for metrics, regime, news tagging, insight rules, ETL helpers
```

Run tests with `.venv/bin/python -m pytest`.
