import os
import pandas as pd
import yfinance as yf
from fredapi import Fred
from datetime import datetime, timedelta
from dotenv import load_dotenv

load_dotenv()

# 임계값 설정
THRESHOLDS = {
    "T10Y2Y": 0.0,       
    "DTWEXBGS": 120.0,   
    "VIX": 20.0,         
    "HY_SPREAD": 4.0  
}

# 차트 링크
CHART_LINKS = {
    "T10Y2Y": "https://fred.stlouisfed.org/series/T10Y2Y",
    "DTWEXBGS": "https://fred.stlouisfed.org/series/DTWEXBGS",
    "VIX": "https://finance.yahoo.com/quote/%5EVIX",
    "HY_SPREAD": "https://fred.stlouisfed.org/series/BAMLH0A0HYM2"
}

def get_indicators_data():
    fred_key = os.getenv("FRED_API_KEY")
    if not fred_key:
        print("⚠️ FRED_API_KEY가 설정되지 않았습니다.")
        return None
    
    fred = Fred(api_key=fred_key)
    end = datetime.now()
    start = end - timedelta(days=30)
    
    results = {}

    # 1. FRED 지표 (T10Y2Y, DTWEXBGS, BAMLH0A0HYM2)
    fred_symbols = {
        "T10Y2Y": "장단기 금리차",
        "DTWEXBGS": "달러 인덱스",
        "BAMLH0A0HYM2": "High Yield 스프레드"
    }

    for sym, name in fred_symbols.items():
        try:
            series = fred.get_series(sym, observation_start=start, observation_end=end).dropna()
            if len(series) < 2: continue
            
            # 최신값(iloc[-1])과 바로 전날값(iloc[-2]) 추출
            curr_val = float(series.iloc[-1])
            prev_val = float(series.iloc[-2])
            curr_date = series.index[-1].strftime('%m/%d')
            
            ref_key = "HY_SPREAD" if sym == "BAMLH0A0HYM2" else sym
            results[ref_key] = {
                "name": name,
                "current": round(curr_val, 3),
                "date": curr_date,
                "diff": round(curr_val - prev_val, 3),
                "threshold": THRESHOLDS[ref_key],
                "link": CHART_LINKS[ref_key]
            }
        except Exception as e:
            print(f"❌ FRED {sym} 로드 실패: {e}")

    # 2. Yahoo Finance (VIX) 
    try:
        # yfinance는 데이터프레임을 반환하므로 명확하게 인덱싱 필요
        vix_df = yf.download("^VIX", start=start, end=end, progress=False).dropna()
        if len(vix_df) >= 2:
            # Multi-Index 대응을 위해 values.flatten() 혹은 iloc 사용
            close_prices = vix_df['Close'].values.flatten()
            curr_vix = float(close_prices[-1])
            prev_vix = float(close_prices[-2])
            curr_vix_date = vix_df.index[-1].strftime('%m/%d')
            
            results["VIX"] = {
                "name": "공포 지수 (VIX)",
                "current": round(curr_vix, 2),
                "date": curr_vix_date,
                "diff": round(curr_vix - prev_vix, 2),
                "threshold": THRESHOLDS["VIX"],
                "link": CHART_LINKS["VIX"]
            }
    except Exception as e:
        print(f"❌ VIX 로드 실패: {e}")

    return results

def format_to_markdown(data):
    if not data: return "⚠️ 지표 데이터를 불러올 수 없습니다."
    
    md = "### 📊 시장 주요 지표 (전일 대비)\n"
    md += "| 지표명 (기준일) | 현재값 | 전일대비 | 임계값 | 상태 |\n"
    md += "| :--- | :---: | :---: | :---: | :---: |\n"
    
    for key, val in data.items():
        # 변동폭 부호 처리
        diff_val = val['diff']
        diff_str = f"+{diff_val}" if diff_val > 0 else f"{diff_val}"
        
        # 상태 판별 로직
        status = "✅"
        # 장단기 금리차는 역전(0이하) 시 위험
        if key == "T10Y2Y" and val['current'] <= val['threshold']: status = "⚠️"
        # 나머지는 임계값 이상 시 위험
        elif key != "T10Y2Y" and val['current'] >= val['threshold']: status = "⚠️"
        
        md += f"| [{val['name']}]({val['link']}) ({val['date']}) | {val['current']} | {diff_str} | {val['threshold']} | {status} |\n"

    return md + "\n"