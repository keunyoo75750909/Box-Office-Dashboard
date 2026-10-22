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

    st.subheader(f"🏆 {tab_name} 주요 하이라이트
