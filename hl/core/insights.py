"""Rule-based proactive insights.

Every insight is explainable: it states the observed gap and the drivers that
plausibly explain it (market regime, rates, prices, news signals, borrower
profile). Inputs are plain dicts so the rules are easy to unit test.
"""
from dataclasses import dataclass, field

from hl.config import PRODUCTS

SHARE_GAP_THRESHOLD = 0.05   # 5 percentage points of product mix is a meaningful skew
YOY_THRESHOLD = 0.15         # +/-15% year-over-year is a notable swing
RATE_MOVE_THRESHOLD = 0.5    # 50 bps over a year changes refi/HELOC economics
HIGH_RATE_LEVEL = 6.0        # above this, owners with sub-4% loans are "locked in"
NEWS_SIGNAL_MIN = 2          # need at least two headlines before calling a trend
CITY_MIN_GAP = 0.02           # city-vs-city: at least 2 pts of share...
CITY_RELATIVE_GAP = 0.15      # ...and 15% relative, so small products like refi aren't drowned out by purchase
MATERIAL_SUPPLY_MOVE = 0.5   # months of supply; smaller moves across a threshold are noise


REGIME_PHRASES = {
    "Seller's market": "a seller's market",
    "Buyer's market": "a buyer's market",
    "Balanced": "a balanced market",
}
# Texas Constitution Sec. 50(a)(6): home equity debt capped at 80% combined LTV,
# one equity loan per year - structurally suppresses HELOC/cash-out share in TX.
RESTRICTED_EQUITY_STATES = {"TX"}


@dataclass
class Insight:
    kind: str                # "opportunity" | "watch" | "info"
    area: str
    title: str
    detail: str
    product: str | None = None
    drivers: list[str] = field(default_factory=list)
    action: str | None = None  # the concrete next step for an adviser


# Next step per (product, direction) when an area's mix skews from its benchmark.
MIX_ACTIONS = {
    ("Purchase", "high"): "Prioritise purchase pre-approvals and realtor/builder partnerships here.",
    ("Purchase", "low"): "Purchase demand is soft - lean on refi and HELOC outreach to existing owners.",
    ("Refinance", "high"): "Call recent high-rate borrowers with a refinance quote (see the Refi opportunity tab).",
    ("Refinance", "low"): "Few owners benefit from refinancing now - shift effort to purchase and HELOC.",
    ("Cash-out Refi", "high"): "Offer cash-out quotes alongside a HELOC comparison so borrowers can keep their first-lien rate.",
    ("Cash-out Refi", "low"): "Position HELOCs instead - owners are reluctant to give up low first-lien rates.",
    ("Home Equity", "high"): "Lead with HELOC offers to existing owners with 20%+ equity.",
    ("Home Equity", "low"): "Check whether equity or state rules limit HELOCs before investing in campaigns here.",
}
REGIME_ACTIONS = {
    "Buyer's market": "Target move-up buyers and sellers who need bridge or purchase financing; watch LTV on recent loans.",
    "Seller's market": "Win on speed: fully underwritten pre-approvals and fast closings beat competing offers.",
    "Balanced": "Track rates and local job news - they will tip this market either way.",
}


def _pct(value: float) -> str:
    return f"{value * 100:.1f}%"


def explain_product(product: str, direction: str, context: dict) -> list[str]:
    """Drivers that plausibly explain a product being over/under-represented."""
    regime = context.get("regime") or {}
    rates = context.get("rates") or {}
    news = context.get("news") or {}
    drivers: list[str] = []
    price_yoy = regime.get("median_sale_price_yoy")
    current_regime = regime.get("current")
    rate_change = rates.get("change")
    rate_level = rates.get("rate")

    if product == "Purchase":
        if direction == "high":
            if current_regime == "Seller's market":
                drivers.append(f"Seller's market ({regime['months_of_supply']:.1f} months of supply) - strong buyer demand")
            if news.get("Inflow", 0) >= NEWS_SIGNAL_MIN:
                drivers.append(f"{news['Inflow']} recent headlines on employers moving in or expanding - in-migration fuels purchases")
            if price_yoy is not None and price_yoy < 0:
                drivers.append(f"Prices down {_pct(-price_yoy)} YoY improve affordability for first-time buyers")
        else:
            if price_yoy is not None and price_yoy > 0.05:
                drivers.append(f"Prices up {_pct(price_yoy)} YoY squeeze affordability")
            if news.get("Outflow", 0) >= NEWS_SIGNAL_MIN:
                drivers.append(f"{news['Outflow']} recent headlines on layoffs/closures dampen buyer confidence")
            if current_regime == "Buyer's market":
                drivers.append("Buyer's market - homes sit longer, fewer closed purchases per listing")
    elif product in ("Refinance", "Cash-out Refi"):
        if direction == "high":
            if rate_change is not None and rate_change <= -RATE_MOVE_THRESHOLD:
                drivers.append(f"30y rate fell {abs(rate_change):.2f} pts in a year - refinance math works again")
            if product == "Cash-out Refi" and price_yoy is not None and price_yoy > 0:
                drivers.append(f"Prices up {_pct(price_yoy)} YoY build tappable equity")
            if not drivers:
                drivers.append("Large stock of loans originated at peak rates (2023-24) that now benefit from refinancing")
        else:
            if rate_level is not None and rate_level >= HIGH_RATE_LEVEL:
                drivers.append(f"At {rate_level:.2f}%, most owners hold cheaper existing mortgages - little incentive to refinance")
    elif product == "Home Equity":
        if direction == "high":
            if rate_level is not None and rate_level >= HIGH_RATE_LEVEL:
                drivers.append(f"With 30y rates at {rate_level:.2f}%, owners keep low first-lien rates and tap equity via HELOC instead of cash-out refi")
            if price_yoy is not None and price_yoy > 0:
                drivers.append(f"Prices up {_pct(price_yoy)} YoY - more equity available")
        else:
            if context.get("state") in RESTRICTED_EQUITY_STATES:
                drivers.append("Texas law caps home equity borrowing at 80% combined LTV and one equity loan "
                               "per year (Tex. Const. art. XVI, sec. 50(a)(6))")
            if price_yoy is not None and price_yoy < 0:
                drivers.append(f"Prices down {_pct(-price_yoy)} YoY shrink available equity")
    return drivers


def mix_insights(area: str, area_shares: dict, benchmark: str, benchmark_shares: dict, context: dict) -> list[Insight]:
    insights = []
    for product in PRODUCTS:
        gap = area_shares.get(product, 0) - benchmark_shares.get(product, 0)
        if abs(gap) < SHARE_GAP_THRESHOLD:
            continue
        direction = "high" if gap > 0 else "low"
        drivers = explain_product(product, direction, context)
        insights.append(Insight(
            kind="opportunity" if direction == "high" else "watch",
            area=area,
            product=product,
            title=f"{product} is {_pct(area_shares[product])} of loans in {area} vs {_pct(benchmark_shares[product])} in {benchmark}",
            detail=f"{abs(gap) * 100:.1f} pts {'above' if gap > 0 else 'below'} {benchmark}",
            drivers=drivers,
            action=MIX_ACTIONS[(product, direction)],
        ))
    return insights


def yoy_insights(area: str, changes: dict, year: int) -> list[Insight]:
    insights = []
    for product, change in changes.items():
        if change is None or abs(change) < YOY_THRESHOLD:
            continue
        insights.append(Insight(
            kind="opportunity" if change > 0 else "watch",
            area=area, product=product,
            title=f"{product} originations {'up' if change > 0 else 'down'} {_pct(abs(change))} in {year} vs {year - 1}",
            detail=f"Year-over-year change in {area}.",
            action=(f"Add {product.lower()} capacity and marketing while demand is growing." if change > 0
                    else f"Check whether the drop is market-wide or lost share (see Market share)."),
        ))
    return insights


REGIME_IMPLICATIONS = {
    "Buyer's market": ("Expect more listings, price cuts and longer days on market. Existing owners may sell "
                       "rather than refinance - prioritise purchase pre-approvals for move-up buyers and "
                       "monitor LTV risk on recent loans."),
    "Seller's market": ("Expect bidding competition and faster closings. Purchase demand outruns supply - "
                        "fast pre-approvals and jumbo/conforming-limit products win share."),
    "Balanced": "Neither side has leverage - volumes track rates and local job growth.",
}


def regime_insight(area: str, shift: dict | None) -> Insight | None:
    if not shift or not shift.get("current"):
        return None
    supply_move = abs(shift["months_of_supply"] - shift["months_of_supply_prev"])
    if shift["changed"] and supply_move >= MATERIAL_SUPPLY_MOVE:
        title = f"{area} moved from {REGIME_PHRASES[shift['previous']]} to {REGIME_PHRASES[shift['current']]}"
        kind = "watch"
    elif shift["changed"]:
        # Crossing a threshold by a hair isn't a real regime change - flag it as context only.
        title = f"{area} edged from {REGIME_PHRASES[shift['previous']]} into {REGIME_PHRASES[shift['current']]}"
        kind = "info"
    else:
        title = f"{area} remains {REGIME_PHRASES[shift['current']]}"
        kind = "info"
    detail = (f"Months of supply {shift['months_of_supply_prev']:.1f} -> {shift['months_of_supply']:.1f}. "
              + REGIME_IMPLICATIONS[shift["current"]])
    return Insight(kind=kind, area=area, title=title, detail=detail, action=REGIME_ACTIONS[shift["current"]])


def news_insight(area: str, counts: dict, sample_titles: dict[str, list[str]]) -> list[Insight]:
    insights = []
    if counts.get("Inflow", 0) >= NEWS_SIGNAL_MIN:
        insights.append(Insight(
            kind="opportunity", area=area, product="Purchase",
            title=f"Employer inflow signals in {area} - expect purchase volume to rise",
            detail=f"{counts['Inflow']} recent headlines about relocations, new facilities or hiring.",
            drivers=sample_titles.get("Inflow", [])[:3],
            action="Contact HR/relocation teams at the arriving employers about relocation mortgage programs.",
        ))
    if counts.get("Outflow", 0) >= NEWS_SIGNAL_MIN:
        insights.append(Insight(
            kind="watch", area=area,
            title=f"Employer outflow signals in {area} - expect more listings and watch credit stress",
            detail=f"{counts['Outflow']} recent headlines about layoffs, closures or exits.",
            drivers=sample_titles.get("Outflow", [])[:3],
            action="Prepare hardship options for affected borrowers; expect listings - pitch move-up buyers.",
        ))
    return insights


def rate_insight(rates: dict) -> Insight | None:
    change = rates["change"]
    if change <= -RATE_MOVE_THRESHOLD:
        return Insight(kind="opportunity", area="National", product="Refinance",
                       title=f"30y rate down {abs(change):.2f} pts in a year (now {rates['rate']:.2f}%)",
                       detail="Borrowers who locked in at the peak are now in the money.",
                       action="Run refi outreach on 2023-24 vintages (see the Refi opportunity tab).")
    if change >= RATE_MOVE_THRESHOLD:
        return Insight(kind="opportunity", area="National", product="Home Equity",
                       title=f"30y rate up {change:.2f} pts in a year (now {rates['rate']:.2f}%)",
                       detail="Cash-out refi gets expensive; HELOCs let owners keep their low first-lien rate.",
                       action="Lead equity conversations with HELOCs rather than cash-out refinances.")
    return Insight(kind="info", area="National",
                   title=f"30y rate steady at {rates['rate']:.2f}% ({change:+.2f} pts YoY)",
                   detail="Rate-driven refi demand is unlikely to change sharply.")


def compare_cities(city_shares: dict[str, dict], profiles: dict[str, dict]) -> list[Insight]:
    """For each product, contrast the city where it is strongest against the weakest."""
    insights = []
    if len(city_shares) < 2:
        return insights
    for product in PRODUCTS:
        ranked = sorted(city_shares, key=lambda city: city_shares[city].get(product, 0), reverse=True)
        leader, laggard = ranked[0], ranked[-1]
        gap = city_shares[leader][product] - city_shares[laggard][product]
        relative_gap = gap / city_shares[laggard][product] if city_shares[laggard][product] else 1.0
        if gap < CITY_MIN_GAP or (gap < SHARE_GAP_THRESHOLD and relative_gap < CITY_RELATIVE_GAP):
            continue
        drivers = _profile_drivers(product, profiles.get(leader, {}), profiles.get(laggard, {}), leader, laggard)
        insights.append(Insight(
            kind="info", area=f"{leader} vs {laggard}", product=product,
            title=(f"{product} is stronger in {leader} ({_pct(city_shares[leader][product])}) "
                   f"than {laggard} ({_pct(city_shares[laggard][product])})"),
            detail=f"{gap * 100:.1f} pt gap in share of loans ({relative_gap:.0%} higher relative to {laggard}).",
            drivers=drivers,
            action=f"Weight {product.lower()} campaigns toward {leader}.",
        ))
    return insights


def refi_pool_insight(area: str, pool_loans: int, pool_volume: float, median_savings: float,
                      market_rate: float) -> Insight | None:
    if pool_loans == 0:
        return Insight(kind="info", area=area, product="Refinance",
                       title=f"No loans in {area} are 0.75+ pts above today's {market_rate:.2f}% rate",
                       detail="Refinance demand will stay low unless rates fall.",
                       action="Use the rate scenario slider to size the pool if rates drop.")
    return Insight(
        kind="opportunity", area=area, product="Refinance",
        title=f"{pool_loans:,} loans (${pool_volume / 1e6:,.0f}M) in {area} could refinance at {market_rate:.2f}%",
        detail=f"Median estimated saving ${median_savings:,.0f}/month per borrower.",
        action="Export the in-the-money list and start with the largest monthly savings.",
    )


def share_gap_insight(bank: str, positions: list[dict]) -> Insight | None:
    """Flag the product where the bank's share lags its overall share the most."""
    overall = next((row for row in positions if row["product"] == "All products"), None)
    products = [row for row in positions if row["product"] != "All products" and row["market_loans"] >= 100]
    if not overall or not overall["share"] or not products:
        return None
    weakest = min(products, key=lambda row: row["share"] / overall["share"])
    if weakest["share"] >= overall["share"] * 0.75:
        return None
    rank = f"rank #{weakest['rank']}" if weakest["rank"] else "no loans"
    return Insight(
        kind="watch", area=bank, product=weakest["product"],
        title=f"{bank} is under-indexed in {weakest['product']}: {_pct(weakest['share'])} share vs {_pct(overall['share'])} overall",
        detail=f"{rank} of {weakest['lenders']} lenders; the leader holds {_pct(weakest['leader_share'])}.",
        action=f"Compare {weakest['product'].lower()} pricing, turn times and referral sources with the top lenders.",
    )


def fair_lending_insight(bank: str, coverage: list[dict]) -> Insight | None:
    flagged = [row for row in coverage if row["needs_review"]]
    if not flagged:
        return None
    gaps = "; ".join(f"{row['segment']}: {_pct(row['bank_share'])} of {bank}'s loans vs {_pct(row['peer_share'])} for peers"
                     for row in flagged)
    return Insight(
        kind="watch", area=bank, title=f"Fair-lending review: {bank} under-represented in {', '.join(r['segment'] for r in flagged)}",
        detail=gaps + ".",
        action="Review with Compliance before launching targeted campaigns; make sure outreach covers the whole territory.",
    )


def _profile_drivers(product: str, leader: dict, laggard: dict, leader_name: str, laggard_name: str) -> list[str]:
    drivers = []

    def higher(metric: str) -> bool:
        return (leader.get(metric) or 0) > (laggard.get(metric) or 0) * 1.1

    if product == "Purchase":
        if higher("investor_share"):
            drivers.append(f"More investor buying in {leader_name} ({_pct(leader['investor_share'])} vs {_pct(laggard['investor_share'])})")
        if higher("median_income_k"):
            drivers.append(f"Higher borrower incomes in {leader_name} (${leader['median_income_k']:.0f}k vs ${laggard['median_income_k']:.0f}k)")
    if product in ("Cash-out Refi", "Home Equity") and higher("median_property_value"):
        drivers.append(f"Higher home values in {leader_name} (${leader['median_property_value']:,.0f} vs "
                       f"${laggard['median_property_value']:,.0f}) mean more equity to tap")
    if product == "Refinance" and (laggard.get("median_income_k") or 0) > (leader.get("median_income_k") or 0) * 1.1:
        drivers.append(f"{leader_name} borrowers have lower incomes - more sensitive to payment relief from refinancing")
    if not drivers:
        drivers.append("No single borrower-profile driver stands out - check market regime and news for each city")
    return drivers
