"""Sign-in gate and the top-of-page banner shown on every page."""
import html
import os
from datetime import datetime, timedelta, timezone

import streamlit as st

from hl.core import landmarks, login_context

APP_NAME = "Home Lending Sales Analytics"
TAGLINE = "Market intelligence for home lending advisers"

BANNER_CSS = """
<style>
.st-key-hl_banner {
  background: linear-gradient(100deg, #0d366b 0%, #184f95 60%, #256abf 100%);
  border-radius: 12px;
  padding: 18px 22px;
  margin-bottom: 0.75rem;
  box-shadow: 0 2px 10px rgba(13, 54, 107, 0.25);
}
.st-key-hl_banner, .st-key-hl_banner p, .st-key-hl_banner span { color: #ffffff; }
.st-key-hl_banner [data-testid="stMarkdownContainer"] { margin-bottom: -1rem; }
/* Pull the banner up into the space Streamlit reserves above page content. */
[data-testid="stMainBlockContainer"] { padding-top: 2.5rem; }
.hl-brand { display: flex; align-items: center; gap: 14px; }
.hl-mark {
  width: 42px; height: 42px; border-radius: 10px; background: rgba(255,255,255,0.14);
  display: flex; align-items: center; justify-content: center; font-size: 22px;
}
.hl-title { font-size: 1.25rem; font-weight: 700; letter-spacing: 0.2px; line-height: 1.2; }
.hl-tagline { font-size: 0.85rem; opacity: 0.8; }
.hl-user { display: flex; align-items: center; gap: 12px; justify-content: flex-end; text-align: right; }
.hl-avatar {
  width: 38px; height: 38px; border-radius: 50%; background: #ffffff; color: #0d366b !important;
  display: flex; align-items: center; justify-content: center; font-weight: 700; flex-shrink: 0;
}
.hl-name { font-weight: 600; font-size: 0.95rem; line-height: 1.2; }
.hl-meta { font-size: 0.78rem; opacity: 0.85; line-height: 1.35; }
.hl-credit { font-size: 0.65rem; opacity: 0.7; margin-top: 2px; }
.hl-dev { background: #fab219; color: #0b0b0b !important; border-radius: 6px; padding: 1px 6px; font-weight: 600; }
.st-key-hl_banner button {
  background: transparent; color: #ffffff; border: 1px solid rgba(255,255,255,0.6);
}
.st-key-hl_banner button:hover { background: rgba(255,255,255,0.15); color: #ffffff; border-color: #ffffff; }
.st-key-hl_banner button p { color: #ffffff; }
</style>
"""


def _landmark_css(landmark: landmarks.Landmark | None) -> str:
    """Photo background for the user's city, under a navy scrim so white text stays readable."""
    if landmark is None:
        return ""
    # Darker on the left (brand) and right (user details), lighter in the middle to show the landmark.
    scrim = ("linear-gradient(90deg, rgba(13,54,107,0.88) 0%, rgba(13,54,107,0.35) 34%, "
             "rgba(13,54,107,0.05) 52%, rgba(13,54,107,0.30) 66%, rgba(13,54,107,0.88) 100%)")
    return (f"<style>.st-key-hl_banner {{ background: {scrim}, url('app/static/{landmark.image}'); "
            f"background-size: cover; background-position: {landmark.focus}; min-height: 150px; "
            f"justify-content: center; }}"
            f".st-key-hl_banner .hl-title, .st-key-hl_banner .hl-tagline, .st-key-hl_banner .hl-name, "
            f".st-key-hl_banner .hl-meta, .st-key-hl_banner .hl-credit "
            f"{{ text-shadow: 0 1px 3px rgba(0,0,0,0.55); }}</style>")


def _auth_configured() -> bool:
    try:
        return "auth" in st.secrets
    except Exception:  # no secrets.toml at all
        return False


def _anonymous_allowed() -> bool:
    return os.environ.get("HL_ALLOW_ANONYMOUS") == "1"


@st.cache_data(ttl=24 * 3600, show_spinner=False)
def _location_for(ip: str | None) -> str:
    return login_context.lookup_location(ip)


def _session_origin() -> tuple[str | None, str]:
    """(ip, city) for this browser session, looked up once and kept in session state."""
    if "hl_origin" not in st.session_state:
        headers = st.context.headers or {}
        ip = login_context.client_ip(headers.get("X-Forwarded-For"), st.context.ip_address)
        # Demo/testing override, e.g. HL_STUB_LOCATION="San Francisco, CA, US".
        stub = os.environ.get("HL_STUB_LOCATION")
        st.session_state["hl_origin"] = (ip, stub or _location_for(ip))
    return st.session_state["hl_origin"]


def _signed_in_at(user: dict) -> datetime:
    issued_at = user.get("iat")
    if isinstance(issued_at, (int, float)):
        return datetime.fromtimestamp(issued_at, tz=timezone.utc)
    return st.session_state.setdefault("hl_signed_in_at", datetime.now(timezone.utc))


def _local_time(moment: datetime) -> str:
    offset_minutes = st.context.timezone_offset
    if offset_minutes is not None:
        # Browser reports minutes *behind* UTC (JS getTimezoneOffset), hence the minus.
        moment = moment.astimezone(timezone(timedelta(minutes=-offset_minutes)))
    return moment.strftime("%b %d, %I:%M %p").replace(" 0", " ")


def _render_login_screen() -> None:
    st.markdown(BANNER_CSS, unsafe_allow_html=True)
    with st.container(key="hl_banner"):
        st.markdown(_brand_html(), unsafe_allow_html=True)
    st.markdown("### Sign in to continue")
    st.write("This dashboard is for authorised lending staff. Sign in with your company account.")
    if st.button("Sign in with company account", type="primary"):
        st.login()


def _render_setup_help() -> None:
    st.markdown(BANNER_CSS, unsafe_allow_html=True)
    with st.container(key="hl_banner"):
        st.markdown(_brand_html(), unsafe_allow_html=True)
    st.error("Sign-in is not configured, so the dashboard is locked.")
    st.markdown(
        "Add an `[auth]` section to `.streamlit/secrets.toml` (gitignored) with your identity provider's "
        "OIDC settings - see `.streamlit/secrets.toml.example`.  \n"
        "For local development only, set `HL_ALLOW_ANONYMOUS=1` in `.env` to run without sign-in."
    )


def _brand_html() -> str:
    return (f"<div class='hl-brand'><div class='hl-mark'>🏠</div><div>"
            f"<div class='hl-title'>{APP_NAME}</div><div class='hl-tagline'>{TAGLINE}</div></div></div>")


def require_login_and_render_banner() -> None:
    """Gate the app behind SSO (fail closed), then draw the banner with user + origin + logout."""
    if _auth_configured():
        if not st.user.is_logged_in:
            _render_login_screen()
            st.stop()
        user = st.user.to_dict()
        dev_mode = False
    elif _anonymous_allowed():
        user = {"name": "Local developer", "email": "sign-in disabled"}
        dev_mode = True
    else:
        _render_setup_help()
        st.stop()

    name = login_context.display_name(user)
    email = user.get("email") or user.get("preferred_username") or ""
    ip, location = _session_origin()
    signed_in = _local_time(_signed_in_at(user))
    ip_text = f" ({ip})" if ip and location == login_context.LOCAL_LABEL else ""
    dev_badge = " <span class='hl-dev'>DEV MODE</span>" if dev_mode else ""
    landmark = landmarks.landmark_for(location)
    credit = (f"<div class='hl-credit'>{html.escape(landmark.name)} · {html.escape(landmark.credit)}</div>"
              if landmark else "")

    st.markdown(BANNER_CSS + _landmark_css(landmark), unsafe_allow_html=True)
    with st.container(key="hl_banner"):
        brand, who, action = st.columns([4, 5, 1], vertical_alignment="center")
        brand.markdown(_brand_html(), unsafe_allow_html=True)
        # Everything from the identity provider or the network is escaped before it hits HTML.
        who.markdown(
            f"<div class='hl-user'><div>"
            f"<div class='hl-name'>{html.escape(name)}{dev_badge}</div>"
            f"<div class='hl-meta'>{html.escape(email)}</div>"
            f"<div class='hl-meta'>📍 Signed in from {html.escape(location + ip_text)}</div>"
            f"<div class='hl-meta'>🕒 {html.escape(signed_in)}</div>{credit}"
            f"</div><div class='hl-avatar'>{html.escape(login_context.initials(name))}</div></div>",
            unsafe_allow_html=True,
        )
        if not dev_mode and action.button("Log out", key="hl_logout", width="stretch"):
            st.session_state.clear()
            st.logout()
