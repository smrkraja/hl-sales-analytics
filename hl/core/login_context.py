"""Where a session comes from: client IP and an approximate city for the banner.

The location is informational only (shown to the user themselves). IP headers
can be spoofed and IP geolocation is approximate, so never use it for access control.
"""
import ipaddress

from hl.etl.http import get_with_retry

# Two free, keyless HTTPS providers; the second covers rate limits on the first.
GEO_PROVIDERS = ["https://ipapi.co/{ip}/json/", "https://ipwho.is/{ip}"]
GEO_HEADERS = {"User-Agent": "hl-sales-analytics/1.0"}
LOCAL_LABEL = "Local network"
UNKNOWN_LABEL = "Location unavailable"


def client_ip(forwarded_for: str | None, direct_ip: str | None) -> str | None:
    """Behind a proxy/load balancer the browser's IP is the first X-Forwarded-For entry."""
    if forwarded_for:
        first = forwarded_for.split(",")[0].strip()
        if first:
            return first
    return direct_ip


def is_private(ip: str | None) -> bool:
    if not ip:
        return True
    try:
        address = ipaddress.ip_address(ip)
    except ValueError:
        return True
    return address.is_private or address.is_loopback or address.is_link_local


def describe_location(payload: dict) -> str:
    """'Austin, TX, US' from an ipapi.co response; falls back gracefully on partial data."""
    if payload.get("error") or payload.get("success") is False:
        return UNKNOWN_LABEL
    region = payload.get("region_code") or payload.get("region")
    parts = [payload.get("city"), region, payload.get("country_code") or payload.get("country")]
    parts = [part for part in parts if part]
    return ", ".join(dict.fromkeys(parts)) if parts else UNKNOWN_LABEL


def lookup_location(ip: str | None) -> str:
    """City-level location for a public IP. Private/loopback IPs never leave the machine."""
    if is_private(ip):
        return LOCAL_LABEL
    for provider in GEO_PROVIDERS:
        try:
            response = get_with_retry(provider.format(ip=ip), attempts=1, timeout=5, headers=GEO_HEADERS)
            location = describe_location(response.json())
        except Exception:  # a failed lookup must never block sign-in
            continue
        if location != UNKNOWN_LABEL:
            return location
    return UNKNOWN_LABEL


def display_name(user: dict) -> str:
    """Identity providers differ: Entra sends name/preferred_username, Okta and Google send name/email."""
    return user.get("name") or user.get("preferred_username") or user.get("email") or "Signed-in user"


def initials(name: str) -> str:
    letters = [part[0] for part in name.replace("@", " ").split() if part and part[0].isalpha()]
    return "".join(letters[:2]).upper() or "?"
