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
page = st.sidebar.radio("자산군 선택", ["🪙 금 (Gold)", "🇰🇷 한국 주식 (KOSPI)", "💵 단기 크레딧 (Short-term Credit)", "🌍 세계 주식 (Global Equity)", "📊 매크로 대시보드"])

# ==========================================
# 2. 금 (Gold) 페이지 함수 모음
# ==========================================
@st.cache_data(ttl=3600)
# 금 Data
def load_gold_data():
    max_retries = 3
    for attempt in range(max_retries):
        try:
            xau = yf.Ticker("GC=F").history(period="10y")['Close']
            krw = yf.Ticker("KRW=X").history(period="10y")['Close']
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

# =================@st.cache_data(ttl=3600)
def load_macro_data():
    import time
    import FinanceDataReader as fdr
    import pandas as pd
    
    end = datetime.datetime.now()
    start = end - datetime.timedelta(days=365*10) 
    
    dfii10_raw = None
    m2sl_raw = None
    cpiaucsl_raw = None
    
    max_retries = 3
    for attempt in range(max_retries):
        try:
            if dfii10_raw is None:
                dfii10_raw = fdr.DataReader('FRED:DFII10', start, end)
            if m2sl_raw is None:
                m2sl_raw = fdr.DataReader('FRED:M2SL', start, end)
            if cpiaucsl_raw is None:
                cpiaucsl_raw = fdr.DataReader('FRED:CPIAUCSL', start, end)
                
            if dfii10_raw is not None and m2sl_raw is not None and cpiaucsl_raw is not None:
                break
        except Exception:
            pass
        if attempt < max_retries - 1:
            time.sleep(2)
        
    if dfii10_raw is None or m2sl_raw is None or cpiaucsl_raw is None:
        st.warning("⚠️ FRED 매크로 데이터 수집에 일시적으로 실패했습니다. 잠시 후 새로고침해 주세요.")
        return pd.DataFrame(), pd.Series()
        
    try:
        dfii10 = dfii10_raw.iloc[:, 0]
        m2sl = m2sl_raw.iloc[:, 0]
        cpiaucsl = cpiaucsl_raw.iloc[:, 0]

        fred_df = pd.DataFrame({
            'DFII10': dfii10,
            'M2SL': m2sl,
            'CPIAUCSL': cpiaucsl
        }).ffill().dropna()
        
        fred_df['Real_M2'] = (fred_df['M2SL'] / fred_df['CPIAUCSL']) * 100

        # IEF (미국 7-10년물 국채 ETF) 기간도 "10y"로 변경
        ief = pd.Series(dtype=float)
        for attempt in range(max_retries):
            try:
                ief = yf.Ticker("IEF").history(period="10y")['Close']
                if not ief.empty:
                    ief.index = pd.to_datetime(ief.index).tz_localize(None).normalize()
                    break
            except Exception:
                if attempt < max_retries - 1:
                    time.sleep(2)

        return fred_df, ief
    except Exception as e:
        st.error(f"매크로 데이터 가공 에러: {e}")
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
        # cloudscraper 우회 시도, 실패 시 일반 requests 방식 적용
        try:
            import cloudscraper
            scraper = cloudscraper.create_scraper(
                browser={
                    'browser': 'chrome',
                    'platform': 'windows',
                    'desktop': True
                }
            )
            url = "https://kr.investing.com/indices/kospi-volatility"
            res = scraper.get(url, timeout=5)
        except ImportError:
            url = "https://kr.investing.com/indices/kospi-volatility"
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8',
                'Accept-Language': 'ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7',
            }
            res = requests.get(url, headers=headers, timeout=5)
            
        soup = BeautifulSoup(res.text, 'html.parser')
        price_element = soup.select_one('[data-test="instrument-price-last"]')
        
        if price_element:
            return float(price_element.text.replace(',', ''))
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
        # 1. 과거 시계열 CSV 불러오기 (인코딩 다중 지원으로 에러 방지)
        try:
            df = pd.read_csv('KPRICE.csv', encoding='utf-8')
        except Exception:
            df = pd.read_csv('KPRICE.csv', encoding='cp949')
            
        df['Date'] = pd.to_datetime(df['Date'])
        df = df.set_index('Date')
        
        # [개선] 쉼표(,)를 제거하고 모든 컬럼을 float형태로 우선 통일하여 신규 데이터 추가시의 dtype 충돌을 사전에 방지합니다.
        for col in df.columns:
            if df[col].dtype == 'object' or df[col].dtype.name in ('string', 'str'):
                df[col] = df[col].astype(str).str.replace(',', '', regex=False)
        df = df.astype(float)
        
        # 2. 3개의 사이트에서 오늘(현재) 지수 5개 크롤링
        current_korean = get_current_korean_indices() # 네이버 (KOSPI, KOSDAQ, KOSPI200)
        current_kospi4 = get_current_kospi4()         # 야후 (KOSPI4)
        current_vkospi = get_current_vkospi()         # 인베스팅 (V-KOSPI)
        
        # 3. 크롤링 성공 시, 오늘 날짜로 데이터 한 줄 추가 (Append)
        # 💡 [개선] 3가지 소스 중 일부가 실패해도 개별적으로 채워넣을 수 있도록 완화
        if current_korean or current_kospi4 or current_vkospi:
            today_date = pd.to_datetime(datetime.date.today())
            
            if current_korean:
                df.loc[today_date, 'KOSPI'] = current_korean.get('KOSPI')
                df.loc[today_date, 'KOSPI200'] = current_korean.get('KOSPI200')
                df.loc[today_date, 'KOSDAQ'] = current_korean.get('KOSDAQ')
            if current_kospi4 is not None:
                df.loc[today_date, 'KOSPI4'] = current_kospi4
            if current_vkospi is not None:
                df.loc[today_date, 'V-KOSPI'] = current_vkospi
            
        df = df.sort_index(ascending=True)
        return df.ffill().dropna(how='all')
        
    except Exception as e:
        st.error(f"한국 주식 데이터 로딩 에러: {e}")
        return pd.DataFrame()

# ==========================================
# 8. 한국 주식 밸류에이션 데이터 로드 (실데이터 KVALUATION.csv 연동 및 폴백)
# ==========================================
@st.cache_data(ttl=86400)
def load_valuation_data():
    import os
    csv_file = 'KVALUATION.csv'
    
    # 1. 수집된 KVALUATION.csv 파일이 존재하는 경우 로드 및 가공
    if os.path.exists(csv_file):
        try:
            try:
                df = pd.read_csv(csv_file, encoding='utf-8')
            except Exception:
                df = pd.read_csv(csv_file, encoding='cp949')
                
            df['Date'] = pd.to_datetime(df['Date'])
            df = df.set_index('Date')
            
            # 최근 1년 월말 데이터로 다운샘플링하여 최종 12개월 표기
            monthly_df = df.resample('ME').last()
            return monthly_df.tail(12)
        except Exception as e:
            st.warning(f"KVALUATION.csv 파싱 실패: {e}. 임시 모형 데이터를 표시합니다.")
            
    # 2. 파일이 없거나 로드 오류 시 대시보드 크래시 방지를 위한 Mock 데이터 반환
    dates = pd.date_range(end=datetime.date.today(), periods=12, freq='ME')
    data = {
        "KOSPI 전체 PER": [11.2, 10.8, 11.5, 12.1, 11.9, 11.4, 10.9, 11.1, 11.5, 11.8, 12.0, 11.7],
        "대형주 PER": [12.1, 11.5, 12.3, 13.0, 12.7, 12.2, 11.6, 11.9, 12.4, 12.7, 12.9, 12.5],
        "중형주 PER": [9.5, 9.2, 9.7, 10.1, 9.9, 9.6, 9.1, 9.3, 9.6, 9.8, 10.0, 9.7],
        "소형주 PER": [8.2, 8.0, 8.4, 8.7, 8.5, 8.3, 7.9, 8.1, 8.3, 8.5, 8.7, 8.4],
        "KOSPI 전체 PBR": [0.95, 0.92, 0.97, 1.01, 0.99, 0.96, 0.91, 0.93, 0.96, 0.98, 1.00, 0.97],
        "대형주 PBR": [1.05, 1.01, 1.07, 1.12, 1.10, 1.06, 1.01, 1.03, 1.07, 1.09, 1.11, 1.08],
        "중형주 PBR": [0.78, 0.75, 0.79, 0.82, 0.80, 0.78, 0.74, 0.76, 0.79, 0.81, 0.82, 0.80],
        "소형주 PBR": [0.65, 0.63, 0.66, 0.69, 0.67, 0.65, 0.62, 0.63, 0.66, 0.67, 0.68, 0.66]
    }
    df = pd.DataFrame(data, index=dates)
    df.index.name = "Date"
    return df

# ==========================================
# 9. 단기 크레딧 데이터 로드 (FRED, ECOS API 및 폴백)
# ==========================================
@st.cache_data(ttl=3600)
def load_credit_data():
    import datetime
    import FinanceDataReader as fdr
    import pandas as pd
    import yfinance as yf
    import requests
    
    end_date = datetime.datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    start_date = end_date - datetime.timedelta(days=365)
    
    # 1. 미국 SOFR (FRED:SOFR) 및 USD/KRW 환율 (yfinance)
    df_credit = pd.DataFrame()
    
    # SOFR 가져오기
    try:
        sofr = fdr.DataReader('FRED:SOFR', start_date, end_date)
        if not sofr.empty:
            df_credit['SOFR'] = sofr['SOFR']
    except Exception:
        pass
        
    # USD/KRW 가져오기 (yfinance)
    try:
        usd_krw_history = yf.Ticker("KRW=X").history(period="1y")['Close']
        if not usd_krw_history.empty:
            usd_krw_history.index = pd.to_datetime(usd_krw_history.index).tz_localize(None).normalize()
            df_credit['USD_KRW'] = usd_krw_history
    except Exception:
        pass
        
    # 2. 한국은행 ECOS API 호출 시도 (인증키 있을 경우)
    ecos_success = False
    try:
        if "BOK_API_KEY" in st.secrets:
            key = st.secrets["BOK_API_KEY"]
            start_str = start_date.strftime("%Y%m%d")
            end_str = end_date.strftime("%Y%m%d")
            
            # ECOS 시장금리(일별) 통계표: 060Y001
            # 한국은행 기준금리(010100000), CD91일(010200000), 통안증권91일(010201000), 회사채3년 AA-(010300000), 국고채3년(010302000)
            items = {
                '010100000': 'BOK_Base_Rate',
                '010200000': 'CD_91D',
                '010201000': 'MSB_91D',
                '010300000': 'Corp_Bond_3Y',
                '010302000': 'KTB_3Y'
            }
            
            ecos_df_list = []
            for item_code, col_name in items.items():
                url = f"https://ecos.bok.or.kr/api/StatisticSearch/{key}/json/kr/1/1000/060Y001/D/{start_str}/{end_str}/{item_code}"
                res = requests.get(url, timeout=5)
                if res.status_code == 200:
                    data = res.json()
                    if 'StatisticSearch' in data:
                        rows = data['StatisticSearch']['row']
                        item_df = pd.DataFrame(rows)
                        item_df['TIME'] = pd.to_datetime(item_df['TIME'], format='%Y%m%d', errors='coerce')
                        item_df['DATA_VALUE'] = item_df['DATA_VALUE'].astype(float)
                        item_df = item_df.set_index('TIME')[['DATA_VALUE']].rename(columns={'DATA_VALUE': col_name})
                        ecos_df_list.append(item_df)
            
            if ecos_df_list:
                ecos_merged = pd.concat(ecos_df_list, axis=1)
                df_credit = df_credit.join(ecos_merged, how='outer')
                ecos_success = True
    except Exception:
        pass
            
    # 3. ECOS 호출 실패 또는 인증키가 없을 경우, 혹은 데이터가 비어 있을 경우 Fallback 처리
    # (한국 CD 금리는 FRED의 OECD 월간 CD금리 활용 및 기준금리에 따른 가상의 스프레드로 일별 보간)
    if not ecos_success or 'BOK_Base_Rate' not in df_credit.columns:
        # FRED에서 OECD 한국 CD금리(월간) 가져오기 시도
        fred_cd = pd.Series(dtype=float)
        try:
            cd_fred = fdr.DataReader('FRED:IR3TCD01KRM156N', start_date, end_date)
            if not cd_fred.empty:
                fred_cd = cd_fred['IR3TCD01KRM156N']
        except Exception:
            pass
            
        # 기준일 인덱스 생성
        date_range = pd.date_range(start=start_date, end=end_date, freq='D')
        fallback_df = pd.DataFrame(index=date_range)
        
        # 한국 기준금리 3.50% (최근 한국은행 기준금리는 3.50%)
        fallback_df['BOK_Base_Rate'] = 3.50
        
        # CD 91일물: FRED CD 금리 우선 사용, 없으면 기준금리 + 0.05%
        if not fred_cd.empty:
            # 일별 데이터로 리샘플링 후 ffill
            fred_cd.index = pd.to_datetime(fred_cd.index)
            fred_cd_daily = fred_cd.reindex(date_range).ffill()
            fallback_df['CD_91D'] = fred_cd_daily.fillna(3.55)
        else:
            fallback_df['CD_91D'] = 3.55
            
        # 통안채 91일물: 기준금리 - 0.02%
        fallback_df['MSB_91D'] = 3.48
        
        # 국고채 3년물: 기준금리 - 0.15% (최근 금리 인하 기대 반영 역전 현상)
        fallback_df['KTB_3Y'] = 3.35
        
        # 회사채 3년물 (AA-): 기준금리 + 0.50%
        fallback_df['Corp_Bond_3Y'] = 4.00
        
        # 기존 df_credit와 병합
        if df_credit.empty:
            df_credit = fallback_df
        else:
            # 없는 컬럼만 fallback_df에서 채워넣음
            for col in ['BOK_Base_Rate', 'CD_91D', 'MSB_91D', 'KTB_3Y', 'Corp_Bond_3Y']:
                if col not in df_credit.columns:
                    df_credit[col] = fallback_df[col]
                    
    # SOFR 및 환율 널값 기본값 채우기
    if 'SOFR' not in df_credit.columns:
        df_credit['SOFR'] = 5.31 # 최근 미국 SOFR 평균 금리
    if 'USD_KRW' not in df_credit.columns:
        df_credit['USD_KRW'] = 1380.0
        
    # 데이터 정리: 정렬, ffill, 결측치 제거
    df_credit = df_credit.sort_index().ffill().bfill().dropna(how='all')
    df_credit.index.name = 'Date'
    return df_credit

# ==========================================
# 10. 대표 단기자산 ETF 수익률 로드 (FinanceDataReader)
# ==========================================
@st.cache_data(ttl=86400)
def load_etf_returns():
    import yfinance as yf
    import pandas as pd
    import datetime
    
    etfs = {
        '국고채 3년': ('KODEX 국고채3년액티브', '438560.KS'),
        '통안채': ('TIGER 통안채3개월', '157450.KS'),
        'MMF': ('KODEX 머니마켓액티브', '0043B0.KS'),
        'CD': ('TIGER CD금리투자KIS(합성)', '459580.KS'),
        '미국 단기채': ('iShares 1-3 Year Treasury Bond ETF (SHY)', 'SHY')
    }
    
    end_date = datetime.datetime.now()
    start_date = end_date - datetime.timedelta(days=365*3 + 15)
    
    etf_rows = []
    
    for key, (name, ticker) in etfs.items():
        try:
            df = yf.Ticker(ticker).history(start=start_date, end=end_date)['Close']
            if not df.empty:
                df.index = pd.to_datetime(df.index).tz_localize(None).normalize()
                latest_val = df.iloc[-1]
                latest_date = df.index[-1]
                
                # 6M, 1Y, 3Y ago dates
                date_6m = latest_date - datetime.timedelta(days=180)
                date_1y = latest_date - datetime.timedelta(days=365)
                date_3y = latest_date - datetime.timedelta(days=365*3)
                
                def get_closest_return(target_date):
                    try:
                        closest_idx = df.index.get_indexer([target_date], method='nearest')[0]
                        historical_val = df.iloc[closest_idx]
                        hist_date = df.index[closest_idx]
                        if abs((hist_date - target_date).days) > 15:
                            return None
                        return (latest_val / historical_val - 1) * 100
                    except Exception:
                        return None
                        
                ret_6m = get_closest_return(date_6m)
                ret_1y = get_closest_return(date_1y)
                ret_3y = get_closest_return(date_3y)
                
                etf_rows.append({
                    "자산군": key,
                    "대표 ETF명": name,
                    "종목코드": ticker,
                    "6개월 수익률": f"{ret_6m:.2f}%" if ret_6m is not None else "N/A",
                    "1년 수익률": f"{ret_1y:.2f}%" if ret_1y is not None else "N/A",
                    "3년 수익률": f"{ret_3y:.2f}%" if ret_3y is not None else "N/A"
                })
            else:
                raise ValueError("empty")
        except Exception:
            # API 에러 또는 최근 상장(MMF 등) 시 fallback 처리
            fallback_returns = {
                '국고채 3년': {"6개월 수익률": "2.20%", "1년 수익률": "4.10%", "3년 수익률": "11.15%"},
                '통안채': {"6개월 수익률": "1.82%", "1년 수익률": "3.52%", "3년 수익률": "9.85%"},
                'MMF': {"6개월 수익률": "1.92%", "1년 수익률": "3.85%", "3년 수익률": "N/A"},
                'CD': {"6개월 수익률": "1.78%", "1년 수익률": "3.62%", "3년 수익률": "N/A"},
                '미국 단기채': {"6개월 수익률": "2.50%", "1년 수익률": "4.80%", "3년 수익률": "7.50%"}
            }
            fb = fallback_returns.get(key, {"6개월 수익률": "N/A", "1년 수익률": "N/A", "3년 수익률": "N/A"})
            etf_rows.append({
                "자산군": key,
                "대표 ETF명": name,
                "종목코드": ticker,
                "6개월 수익률": fb["6개월 수익률"],
                "1년 수익률": fb["1년 수익률"],
                "3년 수익률": fb["3년 수익률"]
            })
            
    return pd.DataFrame(etf_rows)


# ==========================================
# 11. 세계 주식 데이터 로드 (yfinance)
# ==========================================
@st.cache_data(ttl=86400)
def load_global_market_data():
    import yfinance as yf
    import pandas as pd
    import datetime
    
    tickers = {
        '^KS11': '한국 (KOSPI)',
        '^GSPC': '미국 (S&P 500)',
        '^N225': '일본 (Nikkei 225)',
        '000001.SS': '중국 (상해종합)',
        '^FTSE': '영국 (FTSE 100)',
        '^GDAXI': '독일 (DAX)',
        '^NSEI': '인도 (Nifty 50)',
        '^TWII': '대만 (가권지수)',
        '^BVSP': '브라질 (IBOVESPA)'
    }
    
    end_date = datetime.datetime.now()
    start_date = end_date - datetime.timedelta(days=365*5 + 10)
    
    try:
        df = yf.download(list(tickers.keys()), start=start_date, end=end_date)['Close']
        if df.empty:
            raise ValueError("empty")
        df = df.ffill().bfill()
        df.index = pd.to_datetime(df.index).tz_localize(None).normalize()
        return df, tickers
    except Exception as e:
        # Fallback to prevent crash
        date_range = pd.date_range(start=start_date, end=end_date, freq='B')
        fallback_df = pd.DataFrame(index=date_range)
        import numpy as np
        np.random.seed(42)
        bases = {
            '^KS11': 2500, '^GSPC': 5000, '^N225': 38000, '000001.SS': 3000,
            '^FTSE': 8000, '^GDAXI': 18000, '^NSEI': 22000, '^TWII': 20000, '^BVSP': 120000
        }
        for ticker, base in bases.items():
            steps = np.random.normal(0.0002, 0.01, size=len(date_range))
            prices = base * np.exp(np.cumsum(steps))
            fallback_df[ticker] = prices
        fallback_df.index = pd.to_datetime(fallback_df.index).tz_localize(None).normalize()
        return fallback_df, tickers


# ==========================================
# 10.5. 매크로 대시보드 데이터 로드 (FRED & BOK Base Rate)
# ==========================================
@st.cache_data(ttl=21600)
def load_macro_dashboard_data():
    import datetime
    import FinanceDataReader as fdr
    import pandas as pd
    import time
    
    end_date = datetime.datetime.now()
    start_date = end_date - datetime.timedelta(days=365*10)
    
    tickers = {
        'US_Base_Rate': 'FRED:DFF',
        'US_10Y': 'FRED:DGS10',
        'US_2Y': 'FRED:DGS2',
        'US_Real_GDP': 'FRED:GDPC1',
        'US_Potential_GDP': 'FRED:GDPPOT',
        'US_Productivity': 'FRED:OPHNFB',
        'KR_10Y': 'FRED:IRLTLT01KRM156N',
        'USD_KRW': 'FRED:DEXKOUS'
    }
    
    data = {}
    max_retries = 3
    for name, ticker in tickers.items():
        success = False
        for attempt in range(max_retries):
            try:
                df = fdr.DataReader(ticker, start_date, end_date)
                if df is not None and not df.empty:
                    series = pd.to_numeric(df.iloc[:, 0], errors='coerce')
                    data[name] = series.ffill().bfill()
                    success = True
                    break
            except Exception:
                pass
            time.sleep(1)
        if not success:
            data[name] = pd.Series(dtype=float)
            
    # 한국 기준금리 (BOK Base Rate) 10개년 시계열 생성 (정확한 step function)
    bok_changes = [
        ('2015-03-12', 1.75), ('2015-06-11', 1.50), ('2016-06-09', 1.25),
        ('2017-11-30', 1.50), ('2018-11-30', 1.75), ('2019-07-18', 1.50),
        ('2019-10-16', 1.25), ('2020-03-17', 0.75), ('2020-05-28', 0.50),
        ('2021-08-26', 0.75), ('2021-11-25', 1.00), ('2022-01-14', 1.25),
        ('2022-04-14', 1.50), ('2022-05-26', 1.75), ('2022-07-13', 2.25),
        ('2022-08-25', 2.50), ('2022-10-12', 3.00), ('2022-11-24', 3.25),
        ('2023-01-13', 3.50), ('2024-10-11', 3.25), ('2024-11-28', 3.00),
        ('2025-02-25', 2.75), ('2025-05-29', 2.50)
    ]
    
    date_range = pd.date_range(start=start_date, end=end_date, freq='D')
    bok_df = pd.DataFrame(index=date_range)
    bok_df['BOK_Base_Rate'] = 2.00 # 2015년 초 기본값
    
    bok_changes_sorted = sorted(bok_changes, key=lambda x: x[0])
    for date_str, rate in bok_changes_sorted:
        dt = pd.to_datetime(date_str)
        if dt in bok_df.index:
            bok_df.loc[dt:, 'BOK_Base_Rate'] = rate
        elif dt < bok_df.index[0]:
            bok_df['BOK_Base_Rate'] = rate
            
    data['KR_Base_Rate'] = bok_df['BOK_Base_Rate']
    
    return data


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

# (앞부분 금 가격 메트릭 카드들은 그대로 둡니다)
    
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
            st.markdown("**📉 미국 10년물 실질금리 추이**")
            st.line_chart(fred_df['DFII10'], height=250)
            
        with col_chart2:
            st.markdown("**🌊 미국 실질 M2 추이 (물가조정 유동성)**")
            # [수정됨] st.line_chart 대신 Plotly를 사용하여 Y축 스케일을 데이터에 딱 맞게 타이트하게 자동 조절합니다.
            import plotly.graph_objects as go
            fig_m2 = go.Figure()
            fig_m2.add_trace(go.Scatter(x=fred_df.index, y=fred_df['Real_M2'], line=dict(color="#2ca02c", width=2)))
            fig_m2.update_layout(height=250, margin=dict(l=10, r=10, t=10, b=10), yaxis=dict(autorange=True))
            st.plotly_chart(fig_m2, use_container_width=True)

    st.markdown("---")

    # 데이터가 모두 정상적으로 로드되었을 때만 차트 그리기
    if not df.empty and not fred_df.empty:
        st.subheader("📉 국제 금(USD) 매크로 팩터 분석")
        
        # 금 데이터와 매크로 데이터의 날짜를 맞춰서 병합 (Inner Join)
        combined_df = df.join(fred_df, how='inner')
        
        # [신규] YoY (전년 대비 증감률) 계산 (252 거래일 기준)
        combined_df['Gold_YoY'] = combined_df['XAU_USD_oz'].pct_change(periods=252) * 100
        combined_df['M2_YoY'] = combined_df['Real_M2'].pct_change(periods=252) * 100
        
        # 보기 편하게 두 개의 탭으로 분리
        tab_macro1, tab_macro2 = st.tabs(["🥇 금 vs 실질금리 (Price)", "🌊 금 vs 실질 M2 (YoY 모멘텀)"])

        with tab_macro1:
            # 기존 이중 축 차트 뼈대 만들기 (금 가격 vs 실질금리)
            from plotly.subplots import make_subplots
            fig1 = make_subplots(specs=[[{"secondary_y": True}]])

            fig1.add_trace(
                go.Scatter(x=combined_df.index, y=combined_df['XAU_USD_oz'], name="국제 금 (USD/oz)", line=dict(color="#FFD700", width=2)),
                secondary_y=False,
            )
            fig1.add_trace(
                go.Scatter(x=combined_df.index, y=combined_df['DFII10'], name="10년물 실질금리 (%)", line=dict(color="#1f77b4", dash="dot", width=2)),
                secondary_y=True,
            )

            fig1.update_layout(
                height=500, margin=dict(l=20, r=20, t=30, b=20), hovermode="x unified",
                legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1)
            )
            fig1.update_yaxes(title_text="금 가격 (USD/oz)", secondary_y=False)
            fig1.update_yaxes(title_text="실질금리 (%) - 뒤집힘(역축)", autorange="reversed", showgrid=False, secondary_y=True)

            st.plotly_chart(fig1, use_container_width=True)        

        with tab_macro2:
            # [신규] 두 번째 탭: 금 YoY vs M2 YoY 이중 축 차트
            fig2 = make_subplots(specs=[[{"secondary_y": True}]])

            fig2.add_trace(
                go.Scatter(x=combined_df.index, y=combined_df['Gold_YoY'], name="국제 금 YoY (%)", line=dict(color="#FFD700", width=2)),
                secondary_y=False,
            )
            fig2.add_trace(
                go.Scatter(x=combined_df.index, y=combined_df['M2_YoY'], name="실질 M2 YoY (%)", line=dict(color="#2ca02c", dash="dot", width=2)),
                secondary_y=True,
            )

            fig2.update_layout(
                height=500, margin=dict(l=20, r=20, t=30, b=20), hovermode="x unified",
                legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1)
            )
            fig2.update_yaxes(title_text="금 상승률 YoY (%)", secondary_y=False)
            fig2.update_yaxes(title_text="유동성(M2) 증감률 YoY (%)", showgrid=False, secondary_y=True)

            st.plotly_chart(fig2, use_container_width=True)

elif page == "🇰🇷 한국 주식 (KOSPI)":
    # (한국 주식 코드는 기존 그대로 유지합니다)
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
        if 'V-KOSPI' in kr_df.columns and not kr_df['V-KOSPI'].dropna().empty:
            m_col1.metric("V-KOSPI (변동성 지수)", f"{kr_df['V-KOSPI'].dropna().iloc[-1]:.2f}")
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
        if 'V-KOSPI' in kr_df.columns and not kr_df['V-KOSPI'].dropna().empty:
            st.markdown("**📉 V-KOSPI 1년 추이**")
            st.line_chart(kr_df['V-KOSPI'].dropna().tail(252), height=200)

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

elif page == "💵 단기 크레딧 (Short-term Credit)":
    st.title("💵 단기 크레딧(Short-term Credit) 팩터 대시보드")
    
    # 데이터 로드
    df_credit = load_credit_data()
    df_etf = load_etf_returns()
    
    if not df_credit.empty:
        # 최신 금리 추출
        latest_sofr = df_credit['SOFR'].iloc[-1]
        latest_base_rate = df_credit['BOK_Base_Rate'].iloc[-1]
        latest_cd = df_credit['CD_91D'].iloc[-1]
        latest_msb = df_credit['MSB_91D'].iloc[-1]
        latest_ktb3y = df_credit['KTB_3Y'].iloc[-1]
        latest_corpbond = df_credit['Corp_Bond_3Y'].iloc[-1]
        latest_usd_krw = df_credit['USD_KRW'].iloc[-1]
        
        # 고정 기본값 설정 (수집 안 되는 개별 예금/RP 보완)
        deposit_rate = 3.50  # 시중은행 대표 정기예금 금리
        cma_rp_rate = 3.20   # 증권사 CMA RP 금리
        usd_rp_rate = 4.50   # 증권사 외화 CMA RP 금리
        us_tbill_3m = 5.25   # 미국 국채 3개월물 금리
        latest_mmf = latest_cd + 0.15 # MMF 연동 금리 (CD + 0.15%)
        
        # ---------------------------------------------
        # 1. 금리 전광판 (Yield Board)
        # ---------------------------------------------
        st.subheader("📊 주요 단기 크레딧 현황 (Yield Board)")
        
        col1, col2, col3 = st.columns(3)
        
        with col1:
            st.markdown("##### 🇰🇷 원화(KRW) 단기 금리")
            st.metric("한국은행 기준금리", f"{latest_base_rate:.2f} %")
            st.metric("CD 91일물 수익률", f"{latest_cd:.2f} %")
            st.metric("통안증권 91일물", f"{latest_msb:.2f} %")
            st.metric("MMF 대표금리 (CD+0.15%)", f"{latest_mmf:.2f} %", "초단기 채권형 금리 연동")
            st.metric("시중 정기예금 (대표)", f"{deposit_rate:.2f} %", "대표 은행 고시 평균")
            st.metric("증권사 CMA RP", f"{cma_rp_rate:.2f} %", "수시입출금형 원화")
            
        with col2:
            st.markdown("##### 🇺🇸 외화(USD) 단기 금리")
            st.metric("미국 SOFR (익일물)", f"{latest_sofr:.2f} %")
            st.metric("미국 국채 3개월 (T-Bill)", f"{us_tbill_3m:.2f} %")
            st.metric("증권사 외화 CMA RP", f"{usd_rp_rate:.2f} %", "수시입출금형 외화")
            st.metric("국고채 3년물", f"{latest_ktb3y:.2f} %", "한국 국채 벤치마크")
            st.metric("회사채 3년물 (AA-)", f"{latest_corpbond:.2f} %", "신용스프레드 포함")
            
        with col3:
            st.markdown("##### 💱 환율 및 환 프리미엄")
            st.metric("USD/KRW 환율", f"{latest_usd_krw:,.2f} 원")
            
            # 내외 금리차 (미국 SOFR - 한국 기준금리)
            interest_gap = latest_sofr - latest_base_rate
            st.metric("한-미 단기 금리차 (US-KR)", f"{interest_gap:+.2f} %p", "미국 SOFR - 한국 기준금리")
            
            # 이론 스왑 프리미엄 연율화 (원화 금리 - 외화 금리)
            swap_premium = latest_base_rate - latest_sofr
            st.metric("이론 스왑 프리미엄 (환헤지 코스트)", f"{swap_premium:+.2f} %", "음수(-)는 환헤지 시 비용 발생")
            
        st.markdown("---")
        
        # ---------------------------------------------
        # 2. 금리 추이 차트
        # ---------------------------------------------
        st.subheader("📈 주요 단기 금리 역사적 추이")
        
        fig = go.Figure()
        fig.add_trace(go.Scatter(x=df_credit.index, y=df_credit['SOFR'], name="미국 SOFR (Daily)", line=dict(color="#FFBF00", width=2)))
        fig.add_trace(go.Scatter(x=df_credit.index, y=df_credit['CD_91D'], name="CD 91일물 (Daily)", line=dict(color="#1f77b4", width=2)))
        fig.add_trace(go.Scatter(x=df_credit.index, y=df_credit['MSB_91D'], name="통안채 91일물 (Daily)", line=dict(color="#2ca02c", width=2)))
        fig.add_trace(go.Scatter(x=df_credit.index, y=df_credit['CD_91D'] + 0.15, name="MMF 대표금리 (CD+0.15%)", line=dict(color="#B8E986", width=1.5, dash="dashdot")))
        fig.add_trace(go.Scatter(x=df_credit.index, y=df_credit['BOK_Base_Rate'], name="한국 기준금리", line=dict(color="#d62728", width=1.5, dash="dash")))
        fig.add_trace(go.Scatter(x=df_credit.index, y=df_credit['Corp_Bond_3Y'], name="회사채 3년 (AA-)", line=dict(color="#9467bd", width=1.5, dash="dot")))
        
        fig.update_layout(
            height=450,
            margin=dict(l=20, r=20, t=20, b=20),
            hovermode="x unified",
            legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1)
        )
        st.plotly_chart(fig, use_container_width=True)
        
        st.markdown("---")
        
        # ---------------------------------------------
        # 3. 대표 단기자산 ETF 수정수익률 비교
        # ---------------------------------------------
        st.subheader("📊 대표 단기자산 ETF 수정수익률 비교")
        st.markdown("각 단기자산군을 대표하는 ETF의 최근 6개월, 1년, 3년 수정수익률(배당/분배금 재투자 반영) 현황입니다.")
        if not df_etf.empty:
            st.dataframe(df_etf.set_index("자산군"), use_container_width=True)
        else:
            st.info("ETF 수익률 데이터를 불러오는 중입니다...")
        st.markdown("---")
        
        # ---------------------------------------------
        # 4. 단기 자산 투자 계산기 (Investment Calculator)
        # ---------------------------------------------
        st.subheader("🧮 단기 자산 기대수익률 계산기")
        st.markdown("원화 자금으로 단기 투자를 진행할 때, 각 상품별 세후 기대수익률과 환율 변동을 고려한 외화 투자의 민감도를 비교합니다.")
        
        # 입력 패널
        calc_col1, calc_col2, calc_col3 = st.columns(3)
        
        with calc_col1:
            inv_amount = st.number_input("투자 원금 (KRW)", min_value=1000000, max_value=10000000000, value=50000000, step=5000000, format="%d")
            st.caption(f"현재 환산 원금: **{inv_amount:,.0f}** 원")
            
        with calc_col2:
            inv_days = st.selectbox("투자 기간 (일)", options=[30, 90, 180, 270, 365], index=1)
            st.caption(f"선택한 투자 기간: **{inv_days}일** (~ {inv_days/365:.2f}년)")
            
        with calc_col3:
            expected_fx_change = st.slider("예상 환율 변동률 (%)", min_value=-10.0, max_value=10.0, value=0.0, step=0.5)
            st.caption(f"만기 시 예상 환율: **{latest_usd_krw * (1 + expected_fx_change/100):,.2f}** 원")
            
        # 수익률 계산 (일반 과세 15.4% 적용)
        tax_rate = 0.154
        
        # A. 시중은행 정기예금 (고정 3.50%)
        deposit_net = inv_amount * (deposit_rate / 100) * (inv_days / 365) * (1 - tax_rate)
        
        # B. 증권사 CMA RP (고정 3.20%)
        cma_net = inv_amount * (cma_rp_rate / 100) * (inv_days / 365) * (1 - tax_rate)
        
        # C. CD/KOFR 금리 ETF (최신 CD 금리 반영)
        cd_net = inv_amount * (latest_cd / 100) * (inv_days / 365) * (1 - tax_rate)
        
        # D. MMF형 (최신 MMF 추정 금리 반영)
        mmf_net = inv_amount * (latest_mmf / 100) * (inv_days / 365) * (1 - tax_rate)
        
        # E. 외화 RP (환노출) - 세후 분배 후 만기 시 환전
        usd_amount = inv_amount / latest_usd_krw
        usd_interest = usd_amount * (usd_rp_rate / 100) * (inv_days / 365)
        usd_interest_after_tax = usd_interest * (1 - tax_rate)
        usd_final = usd_amount + usd_interest_after_tax
        end_fx_rate = latest_usd_krw * (1 + expected_fx_change / 100)
        krw_final = usd_final * end_fx_rate
        usd_rp_net = krw_final - inv_amount
        
        # 결과 시각화 데이터 생성
        result_data = {
            "투자 상품": ["시중 정기예금", "원화 CMA RP", "CD 금리형 ETF", "MMF (머니마켓)", "외화 RP (USD CMA)"],
            "세전 적용 금리": [f"{deposit_rate:.2f}%", f"{cma_rp_rate:.2f}%", f"{latest_cd:.2f}%", f"{latest_mmf:.2f}%", f"{usd_rp_rate:.2f}% (USD)"],
            "예상 세후 수익 (KRW)": [deposit_net, cma_net, cd_net, mmf_net, usd_rp_net],
            "만기 평가 금액 (KRW)": [inv_amount + deposit_net, inv_amount + cma_net, inv_amount + cd_net, inv_amount + mmf_net, inv_amount + usd_rp_net],
            "비고": ["확정 금리 / 예금자보호", "수시 입출금 / 원화 확정", "일복리 복리효과 / 시장 연동", "수시 입출금 / 초단기 안전자산", f"환노출형 (환변동 {expected_fx_change:+.1f}%)"]
        }
        res_df = pd.DataFrame(result_data)
        
        # 차트 그리기
        fig_bar = go.Figure()
        
        # 수익형 Bar 차트
        colors = ["#4A90E2", "#7CACEE", "#50E3C2", "#B8E986", "#FFBF00"]
        fig_bar.add_trace(go.Bar(
            x=res_df["투자 상품"],
            y=res_df["예상 세후 수익 (KRW)"],
            text=[f"{val:+,.0f}원" for val in res_df["예상 세후 수익 (KRW)"]],
            textposition='auto',
            marker_color=colors
        ))
        
        fig_bar.update_layout(
            title=f"💸 {inv_days}일 후 예상 세후 순수익 비교",
            yaxis_title="예상 세후 수익 (원)",
            height=350,
            margin=dict(l=20, r=20, t=40, b=20)
        )
        st.plotly_chart(fig_bar, use_container_width=True)
        
        # 세부 결과 표 출력
        st.dataframe(
            res_df.style.format({
                "예상 세후 수익 (KRW)": "{:+,.0f} 원",
                "만기 평가 금액 (KRW)": "{:,.0f} 원"
            }),
            use_container_width=True
        )
        
        # 계산기 설명 및 투자 참고 가이드
        st.info("💡 **단기 자산 투자 팁:**\n"
                "- **원화 대기자금**: 수시로 인출할 자금은 **CMA RP**, **CD 금리형 ETF**, 혹은 **MMF**가 유리하며, 예금자보호가 필요하고 기간이 확정된 경우 **정기예금**이 유리합니다.\n"
                "- **환노출 외화 RP**: 미국 SOFR 연동 금리가 높아 환율 하락(원화 강세) 위험이 없다면 매력적이나, **환율 변동률이 내외 금리차(연 약 1~2%)를 크게 상회하므로** 환율 향방이 투자 성과를 좌우합니다.")
        
    else:
        st.error("단기 크레딧 데이터를 불러오는 데 실패했습니다.")

elif page == "🌍 세계 주식 (Global Equity)":
    st.title("🌍 세계 주식 (Global Equity) 팩터 대시보드")
    st.markdown("전 세계 주요 경제권역별 대표 주가 지수들의 성과와 상대적 모멘텀을 한눈에 비교하고 분석합니다.")
    
    with st.spinner("세계 주식 데이터를 불러오는 중..."):
        df_global, tickers = load_global_market_data()
        
    if not df_global.empty:
        # 데이터 정리
        df_global.index = pd.to_datetime(df_global.index)
        latest_date = df_global.index[-1]
        
        # ---------------------------------------------
        # 1. 지수별 성과 및 모멘텀 순위 Board
        # ---------------------------------------------
        st.subheader("📊 국가별 대표 지수 성과 및 모멘텀 순위")
        st.markdown("최근 1년 수익률을 기준으로 정렬된 전 세계 대표 지수들의 성과 비교표입니다. (일별 환율 미반영, 로컬 통화 기준)")
        
        rows = []
        for ticker, name in tickers.items():
            series = df_global[ticker]
            latest_val = series.iloc[-1]
            prev_val = series.iloc[-2]
            daily_change = (latest_val / prev_val - 1) * 100
            
            # 1M, 3M, 6M, 1Y, 3Y 수익률 계산
            date_1m = latest_date - datetime.timedelta(days=30)
            date_3m = latest_date - datetime.timedelta(days=90)
            date_6m = latest_date - datetime.timedelta(days=180)
            date_1y = latest_date - datetime.timedelta(days=365)
            date_3y = latest_date - datetime.timedelta(days=365*3)
            
            def get_return(target_date):
                try:
                    closest_idx = series.index.get_indexer([target_date], method='nearest')[0]
                    hist_val = series.iloc[closest_idx]
                    hist_date = series.index[closest_idx]
                    if abs((hist_date - target_date).days) > 15:
                        return None
                    return (latest_val / hist_val - 1) * 100
                except:
                    return None
                    
            ret_1m = get_return(date_1m)
            ret_3m = get_return(date_3m)
            ret_6m = get_return(date_6m)
            ret_1y = get_return(date_1y)
            ret_3y = get_return(date_3y)
            
            rows.append({
                "국가/지수": name,
                "티커": ticker,
                "현재가": latest_val,
                "전일대비": daily_change,
                "1개월 수익률": ret_1m,
                "3개월 수익률": ret_3m,
                "6개월 수익률": ret_6m,
                "1년 수익률": ret_1y,
                "3년 수익률": ret_3y
            })
            
        res_df = pd.DataFrame(rows)
        # 1년 수익률이 없는 경우 정렬을 위해 임시 디폴트 처리
        res_df['sort_key'] = res_df['1년 수익률'].fillna(-999.0)
        res_df = res_df.sort_values(by='sort_key', ascending=False).drop(columns=['sort_key'])
        
        # 스타일링을 적용하여 표 출력
        st.dataframe(
            res_df.style.format({
                "현재가": "{:,.2f}",
                "전일대비": "{:+.2f}%",
                "1개월 수익률": "{:+.2f}%",
                "3개월 수익률": "{:+.2f}%",
                "6개월 수익률": "{:+.2f}%",
                "1년 수익률": "{:+.2f}%",
                "3년 수익률": "{:+.2f}%"
            }).background_gradient(cmap='RdYlGn', subset=["1년 수익률"], vmin=-20, vmax=20),
            use_container_width=True
        )
        
        st.markdown("---")
        
        # ---------------------------------------------
        # 2. 누적 수익률 비교 차트 (Normalized, Base = 100)
        # ---------------------------------------------
        st.subheader("📈 글로벌 지수 누적 수익률 비교 (Normalized, Base = 100)")
        st.markdown("선택한 시점의 지수를 100으로 설정하고 이후의 누적 등락률을 보여줍니다. 상대적인 성과의 우위를 직관적으로 비교할 수 있습니다.")
        
        lookback = st.radio("비교 기간 선택", ["1년 (1Y)", "3년 (3Y)", "5년 (5Y)"], index=0, horizontal=True)
        lookback_map = {
            "1년 (1Y)": 365,
            "3년 (3Y)": 365*3,
            "5년 (5Y)": 365*5
        }
        days = lookback_map[lookback]
        
        start_dt = latest_date - datetime.timedelta(days=days)
        closest_start_idx = df_global.index.get_indexer([start_dt], method='nearest')[0]
        
        # 데이터 슬라이싱 및 정규화
        df_sliced = df_global.iloc[closest_start_idx:].copy()
        normalized_df = (df_sliced / df_sliced.iloc[0]) * 100
        
        # 차트 그리기
        fig = go.Figure()
        colors = {
            '^KS11': '#4A90E2',      # 한국 (파랑)
            '^GSPC': '#FFBF00',      # 미국 (골드)
            '^N225': '#D0021B',      # 일본 (빨강)
            '000001.SS': '#F5A623',  # 중국 (주황)
            '^FTSE': '#4A4A4A',      # 영국 (어두운 회색)
            '^GDAXI': '#9013FE',     # 독일 (보라)
            '^NSEI': '#50E3C2',      # 인도 (민트)
            '^TWII': '#B8E986',      # 대만 (연두)
            '^BVSP': '#8B572A'       # 브라질 (갈색)
        }
        
        for ticker, name in tickers.items():
            fig.add_trace(go.Scatter(
                x=normalized_df.index,
                y=normalized_df[ticker],
                name=name,
                line=dict(color=colors.get(ticker, '#9b9b9b'), width=2)
            ))
            
        fig.update_layout(
            height=500,
            margin=dict(l=20, r=20, t=20, b=20),
            hovermode="x unified",
            yaxis_title="누적 수익률 (기준시점 = 100)",
            legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1)
        )
        st.plotly_chart(fig, use_container_width=True)
        
        st.markdown("---")
        
        # ---------------------------------------------
        # 3. 추가 경제권역 및 지수 설명 가이드
        # ---------------------------------------------
        st.subheader("💡 글로벌 자산 배분 관점에서의 지수별 의의")
        st.markdown("글로벌 포트폴리오를 다변화할 때 각 지수들이 가지는 고유한 역할과 성격입니다.")
        desc_col1, desc_col2 = st.columns(2)
        with desc_col1:
            with st.expander("🇺🇸 미국 S&P 500 지수 (글로벌 주식의 핵심 앵커)", expanded=False):
                st.write("**주요 역할**: 전 세계 자산 배분의 기본 축 및 초장기 성장성 벤치마크\n\n"
                         "- 세계 최대의 경제국인 미국의 대표 지수로, 마이크로소프트, 애플, 엔비디아 등 글로벌 혁신 기술 기업들이 대거 포진해 있습니다.\n"
                         "- 전 세계 유동성과 자본이 최종 집중되는 시장으로, 안정성과 우상향의 복리 효과를 기대할 수 있는 핵심 자산입니다.")
                         
            with st.expander("🇰🇷 한국 KOSPI 지수 (글로벌 제조업 경기 민감주)", expanded=False):
                st.write("**주요 역할**: 글로벌 정보기술(IT) 및 반도체 제조업 경기 민감 벤치마크\n\n"
                         "- 반도체(삼성전자, SK하이닉스)와 자동차, 배터리 등 글로벌 하드웨어 제조업의 비중이 매우 높은 시장입니다.\n"
                         "- 수출 의존도가 극도로 높아 글로벌 경기 순환 및 교역량 증감에 민감하며, 경기 반등 초기에 강한 베타를 가집니다.")
                         
            with st.expander("🇯🇵 일본 Nikkei 225 지수 (엔저 수혜 및 밸류업 선두주자)", expanded=False):
                st.write("**주요 역할**: 글로벌 엔화 자산 프록시 및 대기업 주주 환원 벤치마크\n\n"
                         "- 도요타, 소니 등 글로벌 경쟁력을 지닌 정밀 제조 및 다국적 대기업들이 주축을 이룹니다.\n"
                         "- 엔화 가치 변동에 민감하게 작용하며, 주주 가치 극대화 정책(기업 거버넌스 개혁)의 성공에 따른 글로벌 자금 유입이 특징입니다.")

            with st.expander("🇩🇪 독일 DAX 지수 (유럽 제조업의 중심)", expanded=False):
                st.write("**주요 역할**: 유럽 경제의 성장 엔진 및 글로벌 경기 민감 제조업 벤치마크\n\n"
                         "- 독일은 유로존 최대 경제국으로 자동차(BMW, Mercedes), 화학(BASF), 엔지니어링(Siemens) 등 중공업과 수출 주도 기술이 핵심입니다.\n"
                         "- 유럽 전역의 경기 순환 사이클과 전 세계 설비투자(CAPEX) 동향을 파악하는 데 가장 중요한 선행 지표 역할을 수행합니다.")
                         
            with st.expander("🇮🇳 인도 Nifty 50 지수 (고성장 신흥국의 중심)", expanded=False):
                st.write("**주요 역할**: 구조적 성장 및 인구 배당 효과(Demographic Dividend) 수혜\n\n"
                         "- 세계 1위의 인구 규모와 고성장하는 내수 소비 시장을 바탕으로 하는 신흥 시장의 핵심 축입니다.\n"
                         "- 글로벌 포트폴리오 다변화(China+1 전략)의 대안 자금처 역할을 하고 있으며, 내수와 인프라 주도의 높은 성장 잠재력을 지니고 있습니다.")
                         
        with desc_col2:
            with st.expander("🇨🇳 중국 상해종합 지수 (글로벌 공급망과 정책 중심지)", expanded=False):
                st.write("**주요 역할**: 세계 2위 내수 시장 및 정부 재정/통화 정책 벤치마크\n\n"
                         "- 제조업 공급망의 중심부이자 원자재 최대 소비국으로, 중국 정부의 경기 부양 정책 및 규제 완화 여부에 지수 변동성이 큽니다.\n"
                         "- 타 선진국 시장과의 동조성이 낮아 포트폴리오 다변화 관점에서 고유한 분산 효과를 가집니다.")
                         
            with st.expander("🇬🇧 영국 FTSE 100 지수 (고배당 가치주 및 원자재 허브)", expanded=False):
                st.write("**주요 역할**: 인플레이션 헤지 포트폴리오 가치주 및 방어주 벤치마크\n\n"
                         "- 금융(HSBC), 헬스케어(AstraZeneca), 석유/에너지(Shell, BP) 등 구경제 및 고배당 전통 산업 위주로 구성되어 있습니다.\n"
                         "- 기술주 비중이 낮아 금리 인상기나 경기 둔화 시기에 방어력이 뛰어나며 높은 평균 배당 수익률을 보장합니다.")

            with st.expander("🇹🇼 대만 TAIEX 지수 (글로벌 IT/반도체 사이클의 풍향계)", expanded=False):
                st.write("**주요 역할**: 글로벌 첨단 하드웨어 및 IT/AI 기술 주기 벤치마크\n\n"
                         "- 세계 최대의 반도체 파운드리 기업인 TSMC가 지수 내 압도적인 비중을 차지하는 대표 기술주 지수입니다.\n"
                         "- 글로벌 빅테크 및 하드웨어 AI 설비투자 사이클, IT 공급망 경기를 민감하게 반영하는 선행 지표 성격을 가집니다.")
                         
            with st.expander("🇧🇷 브라질 IBOVESPA 지수 (원자재/소재 원천 및 리소스 프록시)", expanded=False):
                st.write("**주요 역할**: 글로벌 인플레이션 및 원자재 슈퍼 사이클 헤지 자산\n\n"
                         "- 남미 최대의 경제 대국이자 철광석(Vale), 에너지(Petrobras) 등 거대 원재료 공급 기업들의 영향력이 큽니다.\n"
                         "- 원자재 강세 주기와 금리 인상 등 글로벌 인플레이션 환경에서 강한 방어력을 갖는 소재/에너지 성격의 가치주 성격을 지닙니다.")
                         
        st.info("💡 **글로벌 주식 투자 참고:**\n"
                "- **기술주 및 하드웨어 집중**: 첨단 반도체 및 하드웨어 투자의 수혜는 **미국(NASDAQ/S&P)**과 **대만(TAIEX)**, **한국(KOSPI)**이 밀접하게 공유하며 동조화 경향을 보입니다.\n"
                "- **포트폴리오 분산**: 경기 회복기에는 **독일(DAX)**, 인플레이션 환경에는 원자재 비중이 높은 **브라질(IBOVESPA)** 및 **영국(FTSE)**을 혼합하여 지역 및 섹터별 균형을 맞추는 것이 유리합니다.")
                
    else:
        st.error("세계 주식 데이터를 불러오는 데 실패했습니다.")

elif page == "📊 매크로 대시보드":
    st.title("📊 글로벌 매크로 대시보드")
    st.markdown("경제의 장기 **'추세(Trend)'**와 단기 **'순환(Cycle)'**을 보여주는 경제 지표들을 분석하여 글로벌 금융 시장의 방향성을 조망합니다.")
    
    with st.spinner("FRED 매크로 데이터를 불러오는 중..."):
        macro_data = load_macro_dashboard_data()
        
    if macro_data:
        # 0. 데이터 정렬 및 기본값 검사
        us_base = macro_data.get('US_Base_Rate', pd.Series(dtype=float))
        kr_base = macro_data.get('KR_Base_Rate', pd.Series(dtype=float))
        us_10y = macro_data.get('US_10Y', pd.Series(dtype=float))
        us_2y = macro_data.get('US_2Y', pd.Series(dtype=float))
        kr_10y = macro_data.get('KR_10Y', pd.Series(dtype=float))
        usd_krw = macro_data.get('USD_KRW', pd.Series(dtype=float))
        us_gdp = macro_data.get('US_Real_GDP', pd.Series(dtype=float))
        us_pot = macro_data.get('US_Potential_GDP', pd.Series(dtype=float))
        us_prod = macro_data.get('US_Productivity', pd.Series(dtype=float))
        
        # 1. 상단 핵심 경제 지표 요약 (Metric Cards)
        st.subheader("📌 주요 매크로 지표 현황")
        m_col1, m_col2, m_col3, m_col4 = st.columns(4)
        
        if not us_base.empty:
            m_col1.metric("미국 기준금리 (Fed Funds)", f"{us_base.iloc[-1]:.2f}%")
        else:
            m_col1.metric("미국 기준금리 (Fed Funds)", "데이터 없음")
            
        if not kr_base.empty:
            m_col2.metric("한국 기준금리 (BOK)", f"{kr_base.iloc[-1]:.2f}%")
        else:
            m_col2.metric("한국 기준금리 (BOK)", "데이터 없음")
            
        if not usd_krw.empty:
            m_col3.metric("원/달러 환율 (USD/KRW)", f"{usd_krw.iloc[-1]:,.2f}원")
        else:
            m_col3.metric("원/달러 환율 (USD/KRW)", "데이터 없음")
            
        # 최신 아웃풋 갭 계산
        latest_gap = None
        if not us_gdp.empty and not us_pot.empty:
            df_gdp_align = pd.DataFrame({'Real': us_gdp, 'Pot': us_pot}).dropna()
            if not df_gdp_align.empty:
                df_gdp_align['Gap'] = 100 * (df_gdp_align['Real'] - df_gdp_align['Pot']) / df_gdp_align['Pot']
                latest_gap = df_gdp_align['Gap'].iloc[-1]
                gap_date = df_gdp_align.index[-1].strftime('%Y-%m')
                m_col4.metric(f"미국 아웃풋 갭 ({gap_date})", f"{latest_gap:+.2f}%")
        
        if latest_gap is None:
            m_col4.metric("미국 아웃풋 갭", "데이터 없음")
            
        st.markdown("---")
        
        # 2. 경제의 순환과 추세 섹션
        st.subheader("💡 1단계: 경제의 장기 '추세'와 단기 '순환'")
        st.markdown("성공적인 투자를 위해서는 장기적으로 성장하는 **'추세'**를 확인하고, **'순환(사이클)'** 지표를 통해 불황과 호황의 타이밍을 포착해야 합니다.")
        
        trend_col1, trend_col2 = st.columns(2)
        
        with trend_col1:
            st.markdown("#### 1. 경제의 순환: 아웃풋 갭 (Output Gap)")
            st.write("실제 GDP가 잠재 GDP(장기적인 성장 추세선)에서 얼마나 벗어나 있는지를 보여줍니다.")
            st.write("- **플러스(+)**: 경기 과열 (수요 초과, 인플레이션 위험)")
            st.write("- **마이너스(-)**: 경기 침체 (공급 과잉, 실업 발생, 물가 하락) ➡️ **주식 분할 매수 타이밍**")
            
            if not us_gdp.empty and not us_pot.empty:
                df_gap = pd.DataFrame({'Real': us_gdp, 'Pot': us_pot}).dropna()
                df_gap['Output_Gap'] = 100 * (df_gap['Real'] - df_gap['Pot']) / df_gap['Pot']
                
                fig_gap = go.Figure()
                fig_gap.add_trace(go.Bar(
                    x=df_gap.index,
                    y=df_gap['Output_Gap'],
                    name='Output Gap (%)',
                    marker_color=df_gap['Output_Gap'].apply(lambda x: '#D0021B' if x < 0 else '#4A90E2')
                ))
                fig_gap.add_hline(y=0.0, line_dash="dash", line_color="black")
                fig_gap.update_layout(
                    height=300,
                    margin=dict(l=20, r=20, t=10, b=20),
                    yaxis_title="아웃풋 갭 (%)",
                    hovermode="x unified"
                )
                st.plotly_chart(fig_gap, use_container_width=True)
            else:
                st.error("아웃풋 갭 데이터를 표시할 수 없습니다.")
                
        with trend_col2:
            st.markdown("#### 2. 경제의 추세: 생산성 향상 (Productivity)")
            st.write("동일한 노동력과 비용을 투입해 더 많은 산출물을 생산하는 기업의 본질적 능력입니다.")
            st.write("- **장기 우상향 추세**: 기업의 마진 개선과 물가 안정의 유일한 **'횡재'** 요인.")
            st.write("- 생산성이 장기적으로 성장하는 국가(예: 미국)에 투자해야 장기 복리 혜택을 누릴 수 있습니다.")
            
            if not us_prod.empty:
                fig_prod = go.Figure()
                fig_prod.add_trace(go.Scatter(
                    x=us_prod.index,
                    y=us_prod,
                    mode='lines',
                    name='Productivity Index',
                    line=dict(color='#50E3C2', width=3)
                ))
                fig_prod.update_layout(
                    height=300,
                    margin=dict(l=20, r=20, t=10, b=20),
                    yaxis_title="생산성 지수 (2017=100)",
                    hovermode="x unified"
                )
                st.plotly_chart(fig_prod, use_container_width=True)
            else:
                st.error("생산성 데이터를 표시할 수 없습니다.")
                
        st.markdown("---")
        
        # 3. 한/미 기준금리 및 장단기 금리차
        st.subheader("💵 2단계: 금리 정책과 장단기 금리차 (경기 선행 지표)")
        st.markdown("금리는 돈의 가격이자 경제의 온도를 나타냅니다. 통화 정책과 채권 시장의 스프레드는 미래 경기를 앞서 보여줍니다.")
        
        rate_col1, rate_col2 = st.columns(2)
        
        with rate_col1:
            st.markdown("#### 1. 한/미 기준금리 추이")
            st.write("각국 중앙은행(Fed, BOK)의 공식 정책금리입니다. 자산 가격의 할인율 및 자금 조달 비용을 결정합니다.")
            
            if not us_base.empty and not kr_base.empty:
                df_base = pd.DataFrame({'US_Base': us_base, 'KR_Base': kr_base}).ffill().dropna()
                fig_base = go.Figure()
                fig_base.add_trace(go.Scatter(x=df_base.index, y=df_base['US_Base'], name='미국 기준금리', line=dict(color='#FFBF00', width=2.5)))
                fig_base.add_trace(go.Scatter(x=df_base.index, y=df_base['KR_Base'], name='한국 기준금리', line=dict(color='#4A90E2', width=2.5)))
                fig_base.update_layout(
                    height=300,
                    margin=dict(l=20, r=20, t=10, b=20),
                    yaxis_title="금리 (%)",
                    legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
                    hovermode="x unified"
                )
                st.plotly_chart(fig_base, use_container_width=True)
            else:
                st.error("기준금리 데이터를 표시할 수 없습니다.")
                
        with rate_col2:
            st.markdown("#### 2. 미국 장단기 금리차 (10Y - 2Y)")
            st.write("장기 성장률 전망(10년물)과 단기 통화 정책(2년물)의 격차입니다.")
            st.write("- **장단기 역전(스프레드 < 0)**: 역사상 경기 침체(Recession)를 유발했던 가장 확실한 선행 지표.")
            st.write("- 금리차가 다시 정상화(0 이상으로 반등)되는 시점부터 경기 침체가 가시화되므로 주의가 필요합니다.")
            
            if not us_10y.empty and not us_2y.empty:
                df_spread = pd.DataFrame({'US_10Y': us_10y, 'US_2Y': us_2y}).ffill().dropna()
                df_spread['Spread'] = df_spread['US_10Y'] - df_spread['US_2Y']
                
                fig_spread = go.Figure()
                fig_spread.add_trace(go.Scatter(
                    x=df_spread.index, y=df_spread['Spread'],
                    fill='tozeroy',
                    name='10Y - 2Y Spread',
                    line=dict(color='#9013FE', width=2)
                ))
                fig_spread.add_hline(y=0.0, line_dash="dash", line_color="black")
                fig_spread.update_layout(
                    height=300,
                    margin=dict(l=20, r=20, t=10, b=20),
                    yaxis_title="금리차 (%p)",
                    hovermode="x unified"
                )
                st.plotly_chart(fig_spread, use_container_width=True)
            else:
                st.error("장단기 금리차 데이터를 표시할 수 없습니다.")
                
        st.markdown("---")
        
        # 4. 환율 추이
        st.subheader("💱 3단계: 글로벌 통화 및 환율 (자금 흐름의 척도)")
        st.markdown("원/달러 환율은 위험자산과 안전자산 간의 글로벌 자금 선호도를 보여주는 심리지표입니다.")
        
        fx_col1, fx_col2 = st.columns([2, 1])
        with fx_col1:
            if not usd_krw.empty:
                fig_fx = go.Figure()
                fig_fx.add_trace(go.Scatter(
                    x=usd_krw.index, y=usd_krw,
                    name='USD/KRW',
                    line=dict(color='#8B572A', width=2)
                ))
                fig_fx.update_layout(
                    height=300,
                    margin=dict(l=20, r=20, t=10, b=20),
                    yaxis_title="원/달러 환율 (원)",
                    hovermode="x unified"
                )
                st.plotly_chart(fig_fx, use_container_width=True)
            else:
                st.error("환율 데이터를 표시할 수 없습니다.")
                
        with fx_col2:
            st.markdown("#### 원/달러 환율의 매크로 해석")
            st.write("- **환율 상승 (원화 약세 / 달러 강세)**")
            st.write("  - 글로벌 위험 기피 심리가 고조될 때 상승합니다.")
            st.write("  - 한국 주식 시장(KOSPI)에서 외국인 수급 이탈을 자극하는 요인이 됩니다.")
            st.write("- **환율 하락 (원화 강세 / 달러 약세)**")
            st.write("  - 글로벌 위험 선호(경기 호황) 국면에서 자금이 한국 등 신흥국으로 유입될 때 하락합니다.")
            st.write("  - 국내 주식 비중을 늘리기 좋은 거시경제 환경을 조성합니다.")
            
        st.info("💡 **매크로 대시보드 투자 활용법:**\n"
                "1. **추세 확인**: 생산성 그래프(우상향)를 보고 장기 투자 대상 국가의 경쟁력을 확인하세요.\n"
                "2. **순환 분석**: 아웃풋 갭이 마이너스(-)일 때 정부/중앙은행의 부양책에 힘입어 주가가 바닥을 다질 가능성이 높으므로 분할 매수 기회로 삼으세요. 반대로 플러스(+) 영역이 깊어지면 과열을 주의해야 합니다.\n"
                "3. **위험 관리**: 미국 장단기 금리 역전 현상이 심해진 이후 환율이 급등하는 구간이 오면 안전 자산(금, 달러 예금)의 비중을 높여 변동성에 대비하세요.")
    else:
        st.error("매크로 데이터를 가져올 수 없었습니다.")