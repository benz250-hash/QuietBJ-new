
import base64
import difflib
import math
import os
from pathlib import Path
from typing import Any

import pandas as pd
import requests
import streamlit as st

st.set_page_config(page_title="北京静噪分", page_icon="🔇", layout="wide")

BASE_DIR = Path(__file__).parent
DATA_FILE = BASE_DIR / "communities_sample.csv"
BG_FILE = BASE_DIR / "background.jpg"
AMAP_GEOCODE_URL = "https://restapi.amap.com/v3/geocode/geo"
AMAP_REGEO_URL = "https://restapi.amap.com/v3/geocode/regeo"
TIMEOUT = 12


# -----------------------------
# Data and helpers
# -----------------------------
def get_amap_api_key() -> str:
    try:
        key = str(st.secrets.get("AMAP_API_KEY", "")).strip()
    except Exception:
        key = ""
    if not key:
        key = os.getenv("AMAP_API_KEY", "").strip()
    return key


@st.cache_data(show_spinner=False)
def load_communities() -> pd.DataFrame:
    df = pd.read_csv(DATA_FILE)
    df = df.fillna("")
    return df


@st.cache_data(show_spinner=False)
def file_to_base64(path: str) -> str:
    return base64.b64encode(Path(path).read_bytes()).decode("utf-8")


def normalize_text(text: str | None) -> str:
    if text is None:
        return ""
    value = str(text).strip().lower().replace(" ", "")
    for token in ["北京市", "北京", "小区", "社区", "一期", "二期", "三期", "四期", "五期"]:
        value = value.replace(token, "")
    return value


def safe_float(value: Any, default: float | None = None) -> float | None:
    try:
        if value is None or value == "":
            return default
        return float(value)
    except Exception:
        return default


# -----------------------------
# Scoring model
# -----------------------------
def road_risk(dist_primary: float | None, dist_expressway: float | None) -> float:
    score = 0.0
    if dist_expressway is None:
        score += 58
    elif dist_expressway < 120:
        score += 98
    elif dist_expressway < 250:
        score += 86
    elif dist_expressway < 450:
        score += 66
    elif dist_expressway < 800:
        score += 42
    else:
        score += 16

    if dist_primary is None:
        score += 40
    elif dist_primary < 60:
        score += 80
    elif dist_primary < 120:
        score += 60
    elif dist_primary < 260:
        score += 36
    elif dist_primary < 500:
        score += 22
    else:
        score += 10
    return min(score / 2, 100)


def rail_risk(dist_rail: float | None, dist_aboveground_rail: float | None) -> float:
    score = 0.0
    if dist_rail is None:
        score += 32
    elif dist_rail < 120:
        score += 76
    elif dist_rail < 250:
        score += 56
    elif dist_rail < 500:
        score += 30
    else:
        score += 12

    if dist_aboveground_rail is None:
        score += 18
    elif dist_aboveground_rail < 150:
        score += 84
    elif dist_aboveground_rail < 350:
        score += 56
    elif dist_aboveground_rail < 700:
        score += 32
    else:
        score += 10
    return min(score / 2, 100)


def flight_risk(dist_airport_path: float | None) -> float:
    if dist_airport_path is None:
        return 18
    if dist_airport_path < 3000:
        return 85
    if dist_airport_path < 8000:
        return 55
    if dist_airport_path < 15000:
        return 28
    return 10


def scale_density(value: float | None, low: float, high: float, default: float = 30) -> float:
    if value is None:
        return default
    if high <= low:
        return default
    result = 100 * (value - low) / (high - low)
    return max(0, min(100, result))


def local_business_risk(nightlife_density: float | None, market_density: float | None, school_density: float | None) -> float:
    nightlife = scale_density(nightlife_density, 0, 45, 24)
    market = scale_density(market_density, 0, 80, 26)
    school = scale_density(school_density, 0, 35, 14)
    return round(0.5 * nightlife + 0.3 * market + 0.2 * school, 1)


def complaint_risk(value: float | None) -> float:
    return scale_density(value, 0, 35, 28)


def far_to_penalty(far_ratio: float | None) -> float:
    if far_ratio is None:
        return 42
    if far_ratio <= 1.2:
        return 10
    if far_ratio <= 2.0:
        return 25
    if far_ratio <= 2.8:
        return 45
    if far_ratio <= 4.0:
        return 70
    return 90


def slab_score(thickness_mm: float | None) -> float:
    if thickness_mm is None:
        return 56
    if thickness_mm >= 160:
        return 90
    if thickness_mm >= 140:
        return 80
    if thickness_mm >= 120:
        return 66
    return 50


def building_age_score(building_year: float | None) -> float:
    if building_year is None or math.isnan(building_year):
        return 56
    year = int(building_year)
    if year >= 2021:
        return 84
    if year >= 2015:
        return 78
    if year >= 2008:
        return 68
    if year >= 2000:
        return 58
    return 45


def quality_score(label: str | None) -> float:
    mapping = {"high": 85, "mid": 68, "basic": 52, "old": 42}
    return mapping.get(str(label).lower(), 58)


def score_label(score: int) -> str:
    if score >= 90:
        return "非常安静"
    if score >= 80:
        return "比较安静"
    if score >= 70:
        return "安静度一般"
    if score >= 60:
        return "偏吵"
    return "较吵"


def calculate_score(features: dict[str, Any]) -> dict[str, Any]:
    road = road_risk(safe_float(features.get("distance_to_primary_road")), safe_float(features.get("distance_to_expressway")))
    rail = rail_risk(safe_float(features.get("distance_to_rail_transit")), safe_float(features.get("distance_to_aboveground_rail")))
    flight = flight_risk(safe_float(features.get("distance_to_airport_path")))
    local = local_business_risk(
        safe_float(features.get("poi_nightlife_density")),
        safe_float(features.get("poi_market_density")),
        safe_float(features.get("poi_school_density")),
    )
    complaints = complaint_risk(safe_float(features.get("complaint_noise_count")))

    env_risk = round(0.55 * road + 0.12 * rail + 0.08 * flight + 0.13 * local + 0.12 * complaints, 1)

    building_acoustic = round(
        0.6 * slab_score(safe_float(features.get("slab_thickness_proxy")))
        + 0.25 * building_age_score(safe_float(features.get("building_year")))
        + 0.15 * quality_score(features.get("quality_proxy")),
        1,
    )

    far_penalty = far_to_penalty(safe_float(features.get("far_ratio")))
    score = round(max(50, min(100, 100 - 0.7 * env_risk + 0.15 * building_acoustic - 0.15 * far_penalty)))

    return {
        "score": score,
        "label": score_label(score),
        "road": road,
        "rail": rail,
        "flight": flight,
        "local": local,
        "complaints": complaints,
        "env_risk": env_risk,
        "building_acoustic": building_acoustic,
        "far_penalty": far_penalty,
    }


# -----------------------------
# Matching and estimation
# -----------------------------
def match_community(query: str, df: pd.DataFrame) -> dict[str, Any] | None:
    norm_query = normalize_text(query)
    if not norm_query:
        return None

    best_row = None
    best_score = 0.0
    for _, row in df.iterrows():
        candidates = [str(row.get("community_name", "")), str(row.get("address", ""))]
        aliases = str(row.get("aliases", ""))
        if aliases:
            candidates.extend([item.strip() for item in aliases.split("|") if item.strip()])

        candidate_norms = [normalize_text(item) for item in candidates if item]
        exact = any(norm_query == item for item in candidate_norms)
        contains = any(norm_query in item or item in norm_query for item in candidate_norms)
        similarity = max([difflib.SequenceMatcher(None, norm_query, item).ratio() for item in candidate_norms] + [0.0])

        score = 0.0
        if exact:
            score = 1.0
        elif contains:
            score = 0.93
        else:
            score = similarity

        if score > best_score:
            best_score = score
            best_row = row.to_dict()

    if best_row and best_score >= 0.6:
        return best_row
    return None


@st.cache_data(show_spinner=False)
def amap_geocode(address: str, api_key: str) -> dict[str, Any] | None:
    params = {"key": api_key, "address": address, "city": "北京"}
    resp = requests.get(AMAP_GEOCODE_URL, params=params, timeout=TIMEOUT)
    resp.raise_for_status()
    data = resp.json()
    if str(data.get("status")) != "1" or not data.get("geocodes"):
        return None
    return data["geocodes"][0]


@st.cache_data(show_spinner=False)
def amap_regeo(lon: float, lat: float, api_key: str) -> dict[str, Any] | None:
    params = {
        "key": api_key,
        "location": f"{lon},{lat}",
        "radius": 1000,
        "extensions": "all",
        "roadlevel": 1,
    }
    resp = requests.get(AMAP_REGEO_URL, params=params, timeout=TIMEOUT)
    resp.raise_for_status()
    data = resp.json()
    if str(data.get("status")) != "1":
        return None
    return data.get("regeocode", {})


def classify_road_name(name: str) -> str:
    text = str(name)
    express_markers = ["环路", "高速", "快速", "京藏", "京承", "京开", "机场", "辅路"]
    if any(marker in text for marker in express_markers):
        return "expressway"
    return "primary"


def estimate_from_amap(query: str, api_key: str) -> dict[str, Any] | None:
    if not api_key:
        return None
    try:
        geo = amap_geocode(query, api_key)
        if not geo:
            return None
        location = geo.get("location", "")
        lon_str, lat_str = location.split(",")
        lon, lat = float(lon_str), float(lat_str)
        regeo = amap_regeo(lon, lat, api_key) or {}
        roads = regeo.get("roads", []) or []
        pois = regeo.get("pois", []) or []

        dist_primary: float | None = None
        dist_expressway: float | None = None
        for road in roads:
            distance = safe_float(road.get("distance"))
            if distance is None:
                continue
            road_type = classify_road_name(road.get("name", ""))
            if road_type == "expressway":
                dist_expressway = distance if dist_expressway is None else min(dist_expressway, distance)
            else:
                dist_primary = distance if dist_primary is None else min(dist_primary, distance)

        nightlife = 0
        market = 0
        school = 0
        rail = None
        for poi in pois:
            name = str(poi.get("name", ""))
            ptype = str(poi.get("type", ""))
            distance = safe_float(poi.get("distance"))
            if any(word in name for word in ["酒吧", "KTV", "夜总会"]) or "休闲娱乐" in ptype:
                nightlife += 1
            if any(word in name for word in ["商场", "购物", "超市", "市场"]) or "购物服务" in ptype:
                market += 1
            if "学校" in name or "科教文化服务" in ptype:
                school += 1
            if ("地铁" in name or "公交站" in name or "交通设施服务" in ptype) and distance is not None:
                rail = distance if rail is None else min(rail, distance)

        district = geo.get("district", "") or regeo.get("addressComponent", {}).get("district", "")
        address_text = regeo.get("formatted_address", query)

        features = {
            "community_name": query,
            "district": district,
            "address": address_text,
            "far_ratio": 2.8,
            "building_year": 2012,
            "slab_thickness_proxy": 125,
            "quality_proxy": "mid",
            "distance_to_primary_road": dist_primary if dist_primary is not None else 280,
            "distance_to_expressway": dist_expressway if dist_expressway is not None else 520,
            "distance_to_rail_transit": rail if rail is not None else 420,
            "distance_to_aboveground_rail": 900,
            "distance_to_airport_path": 14000,
            "poi_nightlife_density": nightlife * 12,
            "poi_market_density": market * 14,
            "poi_school_density": school * 10,
            "complaint_noise_count": 8,
            "source": "amap_estimate",
        }
        return features
    except Exception:
        return None


# -----------------------------
# UI
# -----------------------------
def inject_css() -> None:
    bg_b64 = file_to_base64(str(BG_FILE)) if BG_FILE.exists() else ""
    st.markdown(
        f"""
        <style>
        :root {{
            --glass: rgba(255,255,255,0.82);
            --glass-border: rgba(255,255,255,0.22);
            --ink: #202734;
            --muted: #5f6775;
            --green: #8faa7d;
            --green-dark: #779564;
            --dark-btn: #11141d;
            --page-light: #f5f6f8;
        }}

        html, body, [class*="css"] {{
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, "PingFang SC", "Noto Sans SC", sans-serif;
        }}

        .stApp {{
            background: transparent !important;
        }}

        [data-testid="stAppViewContainer"],
        [data-testid="stAppViewContainer"] > .main,
        section.main {{
            background: transparent !important;
        }}

        [data-testid="stHeader"],
        [data-testid="stToolbar"],
        [data-testid="stDecoration"] {{
            background: transparent !important;
        }}

        .bg-wrap {{
            position: fixed;
            inset: 0;
            z-index: 0;
            pointer-events: none;
            overflow: hidden;
        }}

        .bg-photo {{
            position: absolute;
            inset: 0;
            background-image: linear-gradient(rgba(10,14,18,0.18), rgba(10,14,18,0.34)), url("data:image/jpeg;base64,{bg_b64}");
            background-size: cover;
            background-position: center center;
            background-repeat: no-repeat;
            transform: scale(1.01);
        }}

        .bg-fade {{
            position: absolute;
            inset: 0;
            background: linear-gradient(
                to bottom,
                rgba(255,255,255,0.00) 0%,
                rgba(245,246,248,0.05) 58%,
                rgba(245,246,248,0.35) 78%,
                rgba(245,246,248,0.70) 100%
            );
        }}

        .block-container,
        [data-testid="stVerticalBlock"],
        [data-testid="stHorizontalBlock"] {{
            position: relative;
            z-index: 1;
        }}

        .block-container {{
            max-width: 100% !important;
            padding: 0 !important;
        }}

        section.main > div {{
            padding-top: 0 !important;
        }}

        .page {{
            padding: 0 32px 48px 32px;
        }}

        .nav {{
            display: flex;
            align-items: center;
            justify-content: space-between;
            gap: 22px;
            padding: 18px 0 0 0;
            color: #fff;
            font-weight: 800;
        }}

        .nav-brand {{
            font-size: clamp(2rem, 5vw, 4.2rem);
            line-height: 1;
            letter-spacing: 0.02em;
            text-shadow: 0 4px 24px rgba(0,0,0,0.35);
        }}

        .nav-links {{
            display: flex;
            align-items: center;
            gap: 30px;
            font-size: 1.1rem;
            text-shadow: 0 2px 16px rgba(0,0,0,0.25);
        }}

        .nav-login {{
            padding: 14px 22px;
            background: rgba(128,157,108,0.96);
            border-radius: 12px;
            color: white;
            font-weight: 900;
            box-shadow: 0 8px 22px rgba(0,0,0,0.18);
        }}

        .hero {{
            min-height: 74vh;
            display: flex;
            flex-direction: column;
            justify-content: center;
            padding-bottom: 90px;
        }}

        .search-card {{
            width: min(1040px, 92vw);
            margin: 0 auto;
            background: rgba(255,255,255,0.74);
            border: 1px solid rgba(255,255,255,0.35);
            backdrop-filter: blur(10px);
            border-radius: 24px;
            box-shadow: 0 24px 60px rgba(10,14,22,0.18);
            padding: 34px 28px 28px 28px;
        }}

        .search-title {{
            text-align: center;
            color: #444b58;
            font-size: clamp(2.3rem, 5vw, 4.4rem);
            line-height: 1;
            font-weight: 900;
            margin-bottom: 14px;
            letter-spacing: 0.01em;
        }}

        .search-copy {{
            text-align: center;
            color: #5f6675;
            font-size: 1rem;
            line-height: 1.65;
            margin-bottom: 18px;
        }}

        .search-shell form {{
            border: none !important;
            background: transparent !important;
            padding: 0 !important;
        }}

        .search-shell [data-testid="stTextInput"] label {{
            display: none !important;
        }}

        .search-shell [data-testid="stTextInput"] input {{
            min-height: 72px !important;
            border-radius: 10px !important;
            border: 2px solid rgba(33,38,48,0.16) !important;
            background: rgba(255,255,255,0.98) !important;
            color: #283142 !important;
            font-size: 1.7rem !important;
            padding-left: 20px !important;
        }}

        .search-shell [data-testid="stFormSubmitButton"] button {{
            min-height: 72px !important;
            border-radius: 10px !important;
            font-size: 1.55rem !important;
            font-weight: 900 !important;
            border: none !important;
            width: 100% !important;
        }}

        .search-shell [data-testid="stFormSubmitButton"] button[kind="primary"] {{
            background: #9ab48d !important;
            color: white !important;
        }}

        .search-shell [data-testid="stFormSubmitButton"] button[kind="secondary"] {{
            background: var(--dark-btn) !important;
            color: white !important;
        }}

        .content {{
            max-width: 1160px;
            margin: 0 auto;
            padding: 0 18px;
        }}

        .intro-strip {{
            margin-top: -10px;
            margin-bottom: 22px;
            padding: 16px 18px;
            border-radius: 16px;
            color: #55606f;
            background: rgba(255,255,255,0.72);
            border: 1px solid rgba(255,255,255,0.26);
            backdrop-filter: blur(10px);
        }}

        .card {{
            background: rgba(255,255,255,0.94);
            border-radius: 24px;
            border: 1px solid rgba(15,18,28,0.06);
            box-shadow: 0 18px 48px rgba(10,14,22,0.10);
            padding: 28px;
        }}

        .badge {{
            display: inline-block;
            padding: 8px 14px;
            border-radius: 999px;
            background: rgba(137,167,122,0.12);
            color: #5d7552;
            border: 1px solid rgba(137,167,122,0.24);
            font-size: 0.94rem;
            font-weight: 800;
            margin-bottom: 12px;
        }}

        .score-ring {{
            width: 220px;
            height: 220px;
            border-radius: 999px;
            margin: 0 auto;
            display: flex;
            align-items: center;
            justify-content: center;
            border: 12px solid rgba(137,167,122,0.28);
            background: radial-gradient(circle at 30% 30%, rgba(255,255,255,0.99), rgba(243,247,240,1));
            font-size: 3.6rem;
            color: #273244;
            font-weight: 900;
            box-shadow: inset 0 1px 0 rgba(255,255,255,0.7), 0 12px 30px rgba(10,14,22,0.10);
        }}

        .score-label {{
            text-align: center;
            margin-top: 12px;
            color: #5f6979;
            font-size: 1.04rem;
            font-weight: 800;
        }}

        .h2 {{
            color: var(--ink);
            font-size: 1.75rem;
            font-weight: 900;
            margin: 0 0 8px 0;
        }}

        .muted {{
            color: var(--muted);
            font-size: 1rem;
            line-height: 1.7;
        }}

        .reason {{
            background: #f7f8fa;
            border-radius: 18px;
            border: 1px solid rgba(19,23,32,0.06);
            padding: 16px;
            min-height: 108px;
            color: #344054;
            font-weight: 700;
        }}

        .small-note {{
            color: #6a7382;
            text-align: center;
            margin: 26px 0 12px 0;
        }}

        .divider {{
            height: 1px;
            background: rgba(30,35,48,0.08);
            margin: 26px 0;
        }}

        @media (max-width: 980px) {{
            .page {{ padding: 0 16px 34px 16px; }}
            .nav-links {{ display: none; }}
            .hero {{ min-height: 68vh; padding-bottom: 60px; }}
            .search-card {{ width: 94vw; padding: 22px 14px 18px 14px; border-radius: 18px; }}
            .search-shell [data-testid="stTextInput"] input {{ min-height: 56px !important; font-size: 1.15rem !important; }}
            .search-shell [data-testid="stFormSubmitButton"] button {{ min-height: 56px !important; font-size: 1.08rem !important; }}
            .score-ring {{ width: 184px; height: 184px; font-size: 3rem; }}
        }}
        </style>
        <div class="bg-wrap"><div class="bg-photo"></div><div class="bg-fade"></div></div>
        """,
        unsafe_allow_html=True,
    )


def render_nav() -> None:
    st.markdown(
        """
        <div class="page">
          <div class="nav">
            <div class="nav-brand">QUIETBJ</div>
            <div class="nav-links">
              <span>How it works</span>
              <span>FAQs</span>
              <span>Contact</span>
              <span>Blog</span>
              <span>Developers</span>
              <span class="nav-login">Log In</span>
            </div>
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_hero(df: pd.DataFrame) -> tuple[dict[str, Any] | None, str | None]:
    st.markdown('<div class="page"><div class="hero">', unsafe_allow_html=True)
    st.markdown(
        """
        <div class="search-card">
          <div class="search-title">SEARCH QUIETSCORE™</div>
          <div class="search-copy">输入北京小区名或地址。优先命中本地样本库；没命中时，若已配置高德 Key，则自动做在线估算。</div>
        """,
        unsafe_allow_html=True,
    )

    result = None
    status = None
    if "query" not in st.session_state:
        st.session_state.query = ""

    st.markdown('<div class="search-shell">', unsafe_allow_html=True)
    with st.form("hero_search", clear_on_submit=False):
        c1, c2, c3 = st.columns([7.2, 1.1, 1.4])
        with c1:
            query = st.text_input(
                "搜索北京小区或地址",
                value=st.session_state.query,
                placeholder="Enter address / 输入北京小区名、街道地址",
                label_visibility="collapsed",
            )
        with c2:
            go_clicked = st.form_submit_button("Go", type="primary", use_container_width=True)
        with c3:
            reset_clicked = st.form_submit_button("Reset", use_container_width=True)

    st.markdown('</div></div></div></div>', unsafe_allow_html=True)

    if reset_clicked:
        st.session_state.query = ""
        st.rerun()

    if go_clicked:
        st.session_state.query = query.strip()
        text = query.strip()
        if not text:
            status = "empty"
        else:
            matched = match_community(text, df)
            if matched:
                matched["source"] = "sample"
                result = matched
            else:
                api_key = get_amap_api_key()
                estimated = estimate_from_amap(text, api_key)
                if estimated:
                    result = estimated
                else:
                    status = "not_found"
    return result, status


def render_result(result: dict[str, Any]) -> None:
    score_info = calculate_score(result)
    reasons: list[str] = []
    if score_info["road"] <= 25:
        reasons.append("远离环路、快速路与主干线")
    elif score_info["road"] >= 60:
        reasons.append("靠近环路/高速/主干线，外部车流噪音较重")

    if score_info["far_penalty"] <= 25:
        reasons.append("容积率偏低，内部人车活动噪音更可控")
    elif score_info["far_penalty"] >= 70:
        reasons.append("容积率偏高，楼间距与密度拖分")

    if score_info["building_acoustic"] >= 75:
        reasons.append("楼体隔声能力中上")
    elif score_info["building_acoustic"] <= 55:
        reasons.append("楼体隔声能力一般")

    if score_info["complaints"] >= 60:
        reasons.append("周边噪音投诉热度偏高")

    while len(reasons) < 3:
        reasons.append("当前为模型估算值，后续可继续扩展到楼栋级修正")

    source_label = "本地样本库" if result.get("source") == "sample" else "在线估算"
    title = result.get("community_name") or "北京地址结果"
    district = result.get("district", "")
    address = result.get("address", "")

    st.markdown('<div class="content">', unsafe_allow_html=True)
    st.markdown(
        f'<div class="intro-strip">查询来源：<b>{source_label}</b>。当前主模型更重视北京环路、高速、快速路干线影响；这仍是地址级/小区级估算，不是官方实测分贝。</div>',
        unsafe_allow_html=True,
    )

    left, right = st.columns([1.02, 1.25], gap="large")
    with left:
        st.markdown('<div class="card">', unsafe_allow_html=True)
        st.markdown(f'<div class="badge">{source_label}</div>', unsafe_allow_html=True)
        st.markdown(f'<div class="score-ring">{score_info["score"]}</div>', unsafe_allow_html=True)
        st.markdown(f'<div class="score-label">{score_info["label"]}</div>', unsafe_allow_html=True)
        st.markdown(
            f"""
            <div class="divider"></div>
            <div class="muted"><b>{title}</b><br>{district} {address}</div>
            """,
            unsafe_allow_html=True,
        )
        st.markdown("</div>", unsafe_allow_html=True)

    with right:
        st.markdown('<div class="card">', unsafe_allow_html=True)
        st.markdown('<div class="h2">为什么是这个分数</div>', unsafe_allow_html=True)
        st.markdown(
            '<div class="muted">这是一个 50–100 分的北京住宅安静度估算，优先考虑环路/快速路/高速，再叠加容积率与楼体隔声代理值。</div>',
            unsafe_allow_html=True,
        )
        r1, r2, r3 = st.columns(3, gap="small")
        for col, reason in zip([r1, r2, r3], reasons[:3]):
            with col:
                st.markdown(f'<div class="reason">{reason}</div>', unsafe_allow_html=True)
        st.markdown('<div class="divider"></div>', unsafe_allow_html=True)
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("道路风险", round(score_info["road"]))
        c2.metric("环境总风险", round(score_info["env_risk"]))
        c3.metric("楼体隔声", round(score_info["building_acoustic"]))
        c4.metric("容积率拖分", round(score_info["far_penalty"]))
        st.markdown("</div>", unsafe_allow_html=True)

    st.markdown(
        '<div class="small-note">想继续做准，可以下一步升级到楼栋级：输入小区后再选楼栋号、朝向和是否临主路。</div>',
        unsafe_allow_html=True,
    )
    st.markdown('</div>', unsafe_allow_html=True)


def render_status(status: str | None) -> None:
    if status == "empty":
        st.info("先输入北京小区名或地址，再点 Go。")
    elif status == "not_found":
        api_key = get_amap_api_key()
        if api_key:
            st.warning("高德在线估算也没有返回有效地址。可以换成更完整的地址，或者先搜样本库里的小区，例如：新龙城、望京西园四区、天通苑东一区。")
        else:
            st.warning("本地样本库没命中，而且当前还没有配置高德 Key，所以暂时无法在线估算。先在 Streamlit Cloud 的 Secrets 里填 `AMAP_API_KEY`。")


def main() -> None:
    inject_css()
    render_nav()
    df = load_communities()
    result, status = render_hero(df)
    if result:
        render_result(result)
    else:
        render_status(status)


if __name__ == "__main__":
    main()
