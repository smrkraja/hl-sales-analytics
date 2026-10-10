"""Streamlit entry point:  streamlit run app/Home.py"""
import sys
from pathlib import Path

import streamlit as st
from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

load_dotenv()
st.set_page_config(page_title="Home Lending Sales Analytics", page_icon="🏠", layout="wide")

from session_banner import require_login_and_render_banner  # noqa: E402

# Runs before any page: stops the script for signed-out users.
require_login_and_render_banner()

views = Path(__file__).resolve().parent / "views"
navigation = st.navigation([
    st.Page(views / "territory.py", title="My territory", icon="🎯", default=True),
    st.Page(views / "overview.py", title="National overview", icon="🗺️"),
    st.Page(views / "drilldown.py", title="Deep Insights", icon="🔎"),
    st.Page(views / "compare.py", title="Compare cities", icon="⚖️"),
    st.Page(views / "market_news.py", title="Market & news", icon="📰"),
    st.Page(views / "insights_feed.py", title="Insights", icon="💡"),
])
navigation.run()
