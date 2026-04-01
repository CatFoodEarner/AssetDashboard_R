import pandas as pd
import requests
from bs4 import BeautifulSoup
import datetime
import os

# 1. 크롤링 함수들 모음
def get_current_korean_indices():
    try:
        url = "https://finance.naver.com/sise/"
        headers = {'User-Agent': 'Mozilla/5.0'}
        res = requests.get(url, headers=headers, timeout=5)
        soup = BeautifulSoup(res.text, 'html.parser')
        kospi = float(soup.select_one('#KOSPI_now').text.replace(',', ''))
        kosdaq = float(soup.select_one('#KOSDAQ_now').text.replace(',', ''))
        kospi200 = float(soup.select_one('#KPI200_now').text.replace(',', ''))
        return {'KOSPI': kospi, 'KOSDAQ': kosdaq, 'KOSPI200': kospi200}
    except: return None

def get_current_kospi4():
    try:
        url = "https://finance.yahoo.com/quote/KOSPI-4.KS/"
        headers = {'User-Agent': 'Mozilla/5.0', 'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8'}
        res = requests.get(url, headers=headers, timeout=5)
        soup = BeautifulSoup(res.text, 'html.parser')
        price_element = soup.select_one('span[data-testid="qsp-price"]')
        return float(price_element.text.replace(',', '')) if price_element else None
    except: return None

def get_current_vkospi():
    try:
        url = "https://kr.investing.com/indices/kospi-volatility"
        headers = {'User-Agent': 'Mozilla/5.0', 'Accept-Language': 'ko-KR,ko;q=0.9,en-US;q=0.8'}
        res = requests.get(url, headers=headers, timeout=5)
        soup = BeautifulSoup(res.text, 'html.parser')
        price_element = soup.select_one('[data-test="instrument-price-last"]')
        return float(price_element.text.replace(',', '')) if price_element else None
    except: return None

# 2. 메인 업데이트 로직
def update_csv():
    # CSV 읽기 (인코딩 에러 방지를 위해 utf-8과 cp949 모두 시도)
    try:
        df = pd.read_csv('KPRICE.csv', encoding='utf-8')
    except:
        df = pd.read_csv('KPRICE.csv', encoding='cp949')

    # 컬럼명 통일
    rename_dict = {'일자': 'Date', 'KOSPI 소형주': 'KOSPI4', 'VKOSPI': 'V-KOSPI'}
    df.rename(columns=rename_dict, inplace=True)
    df['Date'] = pd.to_datetime(df['Date'])
    df = df.set_index('Date')

    # 오늘 날짜 크롤링
    kr_indices = get_current_korean_indices()
    kospi4 = get_current_kospi4()
    vkospi = get_current_vkospi()

    # 데이터가 모두 정상 수집되었을 때만 추가
    if kr_indices and kospi4 and vkospi:
        today = pd.to_datetime(datetime.date.today())
        df.loc[today, 'KOSPI'] = kr_indices['KOSPI']
        df.loc[today, 'KOSPI200'] = kr_indices['KOSPI200']
        df.loc[today, 'KOSDAQ'] = kr_indices['KOSDAQ']
        df.loc[today, 'KOSPI4'] = kospi4
        df.loc[today, 'V-KOSPI'] = vkospi

    # 정리 후 덮어쓰기 저장 (이제부터는 글로벌 표준인 utf-8로 저장합니다)
    df = df.sort_index(ascending=True).ffill().dropna(how='all')
    df.to_csv('KPRICE.csv', encoding='utf-8')
    print(f"업데이트 완료: {today.strftime('%Y-%m-%d')}")

if __name__ == "__main__":
    update_csv()