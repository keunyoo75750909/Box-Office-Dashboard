from datetime import datetime, timedelta, timezone
import urllib.parse
import pandas as pd
import plotly.express as px
import requests
import streamlit as st

# ------------------------------------------------------------------------------
# 1. 스트림릿 페이지 기본 설정
# ------------------------------------------------------------------------------
st.set_page_config(
    page_title="박스오피스 종합 탐색기",
    page_icon="🎬",
    layout="wide"
)

# ------------------------------------------------------------------------------
# 2. 한국 시간(KST) 기준 어제 날짜 및 달력 선택기
# ------------------------------------------------------------------------------
kst = timezone(timedelta(hours=9))
now_kst = datetime.now(kst)
yesterday_kst = (now_kst - timedelta(days=1)).date()

st.title("🎬 박스오피스 종합 탐색기")

# 상단 날짜 선택 컨트롤러 (최대 선택 가능 날짜: 어제)
col_date, _ = st.columns([1, 2])
with col_date:
    selected_date = st.date_input(
        "📅 조회 날짜 선택",
        value=yesterday_kst,
        max_value=yesterday_kst,
        help="오늘 건 아직 집계 전이므로 어제 날짜까지만 선택할 수 있습니다."
    )

target_dt_str = selected_date.strftime("%Y%m%d")
display_date_str = selected_date.strftime("%Y년 %m월 %d일")

st.caption(f"🗓️ **선택한 날짜**: {display_date_str}")
st.divider()


# ------------------------------------------------------------------------------
# 3. KOBIS API 키 불러오기 및 캐싱 함수
# ------------------------------------------------------------------------------
api_key = st.secrets.get("KOBIS_KEY", None)

if not api_key:
    st.error("⚠️ **API 인증키(KOBIS_KEY)가 설정되지 않았습니다.**")
    st.info("""
    **[해결 방법]**
    Streamlit Cloud 설정의 **Secrets**에 아래와 같이 인증키를 등록해 주세요:
    ```toml
    KOBIS_KEY = "발급받은_KOBIS_인증키"
    ```
    """)
    st.stop()


# 1) 일별 박스오피스 API 호출
@st.cache_data(ttl=3600)
def fetch_daily_box_office(key: str, dt: str):
    url = "https://www.kobis.or.kr/kobisopenapi/webservice/rest/boxoffice/searchDailyBoxOfficeList.json"
    params = {"key": key, "targetDt": dt}
    try:
        res = requests.get(url, params=params, timeout=10)
        res.raise_for_status()
        return res.json(), None
    except Exception as e:
        return None, str(e)


# 2) 주간/주말 박스오피스 API 호출
@st.cache_data(ttl=3600)
def fetch_weekly_box_office(key: str, dt: str, week_gb: str = "0"):
    url = "https://www.kobis.or.kr/kobisopenapi/webservice/rest/boxoffice/searchWeeklyBoxOfficeList.json"
    params = {"key": key, "targetDt": dt, "weekGb": week_gb}
    try:
        res = requests.get(url, params=params, timeout=10)
        res.raise_for_status()
        return res.json(), None
    except Exception as e:
        return None, str(e)


# 3) 영화 상세 정보 API 호출 (선택한 영화 1개만 조회)
@st.cache_data(ttl=86400)
def fetch_movie_detail(key: str, movie_cd: str):
    url = "https://www.kobis.or.kr/kobisopenapi/webservice/rest/movie/searchMovieInfo.json"
    params = {"key": key, "movieCd": movie_cd}
    try:
        res = requests.get(url, params=params, timeout=10)
        res.raise_for_status()
        return res.json().get("movieInfoResult", {}).get("movieInfo", {}), None
    except Exception as e:
        return None, str(e)


# ------------------------------------------------------------------------------
# 4. 공통 대시보드 렌더링 함수
# ------------------------------------------------------------------------------
def render_box_office_dashboard(raw_data, req_err, tab_name):
    if req_err:
        st.error(f"❌ 데이터 요청 중 오류가 발생했습니다: {req_err}")
        return

    if not raw_data or "faultInfo" in raw_data:
        fault = raw_data.get("faultInfo", {}) if raw_data else {}
        st.error(f"⚠️ API 오류 ({fault.get('errorCode', '오류')}): {fault.get('message', '데이터를 불러올 수 없습니다.')}")
        return

    box_result = raw_data.get("boxOfficeResult", {})
    box_list = box_result.get("dailyBoxOfficeList") or box_result.get("weeklyBoxOfficeList", [])

    if not box_list:
        st.warning("그날은 아직 집계 전입니다")
        return

    # 데이터프레임 변환 및 타입 정의
    df = pd.DataFrame(box_list)
    df["rank"] = df["rank"].astype(int)
    df["audiCnt"] = df["audiCnt"].astype(int)
    df["audiAcc"] = df["audiAcc"].astype(int)
    df["scrnCnt"] = df["scrnCnt"].astype(int)
    df["showCnt"] = df["showCnt"].astype(int)
    df["rankInten"] = df["rankInten"].astype(int)
    df["salesShare"] = df["salesShare"].astype(float)

    # 스크린당 평균 관객수 (알짜 흥행 지표) 연산
    df["audi_per_scrn"] = (df["audiCnt"] / df["scrnCnt"].replace(0, 1)).round(1)

    # --------------------------------------------------------------------------
    # [1] 주요 하이라이트 지표 카드
    # --------------------------------------------------------------------------
    top1 = df.iloc[0]
    rank_inten = top1["rankInten"]
    if rank_inten > 0:
        delta_text = f"🔺 +{rank_inten}"
        delta_color = "normal"
    elif rank_inten < 0:
        delta_text = f"🔵 -{abs(rank_inten)}"
        delta_color = "inverse"
    else:
        delta_text = "NEW (신규)" if top1.get("rankOldAndNew") == "NEW" else "─ 변동 없음"
        delta_color = "off"

    # 스크린당 관객수 효율 1위 영화
    best_eff = df.loc[df["audi_per_scrn"].idxmax()]

    # 따옴표와 괄호를 보정한 소제목 출력 부분
    st.subheader(f"🏆 {tab_name} 주요 하이라이트")
    
    m1, m2, m3 = st.columns(3)
    
    top1_display_name = f"{top1['movieNm']} 🏆" if top1["audiAcc"] >= 1_000_000 else top1["movieNm"]
    
    m1.metric("🎬 1위 영화", top1_display_name, f"개봉일: {top1['openDt']}", delta_color="off")
    m2.metric("🍿 1위 관객수", f"{top1['audiCnt']:,} 명", delta_text, delta_color=delta_color)
    m3.metric(
        "🔥 최고 효율 흥행작 (스크린당)", 
        best_eff["movieNm"], 
        f"관객 {best_eff['audi_per_scrn']:.1f}명 / 스크린", 
        delta_color="normal"
    )

    st.write("")

    # --------------------------------------------------------------------------
    # [2] 시각화 차트 (관객수 막대 / 매출 점유율 파이)
    # --------------------------------------------------------------------------
    chart_col1, chart_col2 = st.columns(2)

    with chart_col1:
        st.markdown("##### 📊 관객수 상위 5개 영화")
        top5_df = df.head(5).sort_values(by="rank", ascending=False)
        fig_bar = px.bar(
            top5_df,
            x="audiCnt",
            y="movieNm",
            orientation="h",
            text="audiCnt",
            color="audiCnt",
            color_continuous_scale="Purples"
        )
        fig_bar.update_traces(
            texttemplate="%{text:,} 명",
            textposition="outside",
            hovertemplate="<b>%{y}</b><br>관객수: %{x:,} 명<extra></extra>"
        )
        fig_bar.update_layout(
            xaxis_title="관객수 (명)",
            yaxis_title="",
            coloraxis_showscale=False,
            height=360,
            margin=dict(l=10, r=30, t=10, b=10)
        )
        st.plotly_chart(fig_bar, use_container_width=True)

    with chart_col2:
        st.markdown("##### 🥧 상위 10개 영화 매출액 점유율 (%)")
        fig_pie = px.pie(
            df.head(10),
            values="salesShare",
            names="movieNm",
            hole=0.4,
            color_discrete_sequence=px.colors.qualitative.Pastel
        )
        fig_pie.update_traces(
            textinfo="percent+label",
            hovertemplate="<b>%{label}</b><br>매출 점유율: %{value}%<extra></extra>"
        )
        fig_pie.update_layout(
            showlegend=False,
            height=360,
            margin=dict(l=10, r=10, t=10, b=10)
        )
        st.plotly_chart(fig_pie, use_container_width=True)

    st.write("")

    # --------------------------------------------------------------------------
    # [3] 전체 박스오피스 순위 표 (알짜 흥행 지표 포함)
    # --------------------------------------------------------------------------
    st.markdown(f"##### 📋 {tab_name} 전체 순위 표")
    
    table_df = df.copy()

    def format_rank_change(row):
        inten = row["rankInten"]
        if row.get("rankOldAndNew") == "NEW":
            return "🆕 NEW"
        if inten > 0:
            return f"🔺 +{inten}"
        elif inten < 0:
            return f"🔵 -{abs(inten)}"
        else:
            return "─"

    table_df["순위 변동"] = table_df.apply(format_rank_change, axis=1)

    table_df["영화명_표시"] = table_df.apply(
        lambda r: f"{r['movieNm']} 🏆" if r["audiAcc"] >= 1_000_000 else r["movieNm"], 
        axis=1
    )

    display_table = table_df[[
        "rank", "순위 변동", "영화명_표시", "openDt", 
        "audiCnt", "audi_per_scrn", "audiAcc", "salesShare", "scrnCnt"
    ]].copy()
    
    display_table.columns = [
        "순위", "순위 변동", "영화명", "개봉일", 
        "기간 관객수", "스크린당 관객수", "누적 관객수", "매출 점유율(%)", "스크린수"
    ]

    display_table["기간 관객수"] = display_table["기간 관객수"].apply(lambda x: f"{x:,} 명")
    display_table["스크린당 관객수"] = display_table["스크린당 관객수"].apply(lambda x: f"{x:.1f} 명/개")
    display_table["누적 관객수"] = display_table["누적 관객수"].apply(lambda x: f"{x:,} 명")
    display_table["매출 점유율(%)"] = display_table["매출 점유율(%)"].apply(lambda x: f"{x:.1f} %")
    display_table["스크린수"] = display_table["스크린수"].apply(lambda x: f"{x:,} 개")

    st.dataframe(display_table, use_container_width=True, hide_index=True)

    st.write("")

    # --------------------------------------------------------------------------
    # [4] 영화 상세 정보 조회 + 외부링크 버튼
    # --------------------------------------------------------------------------
    st.markdown("##### 🔍 영화 상세 정보 조회")
    movie_options = {f"{row['rank']}위 : {row['movieNm']}": row['movieCd'] for _, row in df.iterrows()}
    
    selected_movie_label = st.selectbox(
        "상세 정보를 확인할 영화를 선택하세요",
        options=list(movie_options.keys()),
        key=f"select_{tab_name}"
    )

    if selected_movie_label:
        selected_code = movie_options[selected_movie_label]
        with st.spinner("영화 세부 정보를 불러오는 중입니다..."):
            detail, detail_err = fetch_movie_detail(api_key, selected_code)

        if detail_err or not detail:
            st.warning("영화 상세 정보를 불러올 수 없습니다.")
        else:
            movie_title = detail.get('movieNm', '')
            movie_nm_en = detail.get("movieNmEn", "")
            show_tm = detail.get("showTm", "-")
            
            genres = ", ".join([g["genreNm"] for g in detail.get("genres", [])]) or "정보 없음"
            directors = ", ".join([d["peopleNm"] for d in detail.get("directors", [])]) or "정보 없음"
            actors = ", ".join([a["peopleNm"] for a in detail.get("actors", [])[:5]]) or "정보 없음"
            audits = detail.get("audits", [{}])[0].get("watchGradeNm", "정보 없음") if detail.get("audits") else "정보 없음"
            nations = ", ".join([n["nationNm"] for n in detail.get("nations", [])]) or "정보 없음"

            summary_story = (
                f"본 작품은 **{nations}**에서 제작된 **{genres}** 장르의 영화로, **{directors}** 감독이 연출을 맡았습니다.\n"
                f"배우 **{actors}** 등이 열연을 펼치며 극장가에서 관객들의 몰입과 흥미를 이끌어내고 있습니다."
            )

            # 상세 정보 카드
            st.info(f"""
            🎬 **{movie_title}** ({movie_nm_en})
            
            • **장르**: {genres} | **제작국가**: {nations}  
            • **상영시간**: {show_tm}분 | **관람등급**: {audits}  
            • **감독**: {directors}  
            • **주요 출연진**: {actors}
            
            ---
            📖 **영화 줄거리 및 개요**  
            {summary_story}
            """)

            # 외부 링크 버튼 2개 (유튜브 예고편 / 네이버 검색)
            encoded_title = urllib.parse.quote(movie_title)
            yt_url = f"https://www.youtube.com/results?search_query={encoded_title}+예고편"
            naver_url = f"https://search.naver.com/search.naver?query=영화+{encoded_title}"

            btn_col1, btn_col2, _ = st.columns([1, 1, 2])
            btn_col1.link_button("🎬 유튜브 예고편 검색", yt_url, use_container_width=True)
            btn_col2.link_button("🔍 네이버 영화 정보 검색", naver_url, use_container_width=True)


# ------------------------------------------------------------------------------
# 5. 탭 구성 (일별 / 주말 / 주간 박스오피스)
# ------------------------------------------------------------------------------
tab1, tab2, tab3 = st.tabs(["📅 일별 박스오피스", "🗓️ 주말 박스오피스", "📆 주간 박스오피스"])

with tab1:
    daily_data, daily_err = fetch_daily_box_office(api_key, target_dt_str)
    render_box_office_dashboard(daily_data, daily_err, "일별 박스오피스")

with tab2:
    weekend_data, weekend_err = fetch_weekly_box_office(api_key, target_dt_str, week_gb="1")
    render_box_office_dashboard(weekend_data, weekend_err, "주말 박스오피스")

with tab3:
    weekly_data, weekly_err = fetch_weekly_box_office(api_key, target_dt_str, week_gb="0")
    render_box_office_dashboard(weekly_data, weekly_err, "주간 박스오피스")
