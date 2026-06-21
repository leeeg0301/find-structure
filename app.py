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

# 전체 106.84km를 한 화면에 그리면 150m 교량은 너무 작아서 거의 안 보임
# 그래서 실제 연장을 반영하되, 너무 짧은 시설은 최소 6px로 보이게 처리
MIN_VISIBLE_PIXEL = 6

SVG_W = 1180
SVG_H = 315
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
    검색 비교를 쉽게 하기 위해 문자열을 정리한다.
    - None -> ""
    - 공백 제거
    - 영문 소문자 변환
    """
    if value is None:
        return ""

    text = str(value)
    text = re.sub(r"\s+", "", text)
    text = text.lower()

    return text


def make_chosung(value):
    """
    한글 문자열을 초성 문자열로 변환한다.

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
# 3. CSV 읽기 및 값 정리
# =========================================================

def read_csv_auto(path):
    """
    CSV 파일을 읽는다.
    공공기관/엑셀 CSV는 cp949인 경우가 많아서 여러 인코딩을 순서대로 시도한다.
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
    이정, 연장 값을 숫자로 바꾼다.

    예)
    106.84 -> 106.84
    1,234 -> 1234
    106.8k -> 106.8
    150m -> 150
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


def get_value(row, candidate_columns):
    """
    CSV 컬럼명이 약간 다를 수 있어서 후보 컬럼 중 존재하는 값을 가져온다.
    """
    for col in candidate_columns:
        if col in row:
            return row.get(col)

    # 컬럼명 앞뒤 공백이 있는 경우 보정
    stripped_map = {str(k).strip(): v for k, v in row.items()}

    for col in candidate_columns:
        if col in stripped_map:
            return stripped_map.get(col)

    return ""


# =========================================================
# 4. 시설명, 방향, 데이터 구조 정리
# =========================================================

def get_direction(name):
    """
    시설명 괄호 안에 있는 방향 정보를 읽는다.

    예)
    남해청룡1교(순천) -> 순천방향
    남해청룡1교(영암) -> 영암방향
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
    남해청룡1교(순천) -> 남해청룡1교
    남해청룡1교(영암) -> 남해청룡1교
    """
    text = str(name)
    text = re.sub(r"\((순천|영암)\)", "", text)
    return text.strip()


def build_item(row, item_type):
    """
    CSV 한 행을 앱에서 쓰기 좋은 구조로 변환한다.
    """
    if item_type == "bridge":
        category_name = "교량"
        name = clean_value(
            get_value(row, ["교량명", "시설명", "구조물명", "명칭"])
        )
        type_value = clean_value(
            get_value(row, ["종별구분", "종별", "교량종별", "구분"])
        )

    else:
        category_name = "터널"
        name = clean_value(
            get_value(row, ["터널명", "시설명", "구조물명", "명칭"])
        )
        type_value = clean_value(
            get_value(row, ["종별", "종별구분", "터널종별", "구분"])
        )

    branch = clean_value(get_value(row, ["지사", "관리지사"]))
    road = clean_value(get_value(row, ["노선", "노선명"]))

    km = to_float(get_value(row, ["이정", "중심이정", "시점이정", "위치"]))
    length_m = to_float(get_value(row, ["연장", "총연장", "길이"]), 0.0)

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
        "종별": type_value,
        "노선": road,
        "지사": branch,
        "초성": make_chosung(name),
        "검색명": normalize_text(name),
        "검색기본명": normalize_text(base_name(name)),
    }

    return item


@st.cache_data(show_spinner=False)
def load_data():
    """
    bridgedata.csv, tunneldata.csv를 읽고 보성지사 자료만 남긴다.
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
        branch = clean_value(get_value(row, ["지사", "관리지사"]))

        if BRANCH_NAME in branch:
            item = build_item(row, "bridge")

            if item:
                bridge_items.append(item)

    for row in tunnel_rows:
        branch = clean_value(get_value(row, ["지사", "관리지사"]))

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
    2. 괄호 제거 시설명이 검색어로 시작
    3. 시설명 안에 검색어 포함
    4. 괄호 제거 시설명 안에 검색어 포함
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

    type_text = item["종별"] if item["종별"] else "종별 정보 없음"

    return (
        f"{item['시설명']} | "
        f"{item['방향']} | "
        f"{item['이정']:.2f}k | "
        f"{length_text} | "
        f"{type_text}"
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
# 6. SVG 위치 도식
# =========================================================

def km_to_x(km):
    """
    이정 km 값을 SVG의 x 좌표로 변환한다.
    """
    km = max(ROAD_START_KM, min(ROAD_END_KM, km))
    ratio = (km - ROAD_START_KM) / (ROAD_END_KM - ROAD_START_KM)
    x = LEFT + ratio * ROAD_W

    return x


def make_rect_positions(item):
    """
    시설의 실제 시작/종점과 화면 표시 폭을 계산한다.

    원칙:
    - 이정(km)을 중심으로 연장(m)을 km로 환산해서 좌우로 나눠 표시한다.
    - 예: 이정 35.00k, 연장 150m이면
      실제 표시구간은 34.925k ~ 35.075k
    - 단, 전체 노선이 106.84km라서 150m는 화면에서 약 1~2px밖에 안 된다.
      그래서 너무 짧은 시설은 최소 6px로 보이게 한다.
    """
    center_km = item["이정"]
    length_km = max(item["연장_m"], 0.0) / 1000.0

    if length_km <= 0:
        length_km = 0.03

    real_start = max(ROAD_START_KM, center_km - length_km / 2)
    real_end = min(ROAD_END_KM, center_km + length_km / 2)

    center_x = km_to_x(center_km)
    x1 = km_to_x(real_start)
    x2 = km_to_x(real_end)

    width_px = max(x2 - x1, MIN_VISIBLE_PIXEL)

    visual_x1 = center_x - width_px / 2
    visual_x2 = center_x + width_px / 2

    if visual_x1 < LEFT:
        visual_x1 = LEFT
        visual_x2 = LEFT + width_px

    if visual_x2 > LEFT + ROAD_W:
        visual_x2 = LEFT + ROAD_W
        visual_x1 = visual_x2 - width_px

    return real_start, real_end, visual_x1, visual_x2


def draw_facility(svg, item, item_index, target_direction):
    """
    선택된 시설을 도식 위에 표시한다.
    """
    real_start, real_end, x1, x2 = make_rect_positions(item)

    w = max(MIN_VISIBLE_PIXEL, x2 - x1)

    if target_direction == "영암방향":
        y = 92
    else:
        y = 205

    if item["구분"] == "터널":
        h = 26
        fill = "#8fb4dd"
    else:
        h = 20
        fill = "#9e9e9e"

    stroke = "#333333"

    if item["연장_m"]:
        length_text = f"{item['연장_m']:,.0f}m"
    else:
        length_text = "연장 정보 없음"

    label = f"{item['시설명']} / {length_text}"

    title = (
        f"{item['시설명']} / "
        f"{item['방향']} / "
        f"이정 {item['이정']:.2f}k / "
        f"연장 {length_text} / "
        f"개략구간 {real_start:.3f}k~{real_end:.3f}k"
    )

    svg.append("<g>")
    svg.append(f"<title>{html.escape(title)}</title>")

    svg.append(
        f'<rect x="{x1:.1f}" y="{y}" width="{w:.1f}" height="{h}" '
        f'rx="3" fill="{fill}" stroke="{stroke}" stroke-width="1.3" opacity="0.95" />'
    )

    center_x = x1 + w / 2

    # 시설이 짧으면 글씨를 막대 오른쪽에 표시
    if w < 90:
        text_x = x2 + 8
        text_anchor = "start"

        if text_x > SVG_W - 240:
            text_x = x1 - 8
            text_anchor = "end"
    else:
        text_x = center_x
        text_anchor = "middle"

    svg.append(
        f'<text x="{text_x:.1f}" y="{y - 8}" '
        f'text-anchor="{text_anchor}" class="facility-label">'
        f'{html.escape(label)}</text>'
    )

    # 중심 이정 표시
    svg.append(
        f'<line x1="{center_x:.1f}" y1="{y + h}" x2="{center_x:.1f}" y2="{y + h + 16}" '
        f'stroke="#333333" stroke-width="1.2" stroke-dasharray="3,3" />'
    )

    svg.append(
        f'<text x="{center_x:.1f}" y="{y + h + 31}" '
        f'text-anchor="middle" class="km-label">'
        f'{item["이정"]:.2f}k</text>'
    )

    svg.append("</g>")


def make_svg(selected_items):
    """
    전체 노선 도식 SVG를 만든다.

    단순화 버전:
    - 위쪽: 영암방향
    - 아래쪽: 순천방향
    - 차로/갓길 구분 없음
    - IC 위치와 선택 시설만 표시
    """
    svg = []

    svg.append(f"""
    <svg viewBox="0 0 {SVG_W} {SVG_H}" width="100%" height="auto" xmlns="http://www.w3.org/2000/svg">
    <style>
        .ic-label {{
            font-size: 18px;
            fill: #2449ff;
            font-weight: 800;
        }}

        .tick-label {{
            font-size: 14px;
            fill: #555555;
        }}

        .direction-label {{
            font-size: 18px;
            fill: #333333;
            font-weight: 800;
        }}

        .facility-label {{
            font-size: 14px;
            fill: #222222;
            font-weight: 800;
        }}

        .km-label {{
            font-size: 12px;
            fill: #555555;
        }}

        .small-note {{
            font-size: 13px;
            fill: #777777;
        }}
    </style>

    <rect x="0" y="0" width="{SVG_W}" height="{SVG_H}" fill="#ffffff" />
    """)

    # IC 이름 표시
    for ic_name, km in IC_POINTS.items():
        x = km_to_x(km)
        y = 28
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

    # 세로 기준선과 km 숫자
    ticks = list(range(0, 101, 10)) + [107]

    for tick in ticks:
        if tick == 107:
            km = ROAD_END_KM
            tick_text = "106.84"
        else:
            km = float(tick)
            tick_text = f"{tick}"

        x = km_to_x(km)

        if tick in [0, 20, 40, 60, 80, 100, 107]:
            stroke_w = 1.5
            stroke_color = "#999999"
        else:
            stroke_w = 0.8
            stroke_color = "#dddddd"

        svg.append(
            f'<line x1="{x:.1f}" y1="45" x2="{x:.1f}" y2="265" '
            f'stroke="{stroke_color}" stroke-width="{stroke_w}" />'
        )

        svg.append(
            f'<text x="{x:.1f}" y="284" text-anchor="middle" class="tick-label">'
            f'{tick_text}k</text>'
        )

    # 방향별 중심선
    yam_y = 115
    sun_y = 225

    svg.append(
        f'<line x1="{LEFT}" y1="{yam_y}" x2="{LEFT + ROAD_W}" y2="{yam_y}" '
        f'stroke="#444444" stroke-width="5" stroke-linecap="round" />'
    )

    svg.append(
        f'<line x1="{LEFT}" y1="{sun_y}" x2="{LEFT + ROAD_W}" y2="{sun_y}" '
        f'stroke="#444444" stroke-width="5" stroke-linecap="round" />'
    )

    # 방향 라벨
    svg.append(
        f'<text x="{LEFT - 48}" y="{yam_y + 6}" text-anchor="middle" class="direction-label">영암방향</text>'
    )

    svg.append(
        f'<text x="{LEFT - 48}" y="{sun_y + 6}" text-anchor="middle" class="direction-label">순천방향</text>'
    )

    # 방향 설명
    svg.append(
        f'<text x="{LEFT + ROAD_W - 105}" y="{yam_y - 18}" class="small-note">106.84k → 0k</text>'
    )

    svg.append(
        f'<text x="{LEFT + 8}" y="{sun_y - 18}" class="small-note">0k → 106.84k</text>'
    )

    # 방향 화살표
    svg.append(
        f'<text x="{LEFT + 20}" y="{yam_y + 36}" class="direction-label">←</text>'
    )

    svg.append(
        f'<text x="{LEFT + ROAD_W - 30}" y="{sun_y + 36}" class="direction-label">→</text>'
    )

    # 선택 시설 표시
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
# 7. Streamlit 화면 구성
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
        placeholder="예: ㅅ, ㅅㅇㅇ, 서, 서영암, 남해청룡",
        key=f"{key_prefix}_keyword",
    )

    results = search_items(items, keyword)

    if not results:
        st.warning("검색 결과가 없습니다. 초성 또는 시설명 일부를 다시 입력해보세요.")
        components.html(make_svg([]), height=330, scrolling=False)
        return

    option_indices = list(range(len(results)))

    selected_index = st.selectbox(
        select_label,
        options=option_indices,
        format_func=lambda i: format_option(results[i]),
        key=f"{key_prefix}_select",
    )

    selected = results[selected_index]

    selected_items = select_related_items(
        items,
        selected,
        include_related=include_related,
    )

    components.html(
        make_svg(selected_items),
        height=330,
        scrolling=False,
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
#### 작동 방식

1. `bridgedata.csv`, `tunneldata.csv`를 읽습니다.
2. `지사` 컬럼이 `보성지사`인 자료만 남깁니다.
3. `이정`은 km 단위, `연장`은 m 단위로 해석합니다.
4. 시설명에 `(순천)`, `(영암)`이 있으면 방향을 구분합니다.
5. `서영암IC교` 같은 이름은 초성 `ㅅㅇㅇicㄱ`으로 변환해서 초성 검색이 가능하게 합니다.
6. 선택 시설의 이정을 중심으로 `연장 / 2`만큼 앞뒤를 계산해 표시합니다.
7. 전체 구간이 106.84km라 짧은 교량은 너무 작게 보이므로 최소 표시 폭을 적용합니다.
""")
