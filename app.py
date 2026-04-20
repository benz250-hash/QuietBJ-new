from __future__ import annotations

import base64
from pathlib import Path
from typing import Any

import streamlit as st

from amap_provider import AMapProvider
from building_engine import BuildingEngine
from community_engine import CommunityEngine
from community_repository import CommunityMatch, CommunityRepository
from config import AMAP_CITY, BACKGROUND_FILE, COMMUNITIES_FILE, COMMUNITY_ZONES_FILE, DEFAULT_ZONE_CODE, get_amap_api_key
from noise_point_engine import NoisePointEngine
from score_pipeline import ScorePipeline
from text_match import strip_unit_details
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
        .bg-layer {{position: fixed; inset: 0; background-image: linear-gradient(to bottom, rgba(9,18,14,0.38), rgba(9,18,14,0.50)), url("data:image/jpeg;base64,{bg_base64}"); background-size: cover; background-position: center; z-index: -20;}}
        .topbar {{display:flex; justify-content:space-between; align-items:center; padding: 10px 0 0 0; color:#fff; font-size:14px;}}
        .brand {{font-size:24px; font-weight:700; letter-spacing:0.04em;}}
        .nav {{display:flex; gap:22px; opacity:0.96;}}
        .hero-wrap {{min-height:58vh; display:flex; align-items:flex-start; justify-content:center; padding-top:6vh;}}
        .hero-box {{width:min(980px,95%); text-align:center; color:#fff; margin:0 auto;}}
        .hero-kicker {{font-size:14px; letter-spacing:0.22em; text-transform:uppercase; opacity:0.92; margin-bottom:8px;}}
        .hero-title {{font-size: clamp(38px, 6vw, 76px); font-weight: 800; line-height:1.04; margin:0;}}
        .hero-subtitle {{font-size:18px; line-height:1.7; max-width:760px; margin:16px auto 22px; opacity:0.95;}}
        .glass-card {{background: rgba(255,255,255,0.86); backdrop-filter: blur(10px); border:1px solid rgba(255,255,255,0.40); border-radius:24px; box-shadow:0 24px 70px rgba(0,0,0,0.16); padding:18px 18px 10px;}}
        .section-card {{background: rgba(255,255,255,0.92); border:1px solid rgba(20,36,28,0.08); border-radius:22px; padding:26px 24px; box-shadow:0 12px 40px rgba(26,39,31,0.08);}}
        .score-shell {{background: linear-gradient(180deg, rgba(19,60,42,0.96), rgba(23,81,58,0.96)); color:#fff; border-radius:22px; padding:28px; box-shadow:0 18px 45px rgba(14,44,31,0.25);}}
        .score-kicker {{opacity:0.78; letter-spacing:0.12em; text-transform:uppercase; font-size:12px;}}
        .score-number {{font-size:84px; line-height:1; font-weight:800; margin:10px 0 6px;}}
        .chip-row {{display:flex; flex-wrap:wrap; gap:10px; margin-top:14px;}}
        .chip {{padding:8px 12px; border-radius:999px; background:#eef4f0; color:#234632; font-size:13px; border:1px solid #d8e4dc;}}
        .signal-row {{display:flex; justify-content:space-between; gap:12px; padding:10px 0; border-bottom:1px dashed #dfe7e2;}}
        .tiny-note {{font-size:13px; color:#778178;}}
        div[data-testid="stTextInputRootElement"] input {{border-radius:14px !important; height:54px !important; font-size:17px !important;}}
        div[data-testid="stSelectbox"] > div {{border-radius:14px !important;}}
        div.stButton > button {{height:52px; border-radius:14px; font-weight:700;}}
        div.stButton > button[kind="primary"] {{background:#153f2e; border:1px solid #153f2e;}}
        .anchor {{position: relative; top:-90px; visibility:hidden;}}
        .footer-space {{height:48px;}}
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
                <div class="hero-subtitle">先识别小区，再按小区基础分与楼栋位置修正出分；同时实验性抓取学校、医院、商业、主干路等周边噪音点，辅助形成距离权重。</div>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    c1, c2, c3 = st.columns([1.2, 4.8, 1.2])
    with c2:
        st.markdown('<div class="glass-card">', unsafe_allow_html=True)
        with st.form("search_form", clear_on_submit=False):
            query = st.text_input("请输入北京小区或详细地址", placeholder="例如：新龙城 / 回龙观新龙城 / 花家地西里2号楼")
            cc1, cc2, cc3 = st.columns([1.2, 1.2, 3.6])
            with cc1:
                submit = st.form_submit_button("开始查询", type="primary", use_container_width=True)
            with cc2:
                reset = st.form_submit_button("清空", use_container_width=True)
            with cc3:
                st.caption("建议输入：小区名 + 区域 / 楼号。程序会先去掉楼号再匹配小区；高德只做标准化和周边点抓取。")
        st.markdown('</div>', unsafe_allow_html=True)
    return ("" if reset else query), submit


def load_services() -> tuple[CommunityRepository, ZoneRepository, ScorePipeline, AMapProvider, NoisePointEngine]:
    community_repo = CommunityRepository(str(COMMUNITIES_FILE))
    zone_repo = ZoneRepository(str(COMMUNITY_ZONES_FILE))
    pipeline = ScorePipeline(CommunityEngine(), ZoneEngine(), BuildingEngine())
    amap_provider = AMapProvider(get_amap_api_key(st.secrets))
    noise_engine = NoisePointEngine()
    return community_repo, zone_repo, pipeline, amap_provider, noise_engine


def try_local_match(query: str, community_repo: CommunityRepository, district: str = "", subdistrict: str = "", location: tuple[float, float] | None = None) -> dict[str, Any] | None:
    cleaned = strip_unit_details(query)
    match = community_repo.search(cleaned, district=district, subdistrict=subdistrict, location=location, threshold=0.78, max_distance_km=1.2)
    if not match:
        return None
    row = dict(match.row)
    row["_match_source"] = f"本地小区库 / {match.source}"
    row["_match_confidence"] = round(match.score, 2)
    row["_query_used"] = match.query_used
    if match.distance_km is not None:
        row["_distance_km"] = round(match.distance_km, 2)
    return row


def _parse_location(location_text: str | None) -> tuple[float, float] | None:
    if not location_text:
        return None
    try:
        lon, lat = [float(x) for x in str(location_text).split(",", 1)]
        return lon, lat
    except Exception:
        return None


def _extract_context_from_regeo(regeo: dict[str, Any] | None) -> tuple[str, str, list[str]]:
    if not regeo:
        return "", "", []
    ac = regeo.get("addressComponent", {}) if isinstance(regeo, dict) else {}
    district = str(ac.get("district", "")).strip()
    township = str(ac.get("township", "")).strip()
    pois = regeo.get("pois", []) if isinstance(regeo.get("pois", []), list) else []
    aois = regeo.get("aois", []) if isinstance(regeo.get("aois", []), list) else []
    candidate_texts: list[str] = []
    for poi in pois[:5]:
        name = str(poi.get("name", "")).strip()
        if name:
            candidate_texts.append(name)
            if district:
                candidate_texts.append(f"{district}{name}")
    for aoi in aois[:4]:
        name = str(aoi.get("name", "")).strip()
        if name:
            candidate_texts.append(name)
            if district:
                candidate_texts.append(f"{district}{name}")
    return district, township, candidate_texts


def _pick_best_match(candidates: list[str], community_repo: CommunityRepository, district: str = "", subdistrict: str = "", location: tuple[float, float] | None = None) -> CommunityMatch | None:
    best: CommunityMatch | None = None
    for candidate in candidates:
        candidate = strip_unit_details(str(candidate).strip())
        if not candidate:
            continue
        match = community_repo.search(candidate, threshold=0.78, district=district, subdistrict=subdistrict, location=location, max_distance_km=1.2)
        if match and (best is None or match.score > best.score):
            best = match
    return best


def try_amap_normalize(query: str, amap_provider: AMapProvider, community_repo: CommunityRepository) -> tuple[dict[str, Any] | None, dict[str, Any] | None, list[dict[str, Any]], dict[str, list[dict[str, Any]]], dict[str, Any] | None]:
    if not amap_provider.enabled() or not query.strip():
        return None, None, [], {}, None

    cleaned_query = strip_unit_details(query)
    tips = amap_provider.input_tips(cleaned_query)
    candidates: list[str] = [cleaned_query]
    district = ""
    subdistrict = ""
    location: tuple[float, float] | None = None

    for tip in tips[:8]:
        tip_name = str(tip.get("name", "")).strip()
        tip_district = str(tip.get("district", "")).strip()
        tip_address = str(tip.get("address", "")).strip()
        tip_location = _parse_location(str(tip.get("location", "")).strip())
        if not district and tip_district:
            district = tip_district
        if tip_name:
            candidates.append(tip_name)
        if tip_district and tip_name:
            candidates.append(f"{tip_district}{tip_name}")
        if tip_district and tip_address:
            candidates.append(f"{tip_district}{tip_address}")
        if tip_location and location is None:
            location = tip_location

    best = _pick_best_match(candidates, community_repo, district=district, subdistrict=subdistrict, location=location)
    geocode = None
    regeo = None
    poi_results: dict[str, list[dict[str, Any]]] = {}

    if not best:
        geocode = amap_provider.geocode(cleaned_query)
        if geocode:
            formatted = str(geocode.get("formatted_address", "")).strip()
            location_text = str(geocode.get("location", "")).strip()
            location = _parse_location(location_text) or location
            district = district or str(geocode.get("district", "")).strip()
            regeo = amap_provider.reverse_geocode(location_text) if location_text else None
            regeo_district, regeo_subdistrict, regeo_candidates = _extract_context_from_regeo(regeo)
            district = district or regeo_district
            subdistrict = subdistrict or regeo_subdistrict
            all_candidates = candidates + [formatted] + regeo_candidates
            best = _pick_best_match(all_candidates, community_repo, district=district, subdistrict=subdistrict, location=location)
    else:
        loc = best.row.get("longitude"), best.row.get("latitude")
        try:
            location = (float(loc[0]), float(loc[1]))
        except Exception:
            location = None

    debug = {
        "cleaned_query": cleaned_query,
        "district": district,
        "subdistrict": subdistrict,
        "location": location,
    }

    if best:
        row = dict(best.row)
        row["_match_source"] = f"高德标准化地址 → 本地小区库 / {best.source}"
        row["_match_confidence"] = round(best.score, 2)
        row["_query_used"] = best.query_used
        if best.distance_km is not None:
            row["_distance_km"] = round(best.distance_km, 2)

        if location is None:
            try:
                location = (float(row.get("longitude", "")), float(row.get("latitude", "")))
            except Exception:
                location = None

        if regeo is None and location is not None:
            regeo = amap_provider.reverse_geocode(f"{location[0]},{location[1]}")

        if location is not None:
            location_text = f"{location[0]},{location[1]}"
            poi_results = {
                "school": amap_provider.search_around(location_text, "学校", radius=1200),
                "hospital": amap_provider.search_around(location_text, "医院", radius=1500),
                "commercial": amap_provider.search_around(location_text, "购物中心", radius=1000),
                "restaurant": amap_provider.search_around(location_text, "餐饮服务", radius=800),
            }
        return row, regeo, tips, poi_results, debug

    return None, regeo, tips, poi_results, debug


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


def render_noise_panel(noise_summary: dict[str, Any]) -> None:
    st.markdown('<div class="section-card" style="margin-top:16px;">', unsafe_allow_html=True)
    st.subheader("周边嘈杂点实验")
    st.caption("这一步是实验性的：以小区中心点为锚点，抓取学校、医院、商业、餐饮与主干路，再按距离与权重形成附加噪音惩罚。")
    signals = noise_summary.get("signals", [])
    if not signals:
        st.info("这一轮没有抓到足够明确的周边嘈杂点，或周边点距离较远，因此暂不追加惩罚。")
    else:
        for sig in signals:
            label = sig.get("label", "要素")
            distance_m = sig.get("distance_m")
            penalty = sig.get("penalty", 0)
            detail = sig.get("detail", "")
            st.markdown(
                f"<div class='signal-row'><div><strong>{label}</strong><br><span class='tiny-note'>{detail}</span></div><div><strong>{distance_m if distance_m is not None else '-'}m</strong>｜惩罚 {penalty:+d}</div></div>",
                unsafe_allow_html=True,
            )
        st.markdown(f"**实验性总惩罚：{noise_summary.get('total_penalty', 0):+d}**")
    st.markdown('</div>', unsafe_allow_html=True)


def render_result(community_row: dict[str, Any], zone_options: list[dict[str, Any]], pipeline: ScorePipeline, noise_summary: dict[str, Any] | None = None) -> None:
    st.markdown('<div class="section-card">', unsafe_allow_html=True)
    left, right = st.columns([1.15, 1.0])

    with left:
        st.subheader(str(community_row.get("community_name", "目标小区")))
        caption = f"命中来源：{community_row.get('_match_source', '本地小区库')}｜基础分主键：{community_row.get('community_code', '-')}"
        if community_row.get("_match_confidence"):
            caption += f"｜置信度：{community_row.get('_match_confidence')}"
        if community_row.get("_distance_km") is not None:
            caption += f"｜坐标距离：{community_row.get('_distance_km')} km"
        st.caption(caption)
        if community_row.get("_query_used"):
            st.caption(f"此次用于命中的标准化文本：{community_row.get('_query_used')}")
        chips = CommunityEngine().summarize(community_row)
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
        noise_penalty = int((noise_summary or {}).get("total_penalty", 0))
        experimental_score = max(50, min(100, result["final_score"] - noise_penalty))

        st.markdown(f"**位置解释**：{ZoneEngine().explain(zone_row)}")
        st.markdown(
            f"<div class='tiny-note'>基础公式：小区基础分 {result['base_score']} + 分区修正 {result['zone_adjustment']:+d} + 楼栋修正 {result['building_adjustment']:+d} = {result['final_score']}；再叠加实验性周边惩罚 {noise_penalty:+d}，得到实验分 {experimental_score}。</div>",
            unsafe_allow_html=True,
        )

    with right:
        st.markdown('<div class="score-shell">', unsafe_allow_html=True)
        st.markdown('<div class="score-kicker">Quiet Score</div>', unsafe_allow_html=True)
        st.markdown(f'<div class="score-number">{experimental_score}</div>', unsafe_allow_html=True)
        st.markdown(f"### {score_label(experimental_score)}")
        st.write("这个分数不是官方实测分贝，而是住宅体感静噪评分。它现在由小区基础分、楼栋位置修正，以及实验性的周边嘈杂点惩罚共同组成。")
        st.markdown('</div>', unsafe_allow_html=True)

    st.markdown('</div>', unsafe_allow_html=True)
    render_noise_panel(noise_summary or {"signals": [], "total_penalty": 0})


def render_amap_panel(amap_provider: AMapProvider, tips: list[dict[str, Any]], regeo: dict[str, Any] | None, debug: dict[str, Any] | None) -> None:
    st.markdown('<div id="amap" class="anchor"></div>', unsafe_allow_html=True)
    st.markdown('<div class="section-card">', unsafe_allow_html=True)
    st.subheader("高德接口：当前这一版怎么用")
    if amap_provider.enabled():
        st.success("已检测到高德 Web 服务 Key。当前代码会按顺序尝试：输入提示 → 地理编码 → 逆地理编码 → 周边搜索，并把标准化结果严格映射到本地小区库。")
    else:
        st.warning("当前未配置高德 Key。此时仍可使用本地小区库搜索，但不会触发地址标准化与候选提示。")
    c1, c2 = st.columns(2)
    with c1:
        st.markdown("**当前代码已接入**")
        st.markdown("""- 输入提示：把模糊输入收敛成候选地址
- 地理编码：地址 → 经纬度
- 逆地理编码：经纬度 → 标准地址、主干路、POI、AOI
- 周边搜索：抓学校、医院、商业、餐饮等嘈杂点""")
    with c2:
        st.markdown("**这一版的拒识原则**")
        st.markdown("""- 自动去掉楼号 / 单元号再匹配小区
- 置信度不足不自动命中
- 距离本地小区坐标超过约 1km 不自动命中
- 宁可提示“未命中”，也不乱贴到已有样本小区""")
    if debug:
        with st.expander("本次标准化上下文", expanded=False):
            st.json(debug)
    if tips:
        with st.expander("这次搜索拿到的高德候选", expanded=False):
            for tip in tips[:6]:
                st.write(f"- {tip.get('name', '')}｜{tip.get('district', '')} {tip.get('address', '')}")
    if regeo:
        with st.expander("这次搜索拿到的逆地理编码结果", expanded=False):
            st.json(regeo)
    st.markdown('</div>', unsafe_allow_html=True)


def render_docs() -> None:
    st.markdown('<div id="principles" class="anchor"></div>', unsafe_allow_html=True)
    st.markdown('<div class="section-card">', unsafe_allow_html=True)
    st.subheader("工作原理")
    st.write("第一层是小区基础分；第二层是分区修正；第三层开始试验用高德抓取周边嘈杂点，并按距离与类别权重形成附加惩罚。")
    st.write("高德负责“你在哪儿、周边有哪些点”，我们的引擎负责“这里该扣几分”。后续要插楼栋引擎、投诉热度引擎、道路权重引擎，都可以继续扩进去。")
    st.markdown('</div>', unsafe_allow_html=True)

    st.markdown('<div id="faq" class="anchor"></div>', unsafe_allow_html=True)
    st.markdown('<div class="section-card" style="margin-top:16px;">', unsafe_allow_html=True)
    st.subheader("常见问题")
    with st.expander("为什么输入带楼号时容易错配？", expanded=False):
        st.write("因为高德标准化的是地址，而你本地库的主键是小区。现在程序会先自动去掉 23号楼、2单元、301室 这类细节，再把结果映射到小区层。")
    with st.expander("为什么有时候宁可不命中？", expanded=False):
        st.write("因为样本库还小。现在宁可严格拒识，也不把一个完全不同的小区误贴到已有样本上。")
    with st.expander("实验性周边惩罚是不是最终版？", expanded=False):
        st.write("不是。当前只是把学校、医院、商业、餐饮、主干路做成第一批可实验的噪音代理点，后续还会继续细化权重。")
    st.markdown('</div>', unsafe_allow_html=True)


def main() -> None:
    render_styles()
    render_topbar()
    query, submit = render_hero()
    community_repo, zone_repo, pipeline, amap_provider, noise_engine = load_services()

    local_match = None
    regeo = None
    tips: list[dict[str, Any]] = []
    poi_results: dict[str, list[dict[str, Any]]] = {}
    debug: dict[str, Any] | None = None

    if submit and query.strip():
        local_match = try_local_match(query, community_repo)
        if not local_match:
            local_match, regeo, tips, poi_results, debug = try_amap_normalize(query, amap_provider, community_repo)

        if local_match:
            zones = zone_repo.get_by_community(str(local_match.get("community_code", "")))
            if zones:
                noise_summary = noise_engine.evaluate(regeo, poi_results)
                render_result(local_match, zones, pipeline, noise_summary=noise_summary)
            else:
                st.warning("已命中小区，但尚未录入该小区的分区规则。")
        else:
            if amap_provider.enabled():
                st.warning("本地小区库没有命中；高德已完成标准化尝试，但根据当前严格规则，仍未能安全映射到 communities.csv。建议补录该小区，而不是强行贴到现有样本。")
            else:
                st.warning("当前没有命中本地小区库。若你已经配置高德 Key，可以继续补更完整的地址；否则先把该小区录入 communities.csv。")
    elif submit:
        st.info("先输入一个北京小区名或详细地址。")

    render_amap_panel(amap_provider, tips, regeo, debug)
    render_docs()
    st.markdown('<div class="footer-space"></div>', unsafe_allow_html=True)


if __name__ == "__main__":
    main()
