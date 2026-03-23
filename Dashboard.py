import streamlit as st
import yfinance as yf
import pandas as pd
import requests
from bs4 import BeautifulSoup
import pandas_datareader.data as web
import datetime
import time
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from pykrx import stock
import FinanceDataReader as fdr

st.set_page_config(page_title="Asset Factor Dashboard", layout="wide")

# ==========================================
# 1. 공통 사이드바 (메뉴 네비게이션)
# ==========================================
st.sidebar.title("🧭 투자 자산 대시보드")
page = st.sidebar.radio("자산군 선택", ["🪙 금 (Gold)", "🇰🇷 한국 주식 (KOSPI)"])

# ==========================================
# 2. 금 (Gold) 페이지 함수 모음
# ==========================================
@st.cache_data(ttl=3600)
# 금 Data
def load_gold_data():
    max_retries = 3
    for attempt in range(max_retries):
        try:
            xau = yf.Ticker("GC=F").history(period="2y")['Close']
            krw = yf.Ticker("KRW=X").history(period="2y")['Close']
            if xau.empty or krw.empty: raise ValueError("빈 데이터 반환")
            xau.index = pd.to_datetime(xau.index).tz_localize(None).normalize()
            krw.index = pd.to_datetime(krw.index).tz_localize(None).normalize()
            df = pd.DataFrame({'XAU_USD_oz': xau, 'USD_KRW': krw}).ffill().dropna()
            df['XAU_USD_g'] = df['XAU_USD_oz'] / 31.1034768
            df['XAU_KRW_g'] = df['XAU_USD_g'] * df['USD_KRW']
            return df
        except:
            if attempt < max_retries - 1: time.sleep(3)
            else: return pd.DataFrame()

@st.cache_data(ttl=3600)

# 매크로 및 IEF 데이터 로드 (FRED & yfinance)
def load_macro_data():
    try:
        end = datetime.datetime.now()
        start = end - datetime.timedelta(days=365*5) # 추이를 보기 위해 5년치 로드

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
    
# 국내 금 현재가 크롤링
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

# ==========================================
# 3. 한국 주식 (KOSPI) 페이지 함수 모음 (FinanceDataReader로 교체)
# ==========================================
@st.cache_data(ttl=3600)
def load_korean_market_data():
    try:
        end = datetime.datetime.today()
        start = end - datetime.timedelta(days=365*3)
        
        # pykrx의 '지수명' 버그를 피하기 위해 FinanceDataReader 사용
        # KS11: 코스피, KS200: 코스피 200, KQ11: 코스닥
        kospi = fdr.DataReader('KS11', start, end)['Close']
        kospi200 = fdr.DataReader('KS200', start, end)['Close']
        kosdaq = fdr.DataReader('KQ11', start, end)['Close'] # 소형주 대용
        
        # V-KOSPI는 야후 파이낸스 사용 (^VKOSPI)
        vkospi = yf.Ticker("^VKOSPI").history(period="3y")['Close']
        vkospi.index = pd.to_datetime(vkospi.index).tz_localize(None).normalize()

        df = pd.DataFrame({
            'KOSPI': kospi,
            'KOSPI200': kospi200,
            'KOSDAQ(중소형)': kosdaq
        }).ffill().dropna()

        return df, vkospi
    except Exception as e:
        st.error(f"한국 주식 데이터 로딩 에러: {e}")
        return pd.DataFrame(), pd.Series()

# ==========================================
# UI 렌더링 (선택된 페이지에 따라 다르게 그림)
# ==========================================

if page == "🪙 금 (Gold)":
    st.title("🪙 금(Gold) 팩터 대시보드")
    df = load_gold_data()
    fred_df, ief = load_macro_data()
    current_domestic_price = get_current_domestic_gold()

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
            st.markdown("**📉 미국 10년물 실질금리 5년 추이**")
            st.line_chart(fred_df['DFII10'], height=250)
        with col_chart2:
            st.markdown("**🌊 미국 실질 M2 5년 추이 (물가조정 유동성)**")
            st.line_chart(fred_df['Real_M2'], height=250)


    st.markdown("---")

    # 데이터가 모두 정상적으로 로드되었을 때만 차트 그리기
    if not df.empty and not fred_df.empty:
        st.subheader("📉 국제 금(USD) vs 미 실질금리 팩터 분석")
        
        # 금 데이터와 매크로 데이터의 날짜를 맞춰서 병합 (Inner Join)
        combined_df = df.join(fred_df, how='inner')
        
        # 이중 축 차트 뼈대 만들기
        fig = make_subplots(specs=[[{"secondary_y": True}]])

        # 1. 왼쪽 축: 국제 금 가격 (금색 실선)
        fig.add_trace(
            go.Scatter(x=combined_df.index, y=combined_df['XAU_USD_oz'], name="국제 금 (USD/oz)", line=dict(color="#FFD700", width=2)),
            secondary_y=False,
        )

        # 2. 오른쪽 축: 10년물 실질금리 (파란색 점선)
        fig.add_trace(
            go.Scatter(x=combined_df.index, y=combined_df['DFII10'], name="10년물 실질금리 (%)", line=dict(color="#1f77b4", dash="dot", width=2)),
            secondary_y=True,
        )

        # 레이아웃 및 축 설정
        fig.update_layout(
            height=500,
            margin=dict(l=20, r=20, t=30, b=20),
            hovermode="x unified", # 마우스를 올렸을 때 두 값을 동시에 보여줌
            legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1)
        )
        
        # y축 이름 및 설정 (실질금리 축은 직관적인 비교를 위해 뒤집음)
        fig.update_yaxes(title_text="금 가격 (USD/oz)", secondary_y=False)
        fig.update_yaxes(title_text="실질금리 (%) - 뒤집힘(역축)", autorange="reversed", showgrid=False, secondary_y=True)

        # Streamlit에 차트 띄우기
        st.plotly_chart(fig, use_container_width=True)        

elif page == "🇰🇷 한국 주식 (KOSPI)":
    st.title("🇰🇷 한국 주식 (KOSPI) 팩터 대시보드")
    kr_df, vkospi = load_korean_market_data()

    if not kr_df.empty:
        # --- 1. 모멘텀 (등락률) ---
        kr_df['1M_Ret'] = kr_df['KOSPI200'].pct_change(periods=21) * 100
        kr_df['3M_Ret'] = kr_df['KOSPI200'].pct_change(periods=63) * 100
        kr_df['6M_Ret'] = kr_df['KOSPI200'].pct_change(periods=126) * 100
        kr_df['12M_Ret'] = kr_df['KOSPI200'].pct_change(periods=252) * 100
        latest_kr = kr_df.iloc[-1]

        st.subheader("📈 KOSPI 200 등락률 (Momentum)")
        col1, col2, col3, col4, col5 = st.columns(5)
        col1.metric("현재 KOSPI 200", f"{latest_kr['KOSPI200']:.2f}")
        col2.metric("1개월", f"{latest_kr['1M_Ret']:.2f}%")
        col3.metric("3개월", f"{latest_kr['3M_Ret']:.2f}%")
        col4.metric("6개월", f"{latest_kr['6M_Ret']:.2f}%")
        col5.metric("12개월", f"{latest_kr['12M_Ret']:.2f}%")
        st.markdown("---")

        # --- 2. 3년 추이 및 비교 차트 ---
        st.subheader("📊 지수 3년 추이 및 등락률 비교")
        tab1, tab2 = st.tabs(["주가 지수 추이 (Price)", "누적 등락률 비교 (Normalized % / Base=100)"])
        
        with tab1:
            col_chart1, col_chart2, col_chart3 = st.columns(3)
            with col_chart1:
                st.markdown("**KOSPI**")
                st.line_chart(kr_df['KOSPI'], height=350)
            with col_chart2:
                st.markdown("**KOSPI200**")
                st.line_chart(kr_df['KOSPI200'], height=350)
            with col_chart3:
                st.markdown("**KOSDAQ(중소형)**")
                st.line_chart(kr_df['KOSDAQ(중소형)'], height=350)
        
        with tab2:
            # 시작일을 100으로 맞춘 누적 수익률 차트
            normalized_df = (kr_df[['KOSPI', 'KOSPI200', 'KOSDAQ(중소형)']] / kr_df[['KOSPI', 'KOSPI200', 'KOSDAQ(중소형)']].iloc[0]) * 100
            st.line_chart(normalized_df, height=350)
        st.markdown("---")

        # --- 3. 매크로 및 추가 지표 ---
        st.subheader("🦅 추가 지표 (V-KOSPI & 거시 지표)")
        m_col1, m_col2, m_col3 = st.columns(3)
        
        if not vkospi.empty:
            m_col1.metric("V-KOSPI (변동성 지수)", f"{vkospi.iloc[-1]:.2f}")
        else:
            m_col1.metric("V-KOSPI (변동성 지수)", "수집 불가")
            
        m_col2.metric("한국판 버핏 지수", "API 연동 필요", "시총 / GDP")
        m_col3.metric("Aggregate Investor Allocation", "API 연동 필요", "시총 / (부채+시총)")

        # --- 4. 밸류에이션 (PER, PBR 표) ---
        st.markdown("---")
        st.subheader("🧮 KOSPI 규모별 밸류에이션 (PER / PBR)")
        st.info("💡 실시간 월간 PER/PBR 데이터는 pykrx fundamental API를 통해 추출 중입니다. (코드 추가 예정)")