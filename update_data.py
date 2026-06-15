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

# --- 방어막이 추가된 메인 업데이트 로직 ---
def update_csv():
    # 1. 깃허브 서버(UTC) 기준이 아닌, 완벽한 한국 시간(KST) 구하기
    KST = timezone(timedelta(hours=9))
    today_kst = datetime.now(KST).date()
    today_str = today_kst.strftime("%Y-%m-%d")

    # 2. 네이버 증권에서 '실제로 장이 열린 기준일' 확인하기
    url = "https://finance.naver.com/sise/"
    headers = {'User-Agent': 'Mozilla/5.0'}
    res = requests.get(url, headers=headers, timeout=5)
    soup = BeautifulSoup(res.text, 'html.parser')
    
    market_date_str = soup.select_one('#time1').text.strip()[:10].replace('.', '-')

    # 3. [휴장일 방어막]
    if today_str != market_date_str:
        print(f"오늘은 휴장일(공휴일/주말)입니다. 업데이트를 건너뜁니다. (시장 열린 날: {market_date_str} / 오늘: {today_str})")
        return 

    # 4. CSV 불러오기
    try: df = pd.read_csv('KPRICE.csv', encoding='utf-8')
    except: df = pd.read_csv('KPRICE.csv', encoding='cp949')

    df.rename(columns={'일자': 'Date', 'KOSPI 소형주': 'KOSPI4', 'VKOSPI': 'V-KOSPI'}, inplace=True)
    df['Date'] = pd.to_datetime(df['Date'])
    df = df.set_index('Date')

    # 5. 크롤링 시도
    kr = get_current_korean_indices()
    ko4 = get_current_kospi4()
    vk = get_current_vkospi()
    
    # 💡 봇이 어디서 막혔는지 깃허브 로그에서 볼 수 있도록 기록을 남깁니다.
    print(f"📊 수집 상태 확인 -> 네이버: {kr is not None}, 야후(소형주): {ko4 is not None}, 인베스팅(V-KOSPI): {vk is not None}")

    # 6. [핵심] 가장 믿음직한 네이버(kr)만 성공해도 무조건 오늘 행을 만듭니다.
    if kr:
        today_dt = pd.to_datetime(today_kst)
        df.loc[today_dt, 'KOSPI'] = kr['KOSPI']
        df.loc[today_dt, 'KOSPI200'] = kr['KOSPI200']
        df.loc[today_dt, 'KOSDAQ'] = kr['KOSDAQ']
        
        # 야후와 인베스팅은 성공했을 때만 넣습니다. 
        # (실패해서 빈칸이 되면 아래 ffill()이 자동으로 어제 가격으로 메워줍니다.)
        if ko4: df.loc[today_dt, 'KOSPI4'] = ko4
        if vk: df.loc[today_dt, 'V-KOSPI'] = vk

    # 7. 빈칸 채우고 저장하기
    df = df.sort_index(ascending=True).ffill().dropna(how='all')
    df.to_csv('KPRICE.csv', encoding='utf-8')
    print(f"✅ 정상 영업일 업데이트 완료: {today_str}")

if __name__ == "__main__":
    update_csv()
