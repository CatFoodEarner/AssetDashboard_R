import streamlit as st
import yfinance as yf
import pandas as pd
import requests
from bs4 import BeautifulSoup
import pandas_datareader.data as web
import datetime

st.set_page_config(page_title="Gold Factor Dashboard", layout="wide")

st.title("🪙 금(Gold) 팩터 및 동향 대시보드")

# 1. 국제 금 및 환율 데이터 로드
@st.cache_data(ttl=3600)
def load_historical_data():
    try:
        xau = yf.Ticker("GC=F").history(period="3y")['Close']
        krw = yf.Ticker("KRW=X").history(period="3y")['Close']
        
        xau.index = pd.to_datetime(xau.index).tz_localize(None).normalize()
        krw.index = pd.to_datetime(krw.index).tz_localize(None).normalize()
        
        df = pd.DataFrame({'XAU_USD_oz': xau, 'USD_KRW': krw})
        df = df.ffill().dropna()
        
        OZ_TO_GRAM = 31.1034768
        df['XAU_USD_g'] = df['XAU_USD_oz'] / OZ_TO_GRAM
        df['XAU_KRW_g'] = df['XAU_USD_g'] * df['USD_KRW']
        
        return df
    except Exception as e:
        st.error(f"금 데이터 로딩 에러: {e}")
        return pd.DataFrame()

# 2. 국내 금 현재가 크롤링
def get_current_domestic_gold():
    try:
        url = "https://finance.naver.com/marketindex/"
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8',
            'Accept-Language': 'ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7',
            'Referer': 'https://finance.naver.com/'
        }
        res = requests.get(url, headers=headers, timeout=5)
        res.raise_for_status()
        soup = BeautifulSoup(res.text, 'html.parser')
        gold_str = soup.select_one('a.gold_domestic .value').text
        return float(gold_str.replace(',', ''))
    except Exception as e:
        st.error(f"국내 금 데이터 수집 에러: {e}")
        return None

# 3. 매크로 및 IEF 데이터 로드 (FRED & yfinance)
@st.cache_data(ttl=3600)
def load_macro_data():
    try:
        end = datetime.datetime.now()
        start = end - datetime.timedelta(days=365*3) # 추이를 보기 위해 3년치 로드

        # FRED 매크로 지표 (DFII10: 10년물 실질금리, M2SL: M2 유동성, CPIAUCSL: 소비자물가지수)
        fred_df = web.DataReader(['DFII10', 'M2SL', 'CPIAUCSL'], 'fred', start, end)
        fred_df = fred_df.ffill().dropna()
        
        # 실질 M2 계산 = (명목 M2 / CPI) * 100
        fred_df['Real_M2'] = (fred_df['M2SL'] / fred_df['CPIAUCSL']) * 100

        # IEF (미국 7-10년물 국채 ETF) 수정종가 (배당 재투자 포함 Total Return용)
        ief = yf.Ticker("IEF").history(period="3y")['Close']
        ief.index = pd.to_datetime(ief.index).tz_localize(None).normalize()

        return fred_df, ief
    except Exception as e:
        st.error(f"매크로 데이터 로딩 에러: {e}")
        return pd.DataFrame(), pd.Series()

# --- 데이터 실행 ---
df = load_historical_data()
fred_df, ief = load_macro_data()
current_domestic_price = get_current_domestic_gold()

# --- UI 레이아웃 구성 ---
if not df.empty:
    latest_intl_krw_g = df['XAU_KRW_g'].iloc[-1]
    df['1M_Return'] = df['XAU_USD_oz'].pct_change(periods=21) * 100
    df['3M_Return'] = df['XAU_USD_oz'].pct_change(periods=63) * 100
    df['6M_Return'] = df['XAU_USD_oz'].pct_change(periods=126) * 100
    df['12M_Return'] = df['XAU_USD_oz'].pct_change(periods=252) * 100
    latest_returns = df.iloc[-1]

    st.subheader("📊 현재 금 가격 및 괴리율 (g당)")
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("국제 금 환산가 (KRW/g)", f"{latest_intl_krw_g:,.0f} 원")
    if current_domestic_price:
        col2.metric("국내 금 현물 (KRW/g)", f"{current_domestic_price:,.0f} 원")
        disparity = ((current_domestic_price - latest_intl_krw_g) / latest_intl_krw_g) * 100
        col3.metric("프리미엄 (괴리율)", f"{disparity:.2f} %")
    else:
        col2.metric("국내 금 현물 (KRW/g)", "수집 불가")
        col3.metric("프리미엄 (괴리율)", "-")
    col4.metric("원/달러 환율", f"{latest_returns['USD_KRW']:,.1f} 원")

    st.markdown("---")
    st.subheader("📈 국제 금 상승률 (Momentum)")
    m_col1, m_col2, m_col3, m_col4 = st.columns(4)
    m_col1.metric("1개월 상승률", f"{latest_returns['1M_Return']:.2f}%")
    m_col2.metric("3개월 상승률", f"{latest_returns['3M_Return']:.2f}%")
    m_col3.metric("6개월 상승률", f"{latest_returns['6M_Return']:.2f}%")
    m_col4.metric("12개월 상승률", f"{latest_returns['12M_Return']:.2f}%")

    st.markdown("---")

# 새롭게 추가된 매크로 팩터 섹션
if not fred_df.empty and not ief.empty:
    st.subheader("🦅 금 핵심 매크로 팩터 (실질금리, 유동성, 미국채)")
    
    # 지표 계산 (약 252 거래일 기준 1년)
    ief_1y_return = (ief.iloc[-1] / ief.iloc[-252] - 1) * 100 if len(ief) >= 252 else 0
    current_real_rate = fred_df['DFII10'].iloc[-1]
    # M2 YoY (1년 전 대비 증감률)
    real_m2_yoy = (fred_df['Real_M2'].iloc[-1] / fred_df['Real_M2'].iloc[-252] - 1) * 100 if len(fred_df) >= 252 else 0

    mac_col1, mac_col2, mac_col3 = st.columns(3)
    mac_col1.metric("IEF (미 7-10년물) 1년 Total Return", f"{ief_1y_return:.2f} %")
    mac_col2.metric("미국 10년물 실질금리 (TIPS)", f"{current_real_rate:.2f} %")
    mac_col3.metric("실질 M2 YoY (유동성 증감)", f"{real_m2_yoy:.2f} %")

    col_chart1, col_chart2 = st.columns(2)
    with col_chart1:
        st.markdown("**📉 미국 10년물 실질금리 3년 추이**")
        st.line_chart(fred_df['DFII10'], height=250)
    with col_chart2:
        st.markdown("**🌊 미국 실질 M2 3년 추이 (물가조정 유동성)**")
        st.line_chart(fred_df['Real_M2'], height=250)

st.markdown("---")
if not df.empty:
    st.subheader("📉 국제 금 가격(USD/oz) 장기 추이")
    st.line_chart(df[['XAU_USD_oz']], height=400)