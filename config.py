from __future__ import annotations
import os
from pathlib import Path

BASE_DIR = Path(__file__).parent
COMMUNITIES_FILE = BASE_DIR / "communities.csv"
COMMUNITY_ZONES_FILE = BASE_DIR / "community_zones.csv"
BACKGROUND_FILE = BASE_DIR / "background.jpg"
TIMEOUT_SECONDS = 10
AMAP_CITY = "北京"
DEFAULT_BASE_SCORE = 75


def get_amap_api_key(streamlit_secrets=None) -> str:
    key = ""
    if streamlit_secrets is not None:
        try:
            key = str(streamlit_secrets.get("AMAP_API_KEY", "")).strip()
        except Exception:
            key = ""
    if not key:
        key = os.getenv("AMAP_API_KEY", "").strip()
    return key
