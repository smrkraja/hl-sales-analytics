import pytest

from hl.core import landmarks, login_context


@pytest.mark.parametrize("forwarded, direct, expected", [
    ("203.0.113.7, 10.0.0.2", "10.0.0.2", "203.0.113.7"),  # behind a proxy: first hop is the browser
    (None, "198.51.100.4", "198.51.100.4"),
    ("", "127.0.0.1", "127.0.0.1"),
    (None, None, None),
])
def test_client_ip_prefers_forwarded_for(forwarded, direct, expected):
    assert login_context.client_ip(forwarded, direct) == expected


@pytest.mark.parametrize("ip, private", [
    ("127.0.0.1", True), ("::1", True), ("10.1.2.3", True), ("192.168.1.10", True),
    ("8.8.8.8", False), ("not-an-ip", True), (None, True),
])
def test_is_private(ip, private):
    assert login_context.is_private(ip) is private


def test_private_ip_never_calls_geolocation(monkeypatch):
    def fail(*args, **kwargs):
        raise AssertionError("private IPs must not be sent to a third party")
    monkeypatch.setattr(login_context, "get_with_retry", fail)
    assert login_context.lookup_location("192.168.0.5") == login_context.LOCAL_LABEL


def test_lookup_failure_degrades_to_unknown(monkeypatch):
    def boom(*args, **kwargs):
        raise TimeoutError
    monkeypatch.setattr(login_context, "get_with_retry", boom)
    assert login_context.lookup_location("8.8.8.8") == login_context.UNKNOWN_LABEL


@pytest.mark.parametrize("payload, expected", [
    ({"city": "Austin", "region_code": "TX", "country_code": "US"}, "Austin, TX, US"),
    ({"city": "Singapore", "region": "Singapore", "country_code": "SG"}, "Singapore, SG"),
    ({"error": True, "reason": "RateLimited"}, login_context.UNKNOWN_LABEL),
    ({}, login_context.UNKNOWN_LABEL),
])
def test_describe_location(payload, expected):
    assert login_context.describe_location(payload) == expected


@pytest.mark.parametrize("user, name, letters", [
    ({"name": "Ramkumar Murugiah", "email": "r@bank.com"}, "Ramkumar Murugiah", "RM"),
    ({"preferred_username": "jdoe@bank.com"}, "jdoe@bank.com", "JB"),
    ({}, "Signed-in user", "SU"),
])
def test_display_name_and_initials(user, name, letters):
    assert login_context.display_name(user) == name
    assert login_context.initials(name) == letters


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload

    def json(self):
        return self.payload


def test_lookup_falls_back_to_second_provider(monkeypatch):
    def fake_get(url, **kwargs):
        if "ipapi.co" in url:
            return FakeResponse({"error": True, "reason": "RateLimited"})
        return FakeResponse({"success": True, "city": "Cedar Park", "region_code": "TX", "country_code": "US"})
    monkeypatch.setattr(login_context, "get_with_retry", fake_get)
    assert login_context.lookup_location("24.28.0.1") == "Cedar Park, TX, US"



@pytest.mark.parametrize("location, landmark", [
    ("San Francisco, CA, US", "Golden Gate Bridge"),
    ("san francisco", "Golden Gate Bridge"),
    ("Austin, TX, US", None),          # no image yet -> plain navy banner
    (login_context.LOCAL_LABEL, None),
    (None, None),
])
def test_landmark_for_city(location, landmark):
    found = landmarks.landmark_for(location)
    assert (found.name if found else None) == landmark


def test_every_landmark_image_exists():
    from pathlib import Path
    static = Path(__file__).resolve().parent.parent / "app" / "static"
    for city, landmark in landmarks.LANDMARKS.items():
        assert (static / landmark.image).is_file(), f"missing image for {city}"
