import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "app"))

import session_banner  # noqa: E402


def test_provider_photo_wins(tmp_path, monkeypatch):
    monkeypatch.setattr(session_banner, "STATIC_DIR", tmp_path)
    user = {"picture": "https://example.com/me.jpg"}
    assert session_banner._avatar_for(user, dev_mode=True) == "https://example.com/me.jpg"


def test_local_photo_only_in_dev_mode(tmp_path, monkeypatch):
    (tmp_path / "avatars").mkdir()
    (tmp_path / "avatars" / "me.png").write_bytes(b"png")
    monkeypatch.setattr(session_banner, "STATIC_DIR", tmp_path)
    assert session_banner._avatar_for({}, dev_mode=True) == "app/static/avatars/me.png"
    # A signed-in user without a provider photo must never see the developer's face.
    assert session_banner._avatar_for({}, dev_mode=False) == "app/static/avatars/default.jpg"


def test_stock_photo_fallback(tmp_path, monkeypatch):
    monkeypatch.setattr(session_banner, "STATIC_DIR", tmp_path)
    assert session_banner._avatar_for({}, dev_mode=True) == "app/static/avatars/default.jpg"
