from __future__ import annotations

import base64
from pathlib import Path

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
        .stApp, [data-testid="stAppViewContainer"], [data-testid="stHeader"], [data-testid="stToolbar"], section.main {{background: transparent !important;}}
        .block-container {{max-width: 100% !important; padding-top: 0 !important; padding-left: 2rem !important; padding-right: 2rem !important;}}
        .bg-layer {{position: fixed; inset: 0; z-index: -20; pointer-events: none; background-image: linear-gradient(180deg, rgba(8,15,12,0.30), rgba(8,15,12,0.58)), url("data:image/jpeg;base64,{bg_base64}"); background-size: cover; background-position: center center; background-repeat: no-repeat;}}
        .topbar {{display: flex; justify-content: space-between; align-items: center; padding: 14px 0 0; color: #fff;}}
        .brand {{font-size: 20px; font-weight: 700; letter-spacing: 0.08em; opacity: 0.70;}}
        .hero {{min-height: 56vh; display: flex; align-items: flex-start; justify-content: center; padding-top: 4.8vh;}}
        .hero-box {{width: min(940px, 96%); text-align: center; color: #fff; margin: 0 auto;}}
        .hero-kicker {{font-size: 12px; letter-spacing: 0.24em; text-transform: uppercase; opacity: 0.86; margin-bottom: 10px;}}
        .hero-title {{font-size: clamp(44px, 6vw, 82px); font-weight: 800; line-height: 1.02; margin: 0; text-shadow: 0 8px 32px rgba(0,0,0,0.22);}}
        .hero-sub {{font-size: 16px; line-height: 1.8; max-width: 760px; margin: 14px auto 0; color: rgba(255,255,255,0.95);}}
        .hero-note {{display: inline-block; margin-top: 16px; padding: 10px 16px; border-radius: 999px; background: rgba(255,255,255,0.10); border: 1px solid rgba(255,255,255,0.20); color: rgba(255,255,255,0.94); font-size: 12px; letter-spacing: 0.03em;}}
        .search-wrap {{margin-top: 18px; margin-bottom: 28px;}}
        .glass-card {{background: rgba(255,255,255,0.88); backdrop-filter: blur(14px); border: 1px solid rgba(255,255,255,0.40); border-radius: 24px; box-shadow: 0 24px 80px rgba(0,0,0,0.18); padding: 16px 16px 10px; max-width: 860px; margin: 0 auto;}}
        .search-label {{font-size: 13px; color: rgba(31,40,36,0.70); text-align: left; margin: 2px 4px 8px;}}
        .search-footnote {{font-size: 13px; color: #6d766f; text-align: left; padding: 6px 4px 4px;}}
        .section-card {{background: rgba(255,255,255,0.95); border: 1px solid rgba(20,36,28,0.08); border-radius: 22px; padding: 22px 22px; box-shadow: 0 12px 40px rgba(26,39,31,0.08);}}
        .score-shell {{background: linear-gradient(180deg, rgba(19,60,42,0.97), rgba(23,81,58,0.96)); color: #fff; border-radius: 22px; padding: 28px; box-shadow: 0 18px 45px rgba(14,44,31,0.25);}}
        .score-number {{font-size: 84px; line-height: 1; font-weight: 800; margin: 10px 0 6px;}}
        .score-kicker {{opacity: 0.78; letter-spacing: 0.12em; text-transform: uppercase; font-size: 12px;}}
        .chip-row {{display: flex; flex-wrap: wrap; gap: 10px; margin-top: 14px;}}
        .chip {{padding: 8px 12px; border-radius: 999px; background: #eef4f0; color: #234632; font-size: 13px; border: 1px solid #d8e4dc;}}
        .signal-row {{display: flex; justify-content: space-between; gap: 12px; padding: 10px 0; border-bottom: 1px dashed #dfe7e2;}}
        .tiny-note {{font-size: 13px; color: #778178;}}
        .anchor {{position: relative; top: -90px; visibility: hidden;}}
        .result-shell {{margin-top: 0;}}
        div[data-testid="stTextInputRootElement"] input {{border-radius: 16px !important; height: 58px !important; font-size: 18px !important; border: 1px solid rgba(26,48,38,0.12) !important; box-shadow: none !important;}}
        div[data-testid="stTextInputRootElement"] input::placeholder {{color: rgba(70,78,74,0.52) !important;}}
        div[data-testid="InputInstructions"] {{display: none !important;}}
        div[data-testid="stSelectbox"] > div {{border-radius: 14px !important;}}
        div.stButton > button {{height: 52px; border-radius: 14px; font-weight: 700; box-shadow: none !important;}}
        div.stButton > button[kind="primary"] {{background: #17382c !important; border: 1px solid #17382c !important; color: white !important;}}
        div.stButton > button[kind="secondary"] {{background: rgba(255,255,255,0.60) !important; border: 1px solid rgba(27,48,38,0.10) !important; color: #6f7872 !important;}}
        @media (max-width: 900px) {{
            .block-container {{padding-left: 1rem !important; padding-right: 1rem !important;}}
            .hero-sub {{font-size: 15px;}}
            .brand {{font-size: 18px;}}
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
        <div class="hero">
            <div class="hero-box">
                <div class="hero-kicker">BEIJING RESIDENTIAL CALM INDEX</div>
                <h1 class="hero-title">安宁北京</h1>
                <div class="hero-sub">楼栋级住宅环境评估引擎。识别小区，定位楼栋，测算道路、商业、学校、医院与轨道暴露。</div>
                <div class="hero-note">默认基准 75 · 分区修正 · 建筑加分 · 周边噪音惩罚</div>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def parse_location_text(text: str | None) -> tuple[float, float] | None:
    if not text:
        return None
    try:
        lon, lat = [float(x) for x in str(text).split(',', 1)]
        return lon, lat
    except Exception:
        return None


def label_score(score: int) -> str:
    if score >= 90:
        return '非常安静'
    if score >= 80:
        return '较为安静'
    if score >= 70:
        return '中等偏静'
    if score >= 60:
        return '略受噪音影响'
    return '噪音偏高'


def render_search() -> tuple[str, bool, bool]:
    left, center, right = st.columns([1.1, 4.8, 1.1])
    with center:
        st.markdown('<div class="search-wrap"><div class="glass-card"><div class="search-label">输入北京小区或楼栋地址</div>', unsafe_allow_html=True)
        with st.form('search_form', clear_on_submit=False):
            query = st.text_input(
                '输入北京小区或楼栋地址',
                placeholder='例如：新龙城6号楼 / 花家地西里2号楼',
                label_visibility='collapsed',
            )
            c1, c2 = st.columns([1.1, 0.9])
            with c1:
                submitted = st.form_submit_button('开始查询', type='primary', use_container_width=True)
            with c2:
                clear = st.form_submit_button('清空', use_container_width=True)
        st.markdown('<div class="search-footnote">建议输入：小区名 + 楼号。系统会先识别小区，再围绕更接近楼栋的坐标测算外部噪音暴露。</div></div></div>', unsafe_allow_html=True)
    return query, submitted, clear


def main() -> None:
    render_styles()
    render_header()
    community_repo = CommunityRepository(str(COMMUNITIES_FILE))
    zone_repo = ZoneRepository(str(COMMUNITY_ZONES_FILE))
    amap = AMapProvider(get_amap_api_key(st.secrets))
    noise_engine = NoisePointEngine()
    score_engine = ScoreEngine()

    query, submitted, clear = render_search()

    if clear:
        st.rerun()

    if not submitted or not query.strip():
        return

    cleaned_query = strip_unit_details(query)
    tip_list = amap.input_tips(query) if amap.enabled() else []
    district_hint = str(tip_list[0].get('district', '')).strip() if tip_list else ''
    community_match = community_repo.search(cleaned_query, district=district_hint)

    geocode_full = amap.geocode(query) if amap.enabled() else None
    geocode_clean = amap.geocode(cleaned_query) if amap.enabled() and not geocode_full else None
    geocode_used = geocode_full or geocode_clean
    building_location_text = str(geocode_used.get('location', '')).strip() if geocode_used else ''
    regeo = amap.reverse_geocode(building_location_text) if amap.enabled() and building_location_text else None

    poi_results = {}
    if amap.enabled() and building_location_text:
        poi_results = {
            'school': amap.search_around(building_location_text, '学校', radius=1200),
            'hospital': amap.search_around(building_location_text, '医院', radius=1500),
            'commercial': amap.search_around(building_location_text, '便利店 超市 商场 购物服务 生活服务', radius=300),
            'restaurant': amap.search_around(building_location_text, '餐饮服务', radius=300),
            'rail': amap.search_around(building_location_text, '地铁站', radius=800),
        }
    noise_summary = noise_engine.evaluate(regeo, poi_results)

    if community_match:
        community_row = community_match.row
        community_row['_match_source'] = f'本地小区库 / {community_match.source}'
        community_row['_match_confidence'] = round(community_match.score, 2)
        community_row['_query_used'] = community_match.query_used
        zone_options = zone_repo.get_by_community(str(community_row.get('community_code', '')))
    else:
        community_row = {
            'community_code': 'TEMP-DEFAULT',
            'community_name': cleaned_query or query,
            'district': district_hint or str((geocode_used or {}).get('district', '')),
            'address': str((geocode_used or {}).get('formatted_address', '')),
            'aliases': '',
            'far_ratio': '',
            'build_year': '',
            'base_score': DEFAULT_BASE_SCORE,
            '_match_source': '未命中本地小区库，按默认基础分75处理',
            '_match_confidence': '',
            '_query_used': cleaned_query,
        }
        zone_options = [
            {'zone_code':'street_front','zone_name':'临主路首排','adjustment_score':-8,'description':'直接朝向主路或高速一侧，车辆持续噪音更强。'},
            {'zone_code':'secondary_street','zone_name':'次临街区','adjustment_score':-4,'description':'不在首排，但仍会明显感受到道路噪音。'},
            {'zone_code':'central_inner','zone_name':'小区中央','adjustment_score':0,'description':'按小区平均位置处理。'},
            {'zone_code':'quiet_inner','zone_name':'内排安静区','adjustment_score':6,'description':'更靠小区内部，有前排遮挡，通常更安静。'},
            {'zone_code':'gate_side','zone_name':'出入口附近','adjustment_score':-5,'description':'出入口、人车流与停车场会增加体感噪音。'},
            {'zone_code':'commercial_edge','zone_name':'靠底商/商业','adjustment_score':-6,'description':'沿街底商、餐饮和生活服务会抬高噪音。'},
        ]

    zone_map = {str(z.get('zone_name','')): z for z in zone_options}
    zone_labels = list(zone_map.keys())
    default_idx = next((i for i, z in enumerate(zone_options) if str(z.get('zone_code','')) == 'central_inner'), 0)

    st.markdown('<div class="result-shell">', unsafe_allow_html=True)
    st.markdown('<div class="section-card">', unsafe_allow_html=True)
    left_col, right_col = st.columns([1.15, 1.0])
    with left_col:
        st.subheader(str(community_row.get('community_name','目标小区')))
        cap = f"命中来源：{community_row.get('_match_source','')}"
        if community_row.get('_match_confidence') != '':
            cap += f"｜置信度：{community_row.get('_match_confidence')}"
        st.caption(cap)
        st.caption(f"楼栋输入：{query}｜小区匹配文本：{community_row.get('_query_used','')}")
        chip_html = [f"<span class='chip'>默认基础分 75</span>"]
        if str(community_row.get('district','')).strip():
            chip_html.append(f"<span class='chip'>{community_row.get('district')}</span>")
        if str(community_row.get('far_ratio','')).strip():
            chip_html.append(f"<span class='chip'>容积率 {community_row.get('far_ratio')}</span>")
        if str(community_row.get('build_year','')).strip():
            chip_html.append(f"<span class='chip'>楼龄 {community_row.get('build_year')}</span>")
        st.markdown('<div class="chip-row">' + ''.join(chip_html) + '</div>', unsafe_allow_html=True)
        selected_name = st.selectbox('请选择楼栋位置', zone_labels, index=default_idx)
        zone_row = zone_map[selected_name]
        zone_adjust = int(float(zone_row.get('adjustment_score', 0)))
        result = score_engine.final_score(
            DEFAULT_BASE_SCORE,
            zone_adjust,
            int(noise_summary.get('total_penalty', 0)),
            community_row.get('far_ratio',''),
            community_row.get('build_year',''),
        )
        st.markdown(f"**位置解释**：{zone_row.get('description','')}")
        st.markdown(
            f"<div class='tiny-note'>公式：75 + 分区修正 {result['zone_adjust']:+d} + 建筑加分 {result['build_bonus']:+d} - 密度惩罚 {result['density_penalty']:+d} - 周边噪音点惩罚 {result['noise_penalty']:+d} = {result['final_score']}</div>",
            unsafe_allow_html=True,
        )
    with right_col:
        st.markdown('<div class="score-shell">', unsafe_allow_html=True)
        st.markdown('<div class="score-kicker">Quiet Score</div>', unsafe_allow_html=True)
        st.markdown(f"<div class='score-number'>{result['final_score']}</div>", unsafe_allow_html=True)
        st.markdown(f"### {label_score(result['final_score'])}")
        st.write('这一版不是用小区中心点算外部噪音，而是尽量用完整楼栋输入去高德取更接近楼栋的坐标，再测最近主干路、学校、医院、底商、餐饮和轨道。')
        st.markdown('</div>', unsafe_allow_html=True)
    st.markdown('</div>', unsafe_allow_html=True)

    st.markdown('<div class="section-card" style="margin-top:16px;">', unsafe_allow_html=True)
    st.subheader('楼栋级外部噪音暴露')
    st.caption('你真正关心的不是小区中心点，而是这栋楼离高速、主干路、学校、医院、底商等嘈杂点有多近。下面这层尽量围绕完整楼栋地址的高德坐标来计算。')
    signals = noise_summary.get('signals', [])
    if signals:
        for sig in signals:
            st.markdown(
                f"<div class='signal-row'><div><strong>{sig.get('label','')}</strong><br><span class='tiny-note'>{sig.get('detail','')}</span></div><div><strong>{sig.get('distance_m','-')}m</strong>｜惩罚 {int(sig.get('penalty',0)):+d}</div></div>",
                unsafe_allow_html=True,
            )
        st.markdown(f"**总惩罚：{int(noise_summary.get('total_penalty', 0)):+d}**")
    else:
        st.info('这一轮没有抓到足够明确的周边噪音点，或者这些点离楼栋较远。')
    st.markdown('</div>', unsafe_allow_html=True)

    st.markdown('<div class="section-card" style="margin-top:16px;">', unsafe_allow_html=True)
    st.subheader('高德返回结果核查')
    d1, d2 = st.columns(2)
    with d1:
        st.markdown('**楼栋点位**')
        if geocode_used:
            st.write(f"标准化地址：{geocode_used.get('formatted_address','')}")
            st.write(f"location：{building_location_text or '—'}")
            st.write(f"district：{geocode_used.get('district','')}")
        else:
            st.write('没有拿到楼栋级 geocode 结果。')
    with d2:
        st.markdown('**高德候选**')
        if tip_list:
            for tip in tip_list[:5]:
                st.write(f"- {tip.get('name','')}｜{tip.get('district','')} {tip.get('address','')}")
        else:
            st.write('没有拿到输入提示候选。')
    with st.expander('逆地理编码结果', expanded=False):
        st.json(regeo if regeo else {'note':'无'})
    st.markdown('</div>', unsafe_allow_html=True)


if __name__ == '__main__':
    main()
