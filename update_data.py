import pandas as pd
import requests
from bs4 import BeautifulSoup
from datetime import datetime, timezone, timedelta
import os
import yfinance as yf

# --- 지수 및 기준일 크롤링 (네이버 모바일 REST API + yfinance 2중 안전망) ---
def get_current_korean_indices():
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
    }
    indices = {}
    market_date_str = None
    
    # 1. 1차 시도: 네이버 증권 모바일 REST API (Next.js 웹 개편과 무관하게 영구 작동)
    symbol_map = {
        'KOSPI': 'KOSPI',
        'KOSDAQ': 'KOSDAQ',
        'KOSPI200': 'KPI200'
    }
    try:
        for key, sym in symbol_map.items():
            url = f"https://m.stock.naver.com/api/index/{sym}/basic"
            res = requests.get(url, headers=headers, timeout=5)
            if res.status_code == 200:
                data = res.json()
                price_str = data.get('closePrice', '').replace(',', '')
                indices[key] = float(price_str)
                if not market_date_str and data.get('localTradedAt'):
                    market_date_str = data['localTradedAt'][:10]
        if len(indices) == 3:
            return indices, market_date_str
    except Exception as e:
        print(f"[API] 네이버 증권 API 에러: {e}")
        
    # 2. 2차 시도 (대체 백업): yfinance (^KS11, ^KQ11, ^KS200)
    try:
        yf_map = {'KOSPI': '^KS11', 'KOSDAQ': '^KQ11', 'KOSPI200': '^KS200'}
        for key, sym in yf_map.items():
            t = yf.Ticker(sym)
            hist = t.history(period="5d")
            if not hist.empty:
                indices[key] = float(hist['Close'].dropna().iloc[-1])
                if not market_date_str:
                    market_date_str = hist.index[-1].strftime('%Y-%m-%d')
        if len(indices) == 3:
            return indices, market_date_str
    except Exception as e:
        print(f"[API] yfinance 보조 수집 에러: {e}")

    return (indices if indices else None), market_date_str

def get_current_kospi4():
    # 1. yfinance 시도
    try:
        t = yf.Ticker("KOSPI-4.KS")
        hist = t.history(period="5d")
        if not hist.empty and 'Close' in hist.columns:
            val = float(hist['Close'].dropna().iloc[-1])
            if val > 0:
                return val
    except Exception:
        pass
        
    # 2. Yahoo Finance 웹 스크래핑 보조 시도
    try:
        url = "https://finance.yahoo.com/quote/KOSPI-4.KS/"
        headers = {'User-Agent': 'Mozilla/5.0'}
        res = requests.get(url, headers=headers, timeout=5)
        soup = BeautifulSoup(res.text, 'html.parser')
        price_el = soup.select_one('fin-streamer[data-field="regularMarketPrice"]') or soup.select_one('span[data-testid="qsp-price"]')
        if price_el:
            return float(price_el.text.replace(',', ''))
    except Exception:
        pass
    return None

# --- V-KOSPI 크롤링 (Investing.com Cloudflare 우회 버전) ---
def get_current_vkospi():
    try:
        import cloudscraper
        
        url = "https://kr.investing.com/indices/kospi-volatility"
        
        # 💡 핵심: 일반 파이썬 requests 대신, 진짜 윈도우 크롬 브라우저의 지문(Fingerprint)을 복제하는 스크래퍼 생성
        scraper = cloudscraper.create_scraper(
            browser={
                'browser': 'chrome',
                'platform': 'windows',
                'desktop': True
            }
        )
        
        # requests.get 대신 scraper.get 사용
        res = scraper.get(url, timeout=10)
        soup = BeautifulSoup(res.text, 'html.parser')
        
        # Investing.com의 고유 속성 타겟팅
        price_element = soup.select_one('[data-test="instrument-price-last"]')
        
        if price_element:
            return float(price_element.text.replace(',', ''))
        return None
        
    except Exception as e:
        print(f"V-KOSPI 우회 에러: {e}")
        return None

# --- 궁극의 업데이트 로직 (시간 지연 완벽 방어) ---
def update_csv():
    # 1. 지수 및 '실제로 장이 열린 기준일' 가져오기 (진실의 시계)
    kr, market_date_str = get_current_korean_indices()
    
    if not market_date_str:
        kst_tz = timezone(timedelta(hours=9))
        market_date_str = datetime.now(kst_tz).strftime('%Y-%m-%d')
    
    # 💡 봇의 실행 시간이 아닌, '시장이 열린 날짜'를 인덱스 이름표로 무조건 사용합니다!
    market_dt = pd.to_datetime(market_date_str) 

    # 2. CSV 불러오기
    try: df = pd.read_csv('KPRICE.csv', encoding='utf-8')
    except: df = pd.read_csv('KPRICE.csv', encoding='cp949')

    df.rename(columns={'일자': 'Date', 'KOSPI 소형주': 'KOSPI4', 'VKOSPI': 'V-KOSPI'}, inplace=True)
    df['Date'] = pd.to_datetime(df['Date'])
    df = df.set_index('Date')

    # 3. 크롤링 시도
    ko4 = get_current_kospi4()
    vk = get_current_vkospi() # (우회 도구 적용된 함수)
    
    print(f"[STATUS] 수집 상태 -> 한국 지수: {kr is not None}, KOSPI4: {ko4 is not None}, V-KOSPI: {vk is not None}")

    # 4. 데이터 덮어쓰기 (핵심: today_dt가 아니라 market_dt 위치에 넣습니다)
    if kr:
        df.loc[market_dt, 'KOSPI'] = kr['KOSPI']
        df.loc[market_dt, 'KOSPI200'] = kr['KOSPI200']
        df.loc[market_dt, 'KOSDAQ'] = kr['KOSDAQ']
        
        if ko4: df.loc[market_dt, 'KOSPI4'] = ko4
        if vk: df.loc[market_dt, 'V-KOSPI'] = vk

    # 5. 빈칸 채우고 저장하기
    df = df.sort_index(ascending=True).ffill().dropna(how='all')
    df.to_csv('KPRICE.csv', encoding='utf-8')
    print(f"[SUCCESS] 업데이트 완료 (기준일: {market_date_str})")
    
    # 6. 한국 주식 밸류에이션 데이터(PER, PBR) 수집 자동화 연동
    try:
        update_valuation_csv(market_dt)
    except Exception as e:
        print(f"[WARNING] 밸류에이션 수집 에러: {e}")

def update_valuation_csv(market_dt):
    from pykrx import stock
    import os
    from datetime import time as dt_time
    
    # 💡 KRX 로그인 환경변수 체크 및 가이드 출력
    krx_id = os.getenv("KRX_ID")
    krx_pw = os.getenv("KRX_PW")
    if not krx_id or not krx_pw:
        print("[WARNING] KRX_ID 또는 KRX_PW 환경 변수가 설정되지 않았습니다.")
        print("          KRX 정보데이터시스템(https://data.krx.co.kr)이 회원제로 개편됨에 따라,")
        print("          pykrx를 통한 밸류에이션(PER/PBR) 데이터 수집을 위해서는 로그인 자격 증명이 필수적입니다.")
        print("          1. KRX 정보데이터시스템(https://data.krx.co.kr) 회원가입 (무료)")
        print("          2. 로컬 실행 시 환경 변수 설정 또는 GitHub Repository Secrets에 KRX_ID, KRX_PW 등록")
        
    csv_file = 'KVALUATION.csv'
    
    # 💡 윈도우 환경/장전 테스트를 위한 안전장치: 장 마감 정산 전(16:30 이전)에 당일 조회를 요청할 경우 
    # 데이터가 없어서 거래소 API가 에러를 내므로 수집 기준일을 어제 날짜로 당깁니다.
    kst_tz = timezone(timedelta(hours=9))
    now = datetime.now(kst_tz)
    adjusted_dt = market_dt
    if market_dt.date() >= now.date() and now.time() < dt_time(16, 30):
        adjusted_dt = market_dt - timedelta(days=1)
        print(f"[FILE] 장 마감 정산 전이므로 수집 범위를 어제({adjusted_dt.strftime('%Y-%m-%d')}) 기준으로 조정합니다.")
        
    start_date = (adjusted_dt - timedelta(days=365)).strftime("%Y%m%d")
    end_date = adjusted_dt.strftime("%Y%m%d")
    
    # 지수 코드 정의 (KOSPI: 1001, 대형주: 1002, 중형주: 1003, 소형주: 1004)
    indices = {
        '1001': 'KOSPI 전체',
        '1002': '대형주',
        '1003': '중형주',
        '1004': '소형주'
    }
    
    if not os.path.exists(csv_file):
        print("[FILE] KVALUATION.csv 파일이 없습니다. 최초 1년치 데이터를 수집하여 초기 생성합니다...")
        
        merged_df = None
        for code, name in indices.items():
            try:
                print(f"[API] pykrx 수집 중: {name} ({code}) [{start_date} ~ {end_date}]")
                df = stock.get_index_fundamental(start_date, end_date, code)
                if df.empty:
                    continue
                
                # 필요한 컬럼만 추출
                sub_df = df[['PER', 'PBR']].copy()
                sub_df.columns = [f"{name} PER", f"{name} PBR"]
                
                if merged_df is None:
                    merged_df = sub_df
                else:
                    merged_df = merged_df.join(sub_df, how='outer')
            except Exception as e:
                print(f"[ERROR] {name} 데이터 수집 실패: {e}")
                
        if merged_df is not None:
            merged_df.index.name = 'Date'
            import numpy as np
            merged_df = merged_df.replace(0.0, np.nan).sort_index().ffill().bfill()
            merged_df.to_csv(csv_file, encoding='utf-8')
            print(f"[SUCCESS] KVALUATION.csv 초기 생성 완료 (행 개수: {len(merged_df)})")
        else:
            print("[ERROR] 초기 데이터 수집에 실패하여 CSV를 생성하지 못했습니다.")
            
    else:
        print("[FILE] 기존 KVALUATION.csv를 업데이트합니다...")
        try:
            val_df = pd.read_csv(csv_file, encoding='utf-8')
        except Exception:
            val_df = pd.read_csv(csv_file, encoding='cp949')
            
        val_df['Date'] = pd.to_datetime(val_df['Date'])
        val_df = val_df.set_index('Date')
        
        # 기존에 잘못 수집된 0.0 값들을 NaN으로 변환하여 ffill로 자연스럽게 채워지도록 조치
        import numpy as np
        val_df = val_df.replace(0.0, np.nan)
        
        # market_dt가 인덱스에 없으면 추가 (ffill로 자동 전파하기 위해 미리 자리를 만들어 둠)
        if market_dt not in val_df.index:
            val_df.loc[market_dt] = [np.nan] * len(val_df.columns)
            
        # 당일 데이터 크롤링 (데이터가 0.0이거나 수집 실패 시 이전 영업일로 역추적하여 수집)
        max_lookback = 5
        success_dt = None
        for attempt in range(max_lookback):
            query_date_str = adjusted_dt.strftime("%Y%m%d")
            print(f"[API] pykrx 당일 조회 시도: {adjusted_dt.strftime('%Y-%m-%d')} (시도 {attempt+1}/{max_lookback})")
            
            temp_data = {}
            valid = True
            for code, name in indices.items():
                try:
                    df = stock.get_index_fundamental(query_date_str, query_date_str, code)
                    if not df.empty:
                        per = float(df.iloc[0]['PER'])
                        pbr = float(df.iloc[0]['PBR'])
                        if per == 0.0 and pbr == 0.0:
                            valid = False
                            break
                        temp_data[f"{name} PER"] = per
                        temp_data[f"{name} PBR"] = pbr
                    else:
                        valid = False
                        break
                except Exception as e:
                    print(f"[ERROR] {name} 수집 중 에러: {e}")
                    valid = False
                    break
            
            if valid and temp_data:
                # 모든 지수의 당일 데이터가 정상적으로 들어온 경우 저장
                for col, val in temp_data.items():
                    val_df.loc[adjusted_dt, col] = val
                    if "PER" in col:
                        pbr_col = col.replace("PER", "PBR")
                        print(f"[STATUS] {col.split(' ')[0]} 당일 수집 완료 -> PER: {val}, PBR: {temp_data[pbr_col]}")
                success_dt = adjusted_dt
                break
            else:
                print(f"[WARNING] {adjusted_dt.strftime('%Y-%m-%d')} 데이터가 0.0이거나 정산 전입니다. 이전 영업일로 재시도합니다.")
                adjusted_dt = adjusted_dt - timedelta(days=1)
                
        # 만약 끝내 수집에 실패한 경우 로그 출력
        if success_dt is None:
            print("[WARNING] 최근 5 영업일간 유효한 밸류에이션 데이터를 찾지 못했습니다. 기존 데이터를 ffill로 유지합니다.")
            
        val_df = val_df.sort_index().ffill()
        # 혹시 ffill 후에도 남아있을 수 있는 첫 행의 결측치는 bfill로 임시 처리
        val_df = val_df.bfill()
        val_df.to_csv(csv_file, encoding='utf-8')
        print(f"[SUCCESS] KVALUATION.csv 업데이트 완료 (정산 반영 기준일: {(success_dt or market_dt).strftime('%Y-%m-%d')})")

if __name__ == "__main__":
    update_csv()
