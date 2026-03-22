import streamlit as st
import yfinance as yf
import pandas as pd
import requests
from bs4 import BeautifulSoup

st.set_page_config(page_title="Gold Factor Dashboard", layout="wide")

st.title("🪙 금(Gold) 팩터 및 동향 대시보드")

# 1. 국제 금 데이터 및 환율 데이터 로드 (Session 위장 및 캐싱)
# ttl=3600을 넣으면 1시간 동안은 서버에 다시 요청하지 않고 기존 데이터를 써서 차단 확률을 낮춤
@st.cache_data(ttl=3600) 
def load_historical_data():
    try:
        # 야후 파이낸스 전용 세션 생성 및 위장
        session = requests.Session()
        session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
        })
        
        # session=session 파라미터를 추가하여 호출
        xau = yf.Ticker("GC=F", session=session).history(period="2y")['Close']
        krw = yf.Ticker("KRW=X", session=session).history(period="2y")['Close']
        
        xau.index = pd.to_datetime(xau.index).tz_localize(None).normalize()
        krw.index = pd.to_datetime(krw.index).tz_localize(None).normalize()
        
        df = pd.DataFrame({'XAU_USD_oz': xau, 'USD_KRW': krw})
        df = df.ffill().dropna()
        
        OZ_TO_GRAM = 31.1034768
        df['XAU_USD_g'] = df['XAU_USD_oz'] / OZ_TO_GRAM
        df['XAU_KRW_g'] = df['XAU_USD_g'] * df['USD_KRW']
        
        return df
    except Exception as e:
        st.error(f"데이터 로딩 상세 에러: {e}")
        return pd.DataFrame()

# 2. 국내 금 현재가 크롤링 (차단 우회 강화 버전)
def get_current_domestic_gold():
    try:
        url = "https://finance.naver.com/marketindex/"
        # 헤더를 실제 브라우저와 완벽하게 동일하게 위장
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8',
            'Accept-Language': 'ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7',
            'Referer': 'https://finance.naver.com/' # 네이버에서 넘어온 것처럼 속임
        }
        res = requests.get(url, headers=headers, timeout=5)
        res.raise_for_status() # 접속 실패 시 즉각 에러 발생시켜서 원인 파악
        
        soup = BeautifulSoup(res.text, 'html.parser')
        gold_str = soup.select_one('a.gold_domestic .value').text
        return float(gold_str.replace(',', ''))
    except Exception as e:
        st.error(f"국내 금 데이터 수집 에러: {e}")
        return None

df = load_historical_data()

# 데이터 수집 실패 시 에러 메시지 띄우고 중단 (앱이 뻗는 것 방지)
if df.empty:
    st.error("🚨 야후 파이낸스에서 데이터를 불러오지 못했습니다. 잠시 후 다시 시도해 주세요.")
    st.stop()

current_domestic_price = get_current_domestic_gold()
latest_intl_krw_g = df['XAU_KRW_g'].iloc[-1]

# 3. 수익률(모멘텀) 계산 로직
df['1M_Return'] = df['XAU_KRW_g'].pct_change(periods=21) * 100
df['3M_Return'] = df['XAU_KRW_g'].pct_change(periods=63) * 100
df['6M_Return'] = df['XAU_KRW_g'].pct_change(periods=126) * 100
df['12M_Return'] = df['XAU_KRW_g'].pct_change(periods=252) * 100

latest_returns = df.iloc[-1]

# --- UI 레이아웃 구성 ---

st.subheader("📊 현재 금 가격 및 괴리율 (g당)")
col1, col2, col3, col4 = st.columns(4)

with col1:
    st.metric(label="국제 금 환산가 (KRW/g)", value=f"{latest_intl_krw_g:,.0f} 원")
    
with col2:
    if current_domestic_price:
        st.metric(label="국내 금 현물 (KRW/g)", value=f"{current_domestic_price:,.0f} 원")
    else:
        st.metric(label="국내 금 현물 (KRW/g)", value="수집 불가")

with col3:
    if current_domestic_price:
        disparity = ((current_domestic_price - latest_intl_krw_g) / latest_intl_krw_g) * 100
        st.metric(label="프리미엄 (괴리율)", value=f"{disparity:.2f} %")
    else:
        st.metric(label="프리미엄 (괴리율)", value="-")

with col4:
    st.metric(label="원/달러 환율", value=f"{latest_returns['USD_KRW']:,.1f} 원")

st.markdown("---")

st.subheader("📈 국제 금 환산가 상승률 (Momentum)")
m_col1, m_col2, m_col3, m_col4 = st.columns(4)
m_col1.metric("1개월 상승률", f"{latest_returns['1M_Return']:.2f}%")
m_col2.metric("3개월 상승률", f"{latest_returns['3M_Return']:.2f}%")
m_col3.metric("6개월 상승률", f"{latest_returns['6M_Return']:.2f}%")
m_col4.metric("12개월 상승률", f"{latest_returns['12M_Return']:.2f}%")

st.markdown("---")

st.subheader("📉 국제 금 환산가(KRW/g) 장기 추이")
st.line_chart(df[['XAU_KRW_g']], height=400)