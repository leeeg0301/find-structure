import re
from pathlib import Path

import pandas as pd


# =========================================================
# 1. 기본 설정: 보성지사 관리 구간과 IC 위치
# =========================================================
ROUTE_MIN_KM = 0.0
ROUTE_MAX_KM = 106.84

IC_POINTS = {
    "서영암IC": 0.0,
    "강진IC": 20.0,
    "장흥IC": 40.0,
    "보성IC": 60.0,
    "벌교IC": 80.0,
    "남순천": 100.0,
    "해룡IC": 106.84,
}

BRIDGE_FILE = "bridgedata.csv"
TUNNEL_FILE = "tunneldata.csv"

# 교량 연장은 대부분 수십~수백 m라서 실제 축척대로 그리면 거의 안 보임.
# 그래서 실제 연장을 계산하되, 화면 표시용 최소 폭을 둔다.
MIN_VISUAL_WIDTH_KM = 0.9


# =========================================================
# 2. 한글 초성 검색 함수
# =========================================================
CHOSUNG_LIST = [
    "ㄱ", "ㄲ", "ㄴ", "ㄷ", "ㄸ", "ㄹ", "ㅁ", "ㅂ", "ㅃ", "ㅅ",
    "ㅆ", "ㅇ", "ㅈ", "ㅉ", "ㅊ", "ㅋ", "ㅌ", "ㅍ", "ㅎ"
]
CHOSUNG_SET = set(CHOSUNG_LIST)


def get_chosung(text: str) -> str:
    """문자열을 초성 문자열로 변환한다. 예: 서영암IC교 -> ㅅㅇㅇicㄱ"""
    result = []
    for char in str(text):
        code = ord(char)
        if 0xAC00 <= code <= 0xD7A3:  # 완성형 한글 범위
            idx = (code - 0xAC00) // 588
            result.append(CHOSUNG_LIST[idx])
        else:
            result.append(char.lower())
    return "".join(result)


def normalize_text(text: str) -> str:
    """검색 비교용으로 공백과 대소문자를 정리한다."""
    return re.sub(r"\s+", "", str(text).lower())


def is_chosung_query(text: str) -> bool:
    """입력값이 ㄱㄴㄷ 같은 초성만으로 구성되어 있는지 확인한다."""
    cleaned = normalize_text(text)
    return bool(cleaned) and all(ch in CHOSUNG_SET for ch in cleaned)


# =========================================================
# 3. 데이터 로드 및 전처리
# =========================================================
@st.cache_data
def read_csv_safely(file_path: str) -> pd.DataFrame:
    """CSV 인코딩이 utf-8인지 cp949인지 몰라도 읽을 수 있게 여러 인코딩을 시도한다."""
    encodings = ["utf-8-sig", "cp949", "euc-kr", "utf-8"]
    last_error = None

    for enc in encodings:
        try:
            return pd.read_csv(file_path, encoding=enc)
        except Exception as e:
            last_error = e

    raise RuntimeError(f"CSV 파일을 읽지 못했습니다: {file_path}\n마지막 오류: {last_error}")


def detect_direction(name: str) -> str:
    """시설물명에 붙은 (순천), (영암)을 이용해 방향을 판정한다."""
    name = str(name)
    if "(순천)" in name or "（순천）" in name:
        return "순천방향"
    if "(영암)" in name or "（영암）" in name:
        return "영암방향"
    return "양방향/공용"


def base_facility_name(name: str) -> str:
    """서영암IC교(순천) -> 서영암IC교 처럼 방향 표기를 제거한다."""
    name = str(name)
    name = re.sub(r"[\(（]\s*(순천|영암)\s*[\)）]", "", name)
    return name.strip()


def preprocess_facility_data(df: pd.DataFrame, name_col: str, type_col: str, facility_kind: str) -> pd.DataFrame:
    """보성지사 자료만 남기고 지도 표시와 검색에 필요한 보조 컬럼을 만든다."""
    required_cols = ["지사", name_col, "이정", "연장"]
    missing = [col for col in required_cols if col not in df.columns]
    if missing:
        raise ValueError(f"{facility_kind} 데이터에 필요한 컬럼이 없습니다: {missing}")

    out = df.copy()

    # 보성지사 + 관리구간만 사용
    out = out[out["지사"].astype(str).str.strip().eq("보성지사")].copy()

    # 숫자형 변환: 이정은 km, 연장은 m 단위로 사용
    out["이정_km"] = pd.to_numeric(out["이정"], errors="coerce")
    out["연장_m"] = pd.to_numeric(out["연장"], errors="coerce")
    out = out.dropna(subset=[name_col, "이정_km"])

    # 106.84k 바로 근처 시설물은 107로 입력된 경우가 있어 약간 여유를 둔다.
    out = out[(out["이정_km"] >= ROUTE_MIN_KM - 0.5) & (out["이정_km"] <= ROUTE_MAX_KM + 0.5)].copy()

    out["시설구분"] = facility_kind
    out["시설명"] = out[name_col].astype(str).str.strip()
    out["기본시설명"] = out["시설명"].apply(base_facility_name)
    out["방향"] = out["시설명"].apply(detect_direction)

    if type_col in out.columns:
        out["종별표시"] = out[type_col].astype(str).replace("nan", "-")
    else:
        out["종별표시"] = "-"

    # 검색용 보조 컬럼
    out["_norm_name"] = out["시설명"].apply(normalize_text)
    out["_norm_base"] = out["기본시설명"].apply(normalize_text)
    out["_chosung_name"] = out["시설명"].apply(lambda x: normalize_text(get_chosung(x)))
    out["_chosung_base"] = out["기본시설명"].apply(lambda x: normalize_text(get_chosung(x)))

    out = out.sort_values(["이정_km", "시설명"]).reset_index(drop=True)
    return out


@st.cache_data
def load_all_data() -> tuple[pd.DataFrame, pd.DataFrame]:
    bridge_raw = read_csv_safely(BRIDGE_FILE)
    tunnel_raw = read_csv_safely(TUNNEL_FILE)

    bridge_df = preprocess_facility_data(
        bridge_raw,
        name_col="교량명",
        type_col="종별구분",
        facility_kind="교량",
    )
    tunnel_df = preprocess_facility_data(
        tunnel_raw,
        name_col="터널명",
        type_col="종별",
        facility_kind="터널",
    )
    return bridge_df, tunnel_df


# =========================================================
# 4. 검색 로직
# =========================================================
def search_facilities(df: pd.DataFrame, query: str, limit: int = 60) -> pd.DataFrame:
    """
    검색 우선순위
    1) 시설명/기본시설명에 직접 포함되는 경우
    2) 초성 입력이 시설명 초성과 일치하는 경우
    3) 두 글자 이상 입력했을 때 초성 변환값이 일치하는 경우
    """
    q = normalize_text(query)
    if not q:
        return df.head(limit).copy()

    q_chosung = normalize_text(get_chosung(query))
    only_chosung = is_chosung_query(query)

    rows = []
    for idx, row in df.iterrows():
        score = None

        # 일반 검색: 서, 서영암, ic 등
        if row["_norm_name"].startswith(q) or row["_norm_base"].startswith(q):
            score = 0
        elif q in row["_norm_name"] or q in row["_norm_base"]:
            score = 1

        # 초성 검색: ㅅ, ㅅㄷ, ㅅㅇㅇ 등
        elif only_chosung and (q in row["_chosung_name"] or q in row["_chosung_base"]):
            score = 2

        # '서영'처럼 한글 두 글자 이상을 입력했을 때도 초성 ㅅㅇ으로 보조 검색
        elif len(q) >= 2 and q_chosung and (q_chosung in row["_chosung_name"] or q_chosung in row["_chosung_base"]):
            score = 3

        if score is not None:
            rows.append((score, idx))

    if not rows:
        return df.iloc[0:0].copy()

    matched_idx = [idx for score, idx in sorted(rows, key=lambda x: (x[0], df.loc[x[1], "이정_km"], df.loc[x[1], "시설명"]))]
    return df.loc[matched_idx].head(limit).copy()


def make_option_label(row: pd.Series) -> str:
    length = row.get("연장_m")
    length_txt = "-" if pd.isna(length) else f"{length:,.0f}m"
    return f"{row['시설명']}  |  {row['이정_km']:.2f}k  |  {row['방향']}  |  {row['종별표시']}  |  {length_txt}"


# =========================================================
# 5. 이정 + 연장을 화면 좌표로 변환
# =========================================================
def calc_span(km: float, length_m: float | int | None) -> tuple[float, float, float, float]:
    """
    실제 표시 구간과 화면 표시 구간을 모두 계산한다.
    - 실제 구간: 이정을 중심으로 연장/2만큼 좌우로 배치
    - 화면 구간: 너무 짧으면 MIN_VISUAL_WIDTH_KM로 확대
    """
    km = float(km)
    length_km = 0.0 if pd.isna(length_m) else max(float(length_m) / 1000.0, 0.0)

    actual_start = max(ROUTE_MIN_KM, km - length_km / 2)
    actual_end = min(ROUTE_MAX_KM, km + length_km / 2)

    visual_width = max(actual_end - actual_start, MIN_VISUAL_WIDTH_KM)
    visual_start = km - visual_width / 2
    visual_end = km + visual_width / 2

    # 관리구간 밖으로 삐져나가지 않게 보정
    if visual_start < ROUTE_MIN_KM:
        visual_end += ROUTE_MIN_KM - visual_start
        visual_start = ROUTE_MIN_KM
    if visual_end > ROUTE_MAX_KM:
        visual_start -= visual_end - ROUTE_MAX_KM
        visual_end = ROUTE_MAX_KM
    visual_start = max(ROUTE_MIN_KM, visual_start)

    return actual_start, actual_end, visual_start, visual_end


def direction_bands(direction: str) -> list[tuple[float, float]]:
    """방향별로 도식에서 칠할 y 구간을 반환한다."""
    if direction == "영암방향":
        return [(3.05, 5.95)]
    if direction == "순천방향":
        return [(0.05, 2.95)]
    # 방향 표기가 없으면 양방향에 모두 표시
    return [(3.05, 5.95), (0.05, 2.95)]


# =========================================================
# 6. 도식 그리기
# =========================================================
def draw_route_map(selected_df: pd.DataFrame, title: str) -> go.Figure:
    fig = go.Figure()

    # 세로 격자: 10km 단위 + 종점 106.84k
    grid_x = list(range(0, 101, 10)) + [ROUTE_MAX_KM]
    for x in grid_x:
        fig.add_shape(
            type="line", x0=x, x1=x, y0=0, y1=6,
            line=dict(color="rgba(90,90,90,0.85)", width=1.3),
        )

    # 가로 격자: 6개 band + 중앙분리대
    for y in range(0, 7):
        fig.add_shape(
            type="line", x0=ROUTE_MIN_KM, x1=ROUTE_MAX_KM, y0=y, y1=y,
            line=dict(color="rgba(90,90,90,0.85)", width=1.3),
        )

    # 중앙분리대 굵은 선
    fig.add_shape(
        type="rect", x0=ROUTE_MIN_KM, x1=ROUTE_MAX_KM, y0=2.96, y1=3.04,
        fillcolor="black", line=dict(color="black"),
    )

    # IC 이름과 km 표기
    for ic_name, km in IC_POINTS.items():
        fig.add_annotation(x=km, y=6.42, text=f"<b>{ic_name}</b>", showarrow=False,
                           font=dict(color="#2458ff", size=15), yanchor="bottom")
        fig.add_annotation(x=km, y=6.13, text=f"{km:g}k", showarrow=False,
                           font=dict(color="rgb(70,70,70)", size=13), yanchor="bottom")

    # 10km 숫자 보조 표기
    for km in range(10, 101, 10):
        if km not in IC_POINTS.values():
            fig.add_annotation(x=km, y=6.05, text=f"{km}", showarrow=False,
                               font=dict(color="rgb(70,70,70)", size=12), yanchor="bottom")

    # 좌측 방향 라벨
    fig.add_annotation(x=-3.5, y=4.5, text="영암<br>방향", showarrow=False,
                       font=dict(size=14, color="rgb(40,40,40)"), xanchor="right")
    fig.add_annotation(x=-3.5, y=1.5, text="순천<br>방향", showarrow=False,
                       font=dict(size=14, color="rgb(40,40,40)"), xanchor="right")

    # 우측 차로 라벨
    right_labels = [(5.5, "갓길"), (4.5, "2차로"), (3.5, "1차로"),
                    (2.5, "1차로"), (1.5, "2차로"), (0.5, "갓길")]
    for y, label in right_labels:
        fig.add_annotation(x=ROUTE_MAX_KM + 1.0, y=y, text=label, showarrow=False,
                           font=dict(size=12, color="rgb(80,80,80)"), xanchor="left")

    # 방향 화살표 안내
    fig.add_annotation(x=53, y=6.72, text="영암방향: 106.8k → 0k &nbsp;&nbsp;&nbsp; | &nbsp;&nbsp;&nbsp; 순천방향: 0k → 106.8k",
                       showarrow=False, font=dict(size=12, color="rgb(90,90,90)"))

    # 선택된 교량/터널 표시
    for i, (_, row) in enumerate(selected_df.iterrows(), start=1):
        actual_start, actual_end, visual_start, visual_end = calc_span(row["이정_km"], row.get("연장_m"))
        label = f"#{i}"
        hover = (
            f"<b>{row['시설명']}</b><br>"
            f"구분: {row['시설구분']}<br>"
            f"종별: {row['종별표시']}<br>"
            f"방향: {row['방향']}<br>"
            f"이정: {row['이정_km']:.2f}k<br>"
            f"연장: {row.get('연장_m', float('nan')):,.0f}m<br>"
            f"실제 추정구간: {actual_start:.3f}k ~ {actual_end:.3f}k"
        )

        for y0, y1 in direction_bands(row["방향"]):
            fig.add_shape(
                type="rect",
                x0=visual_start, x1=visual_end, y0=y0, y1=y1,
                fillcolor="rgba(130,130,130,0.55)",
                line=dict(color="rgb(60,60,60)", width=2),
            )
            fig.add_trace(go.Scatter(
                x=[(visual_start + visual_end) / 2],
                y=[(y0 + y1) / 2],
                mode="text",
                text=[f"<b>{label}</b>"],
                textfont=dict(size=14, color="black"),
                hovertext=[hover],
                hoverinfo="text",
                showlegend=False,
            ))

        # 도식 위 설명은 너무 긴 이름이 겹치지 않도록 번호만 도식에 넣고, 상세 표에서 풀어준다.

    fig.update_xaxes(range=[-6, ROUTE_MAX_KM + 6], visible=False, fixedrange=True)
    fig.update_yaxes(range=[-0.2, 6.9], visible=False, fixedrange=True)
    fig.update_layout(
        title=dict(text=title, x=0.5, xanchor="center"),
        height=450,
        margin=dict(l=35, r=45, t=75, b=25),
        plot_bgcolor="white",
        paper_bgcolor="white",
        hoverlabel=dict(bgcolor="white", font_size=13),
    )
    return fig


# =========================================================
# 7. Streamlit 화면 구성
# =========================================================
def show_facility_tab(df: pd.DataFrame, kind: str):
    st.subheader(f"{kind} 위치 검색")

    query = st.text_input(
        f"{kind}명 검색",
        placeholder=f"예: ㅅ, ㅅㄷ, 서, 서영암, 강진 ...",
        key=f"{kind}_query",
    )

    result_df = search_facilities(df, query)

    if result_df.empty:
        st.warning("검색 결과가 없습니다. 초성 또는 시설물명을 다시 입력해 주세요.")
        return

    option_map = {idx: make_option_label(row) for idx, row in result_df.iterrows()}
    selected_idx = st.selectbox(
        f"표시할 {kind} 선택",
        options=list(option_map.keys()),
        format_func=lambda idx: option_map[idx],
        key=f"{kind}_select",
    )

    selected_row = df.loc[[selected_idx]].copy()

    show_same_base = st.checkbox(
        "같은 이름의 반대방향/공용 시설도 함께 표시",
        value=True,
        key=f"{kind}_same_base",
    )

    if show_same_base:
        base_name = selected_row.iloc[0]["기본시설명"]
        selected_df = df[df["기본시설명"].eq(base_name)].copy()
    else:
        selected_df = selected_row

    fig = draw_route_map(selected_df, f"보성지사 남해선(영암순천) {kind} 개략 위치")
    st.plotly_chart(fig, use_container_width=True)

    # 상세 정보 표
    detail = selected_df.copy()
    detail["추정 시작(k)"], detail["추정 종료(k)"] = zip(*detail.apply(
        lambda r: calc_span(r["이정_km"], r.get("연장_m"))[:2], axis=1
    ))
    detail["연장(m)"] = detail["연장_m"].round(1)
    detail["이정(k)"] = detail["이정_km"].round(3)

    show_cols = ["시설명", "시설구분", "방향", "종별표시", "이정(k)", "연장(m)", "추정 시작(k)", "추정 종료(k)"]
    st.markdown("#### 선택 시설 정보")
    st.dataframe(
        detail[show_cols],
        hide_index=True,
        use_container_width=True,
    )

    st.caption(
        "※ 추정 시작/종료는 이정을 중심으로 연장의 절반을 좌우에 배치해 계산했습니다. "
        "실제 관리대장상의 시·종점 이정과는 다를 수 있으며, 위치 기억용 개략 도식입니다."
    )


def main():
    st.set_page_config(page_title="보성지사 교량·터널 위치 검색", layout="wide")

    st.title("보성지사 교량·터널 개략 위치 검색")
    st.write(
        "남해선(영암순천) 0k ~ 106.84k 구간에서 교량 또는 터널명을 검색하면 "
        "IC 기준 개략 위치와 방향별 위치를 표시합니다."
    )

    with st.expander("사용 방법", expanded=False):
        st.markdown(
            """
            - `ㅅ`처럼 초성만 입력하면 초성이 일치하는 시설물이 검색됩니다.
            - `서`, `서영암`, `강진`처럼 실제 글자를 입력해도 검색됩니다.
            - 시설물명에 `(순천)`이 있으면 아래쪽 순천방향, `(영암)`이 있으면 위쪽 영암방향에 표시합니다.
            - 방향 표기가 없는 시설물은 양방향/공용으로 보고 양쪽에 모두 표시합니다.
            - 교량은 연장이 짧아 실제 축척대로 그리면 거의 보이지 않으므로, 도식에서는 최소 폭을 적용합니다.
            """
        )

    try:
        bridge_df, tunnel_df = load_all_data()
    except Exception as e:
        st.error("데이터를 불러오지 못했습니다.")
        st.exception(e)
        st.info("app.py와 같은 폴더에 bridgedata.csv, tunneldata.csv 파일이 있는지 확인해 주세요.")
        return

    col1, col2, col3 = st.columns(3)
    col1.metric("교량 데이터", f"{len(bridge_df):,}개")
    col2.metric("터널 데이터", f"{len(tunnel_df):,}개")
    col3.metric("관리구간", f"{ROUTE_MIN_KM:g}k ~ {ROUTE_MAX_KM:g}k")

    tab_bridge, tab_tunnel = st.tabs(["교량명 검색", "터널명 검색"])
    with tab_bridge:
        show_facility_tab(bridge_df, "교량")
    with tab_tunnel:
        show_facility_tab(tunnel_df, "터널")


if __name__ == "__main__":
    main()
