# Home Lending Sales Analytics

Streamlit dashboard for home lending advisers: where purchase, refinance, cash-out and home equity loans are sold, why the mix differs between places, and which market shifts (buyer/seller market, employers moving in or out) to act on. Requirements: [hl-dashboard-prd.md](hl-dashboard-prd.md).

## Quick start

Requires Python 3.12 and about 1 GB of free disk for downloaded data.

```bash
git clone https://github.com/smrkraja/hl-sales-analytics.git && cd hl-sales-analytics

# 1. Environment (uv shown; plain `python3.12 -m venv .venv && .venv/bin/pip install -r requirements.txt` also works)
uv venv .venv --python 3.12 && uv pip install --python .venv/bin/python -r requirements.txt

# 2. Local settings: try it without SSO (shows a DEV MODE badge in the banner)
cp .env.example .env && echo "HL_ALLOW_ANONYMOUS=1" >> .env

# 3. Load public data into ./data
.venv/bin/python -m hl.etl.run --states TX   # quick trial, ~2-5 min: all states + Texas counties + sample metros
# .venv/bin/python -m hl.etl.run             # full US load, ~20-40 min (reruns reuse cached downloads)

# 4. Run - opens on http://localhost:8599
.venv/bin/streamlit run app/Home.py
```

Check the install with `.venv/bin/python -m pytest` (no network or data needed).

Optional `.env` settings (see `.env.example`): `ANTHROPIC_API_KEY` enables the Claude-written adviser briefing on the Insights page; `HL_STUB_LOCATION="San Francisco, CA, US"` previews the landmark banner.

## Sign-in

Every page sits behind company SSO (Streamlit's built-in OIDC: Microsoft Entra ID, Okta or Google). Copy `.streamlit/secrets.toml.example` to `.streamlit/secrets.toml` (gitignored), register a web app with your identity provider using the redirect URI `http://localhost:8599/oauth2callback`, and fill in the client ID/secret.

- **Fails closed:** with no `[auth]` section the dashboard stays locked. For local development only, set `HL_ALLOW_ANONYMOUS=1` in `.env`; the banner then shows a DEV MODE badge.
- **Banner** (every page): signed-in user's name, email and initials, a **Log out** button, and "Signed in from <city>" with the sign-in time in the user's timezone.
- **Location** comes from the visitor's IP (the `X-Forwarded-For` header when behind a proxy) via ipapi.co, with ipwho.is as a fallback. Private/local IPs are never sent out and show as "Local network". It's approximate and for display only, never for access control.

## Pages

| Page | What it answers |
|---|---|
| **My territory** (landing) | Pick a metro and your bank: this week's actions (each with a "What to do"), lender market share and rank, refi in-the-money pool with rate scenarios, fair-lending peer screen, county table. The URL keeps your selection (`?metro=12420&bank=<LEI>`) so it can be bookmarked or shared |
| National overview | Volumes, product mix by state, choropleth map, mortgage-rate trend |
| Deep Insights | Breadcrumb drill path United States › state › county › city › loan records (anonymized), with insights at each level; click any step to go back up |
| Compare cities | Product mix, volume and borrower profile side by side, plus why they differ |
| Market & news | Buyer's/seller's market from months of supply, price trend, tagged employer news |
| Insights | Rule-based signals across a state's largest counties, plus an optional AI briefing |

## Data sources (all public, no keys)

| Source | Used for |
|---|---|
| [CFPB HMDA](https://ffiec.cfpb.gov/data-browser/) 2022-2024 | Originated loans by product, state, county, census tract |
| [Census 2020 block assignment files](https://www.census.gov/geographies/reference-files/time-series/geo/block-assignment-files.html) | Census tract → city (majority of blocks) |
| [Redfin Data Center](https://www.redfin.com/news/data-center/) | Months of supply, sale-to-list, prices → market regime |
| [OMB metro delineation](https://data.nber.org/cbsa-csa-fips-county-crosswalk/) (NBER CSV) | County → metro area, matching HMDA's metro code |
| HMDA filer list | Lender names for market share |
| [FRED MORTGAGE30US](https://fred.stlouisfed.org/series/MORTGAGE30US) | 30-year rate context for refi/HELOC economics |
| Google News RSS, GDELT | City headlines, keyword-tagged Inflow / Outflow / Housing |

## Known limits

- **No homeowner names or addresses.** HMDA is anonymized; the deepest level is the individual loan record (tract, amount, rate, income, property value, lender). Plug the bank's own CRM in at `hl/etl/hmda.py::fetch_county_loans` for borrower-level detail.
- **Home Equity** = HMDA purposes "home improvement" + "other", where most HELOCs are reported. Loan records also carry the open-end (HELOC) flag.
- **Refi pool is an upper bound**: HMDA records originations but not payoffs, so some in-the-money loans have already refinanced. Savings use the original amount and term. "In the money" = note rate at least 0.75 pts above the scenario rate.
- **Fair-lending screen** compares a lender's share of loans in LMI and majority-minority tracts with its peers (the examiner-style peer comparison). A ratio below 0.8 flags a review; it is a screening signal, not a legal finding. Race, ethnicity and sex fields are never loaded.
- HMDA lags about a year (2024 is the latest full year). Redfin county data is a rolling 90-day window.
- News signals are keyword-based leads, not forecasts. GDELT throttles heavily, so Google News is the main source.

## Layout

```
hl/etl/    download + clean: geo.py, hmda.py, redfin.py, fred.py, run.py
hl/core/   metrics.py, market.py (regime), insights.py (rules + actions), territory.py (market share,
           refi pool, fair lending), news.py, narrative.py (Claude)
app/       Home.py (navigation), common.py (cached loaders, chart helpers), views/*.py
tests/     pytest unit tests for metrics, regime, news tagging, insight rules, ETL helpers
```

Run tests with `.venv/bin/python -m pytest`.
