"""Market news per city from free sources (Google News RSS, GDELT), tagged by signal.

Signals are keyword-based so they're explainable: an "Inflow" headline (HQ move,
new plant, hiring) hints at rising purchase demand; "Outflow" (layoffs, closures)
hints at more listings and possible credit stress.
"""
import hashlib
import json
import re
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from urllib.parse import quote_plus

import feedparser

from hl.config import NEWS_CACHE_DIR
from hl.etl.http import get_with_retry

CACHE_TTL_SECONDS = 6 * 3600
GOOGLE_NEWS_RSS = "https://news.google.com/rss/search?q={query}&hl=en-US&gl=US&ceid=US:en"
GDELT_API = "https://api.gdeltproject.org/api/v2/doc/doc"
TOPIC_TERMS = ('headquarters OR relocation OR relocating OR "new plant" OR expansion '
               'OR layoffs OR "job cuts" OR hiring OR "housing market"')

SIGNAL_PATTERNS = {
    "Outflow": re.compile(
        r"\b(layoffs?|lay off|laying off|job cuts?|cutting [\d,]+ jobs|closing|closure|closes|shut(ting)? down|"
        r"WARN notice|moves? (its )?(hq|headquarters) (out|away|from)|bankrupt\w*|downsiz\w*)\b",
        re.IGNORECASE),
    "Inflow": re.compile(
        r"\b(relocat\w* (to|its)|moves? (its )?(hq|headquarters) to|new (hq|headquarters|campus|plant|factory|facility|office)|"
        r"to (hire|add|create|bring) [\d,]+|[\d,]+ (new )?jobs|breaks ground|data center|"
        r"expan\w*.{0,60}\b(jobs|plant|facility|campus|headquarters|office|manufactur\w*|distribution center))\b",
        re.IGNORECASE),
    "Housing": re.compile(
        r"\b(home prices?|housing market|mortgage|inventory|listings|buyer'?s market|seller'?s market|home sales)\b",
        re.IGNORECASE),
}
# Sports, parks and events say "expansion" and "opens" too, but don't move housing demand.
NOISE_PATTERN = re.compile(r"\b(NHL|NBA|NFL|MLB|MLS|WNBA|hockey|soccer|football|basketball|baseball|"
                           r"state park|festival|concert)\b", re.IGNORECASE)
SOURCE_SUFFIX = re.compile(r"\s+-\s+[^-]+$")


def classify_headline(title: str) -> str:
    """First matching signal wins; outflow is checked first because 'closing' outranks 'opens'."""
    if NOISE_PATTERN.search(title):
        return "Other"
    for signal, pattern in SIGNAL_PATTERNS.items():
        if pattern.search(title):
            return signal
    return "Other"


def _cache_path(key: str):
    return NEWS_CACHE_DIR / f"{hashlib.sha1(key.encode()).hexdigest()}.json"


def _google_news(city: str, state: str) -> list[dict]:
    query = quote_plus(f'"{city}" {state} ({TOPIC_TERMS})')
    feed = feedparser.parse(get_with_retry(GOOGLE_NEWS_RSS.format(query=query), attempts=2, timeout=20).content)
    return [{
        # Google appends " - Outlet"; strip it so syndicated copies dedupe.
        "title": SOURCE_SUFFIX.sub("", entry.get("title", "")),
        "link": entry.get("link", ""),
        "source": entry.get("source", {}).get("title", "Google News"),
        "published": entry.get("published", ""),
    } for entry in feed.entries]


def _gdelt(city: str, state: str) -> list[dict]:
    params = {"query": f'"{city}" (relocation OR headquarters OR layoffs OR expansion) sourcecountry:US',
              "mode": "artlist", "format": "json", "maxrecords": 50, "timespan": "3months"}
    # GDELT throttles hard; it is a secondary source, so fail fast instead of retrying.
    articles = get_with_retry(GDELT_API, params, attempts=1, timeout=8).json().get("articles", [])
    return [{"title": item.get("title", ""), "link": item.get("url", ""),
             "source": item.get("domain", "GDELT"), "published": item.get("seendate", "")} for item in articles]


def fetch_city_news(city: str, state: str) -> dict:
    """Return {"articles": [...], "errors": [...], "fetched_at": iso} - cached on disk for a few hours."""
    cache_file = _cache_path(f"{city}|{state}")
    if cache_file.exists() and time.time() - cache_file.stat().st_mtime < CACHE_TTL_SECONDS:
        return json.loads(cache_file.read_text())

    articles, errors = [], []
    sources = {"Google News": _google_news, "GDELT": _gdelt}
    with ThreadPoolExecutor(max_workers=len(sources)) as pool:
        futures = {name: pool.submit(fetcher, city, state) for name, fetcher in sources.items()}
    for source_name, future in futures.items():
        try:
            articles.extend(future.result())
        except Exception as error:  # a failed source should degrade, not break the page
            errors.append(f"{source_name} unavailable ({type(error).__name__})")

    seen_titles: set[str] = set()
    unique = []
    for article in articles:
        normalized = article["title"].lower().strip()
        if normalized and normalized not in seen_titles:
            seen_titles.add(normalized)
            unique.append({**article, "signal": classify_headline(article["title"])})

    result = {"articles": unique, "errors": errors, "fetched_at": datetime.now(timezone.utc).isoformat()}
    if unique:  # don't cache an empty result caused by a transient outage
        NEWS_CACHE_DIR.mkdir(parents=True, exist_ok=True)
        cache_file.write_text(json.dumps(result))
    return result


def signal_counts(articles: list[dict]) -> dict[str, int]:
    counts = {"Inflow": 0, "Outflow": 0, "Housing": 0, "Other": 0}
    for article in articles:
        counts[article["signal"]] += 1
    return counts
