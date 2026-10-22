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

# 상단 달력 선택 컨트롤러 (최대 선택 가능 날짜: 어제)
col_date, _ = st.columns([1, 2])
with col_date:
    selected_date = st.date_input(
        "📅 조회 날짜 선택",
        value=yesterday_kst,
        max_value=yesterday_kst,  # 오늘 건 아직 집계 전이므로 어제까지 선택 가능
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


# 3) 영화 상세 정보 API 호출 (24시간 캐싱)
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

    if "faultInfo" in raw_data:
        fault = raw_data["faultInfo"]
        st.error(f"⚠️ API 오류 ({fault.get('errorCode')}): {fault.get('message')}")
        return

    box_result = raw_data.get("boxOfficeResult", {})
    box_list = box_result.get("dailyBoxOfficeList") or box_result.get("weeklyBoxOfficeList", [])

    if not box_list:
        st.warning("그날은 아직 집계 전입니다")
        return

    df = pd.DataFrame(box_list)
    df["rank"] = df["rank"].astype(int)
    df["audiCnt"] = df["audiCnt"].astype(int)
    df["audiAcc"] = df["audiAcc"].astype(int)
    df["scrnCnt"] = df["scrnCnt"].astype(int)
    df["showCnt"] = df["showCnt"].astype(int)
    df["rankInten"] = df["rankInten"].astype(int)
    df["salesShare"] = df["salesShare"].astype(float)

    # --------------------------------------------------------------------------
    # [데이터 보강] 영화 상세 정보 연동 (장르, 관람등급, 스크린당 관객수 연산)
    # --------------------------------------------------------------------------
    genres_list = []
    ratings_list = []
    
    for m_code in df["movieCd"]:
        d_info, _ = fetch_movie_detail(api_key, m_code)
        if d_info:
            g_str = ", ".join([g["genreNm"] for g in d_info.get("genres", [])]) or "기타"
            r_str = d_info.get("audits", [{}])[0].get("watchGradeNm", "정보 없음") if d_info.get("audits") else "정보 없음"
        else:
            g_str, r_str = "기타", "정보 없음"
        genres_list.append(g_str)
        ratings_list.append(r_str)

    df["genres"] = genres_list
    df["rating"] = ratings_list
    # 스크린당 관객수 (알짜 흥행 지표) 연산
    df["audi_per_scrn"] = (df["audiCnt"] / df["scrnCnt"].replace(0, 1)).round(1)

    # --------------------------------------------------------------------------
    # [필터링 UI] (기능 4: 관람등급 & 장르 필터)
    # --------------------------------------------------------------------------
    with st.expander("🎯 관람등급 및 장르 필터링 설정", expanded=False):
        f_col1, f_col2 = st.columns(2)
        
        all_ratings = sorted(list(set(df["rating"])))
        selected_ratings = f_col1.multiselect("관람등급 선택", options=all_ratings, default=all_ratings)

        # 개별 장르 단어 추출
        unique_genres = set()
        for g_item in df["genres"]:
            for g in g_item.split(", "):
                if g: unique_genres.add(g)
        all_genres = sorted(list(unique_genres))
        selected_genres = f_col2.multiselect("장르 선택", options=all_genres, default=all_genres)

    # 필터 적용
    filtered_df = df[
        df["rating"].isin(selected_ratings) &
        df["genres"].apply(lambda x: any(g in x for g in selected_genres))
    ].copy()

    if filtered_df.empty:
        st.warning("선택하신 조건(관람등급/장르)에 해당하는 영화가 없습니다. 필터를 변경해 주세요.")
        return

    # --------------------------------------------------------------------------
    # [1] 주요 지표 카드 (1위 영화 + 스크린당 효율 1위 영화) - 기능 2
    # --------------------------------------------------------------------------
    top1 = filtered_df.iloc[0]
    rank_inten = top1["rankInten"]
    if rank_inten > 0:
        delta_text = f"🔺 +{rank_inten}"
        delta_color = "normal"
