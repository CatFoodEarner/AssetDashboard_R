import pandas as pd
import requests
from bs4 import BeautifulSoup
import datetime

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
        headers = {'User-Agent': 'Mozilla/5.0', 'Accept': 'text/html,application/xhtml+xml'}
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

def update_csv():
    try: df = pd.read_csv('KPRICE.csv', encoding='utf-8')
    except: df = pd.read_csv('KPRICE.csv', encoding='cp949')

    df.rename(columns={'일자': 'Date', 'KOSPI 소형주': 'KOSPI4', 'VKOSPI': 'V-KOSPI'}, inplace=True)
    df['Date'] = pd.to_datetime(df['Date'])
    df = df.set_index('Date')

    kr = get_current_korean_indices()
    ko4 = get_current_kospi4()
    vk = get_current_vkospi()

    if kr and ko4 and vk:
        today = pd.to_datetime(datetime.date.today())
        df.loc[today, 'KOSPI'] = kr['KOSPI']
        df.loc[today, 'KOSPI200'] = kr['KOSPI200']
        df.loc[today, 'KOSDAQ'] = kr['KOSDAQ']
        df.loc[today, 'KOSPI4'] = ko4
        df.loc[today, 'V-KOSPI'] = vk

    df = df.sort_index(ascending=True).ffill().dropna(how='all')
    df.to_csv('KPRICE.csv', encoding='utf-8')

if __name__ == "__main__":
    update_csv()