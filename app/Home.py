"""Streamlit entry point:  streamlit run app/Home.py"""
import sys
from pathlib import Path

import streamlit as st
from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

load_dotenv()
st.set_page_config(page_title="Home Lending Sales Analytics", page_icon="🏠", layout="wide")

views = Path(__file__).resolve().parent / "views"
navigation = st.navigation([
    st.Page(views / "overview.py", title="National overview", icon="🗺️", default=True),
    st.Page(views / "drilldown.py", title="Drill-down", icon="🔎"),
    st.Page(views / "compare.py", title="Compare cities", icon="⚖️"),
    st.Page(views / "market_news.py", title="Market & news", icon="📰"),
    st.Page(views / "insights_feed.py", title="Insights", icon="💡"),
])
navigation.run()
