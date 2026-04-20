from __future__ import annotations

import base64
from pathlib import Path
from typing import Any

import streamlit as st

from amap_provider import AMapProvider
from community_repository import CommunityRepository
from config import BACKGROUND_FILE, COMMUNITIES_FILE, COMMUNITY_ZONES_FILE, DEFAULT_BASE_SCORE, get_amap_api_key
from noise_point_engine import NoisePointEngine
from score_engine import ScoreEngine
from text_match import strip_unit_details
from zone_repository import ZoneRepository

st.set_page_config(page_title="QuietBJ｜安宁北京", page_icon="🔇", layout="wide")


def file_to_base64(path: str | Path) -> str:
    return base64.b64encode(Path(path).read_bytes()).decode("utf-8")


def render_styles() -> None:
    bg_base64 = file_to_base64(BACKGROUND_FILE)
    st.markdown(
        f"""
        <style>
        .stApp, [data-testid="stAppViewContainer"], [data-testid="stHeader"], [data-testid="stToolbar"], section.main {{
            background: transparent !important;
        }}
        .block-container {{
            max-width: 1160px !important;
            padding-top: 0 !important;
            padding-left: 1.2rem !important;
            padding-right: 1.2rem !important;
            padding-bottom: 4rem !important;
        }}
        .bg-layer {{
            position: fixed;
            inset: 0;
            z-index: -20;
            pointer-events: none;
            background-image: linear-gradient(180deg, rgba(8,16,13,0.22), rgba(8,16,13,0.58)), url("data:image/jpeg;base64,{bg_base64}");
            background-size: cover;
            background-position: center center;
            background-repeat: no-repeat;
        }}
        .topbar {{
            display: flex;
            justify-content: space-between;
            align-items: center;
            padding: 16px 0 0;
            color: white;
        }}
        .brand {{
            font-size: 14px;
            font-weight: 600;
            letter-spacing: 0.10em;
            opacity: 0.36;
        }}
        .hero-wrap {{
            min-height: 46vh;
            display: flex;
            align-items: flex-start;
            justify-content: center;
            padding-top: 5vh;
            text-align: center;
            color: white;
        }}
        .hero-kicker {{
            font-size: 11px;
            letter-spacing: 0.24em;
            text-transform: uppercase;
            opacity: 0.86;
            margin-bottom: 12px;
        }}
        .hero-title {{
            font-size: clamp(42px, 6vw, 80px);
            font-weight: 800;
            line-height: 1.02;
            margin: 0;
            text-shadow: 0 8px 30px rgba(0,0,0,0.24);
        }}
        .hero-sub {{
            max-width: 760px;
            margin: 14px auto 0;
            font-size: 16px;
            line-height: 1.72;
            color: rgba(255,255,255,0.96);
        }}
        .hero-note {{
            display: inline-block;
            margin-top: 16px;
            padding: 10px 16px;
            border-radius: 999px;
            background: rgba(255,255,255,0.08);
            border: 1px solid rgba(255,255,255,0.18);
            color: rgba(255,255,255,0.92);
            font-size: 11px;
            letter-spacing: 0.04em;
        }}
        div[data-testid="stTextInputRootElement"] input {{
            height: 52px !important;
            border-radius: 14px !important;
            border: none !important;
            background: rgba(255,255,255,0.98) !important;
            box-shadow: none !important;
            font-size: 17px !important;
        }}
        div[data-testid="stTextInputRootElement"] input::placeholder {{
            color: rgba(65,74,70,0.42) !important;
        }}
        div[data-testid="stWidgetLabel"], div[data-testid="InputInstructions"] {{
            display: none !important;
        }}
        div[data-testid="stForm"] {{
            background: rgba(255,255,255,0.10);
            border: 1px solid rgba(255,255,255,0.16);
            border-radius: 22px;
            padding: 14px;
            backdrop-filter: blur(10px);
            box-shadow: 0 20px 60px rgba(0,0,0,0.14);
        }}
        div[data-testid="stFormSubmitButton"] > button {{
            height: 46px;
            border-radius: 13px;
            font-weight: 700;
            box-shadow: none !important;
        }}
        div[data-testid="stFormSubmitButton"] > button[kind="primary"] {{
            background: #173a2d !important;
            border: 1px solid #173a2d !important;
            color: white !important;
        }}
        div[data-testid="stFormSubmitButton"] > button[kind="secondary"] {{
            background: rgba(255,255,255,0.88) !important;
            border: 1px solid rgba(24,37,31,0.08) !important;
            color: #31443b !important;
        }}
        .search-footnote {{
            margin-top: 10px;
            text-align: center;
            color: rgba(255,255,255,0.74);
            font-size: 12px;
        }}
        .result-shell-title {{
            font-size: 13px;
            letter-spacing: 0.18em;
            text-transform: uppercase;
            color: #6f7c74;
            margin-top: 18px;
            margin-bottom: 12px;
        }}
        .card-title {{
            font-size: 24px;
            font-weight: 800;
            color: #16241e;
            margin-bottom: 6px;
        }}
        .card-sub {{
            font-size: 14px;
            line-height: 1.7;
            color: #6d7a72;
            margin-bottom: 10px;
        }}
        .hero-divider {{
            height: 20px;
        }}
        div[data-testid="stVerticalBlockBorderWrapper"] {{
            background: rgba(248,250,248,0.98) !important;
            border: 1px solid rgba(21,34,26,0.06) !important;
            border-radius: 22px !important;
            box-shadow: 0 14px 42px rgba(16,24,19,0.08) !important;
            padding: 8px 10px !important;
        }}
        .overview-kicker {{
            font-size: 12px;
            letter-spacing: 0.12em;
            text-transform: uppercase;
            color: #748178;
        }}
        .overview-name {{
            font-size: 38px;
            line-height: 1.08;
            font-weight: 800;
            color: #15231d;
            margin: 8px 0;
        }}
        .overview-line {{
            font-size: 16px;
            line-height: 1.7;
            color: #2f4138;
        }}
        .pill-row {{
            display: flex;
            flex-wrap: wrap;
            gap: 10px;
            margin-top: 14px;
        }}
        .pill {{
            padding: 8px 12px;
            border-radius: 999px;
            background: #eef3ef;
            border: 1px solid #dde7e1;
            color: #264335;
            font-size: 13px;
        }}
        .score-panel {{
            background: linear-gradient(180deg, #163a2c 0%, #1b583d 100%);
            color: white;
            border-radius: 24px;
            padding: 26px;
            box-shadow: 0 18px 42px rgba(21,58,43,0.24);
            min-height: 100%;
        }}
        .score-kicker {{
            opacity: 0.78;
            letter-spacing: 0.16em;
            text-transform: uppercase;
            font-size: 12px;
        }}
        .score-number {{
            font-size: 88px;
            line-height: 1;
            font-weight: 800;
            margin: 10px 0 6px;
        }}
        .metric-grid {{
            display: grid;
            grid-template-columns: repeat(4, minmax(0,1fr));
            gap: 12px;
            margin-top: 16px;
        }}
        .metric-box {{
            background: #f5f8f5;
            border: 1px solid #e5ece7;
            border-radius: 18px;
            padding: 14px;
        }}
        .metric-label {{
            font-size: 12px;
            color: #728077;
            margin-bottom: 4px;
        }}
        .metric-value {{
            font-size: 28px;
            font-weight: 800;
            color: #182820;
        }}
        .metric-note {{
            font-size: 12px;
            color: #78847d;
            margin-top: 4px;
        }}
        .deduct-row {{
            display: flex;
            justify-content: space-between;
            align-items: flex-start;
            gap: 14px;
            padding: 14px 0;
            border-bottom: 1px dashed #e2e9e4;
        }}
        .deduct-row:last-child {{
            border-bottom: none;
        }}
        .deduct-title {{
            font-size: 16px;
            font-weight: 700;
            color: #1b2a23;
        }}
        .deduct-detail {{
            font-size: 13px;
            color: #728078;
            margin-top: 4px;
        }}
        .deduct-right {{
            font-size: 16px;
            font-weight: 700;
            color: #173a2d;
            white-space: nowrap;
        }}
        .result-divider {{
            height: 12px;
        }}
        .subtle {{
            color: #6f7b73;
            font-size: 13px;
            line-height: 1.7;
        }}
        @media (max-width: 900px) {{
            .block-container {{
                padding-left: 0.9rem !important;
                padding-right: 0.9rem !important;
            }}
            .hero-wrap {{
                min-height: 44vh;
                padding-top: 4vh;
            }}
            .hero-sub {{font-size: 14px;}}
            .overview-name {{font-size: 32px;}}
            .metric-grid {{grid-template-columns: repeat(2, minmax(0,1fr));}}
        }}
        </style>
        <div class="bg-layer"></div>
        """,
        unsafe_allow_html=True,
    )


def render_header() -> None:
    st.markdown('<div class="topbar"><div class="brand">QuietBJ</div><div></div></div>', unsafe_allow_html=True)
    st.markdown(
        """
        <div class="hero-wrap">
            <div>
                <div class="hero-kicker">BEIJING RESIDENTIAL CALM INDEX</div>
                <h1 class="hero-title">安宁北京</h1>
                <div class="hero-sub">楼栋级住宅环境评估引擎。识别小区，定位楼栋，测算道路、商业、学校、医院与轨道暴露。</div>
                <div class="hero-note">标准基准分 · 楼栋位置修正 · 外部暴露惩罚</div>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_search() -> tuple[str, bool, bool]:
    left, center, right = st.columns([1.0, 4.9, 1.0])
    with center:
        with st.form("hero_search", clear_on_submit=False):
            query = st.text_input(
                "hero_query",
                placeholder="输入北京小区或楼栋地址，例如：新龙城6号楼 / 花家地西里2号楼",
                label_visibility="collapsed",
            )
            a, b, c = st.columns([5.0, 1.3, 1.0])
            with b:
                submit = st.form_submit_button("开始查询", type="primary", use_container_width=True)
            with c:
                clear = st.form_submit_button("清空", use_container_width=True)
        st.markdown(
            '<div class="search-footnote">建议输入：小区名 + 楼号。系统会先识别小区，再围绕更接近楼栋的坐标测算外部噪音暴露。</div>',
            unsafe_allow_html=True,
        )
    return query, submit, clear


def label_score(score: int) -> str:
    if score >= 90:
        return "非常安静"
    if score >= 80:
        return "较为安静"
    if score >= 70:
        return "中等偏静"
    if score >= 60:
        return "略受噪音影响"
    return "噪音偏高"


def build_summary_line(signals: list[dict[str, Any]]) -> str:
    if not signals:
        return "当前没有捕捉到足够强的外部噪音暴露，整体更接近中性楼栋。"
    ordered = sorted(signals, key=lambda x: int(x.get("penalty", 0)), reverse=True)
    top = ordered[:2]
    labels = [str(item.get("label", "")) for item in top if str(item.get("label", "")).strip()]
    if len(labels) == 1:
        return f"该楼栋当前主要受{labels[0]}影响。"
    return f"该楼栋当前主要受{labels[0]}与{labels[1]}影响。"


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
            "_match_source": "未命中本地小区库，按标准基准分处理",
            "_match_confidence": "",
            "_query_used": cleaned_query,
        }
    return community_row, tips, regeo, building_location_text, geocode_used


def render_overview_card(query: str, community_row: dict[str, Any], result: dict[str, int], signals: list[dict[str, Any]]) -> None:
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
            st.markdown('<div class="pill-row">' + "".join(pills) + '</div>', unsafe_allow_html=True)
            st.markdown(
                f'<div class="subtle" style="margin-top:12px;">楼栋输入：{query}｜用于小区匹配的文本：{community_row.get("_query_used", "") or query}</div>',
                unsafe_allow_html=True,
            )
            metric_html = [
                ("标准基准", str(DEFAULT_BASE_SCORE), "统一起点评估"),
                ("楼栋修正", f"{result['zone_adjust']:+d}", "来自楼栋位置"),
                ("建筑加分", f"{result['build_bonus']:+d}", "来自楼龄代理值"),
                ("外部惩罚", f"-{result['noise_penalty']}", "来自道路/商业/学校/轨道"),
            ]
            st.markdown(
                '<div class="metric-grid">'
                + "".join(
                    [f'<div class="metric-box"><div class="metric-label">{a}</div><div class="metric-value">{b}</div><div class="metric-note">{c}</div></div>' for a, b, c in metric_html]
                )
                + '</div>',
                unsafe_allow_html=True,
            )
        with right:
            st.markdown(
                f"""
                <div class="score-panel">
                    <div class="score-kicker">Quiet Score</div>
                    <div class="score-number">{result['final_score']}</div>
                    <h3>{label_score(result['final_score'])}</h3>
                    <div style="line-height:1.75; font-size:14px; opacity:0.96;">系统按楼栋位置、道路距离、商业暴露、学校医院和轨道交通进行估算，用于快速判断这套房是否值得继续看。</div>
                </div>
                """,
                unsafe_allow_html=True,
            )


def render_penalty_card(noise_summary: dict[str, Any]) -> None:
    signals = noise_summary.get("signals", [])
    with st.container(border=True):
        st.markdown('<div class="card-title">扣分来源</div>', unsafe_allow_html=True)
        st.markdown('<div class="card-sub">先看拖分项，再决定要不要继续实勘。这一层只展示真正影响当前楼栋体感的主要外部因素。</div>', unsafe_allow_html=True)
        if not signals:
            st.info("当前没有识别到显著的外部噪音暴露，系统没有形成有效扣分。")
        else:
            rows = []
            for sig in sorted(signals, key=lambda x: int(x.get("penalty", 0)), reverse=True):
                rows.append(
                    f'<div class="deduct-row"><div><div class="deduct-title">{sig.get("label", "")}</div><div class="deduct-detail">{sig.get("detail", "")}</div></div><div class="deduct-right">{sig.get("distance_m", "-")}m ｜ -{int(sig.get("penalty", 0))}</div></div>'
                )
            st.markdown("".join(rows), unsafe_allow_html=True)
            st.markdown(
                f"<div class='subtle' style='margin-top:10px;'>外部暴露总惩罚：<strong style='color:#173a2d;'>-{int(noise_summary.get('total_penalty', 0))}</strong></div>",
                unsafe_allow_html=True,
            )


def compute_position_result(zone_options: list[dict[str, Any]], community_row: dict[str, Any], score_engine: ScoreEngine, noise_penalty: int, selected_name: str) -> dict[str, int]:
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
    result["zone_description"] = zone_row.get("description", "按当前楼栋位置修正")
    return result


def render_position_card(result: dict[str, Any]) -> None:
    with st.container(border=True):
        st.markdown('<div class="card-title">楼栋位置修正</div>', unsafe_allow_html=True)
        st.markdown('<div class="card-sub">这里不是让用户调后台参数，而是把楼栋放回真实位置语境里：临街、中央区、内排安静区，体感差异会很明显。</div>', unsafe_allow_html=True)
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
        st.markdown(f"<div class='subtle' style='margin-top:12px;'>位置解释：{result['zone_description']}。</div>", unsafe_allow_html=True)


def render_debug_card(geocode_used: dict[str, Any] | None, building_location_text: str, community_row: dict[str, Any], tip_list: list[dict[str, Any]], regeo: dict[str, Any] | None) -> None:
    with st.expander("高德识别详情", expanded=False):
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


def main() -> None:
    render_styles()
    render_header()

    community_repo = CommunityRepository(str(COMMUNITIES_FILE))
    zone_repo = ZoneRepository(str(COMMUNITY_ZONES_FILE))
    amap = AMapProvider(get_amap_api_key(st.secrets))
    noise_engine = NoisePointEngine()
    score_engine = ScoreEngine()

    if "last_query" not in st.session_state:
        st.session_state["last_query"] = ""

    query, submitted, clear = render_search()
    if clear:
        st.session_state["last_query"] = ""
        st.rerun()
    if submitted:
        st.session_state["last_query"] = query.strip()

    query = st.session_state.get("last_query", "").strip()
    if not query:
        return

    st.markdown('<div class="result-shell-title">Residential Result</div>', unsafe_allow_html=True)

    community_row, tip_list, regeo, building_location_text, geocode_used = parse_geocode_result(query, community_repo, amap)

    poi_results = {}
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

    zone_map = {str(z.get("zone_name", "")): z for z in zone_options}
    labels = list(zone_map.keys())
    default_idx = next((i for i, z in enumerate(zone_options) if str(z.get("zone_code", "")) in {"central_inner", "DEFAULT", "default"}), 0)
    selected_name = st.selectbox("楼栋位置", labels, index=default_idx, label_visibility="collapsed")
    result = compute_position_result(zone_options, community_row, score_engine, int(noise_summary.get("total_penalty", 0)), selected_name)

    render_overview_card(query, community_row, result, noise_summary.get("signals", []))
    st.markdown('<div class="result-divider"></div>', unsafe_allow_html=True)
    render_penalty_card(noise_summary)
    st.markdown('<div class="result-divider"></div>', unsafe_allow_html=True)
    render_position_card(result)
    st.markdown('<div class="result-divider"></div>', unsafe_allow_html=True)
    render_debug_card(geocode_used, building_location_text, community_row, tip_list, regeo)


if __name__ == "__main__":
    main()
