from __future__ import annotations

import base64
from pathlib import Path
from typing import Any

import streamlit as st

from amap_provider import AMapProvider
from building_engine import BuildingEngine
from community_engine import CommunityEngine
from community_repository import CommunityRepository
from config import AMAP_CITY, BACKGROUND_FILE, COMMUNITIES_FILE, COMMUNITY_ZONES_FILE, DEFAULT_ZONE_CODE, get_amap_api_key
from score_pipeline import ScorePipeline
from zone_engine import ZoneEngine
from zone_repository import ZoneRepository


st.set_page_config(page_title="QuietBJ｜北京静噪分", page_icon="🔇", layout="wide")


def file_to_base64(path: str | Path) -> str:
    return base64.b64encode(Path(path).read_bytes()).decode("utf-8")


def render_styles() -> None:
    bg_base64 = file_to_base64(BACKGROUND_FILE)
    st.markdown(
        f"""
        <style>
        .stApp {{background: #eef2f0;}}
        .bg-layer {{
            position: fixed; inset: 0;
            background-image: linear-gradient(to bottom, rgba(9,18,14,0.38), rgba(9,18,14,0.50)), url("data:image/jpeg;base64,{bg_base64}");
            background-size: cover; background-position: center;
            z-index: -20;
        }}
        .topbar {{
            display:flex; justify-content:space-between; align-items:center;
            padding: 10px 0 0 0; color: #fff; font-size: 14px;
        }}
        .brand {{font-size: 24px; font-weight: 700; letter-spacing: 0.04em;}}
        .nav {{display:flex; gap: 22px; opacity: 0.96;}}
        .hero-wrap {{
            min-height: 58vh; display:flex; align-items:flex-start; justify-content:center;
            padding-top: 6vh;
        }}
        .hero-box {{
            width: min(980px, 95%); text-align:center; color:#fff;
            margin: 0 auto;
        }}
        .hero-kicker {{
            font-size: 14px; letter-spacing: 0.22em; text-transform: uppercase;
            opacity: 0.92; margin-bottom: 8px;
        }}
        .hero-title {{font-size: clamp(38px, 6vw, 76px); font-weight: 800; line-height: 1.04; margin: 0;}}
        .hero-subtitle {{font-size: 18px; line-height: 1.7; max-width: 760px; margin: 16px auto 22px; opacity: 0.95;}}
        .glass-card {{
            background: rgba(255,255,255,0.86); backdrop-filter: blur(10px);
            border: 1px solid rgba(255,255,255,0.40); border-radius: 24px;
            box-shadow: 0 24px 70px rgba(0,0,0,0.16);
            padding: 18px 18px 10px;
        }}
        .section-card {{
            background: rgba(255,255,255,0.92); border: 1px solid rgba(20,36,28,0.08);
            border-radius: 22px; padding: 26px 24px; box-shadow: 0 12px 40px rgba(26,39,31,0.08);
        }}
        .score-shell {{
            background: linear-gradient(180deg, rgba(19,60,42,0.96), rgba(23,81,58,0.96));
            color: #fff; border-radius: 22px; padding: 28px; box-shadow: 0 18px 45px rgba(14,44,31,0.25);
        }}
        .score-kicker {{opacity: 0.78; letter-spacing: 0.12em; text-transform: uppercase; font-size: 12px;}}
        .score-number {{font-size: 84px; line-height: 1; font-weight: 800; margin: 10px 0 6px;}}
        .muted {{color: #647067; font-size: 14px;}}
        .chip-row {{display:flex; flex-wrap:wrap; gap:10px; margin-top: 14px;}}
        .chip {{padding: 8px 12px; border-radius: 999px; background:#eef4f0; color:#234632; font-size:13px; border:1px solid #d8e4dc;}}
        .tiny-note {{font-size: 13px; color: #778178;}}
        div[data-testid="stTextInputRootElement"] input {{border-radius: 14px !important; height: 54px !important; font-size: 17px !important;}}
        div[data-testid="stSelectbox"] > div {{border-radius: 14px !important;}}
        div.stButton > button {{height: 52px; border-radius: 14px; font-weight: 700;}}
        div.stButton > button[kind="primary"] {{background:#153f2e; border:1px solid #153f2e;}}
        .anchor {{position: relative; top: -90px; visibility: hidden;}}
        .footer-space {{height: 48px;}}
        </style>
        <div class="bg-layer"></div>
        """,
        unsafe_allow_html=True,
    )


def render_topbar() -> None:
    st.markdown(
        """
        <div class="topbar">
            <div class="brand">QuietBJ</div>
            <div class="nav">
                <a href="#principles" style="color:white;text-decoration:none;">工作原理</a>
                <a href="#amap" style="color:white;text-decoration:none;">高德接口</a>
                <a href="#faq" style="color:white;text-decoration:none;">常见问题</a>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_hero() -> tuple[str, bool]:
    st.markdown(
        """
        <div class="hero-wrap">
            <div class="hero-box">
                <div class="hero-kicker">BEIJING RESIDENTIAL NOISE MODEL</div>
                <h1 class="hero-title">搜索静噪分™</h1>
                <div class="hero-subtitle">先识别小区，再按小区基础分与楼栋位置修正出分。高德负责把地址标准化，我们自己的引擎负责判断“临街、内排、出入口、商业边”。</div>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    c1, c2, c3 = st.columns([1.2, 4.8, 1.2])
    with c2:
        st.markdown('<div class="glass-card">', unsafe_allow_html=True)
        with st.form("search_form", clear_on_submit=False):
            query = st.text_input("请输入北京小区或详细地址", placeholder="例如：新龙城 / 回龙观新龙城 / 望京西园四区 5号楼")
            cc1, cc2, cc3 = st.columns([1.2, 1.2, 3.6])
            with cc1:
                submit = st.form_submit_button("开始查询", type="primary", use_container_width=True)
            with cc2:
                reset = st.form_submit_button("清空", use_container_width=True)
            with cc3:
                st.caption("建议输入：小区名 + 区域 / 楼号。先命中本地小区库，未命中再走高德标准化。")
        st.markdown('</div>', unsafe_allow_html=True)
    return ("" if reset else query), submit


def load_services() -> tuple[CommunityRepository, ZoneRepository, ScorePipeline, AMapProvider]:
    community_repo = CommunityRepository(str(COMMUNITIES_FILE))
    zone_repo = ZoneRepository(str(COMMUNITY_ZONES_FILE))
    pipeline = ScorePipeline(CommunityEngine(), ZoneEngine(), BuildingEngine())
    amap_provider = AMapProvider(get_amap_api_key(st.secrets))
    return community_repo, zone_repo, pipeline, amap_provider


def try_local_match(query: str, community_repo: CommunityRepository) -> dict[str, Any] | None:
    match = community_repo.search(query)
    if not match:
        return None
    row = dict(match.row)
    row["_match_source"] = f"本地小区库 / {match.source}"
    row["_match_confidence"] = round(match.score, 2)
    return row


def try_amap_normalize(query: str, amap_provider: AMapProvider, community_repo: CommunityRepository) -> tuple[dict[str, Any] | None, dict[str, Any] | None, list[dict[str, Any]]]:
    if not amap_provider.enabled() or not query.strip():
        return None, None, []

    tips = amap_provider.input_tips(query)
    candidate_texts: list[str] = []
    for tip in tips[:5]:
        parts = [str(tip.get("district", "")).strip(), str(tip.get("name", "")).strip(), str(tip.get("address", "")).strip()]
        candidate_text = " ".join(part for part in parts if part)
        if candidate_text:
            candidate_texts.append(candidate_text)

    for candidate in candidate_texts + [query]:
        local_match = try_local_match(candidate, community_repo)
        if local_match:
            local_match["_match_source"] = "高德候选归一化 → 本地小区库"
            return local_match, None, tips

    geocode = amap_provider.geocode(query)
    if not geocode:
        return None, None, tips
    location = str(geocode.get("location", "")).strip()
    regeo = amap_provider.reverse_geocode(location) if location else None

    for candidate in [str(geocode.get("formatted_address", ""))]:
        local_match = try_local_match(candidate, community_repo)
        if local_match:
            local_match["_match_source"] = "高德地理编码 → 本地小区库"
            return local_match, regeo, tips

    return None, regeo, tips


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


def render_result(community_row: dict[str, Any], zone_options: list[dict[str, Any]], pipeline: ScorePipeline) -> None:
    st.markdown('<div class="section-card">', unsafe_allow_html=True)
    left, right = st.columns([1.15, 1.0])

    with left:
        st.subheader(str(community_row.get("community_name", "目标小区")))
        st.caption(f"命中来源：{community_row.get('_match_source', '本地小区库')}｜基础分主键：{community_row.get('community_code', '-')}")
        community_engine = CommunityEngine()
        chips = community_engine.summarize(community_row)
        if chips:
            st.markdown('<div class="chip-row">' + ''.join(f'<span class="chip">{chip}</span>' for chip in chips) + '</div>', unsafe_allow_html=True)

        zone_map = {str(item.get("zone_name", "")): item for item in zone_options}
        labels = list(zone_map.keys())
        default_index = 0
        for idx, row in enumerate(zone_options):
            if str(row.get("zone_code", "")) == DEFAULT_ZONE_CODE:
                default_index = idx
                break

        selected_name = st.selectbox("请选择楼栋位置", labels, index=default_index)
        zone_row = zone_map[selected_name]
        result = pipeline.run(community_row, zone_row=zone_row)

        st.markdown(f"**位置解释**：{ZoneEngine().explain(zone_row)}")
        st.markdown(
            f"<div class='tiny-note'>公式：最终静噪分 = 小区基础分 {result['base_score']} + 分区修正 {result['zone_adjustment']:+d} + 楼栋修正 {result['building_adjustment']:+d}</div>",
            unsafe_allow_html=True,
        )

    with right:
        result = pipeline.run(community_row, zone_row=zone_row)
        st.markdown('<div class="score-shell">', unsafe_allow_html=True)
        st.markdown('<div class="score-kicker">Quiet Score</div>', unsafe_allow_html=True)
        st.markdown(f'<div class="score-number">{result["final_score"]}</div>', unsafe_allow_html=True)
        st.markdown(f"### {score_label(result['final_score'])}")
        st.write("这个分数不是官方实测分贝，而是住宅体感静噪评分。它更适合帮助你快速判断：同一个小区里，哪类位置更值得优先看。")
        st.markdown('</div>', unsafe_allow_html=True)

    st.markdown('</div>', unsafe_allow_html=True)


def render_amap_panel(amap_provider: AMapProvider, tips: list[dict[str, Any]], regeo: dict[str, Any] | None) -> None:
    st.markdown('<div id="amap" class="anchor"></div>', unsafe_allow_html=True)
    st.markdown('<div class="section-card">', unsafe_allow_html=True)
    st.subheader("高德接口：当前这一版怎么用")
    if amap_provider.enabled():
        st.success("已检测到高德 Web 服务 Key。当前代码会按顺序尝试：输入提示 → 地理编码 → 逆地理编码。")
    else:
        st.warning("当前未配置高德 Key。此时仍可使用本地小区库搜索，但不会触发地址标准化与候选提示。")

    c1, c2 = st.columns(2)
    with c1:
        st.markdown("**当前代码已接入**")
        st.markdown("""- 输入提示：把模糊输入收敛成候选地址
- 地理编码：地址 → 经纬度
- 逆地理编码：经纬度 → 标准地址、主干路、POI、AOI""")
    with c2:
        st.markdown("**我们真正会用到的数据**")
        st.markdown("""- 标准化地址与坐标
- district / adcode / location
- roads（特别是 roadlevel=1 的主干路）
- POI / AOI 线索，用来辅助判断小区与楼栋位置""")

    if tips:
        with st.expander("这次搜索拿到的高德候选", expanded=False):
            for tip in tips[:5]:
                st.write(f"- {tip.get('name', '')}｜{tip.get('district', '')} {tip.get('address', '')}")

    if regeo:
        with st.expander("这次搜索拿到的逆地理编码结果", expanded=False):
            st.json(regeo)
    st.markdown('</div>', unsafe_allow_html=True)


def render_docs() -> None:
    st.markdown('<div id="principles" class="anchor"></div>', unsafe_allow_html=True)
    st.markdown('<div class="section-card">', unsafe_allow_html=True)
    st.subheader("工作原理")
    st.write("第一层是小区基础分；第二层是分区修正。输入框先尽量命中我们自己的小区库，未命中时再让高德做地址归一化，把地址尽量收敛到具体小区。")
    st.write("这一版最关键的工程思想是：高德负责“你在哪儿”，我们的引擎负责“这里该扣几分”。后续要插楼栋引擎、投诉热度引擎、道路权重引擎，都可以通过 score_pipeline 扩进去。")
    st.markdown('</div>', unsafe_allow_html=True)

    st.markdown('<div id="faq" class="anchor"></div>', unsafe_allow_html=True)
    st.markdown('<div class="section-card" style="margin-top:16px;">', unsafe_allow_html=True)
    st.subheader("常见问题")
    with st.expander("为什么不是直接按地址给一个分数？", expanded=False):
        st.write("因为住宅噪音不是普通 POI 查询。真正有价值的是：同一个小区里，首排临街、中央区、内排安静区、出入口边，这些位置差异很大。")
    with st.expander("高德有没有北京所有小区每栋楼的现成噪音数据？", expanded=False):
        st.write("没有现成噪音分。高德更擅长提供地址标准化、坐标、道路、POI、AOI 等空间线索；最终判断仍要靠我们自己的小区与分区规则。")
    with st.expander("后续能不能升级成楼栋级？", expanded=False):
        st.write("可以。当前 building_engine 已经预留了接口。等你有 buildings.csv 或楼栋规则表时，只需要把 building_engine 接进 score_pipeline 即可。")
    st.markdown('</div>', unsafe_allow_html=True)


def main() -> None:
    render_styles()
    render_topbar()
    query, submit = render_hero()
    community_repo, zone_repo, pipeline, amap_provider = load_services()

    local_match = None
    regeo = None
    tips: list[dict[str, Any]] = []

    if submit and query.strip():
        local_match = try_local_match(query, community_repo)
        if not local_match:
            local_match, regeo, tips = try_amap_normalize(query, amap_provider, community_repo)

        if local_match:
            zones = zone_repo.get_by_community(str(local_match.get("community_code", "")))
            if zones:
                render_result(local_match, zones, pipeline)
            else:
                st.warning("已命中小区，但尚未录入该小区的分区规则。")
        else:
            st.warning("当前没有命中本地小区库。若你已经配置高德 Key，可以继续补更完整的地址；否则先把该小区录入 communities.csv。")

    elif submit:
        st.info("先输入一个北京小区名或详细地址。")

    render_amap_panel(amap_provider, tips, regeo)
    render_docs()
    st.markdown('<div class="footer-space"></div>', unsafe_allow_html=True)


if __name__ == "__main__":
    main()
