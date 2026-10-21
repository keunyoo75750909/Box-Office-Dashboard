from datetime import datetime, timedelta, timezone
import pandas as pd
import plotly.express as px
import requests
import streamlit as st

# ------------------------------------------------------------------------------
# 1. 스트림릿 페이지 기본 설정
# ------------------------------------------------------------------------------
st.set_page_config(
    page_title="어제의 박스오피스",
    page_icon="🎬",
    layout="wide"
)

# ------------------------------------------------------------------------------
# 2. 어제 날짜 자동 계산 (한국 표준시 KST 기준)
# ------------------------------------------------------------------------------
# 배포 서버의 표준시(UTC)와 상관없이 한국 시간(UTC+9) 기준으로 정확하게 '어제'를 계산합니다.
kst = timezone(timedelta(hours=9))
now_kst = datetime.now(kst)
yesterday_kst = now_kst - timedelta(days=1)

# API 요청용 날짜 형식 (YYYYMMDD) 및 화면 표시용 날짜 형식
target_dt = yesterday_kst.strftime("%Y%m%d")
display_date = yesterday_kst.strftime("%Y년 %m월 %d일")

# 헤더 타이틀 표시
st.title("🎬 어제의 박스오피스")
st.caption(f"🗓️ **기준 날짜**: {display_date} (한국 시간 기준 어제 데이터)")
st.divider()


# ------------------------------------------------------------------------------
# 3. KOBIS API 키 불러오기 및 데이터 요청
# ------------------------------------------------------------------------------
# Streamlit Secrets(비밀 금고)에서 KOBIS_KEY를 가져옵니다.
api_key = st.secrets.get("KOBIS_KEY", None)

# [예외 처리 1] 비밀 금고에 API 키가 없는 경우 안내 메시지 출력
if not api_key:
    st.error("⚠️ **API 인증키(KOBIS_KEY)가 설정되지 않았습니다.**")
    st.info("""
    **[해결 방법]**
    1. **Streamlit Cloud 배포 시**: 
       앱 설정 페이지의 **Secrets** 메뉴에서 아래와 같이 인증키를 추가해 주세요.
       ```toml
       KOBIS_KEY = "발급받은_KOBIS_인증키"
       ```
    2. **로컬(내 컴퓨터) 실행 시**: 
       프로젝트 폴더 안에 `.streamlit/secrets.toml` 파일을 만들고 키를 적어주세요.
    3. 인증키는 [KOBIS 영화관입장권통합전산망 오픈API](https://www.kobis.or.kr/kobisopenapi)에서 무료로 발급받을 수 있습니다.
    """)
    st.stop()

# KOBIS API 데이터 호출 함수 (1시간 동안 데이터 캐싱으로 불필요한 중복 호출 방지)
@st.cache_data(ttl=3600)
def fetch_box_office(key: str, dt: str):
    url = "https://www.kobis.or.kr/kobisopenapi/webservice/rest/boxoffice/searchDailyBoxOfficeList.json"
    params = {
        "key": key,
        "targetDt": dt
    }
    try:
        response = requests.get(url, params=params, timeout=10)
        response.raise_for_status()
        return response.json(), None
    except Exception as e:
        return None, str(e)

# API 요청 실행
data, req_error = fetch_box_office(api_key, target_dt)


# ------------------------------------------------------------------------------
# 4. API 오류 및 응답 예외 처리
# ------------------------------------------------------------------------------
# [예외 처리 2] 네트워크 접속 오류가 발생한 경우
if req_error:
    st.error("❌ **KOBIS API 서버 연결에 실패했습니다.**")
    st.warning(f"오류 상세: {req_error}")
    st.info("💡 인터넷 연결 상태를 확인하시거나 KOBIS 서버 일시적 장애일 수 있으니 잠시 후 다시 시도해 주세요.")
    st.stop()

# [예외 처리 3] KOBIS에서 faultInfo(인증키 오류 등)를 반환한 경우
if "faultInfo" in data:
    fault = data["faultInfo"]
    err_message = fault.get("message", "알 수 없는 오류가 발생했습니다.")
    err_code = fault.get("errorCode", "UNKNOWN")
    
    st.error(f"⚠️ **KOBIS API 응답 오류가 발생했습니다. (오류 코드: {err_code})**")
    st.warning(f"메시지: {err_message}")
    st.info("""
    **[확인할 사항]**
    • Streamlit Secrets에 입력한 `KOBIS_KEY` 값이 올바른지 확인해 주세요.
    • 발급받은 인증키가 활성화 상태인지 KOBIS 마이페이지에서 확인해 주세요.
    """)
    st.stop()

# [예외 처리 4] 응답 구조에 영화 목록 데이터가 없거나 비어있는 경우
box_office_result = data.get("boxOfficeResult", {})
daily_list = box_office_result.get("dailyBoxOfficeList", [])

if not daily_list:
    st.warning(f"⚠️ **{display_date} 날짜의 박스오피스 데이터가 존재하지 않습니다.**")
    st.info("""
    **[확인할 사항]**
    • KOBIS 전산망의 일별 집계 시점에 따라 자정 직후에는 아직 데이터가 입력되지 않았을 수 있습니다.
    • 집계가 완료되는대로 업데이트되니 잠시 후 다시 확인해 주세요.
    """)
    st.stop()


# ------------------------------------------------------------------------------
# 5. 데이터 전처리 (문자열 -> 숫자 변환)
# ------------------------------------------------------------------------------
df = pd.DataFrame(daily_list)

# KOBIS API는 숫자 데이터도 문자열 형태로 전달하므로 숫자형 타입으로 변환합니다.
df["rank"] = df["rank"].astype(int)
df["audiCnt"] = df["audiCnt"].astype(int)
df["audiAcc"] = df["audiAcc"].astype(int)
df["scrnCnt"] = df["scrnCnt"].astype(int)
df["showCnt"] = df["showCnt"].astype(int)
df["rankInten"] = df["rankInten"].astype(int)


# ------------------------------------------------------------------------------
# 6. 1위 영화 하이라이트 (지표 카드 3장)
# ------------------------------------------------------------------------------
top1 = df.iloc[0]

# 전날 대비 순위 증감 라벨 만들기
rank_inten = top1["rankInten"]
if rank_inten > 0:
    delta_text = f"▲ {rank_inten}단계 상승"
    delta_color = "normal"
elif rank_inten < 0:
    delta_text = f"▼ {abs(rank_inten)}단계 하강"
    delta_color = "inverse"
else:
    delta_text = "NEW (신규 진입)" if top1.get("rankOldAndNew") == "NEW" else "─ 변동 없음"
    delta_color = "off"

st.subheader("🏆 어제의 1위 영화")
col1, col2, col3 = st.columns(3)

col1.metric(
    label="🎬 1위 영화명",
    value=top1["movieNm"],
    delta=f"개봉일: {top1['openDt']}",
    delta_color="off"
)

col2.metric(
    label="🍿 어제 관객수",
    value=f"{top1['audiCnt']:,} 명",
    delta=delta_text,
    delta_color=delta_color
)

col3.metric(
    label="🎟️ 누적 관객수",
    value=f"{top1['audiAcc']:,} 명",
    delta=f"상영 횟수: {top1['showCnt']:,} 회",
    delta_color="off"
)

st.divider()


# ------------------------------------------------------------------------------
# 7. 관객수 상위 5편 막대그래프 (Plotly 시각화)
# ------------------------------------------------------------------------------
st.subheader("📊 관객수 상위 5개 영화")

top5_df = df.head(5).copy()
# 가로 막대그래프에서 1위가 가장 위로 오도록 순서를 역순 정렬합니다.
top5_chart_df = top5_df.sort_values(by="rank", ascending=False)

fig = px.bar(
    top5_chart_df,
    x="audiCnt",
    y="movieNm",
    orientation="h",
    text="audiCnt",
    labels={"audiCnt": "어제 관객수(명)", "movieNm": "영화명"},
    color="audiCnt",
    color_continuous_scale="Purples"
)

# 차트 디자인 세부 설정
fig.update_traces(
    texttemplate="%{text:,} 명",
    textposition="outside",
    hovertemplate="<b>%{y}</b><br>어제 관객수: %{x:,} 명<extra></extra>"
)

fig.update_layout(
    xaxis_title="관객수 (명)",
    yaxis_title="",
    coloraxis_showscale=False,
    height=380,
    margin=dict(l=20, r=40, t=20, b=20)
)

st.plotly_chart(fig, use_container_width=True)

st.divider()


# ------------------------------------------------------------------------------
# 8. 일별 박스오피스 전체 표 (DataFrame)
# ------------------------------------------------------------------------------
st.subheader("📋 전체 박스오피스 순위 표")

# 요구된 컬럼 선택 (순위, 영화명, 개봉일, 관객수, 누적관객, 스크린수)
table_df = df[["rank", "movieNm", "openDt", "audiCnt", "audiAcc", "scrnCnt"]].copy()

# 보기 좋게 한글 열 이름으로 변경
table_df.columns = ["순위", "영화명", "개봉일", "어제 관객수", "누적 관객수", "스크린수"]

# 천 단위 쉼표(,) 및 단위를 붙여서 표시용 변환
formatted_df = table_df.copy()
formatted_df["어제 관객수"] = formatted_df["어제 관객수"].apply(lambda x: f"{x:,} 명")
formatted_df["누적 관객수"] = formatted_df["누적 관객수"].apply(lambda x: f"{x:,} 명")
formatted_df["스크린수"] = formatted_df["스크린수"].apply(lambda x: f"{x:,} 개")

st.dataframe(
    formatted_df,
    use_container_width=True,
    hide_index=True
)
