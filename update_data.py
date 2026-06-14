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

def get_current_vkospi():
    try:
        url = "https://kr.investing.com/indices/kospi-volatility"
        headers = {'User-Agent': 'Mozilla/5.0', 'Accept-Language': 'ko-KR,ko;q=0.9'}
        res = requests.get(url, headers=headers, timeout=5)
        soup = BeautifulSoup(res.text, 'html.parser')
        return float(soup.select_one('[data-test="instrument-price-last"]').text.replace(',', ''))
    except: return None

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
    
    # 네이버 화면의 "2026.04.01 장마감" 에서 10글자(날짜)만 빼와서 YYYY-MM-DD 형태로 변환
    market_date_str = soup.select_one('#time1').text[:10].replace('.', '-')

    # 3. [휴장일 방어막] 오늘 날짜와 장 열린 날짜가 다르면 그대로 봇을 퇴근시킴!
    if today_str != market_date_str:
        print(f"오늘은 휴장일(공휴일/주말)입니다. 업데이트를 건너뜁니다. (시장 열린 날: {market_date_str} / 오늘: {today_str})")
        return 

    # 4. 날짜가 같으면(정상 영업일) 아래 저장 로직을 실행
    try: df = pd.read_csv('KPRICE.csv', encoding='utf-8')
    except: df = pd.read_csv('KPRICE.csv', encoding='cp949')

    df.rename(columns={'일자': 'Date', 'KOSPI 소형주': 'KOSPI4', 'VKOSPI': 'V-KOSPI'}, inplace=True)
    df['Date'] = pd.to_datetime(df['Date'])
    df = df.set_index('Date')

    kr = get_current_korean_indices()
    ko4 = get_current_kospi4()
    vk = get_current_vkospi()

    if kr and ko4 and vk:
        today_dt = pd.to_datetime(today_kst)
        df.loc[today_dt, 'KOSPI'] = kr['KOSPI']
        df.loc[today_dt, 'KOSPI200'] = kr['KOSPI200']
        df.loc[today_dt, 'KOSDAQ'] = kr['KOSDAQ']
        df.loc[today_dt, 'KOSPI4'] = ko4
        df.loc[today_dt, 'V-KOSPI'] = vk

    df = df.sort_index(ascending=True).ffill().dropna(how='all')
    df.to_csv('KPRICE.csv', encoding='utf-8')
    print(f"정상 영업일 업데이트 완료: {today_str}")

if __name__ == "__main__":
    update_csv()
