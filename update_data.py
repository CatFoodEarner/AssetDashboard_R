import pandas as pd
import requests
from bs4 import BeautifulSoup
from datetime import datetime, timezone, timedelta
import os

# --- 기존 크롤링 함수 3개 (수정 없음) ---
def get_current_korean_indices():
    try:
        url = "https://finance.naver.com/sise/"
        headers = {'User-Agent': 'Mozilla/5.0'}
        res = requests.get(url, headers=headers, timeout=5)
        soup = BeautifulSoup(res.text, 'html.parser')
        return {
            'KOSPI': float(soup.select_one('#KOSPI_now').text.replace(',', '')),
            'KOSDAQ': float(soup.select_one('#KOSDAQ_now').text.replace(',', '')),
            'KOSPI200': float(soup.select_one('#KPI200_now').text.replace(',', ''))
        }
    except: return None

def get_current_kospi4():
    try:
        url = "https://finance.yahoo.com/quote/KOSPI-4.KS/"
        headers = {'User-Agent': 'Mozilla/5.0', 'Accept': 'text/html'}
        res = requests.get(url, headers=headers, timeout=5)
        soup = BeautifulSoup(res.text, 'html.parser')
        return float(soup.select_one('span[data-testid="qsp-price"]').text.replace(',', ''))
    except: return None

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
    # 1. 네이버 증권에서 '실제로 장이 열린 기준일' 가져오기 (진실의 시계)
    url = "https://finance.naver.com/sise/"
    headers = {'User-Agent': 'Mozilla/5.0'}
    res = requests.get(url, headers=headers, timeout=5)
    soup = BeautifulSoup(res.text, 'html.parser')
    
    market_date_str = soup.select_one('#time1').text.strip()[:10].replace('.', '-')
    
    # 💡 봇의 실행 시간이 아닌, '시장이 열린 날짜'를 인덱스 이름표로 무조건 사용합니다!
    market_dt = pd.to_datetime(market_date_str) 

    # 2. CSV 불러오기
    try: df = pd.read_csv('KPRICE.csv', encoding='utf-8')
    except: df = pd.read_csv('KPRICE.csv', encoding='cp949')

    df.rename(columns={'일자': 'Date', 'KOSPI 소형주': 'KOSPI4', 'VKOSPI': 'V-KOSPI'}, inplace=True)
    df['Date'] = pd.to_datetime(df['Date'])
    df = df.set_index('Date')

    # 3. 크롤링 시도
    kr = get_current_korean_indices()
    ko4 = get_current_kospi4()
    vk = get_current_vkospi() # (우회 도구 적용된 함수)
    
    print(f"📊 수집 상태 -> 네이버: {kr is not None}, 야후: {ko4 is not None}, V-KOSPI: {vk is not None}")

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
    print(f"✅ 업데이트 완료 (기준일: {market_date_str})")

if __name__ == "__main__":
    update_csv()
