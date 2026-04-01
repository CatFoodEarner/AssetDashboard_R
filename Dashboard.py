import streamlit as st
import yfinance as yf
import pandas as pd
import requests
from bs4 import BeautifulSoup
import datetime
import time
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import FinanceDataReader as fdr
import re

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

# ==========================================
# 매크로 및 IEF 데이터 로드 (FinanceDataReader로 교체)
# ==========================================
@st.cache_data(ttl=3600)

def load_macro_data():
    try:
        import FinanceDataReader as fdr
        end = datetime.datetime.now()
        start = end - datetime.timedelta(days=365*3)

        # pandas-datareader 대신 fdr의 FRED 기능을 사용하여 각각 불러옴
        dfii10 = fdr.DataReader('FRED:DFII10', start, end).iloc[:, 0]
        m2sl = fdr.DataReader('FRED:M2SL', start, end).iloc[:, 0]
        cpiaucsl = fdr.DataReader('FRED:CPIAUCSL', start, end).iloc[:, 0]

        # 세 데이터를 하나의 DataFrame으로 조립
        fred_df = pd.DataFrame({
            'DFII10': dfii10,
            'M2SL': m2sl,
            'CPIAUCSL': cpiaucsl
        }).ffill().dropna()
        
        # 실질 M2 계산 = (명목 M2 / CPI) * 100
        fred_df['Real_M2'] = (fred_df['M2SL'] / fred_df['CPIAUCSL']) * 100

        # IEF (미국 7-10년물 국채 ETF) 종가
        ief = yf.Ticker("IEF").history(period="3y")['Close']
        ief.index = pd.to_datetime(ief.index).tz_localize(None).normalize()

        return fred_df, ief
    except Exception as e:
        st.error(f"매크로 데이터 로딩 에러: {e}")
        return pd.DataFrame(), pd.Series()
    
# 국내 금 현재가 크롤링
# 2. 국내 금 현재가 크롤링 (네이버 모바일 증권 - KRX 고유 코드 활용)
def get_current_domestic_gold():
    try:
        # 선생님이 찾아내신 KRX 국내 금 전용 모바일 URL
        url = "https://m.stock.naver.com/marketindex/metals/M04020000"
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
        }
        res = requests.get(url, headers=headers, timeout=5)
        soup = BeautifulSoup(res.text, 'html.parser')
        
        # Next.js의 데이터 보따리 추출
        script_data = soup.find('script', id='__NEXT_DATA__')
        if not script_data:
            return None
            
        import json
        data = json.loads(script_data.string)
        
        # JSON 보따리 안에서 KRX 고유코드(M04020000)를 가진 딕셔너리의 종가(closePrice)만 쏙 뽑아내는 탐색기
        def extract_price(obj):
            if isinstance(obj, dict):
                # 정확히 KRX 금 데이터 블록인지 확인
                if obj.get('reutersCode') == 'M04020000' and 'closePrice' in obj:
                    return obj['closePrice']
                for v in obj.values():
                    result = extract_price(v)
                    if result: return result
            elif isinstance(obj, list):
                for item in obj:
                    result = extract_price(item)
                    if result: return result
            return None

        price_str = extract_price(data)
        if price_str:
            return float(str(price_str).replace(',', ''))
        return None
        
    except Exception as e:
        st.error(f"한국거래소 금 데이터 수집 에러: {e}")
        return None
    
# ==========================================
# 3. Investing.com에서 V-KOSPI(변동성 지수) 현재가 긁어오기
# ==========================================

def get_current_vkospi():
    try:
        url = "https://kr.investing.com/indices/kospi-volatility"
        # Investing.com의 강력한 봇 차단을 뚫기 위한 한국어 + 최신 브라우저 위장 헤더
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8',
            'Accept-Language': 'ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7',
        }
        res = requests.get(url, headers=headers, timeout=5)
        soup = BeautifulSoup(res.text, 'html.parser')
        
        # 선생님이 찾으신 고유 속성 data-test="instrument-price-last" 로 타겟팅
        price_element = soup.select_one('[data-test="instrument-price-last"]')
        
        if price_element:
            return float(price_element.text.replace(',', ''))
        else:
            return None
    except Exception as e:
        return None
    
# ==========================================
# 4. 한국은행 ECOS API (매크로 지표) 데이터 로드
# ==========================================
@st.cache_data(ttl=86400) # 하루에 한 번만 호출해서 서버 부하 방지
def load_ecos_macro_data():
    try:
        # 금고에서 안전하게 키를 꺼내옴
        ecos_key = st.secrets["BOK_API_KEY"]
        
        def fetch_ecos(stat_code, freq, start, end, item_code):
            url = f"http://ecos.bok.or.kr/api/StatisticSearch/{ecos_key}/json/kr/1/1000/{stat_code}/{freq}/{start}/{end}/{item_code}"
            res = requests.get(url, timeout=5)
            if res.status_code == 200:
                data = res.json()
                if 'StatisticSearch' in data:
                    df = pd.DataFrame(data['StatisticSearch']['row'])
                    df['DATA_VALUE'] = df['DATA_VALUE'].astype(float)
                    # 분기(Q) 데이터를 Pandas가 인식할 수 있는 월(Month) 형태로 변환
                    df['TIME'] = df['TIME'].str.replace('Q1', '01').replace('Q2', '04').replace('Q3', '07').replace('Q4', '10')
                    df.index = pd.to_datetime(df['TIME'], format='%Y%m', errors='coerce')
                    return df[['DATA_VALUE']]
            return pd.DataFrame()

        # [주의] 아래 통계코드는 '명목 GDP'와 '시가총액'의 대표적인 구조입니다.
        # 정확한 코드는 ECOS 홈페이지에서 통계표를 검색하여 맞게 튜닝해야 합니다.
        gdp_df = fetch_ecos("200Y101", "A", "2015", "2025", "10101") # 연도별 명목 GDP
        mcap_df = fetch_ecos("901Y014", "M", "201501", "202602", "1040000") # 주식 시가총액
        
        return gdp_df, mcap_df
    except KeyError:
        return pd.DataFrame(), pd.DataFrame() # Secrets 키가 아직 없을 때 에러 방지
    except Exception as e:
        st.error(f"한국은행 API 호출 에러: {e}")
        return pd.DataFrame(), pd.DataFrame()

    
# ==========================================
# 5. 네이버 금융 메인(sise)에서 KOSPI, KOSDAQ, KOSPI200 현재가 긁어오기
# ==========================================

def get_current_korean_indices():
    try:
        url = "https://finance.naver.com/sise/"
        headers = {'User-Agent': 'Mozilla/5.0'}
        res = requests.get(url, headers=headers, timeout=5)
        soup = BeautifulSoup(res.text, 'html.parser')
        
        # ID를 이용해 직관적으로 추출하고 쉼표 제거 후 실수(float)로 변환
        kospi = float(soup.select_one('#KOSPI_now').text.replace(',', ''))
        kosdaq = float(soup.select_one('#KOSDAQ_now').text.replace(',', ''))
        kospi200 = float(soup.select_one('#KPI200_now').text.replace(',', ''))
        
        return {
            'KOSPI': kospi,
            'KOSDAQ': kosdaq,
            'KOSPI200': kospi200
        }
    except Exception as e:
        # 에러 발생 시 None 반환
        return None
    
# ==========================================
# 6. 야후 파이낸스에서 KOSPI4(소형주) 현재가 긁어오기
# ==========================================

def get_current_kospi4():
    try:
        url = "https://finance.yahoo.com/quote/KOSPI-4.KS/"
        # 야후 파이낸스의 봇 차단(404/403 에러)을 막기 위한 상세 헤더
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.5',
        }
        res = requests.get(url, headers=headers, timeout=5)
        soup = BeautifulSoup(res.text, 'html.parser')
        
        # 선생님이 찾으신 고유 속성 data-testid="qsp-price" 를 활용해 정확하게 타겟팅
        price_element = soup.select_one('span[data-testid="qsp-price"]')
        
        if price_element:
            return float(price_element.text.replace(',', ''))
        else:
            return None
    except Exception as e:
        # st.error(f"KOSPI4 수집 에러: {e}")
        return None

# ==========================================
# 7. 한국 주식 (KOSPI) 페이지 함수 모음 (FinanceDataReader로 교체)
# ==========================================
@st.cache_data(ttl=3600)
def load_korean_market_data():
    try:
        # 1. 과거 시계열 CSV 불러오기
        df = pd.read_csv('KPRICE.csv', encoding='cp949')
        df['Date'] = pd.to_datetime(df['Date'])
        df = df.set_index('Date')
        
        # 2. 3개의 사이트에서 오늘(현재) 지수 5개 크롤링
        current_korean = get_current_korean_indices() # 네이버 (KOSPI, KOSDAQ, KOSPI200)
        current_kospi4 = get_current_kospi4()         # 야후 (KOSPI4)
        current_vkospi = get_current_vkospi()         # 인베스팅 (V-KOSPI)
        
        # 3. 크롤링 성공 시, 오늘 날짜로 데이터 한 줄 추가 (Append)
        if current_korean and current_kospi4 and current_vkospi:
            today_date = pd.to_datetime(datetime.date.today())
            
            # CSV 컬럼 이름에 맞게 세팅 (순서나 이름은 CSV 파일과 동일해야 함)
            df.loc[today_date, 'KOSPI'] = current_korean['KOSPI']
            df.loc[today_date, 'KOSPI200'] = current_korean['KOSPI200']
            df.loc[today_date, 'KOSDAQ'] = current_korean['KOSDAQ']
            df.loc[today_date, 'KOSPI4'] = current_kospi4
            df.loc[today_date, 'VKOSPI'] = current_vkospi
            
        df = df.sort_index(ascending=True)
        # df = df.astype(float)
        return df.ffill().dropna(how='all')
        
    except Exception as e:
        st.error(f"한국 주식 데이터 로딩 에러: {e}")
        return pd.DataFrame()

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
            col2.metric("KRX 금 현물 (KRW/g)", f"{current_domestic_price:,.0f} 원")
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
    
    # 1. 이제 모든 지수(V-KOSPI 포함)가 kr_df 하나에 담겨서 나옵니다.
    kr_df = load_korean_market_data()
    
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

        # --- 2. 1년 추이 및 비교 차트 ---
        st.subheader("📊 지수 1년 추이 및 등락률 비교")
        tab1, tab2 = st.tabs(["주가 지수 추이 (Price)", "누적 등락률 비교 (Normalized % / Base=100)"])
        
        # 전체 데이터 중 최근 1년(약 252 거래일)만 슬라이싱
        kr_df_1y = kr_df.tail(252)

        with tab1:
            c1, c2 = st.columns(2)
            c3, c4 = st.columns(2)
            with c1:
                st.markdown("**KOSPI**")
                st.line_chart(kr_df_1y['KOSPI'], height=250)
            with c2:
                st.markdown("**KOSPI200**")
                st.line_chart(kr_df_1y['KOSPI200'], height=250)
            with c3:
                st.markdown("**KOSDAQ**")
                st.line_chart(kr_df_1y['KOSDAQ'], height=250)
            with c4:
                st.markdown("**KOSPI4 (소형주)**")
                if 'KOSPI4' in kr_df_1y.columns:
                    st.line_chart(kr_df_1y['KOSPI4'], height=250)
                else:
                    st.info("KOSPI4 데이터 대기 중")
        
        with tab2:
            # 시작일을 100으로 맞춘 누적 수익률 차트 (4개 지수 모두 비교)
            compare_cols = [col for col in ['KOSPI', 'KOSPI200', 'KOSDAQ', 'KOSPI4'] if col in kr_df_1y.columns]
            normalized_df = (kr_df_1y[compare_cols] / kr_df_1y[compare_cols].iloc[0]) * 100
            st.line_chart(normalized_df, height=350)
        st.markdown("---")
        
        with tab2:
            # 시작일을 100으로 맞춘 누적 수익률 차트 (4개 지수 모두 비교)
            compare_cols = [col for col in ['KOSPI', 'KOSPI200', 'KOSDAQ', 'KOSPI4'] if col in kr_df.columns]
            normalized_df = (kr_df[compare_cols] / kr_df[compare_cols].iloc[0]) * 100
            st.line_chart(normalized_df, height=350)
        st.markdown("---")

        # --- 3. 매크로 및 추가 지표 ---
        st.subheader("🦅 추가 지표 (V-KOSPI & 거시 지표)")
        m_col1, m_col2, m_col3 = st.columns(3)
        
        # 통합된 kr_df에서 V-KOSPI 꺼내 쓰기
        if 'VKOSPI' in kr_df.columns and not kr_df['VKOSPI'].dropna().empty:
            m_col1.metric("V-KOSPI (변동성 지수)", f"{kr_df['VKOSPI'].dropna().iloc[-1]:.2f}")
        else:
            m_col1.metric("V-KOSPI (변동성 지수)", "수집 불가")
            
        # ECOS 데이터 로드 시도
        # gdp_df, mcap_df = load_ecos_macro_data()
        
        # if not gdp_df.empty and not mcap_df.empty:
        #     macro_df = mcap_df.join(gdp_df, how='inner', lsuffix='_mcap', rsuffix='_gdp')
        #     macro_df['Buffett'] = (macro_df['DATA_VALUE_mcap'] / 1000000 / macro_df['DATA_VALUE_gdp']) * 100
        #     m_col2.metric("한국판 버핏 지수", f"{macro_df['Buffett'].iloc[-1]:.2f} %", "시총 / 명목 GDP")
        # else:
        #     m_col2.metric("한국판 버핏 지수", "데이터 연동 대기 중", "ECOS 코드 튜닝 필요")
            
        # m_col3.metric("Aggregate Investor Allocation", "데이터 연동 대기 중", "시총 / (부채+시총)")

        # V-KOSPI 차트는 컬럼 밖으로 빼서 가로로 길게 보는 것이 예쁩니다.
        if 'VKOSPI' in kr_df.columns and not kr_df['VKOSPI'].dropna().empty:
            st.markdown("**📉 V-KOSPI 1년 추이**")
            st.line_chart(kr_df['VKOSPI'].dropna().tail(252), height=200)

        # --- 4. 밸류에이션 (PER, PBR 표) ---
        st.markdown("---")
        st.subheader("🧮 KOSPI 규모별 밸류에이션 (최근 1년 월말 기준)")
        
        val_df = load_valuation_data() # 이전에 만든 밸류에이션 함수 호출
        
        if not val_df.empty:
            v_tab1, v_tab2 = st.tabs(["📊 PER (주가수익비율) 추이", "📊 PBR (주가순자산비율) 추이"])
            with v_tab1:
                st.dataframe(val_df[["KOSPI 전체 PER", "대형주 PER", "중형주 PER", "소형주 PER"]].style.format("{:.2f} x").background_gradient(cmap='YlOrRd', axis=0), use_container_width=True)
            with v_tab2:
                st.dataframe(val_df[["KOSPI 전체 PBR", "대형주 PBR", "중형주 PBR", "소형주 PBR"]].style.format("{:.2f} x").background_gradient(cmap='Blues', axis=0), use_container_width=True)
        else:
            st.info("밸류에이션 데이터를 불러오는 중입니다...")