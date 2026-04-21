from __future__ import annotations

import base64
from pathlib import Path
from typing import Any
import re
import time

import streamlit as st

from amap_provider import AMapProvider
from community_repository import CommunityRepository
from config import BACKGROUND_FILE, COMMUNITIES_FILE, COMMUNITY_ZONES_FILE, DEFAULT_BASE_SCORE, get_amap_api_key
from noise_point_engine import NoisePointEngine
from score_engine import ScoreEngine
from text_match import strip_unit_details, normalize_text, similarity
from zone_repository import ZoneRepository

st.set_page_config(page_title="QuietBJ｜安宁北京", page_icon="🔇", layout="wide")


# ---------- shared helpers ----------
def file_to_base64(path: str | Path) -> str:
    return base64.b64encode(Path(path).read_bytes()).decode("utf-8")


def label_score(score: int) -> str:
    if score >= 90:
        return "安静度较高"
    if score >= 80:
        return "安静度良好"
    if score >= 70:
        return "环境较稳定"
    if score >= 60:
        return "略受外部环境影响"
    return "外部环境影响较明显"


def build_summary_line(signals: list[dict[str, Any]]) -> str:
    if not signals:
        return "当前没有识别到足够强的外部环境影响线索，整体更接近中性楼栋。"
    ordered = sorted(signals, key=lambda x: int(x.get("penalty", 0)), reverse=True)
    labels = [str(item.get("label", "")).strip() for item in ordered[:2] if str(item.get("label", "")).strip()]
    if len(labels) == 1:
        return f"该楼栋当前主要受{labels[0]}影响。"
    return f"该楼栋当前主要受{labels[0]}与{labels[1]}影响。"


def init_search_state() -> None:
    st.session_state.setdefault("search_input", st.session_state.get("last_query", ""))
    st.session_state.setdefault("hero_query_input", st.session_state.get("search_input", st.session_state.get("last_query", "")))
    st.session_state.setdefault("selected_search_suggestion", "")
    st.session_state.setdefault("pending_search_value", "")
    st.session_state.setdefault("suggestion_cache", {})
    st.session_state.setdefault("suggestion_request_count", 0)
    st.session_state.setdefault("suggestion_last_nonempty", "")


def reset_suggestion_session() -> None:
    st.session_state["selected_search_suggestion"] = ""
    st.session_state["suggestion_request_count"] = 0
    st.session_state["suggestion_last_nonempty"] = ""
    st.session_state["hero_query_input"] = st.session_state.get("search_input", "")
    # keep cache to save money


def trigger_ready_for_suggestions(query: str) -> bool:
    q = query.strip()
    if not q:
        return False
    cjk_count = len(re.findall(r"[\u4e00-\u9fff]", q))
    compact = re.sub(r"\s+", "", q)
    # 省钱模式：至少 3 个汉字，或 4 个非空字符才开始联想
    return cjk_count >= 3 or len(compact) >= 4


def build_local_suggestions(query: str, community_repo: CommunityRepository, limit: int = 5) -> list[dict[str, str]]:
    q = query.strip()
    cleaned = strip_unit_details(q)
    norm_q = normalize_text(cleaned)
    if not norm_q:
        return []
    rows: list[tuple[float, dict[str, str]]] = []
    seen: set[str] = set()
    for _, row in community_repo.df.iterrows():
        row_dict = row.to_dict()
        district = str(row_dict.get("district", "")).strip()
        community_name = str(row_dict.get("community_name", "")).strip()
        address = str(row_dict.get("address", "")).strip()
        aliases = [x.strip() for x in str(row_dict.get("aliases", "")).split("|") if x.strip()]
        candidates = [community_name] + aliases
        best_score = 0.0
        best_value = ""
        for cand in candidates:
            nc = normalize_text(cand)
            if not nc:
                continue
            if norm_q not in nc and nc not in norm_q and similarity(norm_q, nc) < 0.55:
                continue
            score = similarity(norm_q, nc)
            if norm_q in nc or nc in norm_q:
                score += 0.10
            if cand == community_name:
                score += 0.04
            if score > best_score:
                best_score = score
                best_value = cand
        if best_score <= 0:
            continue
        value = community_name or best_value
        key = f"{value}|{district}"
        if key in seen:
            continue
        seen.add(key)
        rows.append((
            best_score,
            {
                "value": value,
                "primary": value,
                "secondary": f"{district} {address}".strip(),
                "source": "local",
            },
        ))
    rows.sort(key=lambda x: x[0], reverse=True)
    return [item for _, item in rows[:limit]]


def build_remote_suggestions(query: str, amap: AMapProvider, limit: int = 5) -> list[dict[str, str]]:
    q = query.strip()
    if not q or not amap.enabled():
        return []
    cache_key = f"bj::{q}"
    cache = st.session_state["suggestion_cache"]
    now = time.time()
    cached = cache.get(cache_key)
    if cached and now - float(cached.get("ts", 0)) < 600:
        return cached.get("items", [])

    if st.session_state.get("suggestion_request_count", 0) >= 4:
        return []

    tips = amap.input_tips(q)
    st.session_state["suggestion_request_count"] = st.session_state.get("suggestion_request_count", 0) + 1

    items: list[tuple[float, dict[str, str]]] = []
    seen: set[str] = set()
    for tip in tips:
        name = str(tip.get("name", "")).strip()
        district = str(tip.get("district", "")).strip()
        address = str(tip.get("address", "")).strip()
        if not name:
            continue
        score = 0.0
        if "北京" in district or district.endswith("区"):
            score += 1.2
        text = f"{district}{name}{address}"
        if any(tok in text for tok in ["号楼", "栋", "座"]):
            score += 0.9
        if any(tok in text for tok in ["小区", "社区", "苑", "园", "里", "城", "区"]):
            score += 0.5
        if any(tok in text for tok in ["地铁", "公交", "站", "酒店", "公园", "大厦"]):
            score -= 0.35
        key = f"{name}|{district}|{address}"
        if key in seen:
            continue
        seen.add(key)
        items.append((score, {
            "value": name,
            "primary": name,
            "secondary": f"{district} {address}".strip(),
            "source": "amap",
        }))
    items.sort(key=lambda x: x[0], reverse=True)
    results = [item for _, item in items[:limit]]
    cache[cache_key] = {"ts": now, "items": results}
    return results


def merged_suggestions(query: str, community_repo: CommunityRepository, amap: AMapProvider) -> list[dict[str, str]]:
    if not trigger_ready_for_suggestions(query):
        return []
    local_items = build_local_suggestions(query, community_repo, limit=5)
    # 省钱：本地有 3 条及以上候选时，不打高德
    remote_items: list[dict[str, str]] = []
    if len(local_items) < 3:
        remote_items = build_remote_suggestions(query, amap, limit=5)

    merged: list[dict[str, str]] = []
    seen: set[str] = set()
    for item in local_items + remote_items:
        key = f"{item['primary']}|{item['secondary']}"
        if key in seen:
            continue
        seen.add(key)
        merged.append(item)
        if len(merged) >= 5:
            break
    return merged


def parse_geocode_result(query: str, community_repo: CommunityRepository, amap: AMapProvider) -> tuple[dict[str, Any], list[dict[str, Any]], dict[str, Any] | None, str, dict[str, Any] | None]:
    cleaned_query = strip_unit_details(query)
    tips = amap.input_tips(query) if amap.enabled() else []
    district_hint = str(tips[0].get("district", "")).strip() if tips else ""
    community_match = community_repo.search(cleaned_query, district=district_hint)
    geocode_full = amap.geocode(query) if amap.enabled() else None
    geocode_clean = amap.geocode(cleaned_query) if amap.enabled() and not geocode_full else None
    geocode_used = geocode_full or geocode_clean
    building_location_text = str(geocode_used.get("location", "")).strip() if geocode_used else ""
    regeo = amap.reverse_geocode(building_location_text) if amap.enabled() and building_location_text else None

    if community_match:
        community_row = dict(community_match.row)
        community_row["_match_source"] = f"本地小区库 / {community_match.source}"
        community_row["_match_confidence"] = round(community_match.score, 2)
        community_row["_query_used"] = community_match.query_used
    else:
        community_row = {
            "community_code": "TEMP-DEFAULT",
            "community_name": cleaned_query or query,
            "district": district_hint or str((geocode_used or {}).get("district", "")).strip(),
            "address": str((geocode_used or {}).get("formatted_address", "")).strip(),
            "aliases": "",
            "far_ratio": "",
            "build_year": "",
            "base_score": DEFAULT_BASE_SCORE,
            "_match_source": "未匹配到本地小区样本，当前按标准基准分估算",
            "_match_confidence": "",
            "_query_used": cleaned_query,
        }
    return community_row, tips, regeo, building_location_text, geocode_used


def compute_position_result(zone_options: list[dict[str, Any]], community_row: dict[str, Any], score_engine: ScoreEngine, noise_penalty: int, selected_name: str) -> dict[str, Any]:
    zone_map = {str(z.get("zone_name", "")): z for z in zone_options}
    zone_row = zone_map[selected_name]
    zone_adjust = int(float(zone_row.get("adjustment_score", 0)))
    result = score_engine.final_score(
        DEFAULT_BASE_SCORE,
        zone_adjust,
        noise_penalty,
        community_row.get("far_ratio", ""),
        community_row.get("build_year", ""),
    )
    result["zone_name"] = selected_name
    result["zone_description"] = zone_row.get("description", "按当前楼栋位置调整")
    return result


# ---------- styles ----------
def render_styles(result_mode: bool) -> None:
    bg_base64 = file_to_base64(BACKGROUND_FILE)
    app_bg = "#f4f6f3" if result_mode else "transparent"
    main_bg = "#f4f6f3" if result_mode else "transparent"
    bg_layer = "" if result_mode else f'<div class="bg-layer"></div>'
    st.markdown(
        f"""
        <style>
        :root {{
            --font-display: "Songti SC", "Noto Serif SC", "Source Han Serif SC", serif;
            --font-sans: -apple-system, BlinkMacSystemFont, "SF Pro Text", "PingFang SC", "Hiragino Sans GB", "Helvetica Neue", Arial, sans-serif;
        }}
        html, body, [class*="css"], .stApp {{
            font-family: var(--font-sans) !important;
            color: #17211b;
        }}
        .stApp, [data-testid="stAppViewContainer"], [data-testid="stHeader"], [data-testid="stToolbar"], section.main {{
            background: {app_bg} !important;
        }}
        .block-container {{
            max-width: 1160px !important;
            padding-top: 0 !important;
            padding-left: 1.2rem !important;
            padding-right: 1.2rem !important;
            padding-bottom: 4rem !important;
        }}
        [data-testid="stMainBlockContainer"] {{background: {main_bg} !important;}}
        .bg-layer {{
            position: fixed; inset: 0; z-index: -20; pointer-events: none;
            background-image: linear-gradient(180deg, rgba(8,16,13,0.22), rgba(8,16,13,0.58)), url("data:image/jpeg;base64,{bg_base64}");
            background-size: cover; background-position: center center; background-repeat: no-repeat;
        }}
        .topbar {{display:flex; justify-content:space-between; align-items:center; padding:16px 0 0; color:white;}}
        .topbar.light {{color:#14211b; padding:18px 0 12px;}}
        .brand {{font-size:14px; font-weight:600; letter-spacing:.10em; opacity:.34; font-family: var(--font-sans) !important;}}
        .hero-wrap {{min-height:46vh; display:flex; align-items:flex-start; justify-content:center; padding-top:5vh; text-align:center; color:white;}}
        .hero-kicker {{font-size:11px; letter-spacing:.24em; text-transform:uppercase; opacity:.86; margin-bottom:12px; font-family: var(--font-sans) !important;}}
        .hero-title {{font-size:clamp(42px,6vw,80px); font-weight:700; line-height:1.02; margin:0; text-shadow:0 8px 30px rgba(0,0,0,.24); font-family: var(--font-display) !important; letter-spacing:-0.02em;}}
        .hero-sub {{max-width:760px; margin:14px auto 0; font-size:16px; line-height:1.72; color:rgba(255,255,255,.96); font-family: var(--font-sans) !important;}}
        .hero-note {{display:inline-block; margin-top:16px; padding:10px 16px; border-radius:999px; background:rgba(255,255,255,.08); border:1px solid rgba(255,255,255,.18); color:rgba(255,255,255,.92); font-size:11px; letter-spacing:.04em; font-family: var(--font-sans) !important;}}
        .compact-title {{font-size:13px; letter-spacing:.18em; text-transform:uppercase; color:#6f7c74; margin:4px 0 10px; font-family: var(--font-sans) !important;}}
        .result-page-intro {{color:#55635b; font-size:14px; line-height:1.7; margin-top:2px; margin-bottom:10px;}}

        div[data-testid="stTextInputRootElement"] input {{
            height: 52px !important;
            border-radius: 14px !important;
            border: 1px solid rgba(23,58,45,0.12) !important;
            background: rgba(255,255,255,0.98) !important;
            box-shadow: none !important;
            font-size: 17px !important;
            color: #111111 !important;
            -webkit-text-fill-color: #111111 !important;
            caret-color: #111111 !important;
        }}
        div[data-testid="stTextInputRootElement"] input::placeholder {{
            color: rgba(65,74,70,0.42) !important;
            -webkit-text-fill-color: rgba(65,74,70,0.42) !important;
        }}
        div[data-testid="stWidgetLabel"], div[data-testid="InputInstructions"] {{display:none !important;}}

        div[data-testid="stForm"] {{
            background: {'rgba(255,255,255,0.10)' if not result_mode else '#ffffff'};
            border: 1px solid {'rgba(255,255,255,0.16)' if not result_mode else 'rgba(21,34,26,0.08)'};
            border-radius: 22px;
            padding: 14px;
            backdrop-filter: {'blur(10px)' if not result_mode else 'none'};
            box-shadow: {'0 20px 60px rgba(0,0,0,0.14)' if not result_mode else '0 12px 26px rgba(16,24,19,0.06)'};
        }}
        div[data-testid="stFormSubmitButton"] > button {{height:46px; border-radius:13px; font-weight:700; box-shadow:none !important; font-family: var(--font-sans) !important;}}
        div[data-testid="stFormSubmitButton"] > button[kind="primary"] {{background:#173a2d !important; border:1px solid #173a2d !important; color:white !important;}}
        div[data-testid="stFormSubmitButton"] > button[kind="secondary"] {{background:rgba(255,255,255,0.92) !important; border:1px solid rgba(24,37,31,0.10) !important; color:#31443b !important;}}
        div[data-testid="stButton"] > button[kind="primary"], div[data-testid="stFormSubmitButton"] > button[kind="primary"] {{background:#173a2d !important; border:1px solid #173a2d !important; color:white !important;}}

        
        .suggestion-wrap {{margin-top: 10px; border-radius: 16px; overflow: hidden; background: rgba(255,255,255,0.95); border: 1px solid rgba(21,34,26,0.08);}}
        .suggestion-head {{padding: 10px 14px 6px; font-size: 12px; color: #65746b; letter-spacing: .04em;}}
        .suggestion-row {{padding: 6px 0;}}
        .suggestion-meta {{padding: 0 14px 8px; font-size: 12px; color: #6d7a72;}}
        div[data-testid="stButton"] > button[kind="secondary"] {{background: rgba(255,255,255,0.94) !important; border: 1px solid rgba(24,37,31,0.10) !important; color: #31443b !important;}}
        div[data-testid="stButton"] > button[kind="primary"] {{background:#173a2d !important; border:1px solid #173a2d !important; color:white !important;}}
.search-footnote {{margin-top:10px; text-align:center; color:{'rgba(255,255,255,0.74)' if not result_mode else '#67746c'}; font-size:12px;}}
        .result-shell-title {{font-size:13px; letter-spacing:.18em; text-transform:uppercase; color:#6f7c74; margin-top:8px; margin-bottom:12px; font-family: var(--font-sans) !important;}}
        .card-title {{font-size:24px; font-weight:700; color:#16241e; margin-bottom:6px; font-family: var(--font-display) !important; letter-spacing:-0.01em;}}
        .card-sub {{font-size:14px; line-height:1.7; color:#536159; margin-bottom:10px;}}
        .result-divider {{height:12px;}}
        .subtle {{color:#4f5d55; font-size:13px; line-height:1.7;}}

        div[data-testid="stVerticalBlockBorderWrapper"] {{
            background: rgba(248,250,248,0.98) !important;
            border: 1px solid rgba(21,34,26,0.06) !important;
            border-radius: 22px !important;
            box-shadow: 0 14px 42px rgba(16,24,19,0.08) !important;
            padding: 8px 10px !important;
        }}
        .overview-kicker {{font-size:12px; letter-spacing:.12em; text-transform:uppercase; color:#748178; font-family: var(--font-sans) !important;}}
        .overview-name {{font-size:38px; line-height:1.08; font-weight:700; color:#15231d; margin:8px 0; font-family: var(--font-display) !important; letter-spacing:-0.02em;}}
        .overview-line {{font-size:16px; line-height:1.7; color:#2f4138;}}
        .pill-row {{display:flex; flex-wrap:wrap; gap:10px; margin-top:14px;}}
        .pill {{padding:8px 12px; border-radius:999px; background:#eef3ef; border:1px solid #dde7e1; color:#264335; font-size:13px;}}
        .score-panel {{background:linear-gradient(180deg, #163a2c 0%, #1b583d 100%); color:white; border-radius:24px; padding:26px; box-shadow:0 18px 42px rgba(21,58,43,0.24); min-height:100%;}}
        .score-kicker {{opacity:.78; letter-spacing:.16em; text-transform:uppercase; font-size:12px; font-family: var(--font-sans) !important;}}
        .score-number {{font-size:88px; line-height:1; font-weight:800; margin:10px 0 6px; font-family: var(--font-sans) !important;}}
        .metric-grid {{display:grid; grid-template-columns:repeat(4, minmax(0,1fr)); gap:12px; margin-top:16px;}}
        .metric-box {{background:#f5f8f5; border:1px solid #e5ece7; border-radius:18px; padding:14px;}}
        .metric-label {{font-size:12px; color:#728077; margin-bottom:4px;}}
        .metric-value {{font-size:28px; font-weight:800; color:#182820;}}
        .metric-note {{font-size:12px; color:#5e6c64; margin-top:4px;}}
        .deduct-row {{display:flex; justify-content:space-between; align-items:flex-start; gap:14px; padding:14px 0; border-bottom:1px dashed #e2e9e4;}}
        .deduct-row:last-child {{border-bottom:none;}}
        .deduct-title {{font-size:16px; font-weight:700; color:#1b2a23; font-family: var(--font-display) !important;}}
        .deduct-detail {{font-size:13px; color:#67756d; margin-top:4px;}}
        .deduct-right {{font-size:16px; font-weight:700; color:#173a2d; white-space:nowrap;}}
        .plain-band {{background:#f4f6f3; border-radius:24px; padding:18px 18px 22px; margin-top:14px; box-shadow: inset 0 0 0 1px rgba(21,34,26,0.04);}}

        @media (max-width: 900px) {{
            .block-container {{padding-left:.9rem !important; padding-right:.9rem !important;}}
            .hero-wrap {{min-height:44vh; padding-top:4vh;}}
            .hero-sub {{font-size:14px;}}
            .overview-name {{font-size:32px;}}
            .metric-grid {{grid-template-columns:repeat(2, minmax(0,1fr));}}
        }}
        
/* Strong Streamlit form button overrides */
div[data-testid="stForm"] button[kind="primary"],
div[data-testid="stForm"] button[kind="primaryFormSubmit"],
div[data-testid="stForm"] button[data-testid="baseButton-primary"],
div[data-testid="stForm"] button[data-testid="stBaseButton-primary"] {{
    background: #173a2d !important;
    border: 1px solid #173a2d !important;
    color: #ffffff !important;
    -webkit-text-fill-color: #ffffff !important;
    box-shadow: none !important;
}}
div[data-testid="stForm"] button[kind="primary"]:hover,
div[data-testid="stForm"] button[kind="primaryFormSubmit"]:hover,
div[data-testid="stForm"] button[data-testid="baseButton-primary"]:hover,
div[data-testid="stForm"] button[data-testid="stBaseButton-primary"]:hover {{
    background: #1d4636 !important;
    border-color: #1d4636 !important;
    color: #ffffff !important;
}}
div[data-testid="stForm"] button[kind="secondary"],
div[data-testid="stForm"] button[kind="secondaryFormSubmit"],
div[data-testid="stForm"] button[data-testid="baseButton-secondary"],
div[data-testid="stForm"] button[data-testid="stBaseButton-secondary"] {{
    background: rgba(255,255,255,0.92) !important;
    border: 1px solid rgba(24,37,31,0.10) !important;
    color: #31443b !important;
    -webkit-text-fill-color: #31443b !important;
    box-shadow: none !important;
}}
div[data-testid="stForm"] button[kind="secondary"]:hover,
div[data-testid="stForm"] button[kind="secondaryFormSubmit"]:hover,
div[data-testid="stForm"] button[data-testid="baseButton-secondary"]:hover,
div[data-testid="stForm"] button[data-testid="stBaseButton-secondary"]:hover {{
    background: rgba(255,255,255,0.98) !important;
    border-color: rgba(24,37,31,0.16) !important;
    color: #23352d !important;
}}
div[data-testid="stForm"] button {{
    height: 46px !important;
    border-radius: 13px !important;
    font-weight: 700 !important;
    font-family: var(--font-sans) !important;
}}

</style>
        """,
        unsafe_allow_html=True,
    )
    if bg_layer:
        st.markdown(bg_layer, unsafe_allow_html=True)


# ---------- UI blocks ----------
def render_topbar(light: bool = False) -> None:
    cls = "topbar light" if light else "topbar"
    st.markdown(f'<div class="{cls}"><div class="brand">QuietBJ</div><div></div></div>', unsafe_allow_html=True)


def render_hero() -> None:
    st.markdown(
        """
        <div class="hero-wrap">
            <div>
                <div class="hero-kicker">BEIJING RESIDENTIAL CALM INDEX</div>
                <h1 class="hero-title">安宁北京</h1>
                <div class="hero-sub">楼栋级住宅环境评估引擎。识别小区，定位楼栋，测算道路、商业、学校、医院与轨道暴露。</div>
                <div class="hero-note">标准基准分 · 楼栋位置调整 · 外部环境影响</div>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )



def render_search(compact: bool = False, community_repo: CommunityRepository | None = None, amap: AMapProvider | None = None) -> tuple[str, bool, bool]:
    init_search_state()

    if compact:
        st.markdown('<div class="compact-title">New Search</div>', unsafe_allow_html=True)
        st.markdown('<div class="result-page-intro">继续输入新的北京小区或楼栋地址，系统会重新定位楼栋并更新评估结果。</div>', unsafe_allow_html=True)

    query = st.text_input(
        "hero_query",
        key="search_input",
        placeholder="输入北京小区或楼栋地址，例如：新龙城6号楼 / 花家地西里2号楼",
        label_visibility="collapsed",
    ).strip()

    if not query:
        reset_suggestion_session()
    else:
        st.session_state["suggestion_last_nonempty"] = query

    if st.session_state.get("selected_search_suggestion") and query != st.session_state.get("selected_search_suggestion"):
        st.session_state["selected_search_suggestion"] = ""

    suggestions: list[dict[str, str]] = []
    if community_repo is not None and amap is not None and not compact:
        selected = st.session_state.get("selected_search_suggestion", "")
        if query and query != selected:
            suggestions = merged_suggestions(query, community_repo, amap)

    if suggestions and not compact:
        st.markdown('<div class="suggestion-wrap"><div class="suggestion-head">匹配建议（北京优先 · 本地库优先）</div></div>', unsafe_allow_html=True)
        for idx, item in enumerate(suggestions):
            if st.button(item["primary"], key=f"suggest::{idx}", use_container_width=True):
                st.session_state["search_input"] = item["value"]
                st.session_state["selected_search_suggestion"] = item["value"]
                st.rerun()
            if item.get("secondary"):
                st.markdown(f'<div class="suggestion-meta">{item["secondary"]}</div>', unsafe_allow_html=True)

    left, center, right = st.columns([1.4, 1.2, 1.4])
    with center:
        submit = st.button("开始查询", type="primary", use_container_width=True)

    st.markdown(
        '<div class="search-footnote">省钱模式已启用：2 个汉字后自动联想，优先本地库，只有本地候选不足时才调用高德输入提示。</div>',
        unsafe_allow_html=True,
    )
    return query, submit, False


def render_overview_card(query: str, community_row: dict[str, Any], result: dict[str, Any], signals: list[dict[str, Any]]) -> None:
    with st.container(border=True):
        left, right = st.columns([1.25, 0.95], vertical_alignment="top")
        with left:
            st.markdown('<div class="overview-kicker">Result Overview</div>', unsafe_allow_html=True)
            st.markdown(f'<div class="overview-name">{community_row.get("community_name", "目标小区")}</div>', unsafe_allow_html=True)
            st.markdown(f'<div class="overview-line">{build_summary_line(signals)}</div>', unsafe_allow_html=True)
            pills = [f'<span class="pill">标准基准分 {DEFAULT_BASE_SCORE}</span>']
            district = str(community_row.get("district", "")).strip()
            if district:
                pills.append(f'<span class="pill">{district}</span>')
            source = str(community_row.get("_match_source", "")).strip()
            if source:
                pills.append(f'<span class="pill">{source}</span>')
            st.markdown('<div class="pill-row">' + ''.join(pills) + '</div>', unsafe_allow_html=True)
            st.markdown(
                f'<div class="subtle" style="margin-top:12px;">楼栋输入：{query}｜用于小区匹配的文本：{community_row.get("_query_used", "") or query}</div>',
                unsafe_allow_html=True,
            )
            metric_html = [
                ("标准基准分", str(DEFAULT_BASE_SCORE), "统一基准评估"),
                ("楼栋位置调整", f"{result['zone_adjust']:+d}", "来自楼栋位置"),
                ("建筑条件调整", f"{result['build_bonus']:+d}", "来自楼龄代理值"),
                ("外部环境影响", f"{result['noise_penalty']}", "来自道路 / 商业 / 学校 / 轨道"),
            ]
            st.markdown(
                '<div class="metric-grid">' + ''.join(
                    [f'<div class="metric-box"><div class="metric-label">{a}</div><div class="metric-value">{b}</div><div class="metric-note">{c}</div></div>' for a,b,c in metric_html]
                ) + '</div>',
                unsafe_allow_html=True,
            )
        with right:
            st.markdown(
                f'''
                <div class="score-panel">
                    <div class="score-kicker">Quiet Score</div>
                    <div class="score-number">{result['final_score']}</div>
                    <h3>{label_score(result['final_score'])}</h3>
                    <div style="line-height:1.75; font-size:14px; opacity:0.96;">系统基于楼栋位置、道路距离、商业暴露、学校医院和轨道交通进行估算，用于快速判断这套房是否值得继续看。</div>
                </div>
                ''',
                unsafe_allow_html=True,
            )


def render_penalty_card(noise_summary: dict[str, Any]) -> None:
    signals = noise_summary.get("signals", [])
    with st.container(border=True):
        st.markdown('<div class="card-title">影响来源</div>', unsafe_allow_html=True)
        st.markdown('<div class="card-sub">先看主要影响项，再决定要不要继续实勘。这一层只展示对当前楼栋体感最重要的外部环境因素。</div>', unsafe_allow_html=True)
        if not signals:
            st.info("当前没有识别到明显的外部环境影响，系统没有形成显著的影响值。")
        else:
            rows = []
            for sig in sorted(signals, key=lambda x: int(x.get("penalty", 0)), reverse=True):
                rows.append(
                    f'<div class="deduct-row"><div><div class="deduct-title">{sig.get("label", "")}</div><div class="deduct-detail">{sig.get("detail", "")}</div></div><div class="deduct-right">{sig.get("distance_m", "-")}m ｜ 影响值 {int(sig.get("penalty", 0))}</div></div>'
                )
            st.markdown(''.join(rows), unsafe_allow_html=True)
            st.markdown(f"<div class='subtle' style='margin-top:10px;'>总体环境影响值：<strong style='color:#173a2d;'>{int(noise_summary.get('total_penalty', 0))}</strong></div>", unsafe_allow_html=True)


def render_position_card(result: dict[str, Any], zone_labels: list[str], zone_key: str) -> None:
    with st.container(border=True):
        st.markdown('<div class="card-title">楼栋位置调整</div>', unsafe_allow_html=True)
        st.markdown('<div class="card-sub">该部分用于模拟不同楼栋位置语境下的环境差异，例如临街、中央区或内排安静区。</div>', unsafe_allow_html=True)
        st.selectbox("楼栋位置", zone_labels, key=zone_key, label_visibility="collapsed")
        c1, c2, c3, c4 = st.columns(4)
        items = [
            (c1, "标准基准", DEFAULT_BASE_SCORE, "统一起点评估"),
            (c2, "楼栋位置", f"{result['zone_adjust']:+d}", result['zone_name']),
            (c3, "建筑加分", f"{result['build_bonus']:+d}", "楼龄代理值"),
            (c4, "密度调整", f"-{result['density_penalty']}", "容积率代理值"),
        ]
        for col, title, value, note in items:
            with col:
                st.markdown(
                    f'<div class="metric-box"><div class="metric-label">{title}</div><div class="metric-value">{value}</div><div class="metric-note">{note}</div></div>',
                    unsafe_allow_html=True,
                )
        st.markdown(f"<div class='subtle' style='margin-top:12px;'>位置说明：{result['zone_description']}。</div>", unsafe_allow_html=True)


def render_debug_card(geocode_used: dict[str, Any] | None, building_location_text: str, community_row: dict[str, Any], tip_list: list[dict[str, Any]], regeo: dict[str, Any] | None) -> None:
    with st.expander("地址识别核查", expanded=False):
        c1, c2 = st.columns(2)
        with c1:
            st.markdown("**楼栋点位**")
            st.write(f"标准化地址：{str((geocode_used or {}).get('formatted_address', '')).strip() or '—'}")
            st.write(f"location：{building_location_text or '—'}")
            district = str((geocode_used or {}).get("district", "")).strip() or str(community_row.get("district", "")).strip()
            st.write(f"district：{district or '—'}")
        with c2:
            st.markdown("**高德候选**")
            if tip_list:
                for tip in tip_list[:5]:
                    st.write(f"- {tip.get('name', '')}｜{tip.get('district', '')} {tip.get('address', '')}")
            else:
                st.write("没有拿到输入提示候选。")
        with st.expander("逆地理编码原始结果", expanded=False):
            st.json(regeo if regeo else {"note": "无"})


# ---------- app ----------
def main() -> None:
    if "last_query" not in st.session_state:
        st.session_state["last_query"] = ""

    result_mode = bool(st.session_state.get("last_query", "").strip())
    render_styles(result_mode=result_mode)

    community_repo = CommunityRepository(str(COMMUNITIES_FILE))
    zone_repo = ZoneRepository(str(COMMUNITY_ZONES_FILE))
    amap = AMapProvider(get_amap_api_key(st.secrets))
    noise_engine = NoisePointEngine()
    score_engine = ScoreEngine()

    if result_mode:
        render_topbar(light=True)
        query, submitted, clear = render_search(compact=True, community_repo=community_repo, amap=amap)
    else:
        render_topbar(light=False)
        render_hero()
        left, center, right = st.columns([1.0, 4.9, 1.0])
        with center:
            query, submitted, clear = render_search(compact=False, community_repo=community_repo, amap=amap)

    if clear:
        st.session_state["last_query"] = ""
        st.session_state["search_input"] = ""
        st.session_state["hero_query_input"] = ""
        reset_suggestion_session()
        for key in list(st.session_state.keys()):
            if key.startswith("zone_select::"):
                del st.session_state[key]
        st.rerun()
    if submitted:
        st.session_state["last_query"] = query.strip()
        st.session_state["search_input"] = query.strip()
        st.session_state["hero_query_input"] = query.strip()
        reset_suggestion_session()
        st.rerun()

    query = st.session_state.get("last_query", "").strip()
    if not query:
        return

    community_row, tip_list, regeo, building_location_text, geocode_used = parse_geocode_result(query, community_repo, amap)
    poi_results: dict[str, list[dict[str, Any]]] = {}
    if amap.enabled() and building_location_text:
        poi_results = {
            "school": amap.search_around(building_location_text, "学校", radius=1200),
            "hospital": amap.search_around(building_location_text, "医院", radius=1500),
            "commercial": amap.search_around(building_location_text, "便利店 超市 商场 购物服务 生活服务", radius=300),
            "restaurant": amap.search_around(building_location_text, "餐饮服务", radius=300),
            "rail": amap.search_around(building_location_text, "地铁站", radius=800),
        }
    noise_summary = noise_engine.evaluate(regeo, poi_results)

    community_code = str(community_row.get("community_code", ""))
    zone_options = zone_repo.get_by_community(community_code)
    if not zone_options:
        zone_options = [
            {"zone_code": "street_front", "zone_name": "临主路首排", "adjustment_score": -8, "description": "直接朝向主路或高速一侧，车辆持续噪音更强。"},
            {"zone_code": "secondary_street", "zone_name": "次临街区", "adjustment_score": -4, "description": "不在首排，但仍会明显感受到道路噪音。"},
            {"zone_code": "central_inner", "zone_name": "小区中央", "adjustment_score": 0, "description": "按小区平均位置处理。"},
            {"zone_code": "quiet_inner", "zone_name": "内排安静区", "adjustment_score": 6, "description": "更靠小区内部，有前排遮挡，通常更安静。"},
            {"zone_code": "gate_side", "zone_name": "出入口附近", "adjustment_score": -5, "description": "出入口、人车流与停车场会增加体感噪音。"},
            {"zone_code": "commercial_edge", "zone_name": "靠底商/商业", "adjustment_score": -6, "description": "沿街底商、餐饮和生活服务会抬高噪音。"},
        ]

    zone_labels = [str(z.get("zone_name", "")) for z in zone_options]
    default_idx = next((i for i, z in enumerate(zone_options) if str(z.get("zone_code", "")) in {"central_inner", "DEFAULT", "default"}), 0)
    zone_key = f"zone_select::{community_code or 'default'}"
    if zone_key not in st.session_state:
        st.session_state[zone_key] = zone_labels[default_idx]
    selected_name = st.session_state[zone_key]
    if selected_name not in zone_labels:
        selected_name = zone_labels[default_idx]
        st.session_state[zone_key] = selected_name

    result = compute_position_result(zone_options, community_row, score_engine, int(noise_summary.get("total_penalty", 0)), selected_name)

    if result_mode:
        st.markdown('<div class="plain-band">', unsafe_allow_html=True)
    st.markdown('<div class="result-shell-title">Residential Assessment</div>', unsafe_allow_html=True)
    render_overview_card(query, community_row, result, noise_summary.get("signals", []))
    st.markdown('<div class="result-divider"></div>', unsafe_allow_html=True)
    render_penalty_card(noise_summary)
    st.markdown('<div class="result-divider"></div>', unsafe_allow_html=True)
    render_position_card(result, zone_labels, zone_key)
    st.markdown('<div class="result-divider"></div>', unsafe_allow_html=True)
    render_debug_card(geocode_used, building_location_text, community_row, tip_list, regeo)
    if result_mode:
        st.markdown('</div>', unsafe_allow_html=True)


if __name__ == "__main__":
    main()
