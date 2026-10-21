from datetime import datetime, timedelta
import pandas as pd
import requests
import streamlit as st

# 스트림릿 페이지 기본 설정 (제목, 레이아웃 등)
st.set_page_config(
    page_title="어제 박스오피스 순위", page_icon="🎬", layout="wide"
)

# 앱 제목 및 설명
st.title("🎬 어제 영화 박스오피스 순위")
st.markdown("영화진흥위원회(KOBIS) 오픈 API를 활용한 일별 박스오피스 정보입니다.")


# 한국 시간(KST, UTC+9) 기준 '어제' 날짜를 'YYYYMMDD' 형식으로 계산하는 함수
# (스트림릿 클라우드 서버는 UTC 시간대를 사용하므로 한국 시간으로 수동 보정합니다)
def get_yesterday_kst():
  # UTC 기준 현재 시각에 9시간을 더해 한국 시간(KST)을 구합니다.
  kst_now = datetime.utcnow() + timedelta(hours=9)
  # 한국 시간 기준 어제 날짜
  yesterday_kst = kst_now - timedelta(days=1)
  return yesterday_kst.strftime("%Y%m%d")


# 스트림릿 시크릿(Secrets)에서 KOBIS 인증키 불러오기
# (st.secrets 사용법에 따라 st.secrets["KOBIS_KEY"]로 접근합니다)
try:
  api_key = st.secrets["KOBIS_KEY"]
except Exception:
  st.error(
      "❌ **시크릿 설정 오류**: Streamlit Cloud Secrets에 `KOBIS_KEY`가 설정되어"
      " 있는지 확인해주세요.\n\n(로컬 환경인 경우 `.streamlit/secrets.toml` 파일을"
      " 만들어 키를 등록해 주세요.)"
  )
  st.stop()

# 조회 날짜 계산
target_dt = get_yesterday_kst()
display_date = f"{target_dt[:4]}년 {target_dt[4:6]}월 {target_dt[6:]}일"

st.info(f"📅 조회 기준일 (한국 시간 어제): **{display_date}**")

# KOBIS API 요청 URL 생성
url = (
    "https://www.kobis.or.kr/kobisopenapi/webservice/rest/boxoffice/searchDailyBoxOfficeList.json"
)
params = {"key": api_key, "targetDt": target_dt}


# API 데이터를 불러오는 함수 (캐시 기능을 적용하여 중복 요청 방지)
@st.cache_data(ttl=600)  # 10분간 캐시 유지
def fetch_box_office_data(request_url, request_params):
  try:
    response = requests.get(request_url, params=request_params, timeout=10)
    # HTTP 상태 코드가 정상(200)이 아닌 경우
    if response.status_code != 200:
      return (
          None,
          f"서버 연결에 실패했습니다. (HTTP 상태 코드: {response.status_code})",
      )

    data = response.json()

    # KOBIS API는 인증키가 틀려도 200 응답을 주며 faultInfo 필드를 포함해 반환합니다.
    if "faultInfo" in data:
      return (
          None,
          "API 오류(faultInfo)가 발생했습니다. 인증키(KOBIS_KEY)가 올바른지"
          " 확인해주세요.",
      )

    # 응답 구조 내에 박스오피스 목록이 존재하는지 확인
    if (
        "boxOfficeResult" not in data
        or "dailyBoxOfficeList" not in data["boxOfficeResult"]
    ):
      return None, "API 응답 데이터 구조가 올바르지 않습니다."

    movie_list = data["boxOfficeResult"]["dailyBoxOfficeList"]

    # 영화 목록이 비어 있는 경우
    if not movie_list:
      return (
          None,
          f"해당 날짜({display_date})에 집계된 박스오피스 데이터가 없습니다."
          " 아직 데이터가 업데이트되지 않았거나 휴일일 수 있습니다.",
      )

    return movie_list, None

  except requests.exceptions.RequestException as e:
    return (
        None,
        f"네트워크 요청 중 오류가 발생했습니다. 인터넷 연결이나 방화벽을"
        f" 확인해주세요. (상세: {e})",
    )
  except Exception as e:
    return None, f"알 수 없는 오류가 발생했습니다: {e}"


# 데이터 호출 실행
raw_data, error_message = fetch_box_office_data(url, params)

# 오류가 발생했거나 데이터가 비어 있는 경우 안내 메시지 출력
if error_message:
  st.error(f"### ⚠️ 안내\n{error_message}")
  st.markdown("---")
  st.markdown(
      "**체크리스트:**\n1. 스트림릿 클라우드 [Settings] -> [Secrets] 메뉴에"
      " `KOBIS_KEY`가 정확히 등록되어 있는지 확인해주세요.\n2. KOBIS 공식"
      " 홈페이지에서 발급받은 인증키가 유효한지 확인해주세요.\n3. 오늘 날짜 직전의"
      " 데이터가 아직 영화진흥위원회 서버에 반영되지 않았을 수 있습니다."
  )
  st.stop()

# 데이터 가공 (KOBIS API는 모든 숫자 값이 문자열 형태로 오므로 숫자로 변환)
df = pd.DataFrame(raw_data)

# 필요한 컬럼만 추출 및 이름 변경 (순위, 영화명, 개봉일, 관객수, 누적관객, 스크린수)
df_display = pd.DataFrame({
    "순위": df["rank"].astype(int),
    "영화명": df["movieNm"],
    "개봉일": df["openDt"],
    "관객수(명)": df["audiCnt"].astype(int),
    "누적관객(명)": df["audiAcc"].astype(int),
    "스크린수": df["scrnCnt"].astype(int),
})

# 순위 기준으로 오름차순 정렬
df_display = df_display.sort_values("순위").reset_index(drop=True)

# ---------------------------------------------------------
# 1위 영화 지표 카드 세 장 (관객수, 누적 관객, 스크린수)
# ---------------------------------------------------------
st.markdown("---")
st.subheader("🥇 1위 영화 주요 지표")

top_1 = df_display.iloc[0]

col1, col2, col3 = st.columns(3)
with col1:
  st.metric(
      label=f"1위: {top_1['영화명']} (관객수)",
      value=f"{top_1['관객수(명)']:,} 명",
  )
with col2:
  st.metric(
      label=f"1위: {top_1['영화명']} (누적 관객)",
      value=f"{top_1['누적관객(명)']:,} 명",
  )
with col3:
  st.metric(
      label=f"1위: {top_1['영화명']} (스크린수)",
      value=f"{top_1['스크린수']:,} 개",
  )

# ---------------------------------------------------------
# 관객수 상위 5편 막대그래프 시각화
# ---------------------------------------------------------
st.markdown("---")
st.subheader("📊 관객수 상위 5편 영화 비교")

# 상위 5개 데이터 추출
df_top5 = df_display.head(5).copy()
# 차트 X축용으로 보기 좋게 인덱스 설정
df_top5.set_index("영화명", inplace=True)

# 스트림릿 내장 바 차트 활용 (관객수 기준)
st.bar_chart(df_top5["관객수(명)"])

# ---------------------------------------------------------
# 전체 박스오피스 순위 표 출력
# ---------------------------------------------------------
st.markdown("---")
st.subheader("📋 전체 박스오피스 순위 표")

# 숫자에 천 단위 쉼표가 예쁘게 들어가도록 포맷팅 적용
st.dataframe(
    df_display.style.format({
        "관객수(명)": "{:,}",
        "누적관객(명)": "{:,}",
        "스크린수": "{:,}",
    }),
    use_container_width=True,
)
