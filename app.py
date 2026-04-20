
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
    return df.fillna("")


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
        return "较为安静"
    if score >= 70:
        return "中等偏静"
    if score >= 60:
        return "略受噪音影响"
    return "噪音偏高"


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

        score = 1.0 if exact else 0.93 if contains else similarity
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
        lon_str, lat_str = geo.get("location", "").split(",")
        lon, lat = float(lon_str), float(lat_str)
        regeo = amap_regeo(lon, lat, api_key) or {}
        roads = regeo.get("roads", []) or []
        pois = regeo.get("pois", []) or []

        dist_primary = None
        dist_expressway = None
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
        return {
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
    except Exception:
        return None


def inject_css() -> None:
    bg_b64 = file_to_base64(str(BG_FILE)) if BG_FILE.exists() else ""
    st.markdown(
        f"""
        <style>
        :root {{
            --glass: rgba(255,255,255,0.72);
            --glass-strong: rgba(255,255,255,0.84);
            --glass-border: rgba(255,255,255,0.20);
            --ink: #142030;
            --muted: #5e6775;
            --nav: rgba(255,255,255,0.96);
            --accent: #95ad83;
            --accent-dark: #7a9567;
            --btn-dark: #0e1624;
            --page-light: #f6f7f8;
            --shadow: 0 28px 72px rgba(7, 15, 28, 0.18);
        }}

        html, body, [class*="css"] {{
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, "PingFang SC", "Hiragino Sans GB", "Microsoft YaHei", sans-serif;
        }}

        .stApp, [data-testid="stAppViewContainer"], [data-testid="stAppViewContainer"] > .main, section.main,
        [data-testid="stHeader"], [data-testid="stToolbar"], [data-testid="stDecoration"] {{
            background: transparent !important;
        }}

        .block-container, [data-testid="stVerticalBlock"], [data-testid="stHorizontalBlock"] {{
            position: relative;
            z-index: 2;
        }}

        .block-container {{
            max-width: 100% !important;
            padding: 0 !important;
        }}

        section.main > div {{
            padding-top: 0 !important;
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
            background-image:
                linear-gradient(180deg, rgba(5,10,18,0.24) 0%, rgba(7,12,18,0.38) 44%, rgba(7,12,18,0.18) 62%, rgba(255,255,255,0.02) 72%),
                url("data:image/jpeg;base64,{bg_b64}");
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
                rgba(246,247,248,0.00) 54%,
                rgba(246,247,248,0.10) 68%,
                rgba(246,247,248,0.34) 82%,
                rgba(246,247,248,0.54) 100%
            );
        }}

        .page {{
            padding: 0 38px 54px 38px;
        }}

        .nav-wrap {{
            position: sticky;
            top: 0;
            z-index: 20;
            padding-top: 18px;
        }}

        .nav {{
            display: flex;
            align-items: center;
            justify-content: space-between;
            gap: 22px;
            padding: 10px 20px;
            border-radius: 18px;
            background: rgba(255,255,255,0.08);
            border: 1px solid rgba(255,255,255,0.10);
            backdrop-filter: blur(8px);
        }}

        .nav-brand {{
            font-size: clamp(2.6rem, 5vw, 4.5rem);
            line-height: 1;
            letter-spacing: 0.02em;
            color: white;
            font-weight: 900;
            text-shadow: 0 8px 36px rgba(0,0,0,0.35);
        }}

        .nav-links {{
            display: flex;
            align-items: center;
            gap: 28px;
            color: rgba(255,255,255,0.95);
            font-size: 1.1rem;
            font-weight: 800;
            text-shadow: 0 3px 18px rgba(0,0,0,0.25);
        }}

        .nav-login {{
            padding: 13px 22px;
            border-radius: 14px;
            background: rgba(147,170,125,0.94);
            color: white;
            font-weight: 900;
            box-shadow: 0 10px 26px rgba(0,0,0,0.16);
        }}

        .hero {{
            min-height: calc(100vh - 92px);
            display: flex;
            align-items: center;
            justify-content: center;
            padding: 2vh 0 10vh 0;
        }}

        .search-card {{
            width: min(980px, 90vw);
            margin: 0 auto;
            background: rgba(255,255,255,0.74);
            border: 1px solid rgba(255,255,255,0.28);
            backdrop-filter: blur(16px);
            border-radius: 28px;
            box-shadow: var(--shadow);
            padding: 34px 30px 28px 30px;
        }}

        .search-title {{
            text-align: center;
            color: #2f3847;
            font-size: clamp(2.5rem, 5vw, 4.5rem);
            line-height: 1.05;
            font-weight: 900;
            letter-spacing: 0.02em;
            margin-bottom: 10px;
        }}

        .search-copy {{
            text-align: center;
            color: #5b6674;
            font-size: 1.02rem;
            line-height: 1.7;
            margin-bottom: 22px;
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
            border-radius: 12px !important;
            border: 1.5px solid rgba(27,39,55,0.12) !important;
            background: rgba(255,255,255,0.96) !important;
            color: #223041 !important;
            font-size: 1.38rem !important;
            padding-left: 22px !important;
            box-shadow: inset 0 1px 0 rgba(255,255,255,0.8);
        }}

        .search-shell [data-testid="stFormSubmitButton"] button {{
            min-height: 72px !important;
            border-radius: 12px !important;
            font-size: 1.28rem !important;
            font-weight: 900 !important;
            border: none !important;
            width: 100% !important;
            box-shadow: 0 12px 26px rgba(8,14,22,0.10);
        }}

        .search-shell [data-testid="stFormSubmitButton"] button[kind="primary"] {{
            background: linear-gradient(180deg, #a2ba90 0%, #8ea97a 100%) !important;
            color: white !important;
        }}

        .search-shell [data-testid="stFormSubmitButton"] button[kind="secondary"] {{
            background: linear-gradient(180deg, #172131 0%, #0d1421 100%) !important;
            color: white !important;
        }}

        .content {{
            max-width: 1160px;
            margin: 0 auto;
            padding: 0 18px;
        }}

        .intro-strip {{
            margin-top: 4px;
            margin-bottom: 24px;
            padding: 17px 20px;
            border-radius: 18px;
            color: #526070;
            background: rgba(255,255,255,0.74);
            border: 1px solid rgba(255,255,255,0.26);
            backdrop-filter: blur(10px);
            box-shadow: 0 10px 26px rgba(9,14,24,0.06);
        }}

        .card {{
            background: rgba(255,255,255,0.92);
            border-radius: 28px;
            border: 1px solid rgba(16,24,40,0.05);
            box-shadow: 0 20px 50px rgba(9,14,24,0.10);
            padding: 30px;
        }}

        .badge {{
            display: inline-block;
            padding: 8px 14px;
            border-radius: 999px;
            background: rgba(144,167,123,0.12);
            color: #536c46;
            border: 1px solid rgba(144,167,123,0.22);
            font-size: 0.94rem;
            font-weight: 800;
            margin-bottom: 12px;
        }}

        .score-ring {{
            width: 228px;
            height: 228px;
            border-radius: 999px;
            margin: 0 auto;
            display: flex;
            align-items: center;
            justify-content: center;
            border: 12px solid rgba(144,167,123,0.26);
            background: radial-gradient(circle at 28% 28%, rgba(255,255,255,0.99), rgba(243,246,241,1));
            font-size: 3.7rem;
            color: #243040;
            font-weight: 900;
            box-shadow: inset 0 1px 0 rgba(255,255,255,0.9), 0 16px 34px rgba(8,14,22,0.10);
        }}

        .score-label {{
            text-align: center;
            margin-top: 14px;
            color: #5f6979;
            font-size: 1.04rem;
            font-weight: 800;
        }}

        .h2 {{
            color: var(--ink);
            font-size: 1.8rem;
            font-weight: 900;
            margin: 0 0 8px 0;
        }}

        .muted {{
            color: var(--muted);
            font-size: 1rem;
            line-height: 1.72;
        }}

        .reason {{
            background: linear-gradient(180deg, #fafbfc 0%, #f7f8fa 100%);
            border-radius: 18px;
            border: 1px solid rgba(19,23,32,0.06);
            padding: 16px;
            min-height: 114px;
            color: #334155;
            font-weight: 700;
            box-shadow: inset 0 1px 0 rgba(255,255,255,0.8);
        }}

        .small-note {{
            color: #687384;
            text-align: center;
            margin: 28px 0 12px 0;
        }}

        .divider {{
            height: 1px;
            background: rgba(30,35,48,0.08);
            margin: 26px 0;
        }}

        @media (max-width: 980px) {{
            .page {{ padding: 0 16px 34px 16px; }}
            .nav {{ padding: 8px 12px; }}
            .nav-links {{ display: none; }}
            .hero {{ min-height: calc(100vh - 66px); padding: 0 0 6vh 0; }}
            .search-card {{ width: 94vw; padding: 24px 14px 20px 14px; border-radius: 20px; }}
            .search-title {{ font-size: 2.15rem; }}
            .search-copy {{ font-size: 0.95rem; margin-bottom: 16px; }}
            .search-shell [data-testid="stTextInput"] input {{ min-height: 58px !important; font-size: 1.02rem !important; }}
            .search-shell [data-testid="stFormSubmitButton"] button {{ min-height: 58px !important; font-size: 1rem !important; }}
            .score-ring {{ width: 190px; height: 190px; font-size: 3rem; }}
        }}
        </style>
        <div class="bg-wrap"><div class="bg-photo"></div><div class="bg-fade"></div></div>
        """,
        unsafe_allow_html=True,
    )


def render_nav() -> None:
    st.markdown(
        """
        <div class="page nav-wrap">
          <div class="nav">
            <div class="nav-brand">QUIETBJ</div>
            <div class="nav-links">
              <a href="#how-it-works">工作原理</a>
              <a href="#faqs">常见问题</a>
              <a href="#insights">观点文章</a>
              <a href="#contact">联系咨询</a>
              <a href="#api">数据接口</a>
              <a href="#contact" class="nav-login">登录</a>
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
          <div class="search-title">搜索静噪分™</div>
          <div class="search-copy">输入北京小区名称或街道地址。系统优先匹配本地样本库；未命中时，若已配置高德 Key，将自动进行在线估算。</div>
        """,
        unsafe_allow_html=True,
    )

    result = None
    status = None
    if "query" not in st.session_state:
        st.session_state.query = ""

    st.markdown('<div class="search-shell">', unsafe_allow_html=True)
    with st.form("hero_search", clear_on_submit=False):
        c1, c2, c3 = st.columns([7.0, 1.25, 1.45])
        with c1:
            query = st.text_input(
                "搜索北京小区或地址",
                value=st.session_state.query,
                placeholder="请输入北京小区名、楼盘名或街道地址",
                label_visibility="collapsed",
            )
        with c2:
            go_clicked = st.form_submit_button("开始查询", type="primary", use_container_width=True)
        with c3:
            reset_clicked = st.form_submit_button("重新输入", use_container_width=True)

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
    reasons = []
    if score_info["road"] <= 25:
        reasons.append("远离环路、快速路与主干线，对外部车流噪音更有利。")
    elif score_info["road"] >= 60:
        reasons.append("靠近环路、高速或主干线，外部交通噪音对评分形成明显拖累。")

    if score_info["far_penalty"] <= 25:
        reasons.append("容积率偏低，内部人车活动更克制，整体居住安静度更占优。")
    elif score_info["far_penalty"] >= 70:
        reasons.append("容积率偏高，楼间距与密度压力较大，内部环境安静度被拉低。")

    if score_info["building_acoustic"] >= 75:
        reasons.append("楼体隔声代理值处于中上水平，对日常居住体感形成支撑。")
    elif score_info["building_acoustic"] <= 55:
        reasons.append("楼体隔声代理值一般，建议后续结合楼栋、朝向与楼层继续细化判断。")

    if score_info["complaints"] >= 60:
        reasons.append("周边噪音投诉热度偏高，说明体感扰动可能不止来自道路。")

    while len(reasons) < 3:
        reasons.append("当前结果仍属于模型估算值，后续可继续升级到楼栋级与朝向级修正。")

    source_label = "本地样本库" if result.get("source") == "sample" else "在线估算"
    title = result.get("community_name") or "北京地址结果"
    district = result.get("district", "")
    address = result.get("address", "")

    st.markdown('<div class="content">', unsafe_allow_html=True)
    st.markdown(
        f'<div class="intro-strip">查询来源：<b>{source_label}</b>。当前模型优先强调北京环路、高速与快速路干线影响，并结合容积率与楼体隔声代理值，给出 50–100 分的住宅安静度估算。</div>',
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
            '<div class="muted">这是一个面向北京住宅场景的静噪评分模型。它不会替代实地看房，但能先替你筛掉一部分高噪音风险地址。</div>',
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
        '<div class="small-note">下一步若要继续提升准确度，可以增加楼栋位置、朝向、楼层与是否临主路等信息。</div>',
        unsafe_allow_html=True,
    )
    st.markdown('</div>', unsafe_allow_html=True)


def render_status(status: str | None) -> None:
    if status == "empty":
        st.info("请先输入北京小区名或地址，再点击“开始查询”。")
    elif status == "not_found":
        api_key = get_amap_api_key()
        if api_key:
            st.warning("当前地址未能从样本库或高德在线估算中返回有效结果。建议换成更完整的地址，或先尝试：新龙城、望京西园四区、天通苑东一区。")
        else:
            st.warning("本地样本库没有命中，而且当前未配置高德 Key，暂时无法在线估算。先在 Streamlit Cloud 的 Secrets 里填写 `AMAP_API_KEY`。")



def render_knowledge_sections() -> None:
    st.markdown('<div class="knowledge-wrap">', unsafe_allow_html=True)
    st.markdown(
        """
        <div id="how-it-works" class="anchor"></div>
        <div class="section-card">
          <div class="section-title">工作原理介绍</div>
          <div class="section-subtitle">QuietBJ 不是实测分贝仪，而是一个面向北京住宅场景的地址级静噪筛选工具。它优先看环路、高速、快速路与主干线影响，再结合容积率、楼体隔声代理值与投诉热度，对住宅安静度做一个 50–100 分的前置判断。</div>
          <div class="article-grid">
            <div class="article-item">
              <h3>第一步：看外部道路风险</h3>
              <p>北京住宅最先拉开差距的，往往不是内部园林，而是离环路、高架、快速路和主干道有多近。模型会把这部分作为最大权重。</p>
            </div>
            <div class="article-item">
              <h3>第二步：看社区密度与楼体</h3>
              <p>同样是地段不错的小区，容积率更高、楼间距更紧、楼体隔声更弱的项目，长期体感往往更吵。QuietBJ 会把这些结构性因素纳入修正。</p>
            </div>
            <div class="article-item">
              <h3>第三步：做地址级估算</h3>
              <p>如果本地样本库命中，就直接给出分数；没有命中时，会调用高德做在线估算。最终结果适合做第一轮筛选，不替代实地看房。</p>
            </div>
          </div>
        </div>

        <div id="faqs" class="anchor"></div>
        <div class="section-card">
          <div class="section-title">常见问题解释</div>
          <div class="section-subtitle">这部分回答用户在看房、租房和选址时最常问的几个问题。</div>
          <div class="article-grid">
            <div class="article-item">
              <h3>为什么分数不是实测分贝？</h3>
              <p>因为绝大多数地址没有连续可得的楼栋级实时噪声传感器。QuietBJ 采用的是模型估算，更适合批量初筛。</p>
            </div>
            <div class="article-item">
              <h3>为什么同一小区不同楼栋会不一样？</h3>
              <p>同一小区里，临主路、靠大门、靠商业、被前排楼遮挡与否，都会显著改变噪声体感。这也是 QuietBJ 下一步要升级到楼栋级的重要原因。</p>
            </div>
            <div class="article-item">
              <h3>分数能直接代替实地看房吗？</h3>
              <p>不能。它更像一个高效的前置过滤器：先排掉明显高风险地址，再把精力留给更值得看的房源。</p>
            </div>
          </div>
        </div>

        <div id="insights" class="anchor"></div>
        <div class="section-card">
          <div class="section-title">住宅噪音的观点文章</div>
          <div class="section-subtitle">下面这些观点不是法律意见，而是更贴近真实居住体验的判断框架。</div>
          <div class="article-grid">
            <div class="article-item">
              <h3>观点一：地段不是一切，安静本身也是稀缺资产</h3>
              <p>在大城市里，很多房源的溢价不是来自装修，而是来自可持续的安静感。真正好的住宅，通常能在通勤、配套和安静度之间找到平衡。</p>
            </div>
            <div class="article-item">
              <h3>观点二：地图上看着不远，体感可能完全不同</h3>
              <p>离快速路 150 米和离快速路 350 米，看起来只是两百米差距，但在夜间、雨天、低楼层和无遮挡场景下，体感差异常常非常大。</p>
            </div>
            <div class="article-item">
              <h3>观点三：噪音判断要尽量前置</h3>
              <p>一套房子的户型、装修、楼龄都可以改善，但如果外部交通噪音先天太强，后续改造空间有限。先看噪音，再谈细节，效率往往更高。</p>
            </div>
          </div>
        </div>

        <div id="contact" class="anchor"></div>
        <div class="section-card">
          <div class="section-title">联系咨询</div>
          <div class="section-subtitle">如果你准备把 QuietBJ 扩展成楼栋级、楼层级或选房决策工具，可以继续补充数据源与产品说明。</div>
          <div class="contact-strip">
            <div class="contact-chip">可继续扩展：楼栋位置 / 朝向 / 楼层 / 楼间遮挡 / 实地反馈</div>
            <div class="contact-chip">商务方向：住宅筛选、租赁选址、地产信息服务</div>
          </div>
        </div>

        <div id="api" class="anchor"></div>
        <div class="section-card">
          <div class="section-title">数据接口</div>
          <div class="section-subtitle">当前版本仍以本地样本库和高德在线估算为主。未来如要做稳定 API，建议分成小区库、楼栋库、道路特征库和用户反馈库四层。</div>
          <div class="article-grid">
            <div class="article-item">
              <h3>输入层</h3>
              <p>地址、小区名、楼栋号、朝向、楼层。</p>
            </div>
            <div class="article-item">
              <h3>特征层</h3>
              <p>道路距离、轨道影响、容积率、楼体隔声代理值、投诉热度。</p>
            </div>
            <div class="article-item">
              <h3>输出层</h3>
              <p>静噪分、分数解释、风险标签、后续看房建议。</p>
            </div>
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    st.markdown('</div>', unsafe_allow_html=True)


def main() -> None:
    inject_css()
    render_nav()
    df = load_communities()
    result, status = render_hero(df)
    if result:
        render_result(result)
    else:
        render_status(status)
    render_knowledge_sections()


if __name__ == "__main__":
    main()
