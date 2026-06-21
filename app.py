from pathlib import Path
import csv
import html
import re

import streamlit as st
import streamlit.components.v1 as components


# =========================================================
# 1. 기본 설정값
# =========================================================

ROAD_START_KM = 0.0
ROAD_END_KM = 106.84

IC_POINTS = {
    "서영암IC": 0.0,
    "강진IC": 20.0,
    "장흥IC": 40.0,
    "보성IC": 60.0,
    "벌교IC": 80.0,
    "남순천": 100.0,
    "해룡IC": 106.84,
}

BRANCH_NAME = "보성지사"

BRIDGE_FILE = "bridgedata.csv"
TUNNEL_FILE = "tunneldata.csv"

MIN_VISUAL_WIDTH_KM_BRIDGE = 0.65
MIN_VISUAL_WIDTH_KM_TUNNEL = 0.9

SVG_W = 1180
SVG_H = 455
LEFT = 82
RIGHT = 60
ROAD_W = SVG_W - LEFT - RIGHT


# =========================================================
# 2. 초성 검색 함수
# =========================================================

CHOSUNG_LIST = [
    "ㄱ", "ㄲ", "ㄴ", "ㄷ", "ㄸ", "ㄹ", "ㅁ", "ㅂ", "ㅃ", "ㅅ",
    "ㅆ", "ㅇ", "ㅈ", "ㅉ", "ㅊ", "ㅋ", "ㅌ", "ㅍ", "ㅎ"
]


def normalize_text(value):
    """
    검색 비교를 쉽게 하기 위해
    1) None을 빈 문자열로 바꾸고
    2) 공백을 제거하고
    3) 영문은 소문자로 바꾼다.
    """
    if value is None:
        return ""

    text = str(value)
    text = re.sub(r"\s+", "", text)
    text = text.lower()
    return text


def make_chosung(value):
    """
    한글 문자열을 초성 문자열로 바꾼다.

    예)
    서영암IC교 -> ㅅㅇㅇicㄱ
    신덕1교 -> ㅅㄷ1ㄱ
    """
    text = normalize_text(value)
    result = []

    for char in text:
        code = ord(char)

        if 0xAC00 <= code <= 0xD7A3:
            chosung_index = (code - 0xAC00) // 588
            result.append(CHOSUNG_LIST[chosung_index])
        else:
            result.append(char)

    return "".join(result)


# =========================================================
# 3. CSV 읽기
# =========================================================

def read_csv_auto(path):
    """
    CSV 파일을 읽는다.
    도로공사 자료는 cp949인 경우가 많아서 여러 인코딩을 순서대로 시도한다.
    """
    encodings = ["utf-8-sig", "cp949", "euc-kr", "utf-8"]
    last_error = None

    for enc in encodings:
        try:
            with open(path, "r", encoding=enc, newline="") as f:
                reader = csv.DictReader(f)
                rows = list(reader)
                return rows, enc
        except Exception as e:
            last_error = e

    raise RuntimeError(f"CSV 파일을 읽을 수 없습니다: {path}\n{last_error}")


def clean_value(value):
    """
    CSV에서 읽은 값을 화면에 보여주기 좋은 문자열로 정리한다.
    """
    if value is None:
        return ""

    text = str(value).strip()

    if text.lower() in ["nan", "none"]:
        return ""

    return text


def to_float(value, default=None):
    """
    이정, 연장 같은 값을 숫자로 바꾼다.

    예)
    106.84 -> 106.84
    1,234 -> 1234
    106.8k -> 106.8
    30m -> 30
    """
    if value is None:
        return default

    text = str(value).strip().replace(",", "")

    if text == "":
        return default

    match = re.search(r"-?\d+(?:\.\d+)?", text)

    if not match:
        return default

    try:
        return float(match.group())
    except ValueError:
        return default


# =========================================================
# 4. 시설명, 방향, 데이터 구조 정리
# =========================================================

def get_direction(name):
    """
    시설명 괄호 안에 있는 방향 정보를 읽는다.

    예)
    서영암IC교(순천) -> 순천방향
    서영암IC교(영암) -> 영암방향
    방향 표시 없음 -> 양방향/공용
    """
    text = str(name)

    paren_values = re.findall(r"\((.*?)\)", text)
    paren_text = " ".join(paren_values)

    if "순천" in paren_text:
        return "순천방향"

    if "영암" in paren_text:
        return "영암방향"

    return "양방향/공용"


def base_name(name):
    """
    같은 시설의 순천/영암 방향을 묶기 위해 괄호 방향 표기를 제거한다.

    예)
    서영암IC교(순천) -> 서영암IC교
    서영암IC교(영암) -> 서영암IC교
    """
    text = str(name)
    text = re.sub(r"\((순천|영암)\)", "", text)
    return text.strip()


def build_item(row, item_type):
    """
    CSV 한 행을 앱에서 사용하기 좋은 공통 구조로 변환한다.
    교량과 터널의 컬럼명이 조금 다르므로 여기에서 맞춰준다.
    """
    if item_type == "bridge":
        name_col = "교량명"
        type_col = "종별구분"
        category_name = "교량"
    else:
        name_col = "터널명"
        type_col = "종별"
        category_name = "터널"

    name = clean_value(row.get(name_col))
    km = to_float(row.get("이정"))
    length_m = to_float(row.get("연장"), 0.0)

    if not name:
        return None

    if km is None:
        return None

    if km < ROAD_START_KM - 1 or km > ROAD_END_KM + 1:
        return None

    item = {
        "구분": category_name,
        "시설명": name,
        "기본명": base_name(name),
        "방향": get_direction(name),
        "이정": km,
        "연장_m": length_m or 0.0,
        "종별": clean_value(row.get(type_col)),
        "노선": clean_value(row.get("노선")),
        "지사": clean_value(row.get("지사")),
        "초성": make_chosung(name),
        "검색명": normalize_text(name),
        "검색기본명": normalize_text(base_name(name)),
    }

    return item


@st.cache_data(show_spinner=False)
def load_data():
    """
    교량과 터널 CSV를 읽고 보성지사 데이터만 추출한다.
    """
    base_dir = Path(__file__).resolve().parent

    bridge_path = base_dir / BRIDGE_FILE
    tunnel_path = base_dir / TUNNEL_FILE

    missing_files = []

    if not bridge_path.exists():
        missing_files.append(BRIDGE_FILE)

    if not tunnel_path.exists():
        missing_files.append(TUNNEL_FILE)

    if missing_files:
        missing_text = ", ".join(missing_files)
        raise FileNotFoundError(
            f"다음 CSV 파일이 app.py와 같은 폴더에 있어야 합니다: {missing_text}"
        )

    bridge_rows, bridge_encoding = read_csv_auto(bridge_path)
    tunnel_rows, tunnel_encoding = read_csv_auto(tunnel_path)

    bridge_items = []
    tunnel_items = []

    for row in bridge_rows:
        branch = clean_value(row.get("지사"))

        if BRANCH_NAME in branch:
            item = build_item(row, "bridge")

            if item:
                bridge_items.append(item)

    for row in tunnel_rows:
        branch = clean_value(row.get("지사"))

        if BRANCH_NAME in branch:
            item = build_item(row, "tunnel")

            if item:
                tunnel_items.append(item)

    bridge_items.sort(key=lambda x: (x["이정"], x["시설명"]))
    tunnel_items.sort(key=lambda x: (x["이정"], x["시설명"]))

    meta = {
        "bridge_encoding": bridge_encoding,
        "tunnel_encoding": tunnel_encoding,
        "bridge_count": len(bridge_items),
        "tunnel_count": len(tunnel_items),
    }

    return bridge_items, tunnel_items, meta


# =========================================================
# 5. 검색 로직
# =========================================================

def search_items(items, keyword, limit=80):
    """
    시설명 직접 검색과 초성 검색을 동시에 수행한다.

    검색 우선순위
    1. 시설명이 검색어로 시작
    2. 괄호 제거한 시설명이 검색어로 시작
    3. 시설명 안에 검색어 포함
    4. 괄호 제거한 시설명 안에 검색어 포함
    5. 초성이 검색어로 시작
    6. 초성 안에 검색어 포함
    """
    keyword = normalize_text(keyword)
    keyword_chosung = make_chosung(keyword)

    if not keyword:
        return items[:limit]

    results = []

    for item in items:
        name = item["검색명"]
        base = item["검색기본명"]
        chosung = item["초성"]

        score = None

        if name.startswith(keyword):
            score = 0
        elif base.startswith(keyword):
            score = 1
        elif keyword in name:
            score = 2
        elif keyword in base:
            score = 3
        elif chosung.startswith(keyword_chosung):
            score = 4
        elif keyword_chosung in chosung:
            score = 5

        if score is not None:
            results.append((score, item["이정"], item["시설명"], item))

    results.sort(key=lambda x: (x[0], x[1], x[2]))

    return [r[3] for r in results[:limit]]


def format_option(item):
    """
    selectbox에 표시할 문구를 만든다.
    """
    if item["연장_m"]:
        length_text = f"{item['연장_m']:,.0f}m"
    else:
        length_text = "연장 정보 없음"

    return (
        f"{item['시설명']} | "
        f"{item['방향']} | "
        f"{item['이정']:.2f}k | "
        f"{length_text} | "
        f"{item['종별']}"
    )


def select_related_items(items, selected, include_related=True):
    """
    선택한 시설과 같은 이름의 반대방향 시설을 함께 표시한다.
    """
    if not selected:
        return []

    if not include_related:
        return [selected]

    related = []

    for item in items:
        if item["기본명"] == selected["기본명"]:
            related.append(item)

    related.sort(key=lambda x: (x["방향"], x["이정"], x["시설명"]))

    return related


# =========================================================
# 6. SVG 도식 생성
# =========================================================

def km_to_x(km):
    """
    이정 km 값을 SVG의 x 좌표로 변환한다.
    """
    km = max(ROAD_START_KM, min(ROAD_END_KM, km))
    ratio = (km - ROAD_START_KM) / (ROAD_END_KM - ROAD_START_KM)
    x = LEFT + ratio * ROAD_W
    return x


def make_rect_positions(item, item_index):
    """
    시설의 실제 시작/종점과 화면상 표시 시작/종점을 계산한다.

    실제 위치:
    이정을 중심으로 연장/2만큼 앞뒤로 계산

    화면 표시 위치:
    짧은 교량은 실제 축척대로 그리면 너무 작아서 최소 표시 폭을 적용
    """
    km = item["이정"]
    length_km = max(item["연장_m"], 0.0) / 1000.0
    half = length_km / 2.0

    real_start = max(ROAD_START_KM, km - half)
    real_end = min(ROAD_END_KM, km + half)

    if item["구분"] == "터널":
        min_width = MIN_VISUAL_WIDTH_KM_TUNNEL
    else:
        min_width = MIN_VISUAL_WIDTH_KM_BRIDGE

    visual_width_km = max(length_km, min_width)

    visual_start = max(ROAD_START_KM, km - visual_width_km / 2.0)
    visual_end = min(ROAD_END_KM, km + visual_width_km / 2.0)

    if visual_end - visual_start < min_width and visual_start <= ROAD_START_KM:
        visual_end = min(ROAD_END_KM, visual_start + min_width)

    if visual_end - visual_start < min_width and visual_end >= ROAD_END_KM:
        visual_start = max(ROAD_START_KM, visual_end - min_width)

    return real_start, real_end, visual_start, visual_end


def draw_facility(svg, item, item_index, target_direction):
    """
    SVG 위에 선택된 시설을 사각형으로 그린다.
    """
    real_start, real_end, visual_start, visual_end = make_rect_positions(item, item_index)

    x1 = km_to_x(visual_start)
    x2 = km_to_x(visual_end)
    w = max(7, x2 - x1)

    if target_direction == "영암방향":
        y = 140 + (item_index % 2) * 18
    else:
        y = 305 + (item_index % 2) * 18

    if item["구분"] == "터널":
        h = 48
        fill = "#9fb7d9"
    else:
        h = 36
        fill = "#bdbdbd"

    stroke = "#333333"

    label = f"#{item_index + 1} {item['시설명']}"

    if item["연장_m"]:
        length_text = f"{item['연장_m']:,.0f}m"
    else:
        length_text = "연장 정보 없음"

    title = (
        f"{item['시설명']} / "
        f"{item['방향']} / "
        f"이정 {item['이정']:.2f}k / "
        f"개략구간 {real_start:.2f}k~{real_end:.2f}k / "
        f"연장 {length_text}"
    )

    svg.append("<g>")
    svg.append(f"<title>{html.escape(title)}</title>")

    svg.append(
        f'<rect x="{x1:.1f}" y="{y}" width="{w:.1f}" height="{h}" '
        f'rx="2" fill="{fill}" stroke="{stroke}" stroke-width="1.5" opacity="0.92" />'
    )

    text_x = x1 + w / 2
    text_anchor = "middle"

    if w < 95:
        if x1 > SVG_W - 250:
            text_x = x1 - 5
            text_anchor = "end"
        else:
            text_x = x1 + w + 5
            text_anchor = "start"

    text_y = y + h / 2 + 4

    svg.append(
        f'<text x="{text_x:.1f}" y="{text_y:.1f}" '
        f'text-anchor="{text_anchor}" class="facility-label">'
        f'{html.escape(label)}</text>'
    )

    svg.append("</g>")


def make_svg(selected_items):
    """
    전체 도로 도식 SVG를 만든다.
    """
    svg = []

    svg.append(f"""
    <svg viewBox="0 0 {SVG_W} {SVG_H}" width="100%" height="auto" xmlns="http://www.w3.org/2000/svg">
    <style>
        .ic-label {{
            font-size: 19px;
            fill: #2449ff;
            font-weight: 800;
        }}

        .tick-label {{
            font-size: 16px;
            fill: #555555;
        }}

        .side-label {{
            font-size: 17px;
            fill: #333333;
            font-weight: 700;
        }}

        .lane-label {{
            font-size: 15px;
            fill: #555555;
        }}

        .facility-label {{
            font-size: 14px;
            fill: #333333;
            font-weight: 800;
        }}

        .small-note {{
            font-size: 13px;
            fill: #777777;
        }}
    </style>

    <rect x="0" y="0" width="{SVG_W}" height="{SVG_H}" fill="#ffffff" />
    """)

    for ic_name, km in IC_POINTS.items():
        x = km_to_x(km)
        y = 26
        text_anchor = "middle"

        if km <= ROAD_START_KM + 0.1:
            text_anchor = "start"
            x = x - 25
        elif km >= ROAD_END_KM - 0.1:
            text_anchor = "end"
            x = x + 30

        svg.append(
            f'<text x="{x:.1f}" y="{y}" text-anchor="{text_anchor}" class="ic-label">'
            f'{html.escape(ic_name)}</text>'
        )

    ticks = list(range(0, 101, 10)) + [107]

    for tick in ticks:
        if tick == 107:
            km = ROAD_END_KM
        else:
            km = float(tick)

        x = km_to_x(km)

        if tick in [0, 20, 40, 60, 80, 100, 107]:
            stroke_w = 2
        else:
            stroke_w = 1.3

        svg.append(
            f'<line x1="{x:.1f}" y1="52" x2="{x:.1f}" y2="418" '
            f'stroke="#686868" stroke-width="{stroke_w}" />'
        )

        if tick == 107:
            tick_text = "107k"
        elif tick == 0:
            tick_text = "0k"
        else:
            tick_text = str(tick)

        svg.append(
            f'<text x="{x:.1f}" y="47" text-anchor="middle" class="tick-label">'
            f'{tick_text}</text>'
        )

    lane_ys = [52, 111, 170, 229, 288, 347, 418]

    for y in lane_ys:
        if y in [52, 418]:
            stroke_w = 2
        else:
            stroke_w = 1.5

        svg.append(
            f'<line x1="{LEFT}" y1="{y}" x2="{LEFT + ROAD_W}" y2="{y}" '
            f'stroke="#686868" stroke-width="{stroke_w}" />'
        )

    svg.append(
        f'<line x1="{LEFT}" y1="229" x2="{LEFT + ROAD_W}" y2="229" '
        f'stroke="#111111" stroke-width="6" />'
    )

    svg.append(
        f'<rect x="{LEFT}" y="52" width="{ROAD_W}" height="366" '
        f'fill="none" stroke="#595959" stroke-width="2" />'
    )

    svg.append('<text x="44" y="136" text-anchor="middle" class="side-label">영암</text>')
    svg.append('<text x="44" y="158" text-anchor="middle" class="side-label">방향</text>')
    svg.append('<text x="44" y="306" text-anchor="middle" class="side-label">순천</text>')
    svg.append('<text x="44" y="328" text-anchor="middle" class="side-label">방향</text>')

    right_x = LEFT + ROAD_W + 12

    lane_labels = [
        (82, "갓길"),
        (141, "2차로"),
        (200, "1차로"),
        (259, "1차로"),
        (318, "2차로"),
        (383, "갓길"),
    ]

    for y, label in lane_labels:
        svg.append(
            f'<text x="{right_x}" y="{y}" class="lane-label">{label}</text>'
        )

    svg.append(
        f'<text x="{LEFT + 8}" y="96" class="small-note">'
        f'영암방향: 106.84k → 0k</text>'
    )

    svg.append(
        f'<text x="{LEFT + 8}" y="403" class="small-note">'
        f'순천방향: 0k → 106.84k</text>'
    )

    svg.append(
        f'<text x="{LEFT + ROAD_W - 90}" y="96" class="small-note">←</text>'
    )

    svg.append(
        f'<text x="{LEFT + ROAD_W - 90}" y="403" class="small-note">→</text>'
    )

    for idx, item in enumerate(selected_items):
        if item["방향"] == "영암방향":
            draw_facility(svg, item, idx, "영암방향")
        elif item["방향"] == "순천방향":
            draw_facility(svg, item, idx, "순천방향")
        else:
            draw_facility(svg, item, idx, "영암방향")
            draw_facility(svg, item, idx, "순천방향")

    svg.append("</svg>")

    return "".join(svg)


# =========================================================
# 7. 선택 시설 정보 표
# =========================================================

def make_info_table(items):
    """
    선택한 교량/터널 정보를 HTML 표로 만든다.
    """
    if not items:
        return ""

    rows = []

    for i, item in enumerate(items, start=1):
        real_start, real_end, _, _ = make_rect_positions(item, i - 1)

        if item["연장_m"]:
            length_text = f"{item['연장_m']:,.0f}"
        else:
            length_text = ""

        rows.append(f"""
        <tr>
            <td>#{i}</td>
            <td>{html.escape(item["구분"])}</td>
            <td><b>{html.escape(item["시설명"])}</b></td>
            <td>{html.escape(item["방향"])}</td>
            <td>{item["이정"]:.2f}k</td>
            <td>{html.escape(length_text)} m</td>
            <td>{html.escape(item["종별"])}</td>
            <td>{real_start:.2f}k ~ {real_end:.2f}k</td>
        </tr>
        """)

    table_html = f"""
    <style>
        .info-table {{
            width: 100%;
            border-collapse: collapse;
            font-size: 14px;
        }}

        .info-table th {{
            background: #f3f5f7;
            border: 1px solid #d9dde3;
            padding: 8px;
            text-align: center;
        }}

        .info-table td {{
            border: 1px solid #d9dde3;
            padding: 8px;
            text-align: center;
        }}

        .info-table td:nth-child(3) {{
            text-align: left;
        }}
    </style>

    <table class="info-table">
        <thead>
            <tr>
                <th>번호</th>
                <th>구분</th>
                <th>시설명</th>
                <th>방향</th>
                <th>이정</th>
                <th>연장</th>
                <th>종별</th>
                <th>개략 표시구간</th>
            </tr>
        </thead>

        <tbody>
            {"".join(rows)}
        </tbody>
    </table>
    """

    return table_html


# =========================================================
# 8. Streamlit 화면
# =========================================================

st.set_page_config(
    page_title="보성지사 교량·터널 위치 찾기",
    layout="wide",
)

st.title("보성지사 교량·터널 위치 찾기")

st.caption(
    "남해선 영암순천선 0k ~ 106.84k 구간에서 "
    "교량과 터널의 개략적인 위치를 표시합니다."
)

try:
    bridge_items, tunnel_items, meta = load_data()
except Exception as e:
    st.error(str(e))
    st.stop()


with st.sidebar:
    st.subheader("데이터 확인")

    st.write(f"교량: {meta['bridge_count']:,}개")
    st.write(f"터널: {meta['tunnel_count']:,}개")

    st.caption(f"교량 CSV 인코딩: {meta['bridge_encoding']}")
    st.caption(f"터널 CSV 인코딩: {meta['tunnel_encoding']}")

    st.divider()

    include_related = st.checkbox(
        "같은 시설의 반대방향/공용 자료도 함께 표시",
        value=True,
    )

    st.divider()

    st.markdown("### IC 이정")

    for ic_name, km in IC_POINTS.items():
        st.write(f"{ic_name}: {km:g}k")


tab_bridge, tab_tunnel = st.tabs(["교량명 검색", "터널명 검색"])


def render_search_tab(items, search_label, select_label, key_prefix):
    """
    교량 탭과 터널 탭에서 공통으로 사용하는 화면 구성 함수
    """
    keyword = st.text_input(
        search_label,
        placeholder="예: ㅅ, ㅅㅇㅇ, 서, 서영암, 강진",
        key=f"{key_prefix}_keyword",
    )

    results = search_items(items, keyword)

    if not results:
        st.warning("검색 결과가 없습니다. 초성 또는 시설명 일부를 다시 입력해보세요.")
        components.html(make_svg([]), height=430, scrolling=False)
        return

    selected = st.selectbox(
        select_label,
        options=results,
        format_func=format_option,
        key=f"{key_prefix}_select",
    )

    selected_items = select_related_items(
        items,
        selected,
        include_related=include_related,
    )

    st.markdown("#### 위치 도식")

    components.html(
        make_svg(selected_items),
        height=430,
        scrolling=False,
    )

    st.markdown("#### 선택 시설 정보")

    st.markdown(
        make_info_table(selected_items),
        unsafe_allow_html=True,
    )

    with st.expander("검색 결과 목록 보기"):
        for item in results[:50]:
            st.write(format_option(item))


with tab_bridge:
    render_search_tab(
        bridge_items,
        "교량명 또는 초성을 입력하세요",
        "표시할 교량을 선택하세요",
        "bridge",
    )


with tab_tunnel:
    render_search_tab(
        tunnel_items,
        "터널명 또는 초성을 입력하세요",
        "표시할 터널을 선택하세요",
        "tunnel",
    )


st.divider()

st.markdown("""
#### 로직 요약

1. `bridgedata.csv`, `tunneldata.csv`를 읽습니다.
2. `지사` 컬럼이 `보성지사`인 행만 남깁니다.
3. `이정`은 km, `연장`은 m 단위로 해석합니다.
4. 시설명 괄호의 `(순천)`, `(영암)`을 기준으로 방향을 나눕니다.
5. 한글 시설명을 초성 문자열로 변환해서 `ㅅ`, `ㅅㅇㅇ`, `ㄱㅈ` 같은 검색이 가능하게 합니다.
6. 선택 시설의 이정을 중심으로 `연장 / 2`만큼 앞뒤를 계산해 개략 위치를 표시합니다.
7. 연장이 짧은 교량은 화면에서 너무 작게 보이지 않도록 최소 표시 폭을 적용합니다.
""")
