import os
import feedparser
import google.generativeai as genai
import asyncio
from telegram import Bot
from dotenv import load_dotenv

# .env 파일 로드
load_dotenv()

# 환경 변수 설정
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")

# 1. 한국경제 뉴스 데이터 수집 함수
# main.py 내의 해당 부분을 이렇게 수정하세요
def get_news_content():
    urls = [
        "https://www.hankyung.com/feed/economy",
        "https://www.hankyung.com/feed/finance"
    ]
    
    news_text = ""
    for url in urls:
        feed = feedparser.parse(url)
        category = "경제" if "economy" in url else "증권"
        news_text += f"\n--- [{category} 섹션 주요 뉴스] ---\n"
        
        for entry in feed.entries[:10]:
            # 핵심 수정: .summary 대신 .get() 사용 (데이터가 없으면 빈 문자열)
            title = entry.get('title', '제목 없음')
            summary = entry.get('summary', '내용 없음')
            
            # 한경 RSS 특성에 따라 'description' 필드에 내용이 들어있을 수도 있으므로 보강
            if summary == '내용 없음' or not summary:
                summary = entry.get('description', '내용 없음')
                
            news_text += f"제목: {title}\n내용: {summary}\n\n"
            
    return news_text

# 2. Gemini AI 요약 함수 (이전과 동일)
# main.py의 get_gemini_summary 함수를 이렇게 수정해 보세요

import google.generativeai as genai

def get_gemini_summary(news_data):
    if not GEMINI_API_KEY:
        raise ValueError("GEMINI_API_KEY가 설정되지 않았습니다.")
        
    genai.configure(api_key=GEMINI_API_KEY)
    
    # 모델 우선순위 설정: 1순위 Gemini(고성능/20회), 2순위 Gemma(무제한급)
    model_priority = ['gemini-2.5-flash', 'gemma-3-27b']
    
    prompt = f"""
    너는 금융 및 증권 전문 애널리스트야. 제공된 한국경제 뉴스 목록을 읽고, 
    투자자가 오늘 아침 반드시 체크해야 할 '핵심 브리핑'을 작성해줘.
    
    [지침]
    1. 시장 전체의 흐름을 관통하는 가장 중요한 이슈 3개를 선정할 것.
    2. 각 이슈별로 투자자가 주의해야 할 점이나 기회 요인을 분석할 것.
    3. 텔레그램 가독성을 위해 적절한 이모지와 불렛포인트를 사용할 것.

    [뉴스 데이터]
    {news_data}
    """

    for model_name in model_priority:
        try:
            # 모델 인스턴스 생성 및 호출
            model = genai.GenerativeModel(model_name)
            response = model.generate_content(prompt)
            
            # 성공 시 결과 반환 후 종료
            return response.text
            
        except Exception as e:
            error_msg = str(e)
            
            # 429(할당량 초과) 혹은 404(모델 없음)일 경우 다음 모델로 시도
            if "429" in error_msg or "404" in error_msg:
                print(f"⚠️ {model_name} 실패: 할당량 초과 혹은 모델 없음. 다음 모델로 전환합니다...")
                continue
            else:
                # 그 외의 심각한 에러(네트워크 등)는 즉시 중단
                return f"❌ API 호출 중 예외 발생: {e}"

    return "❌ 모든 가용 모델의 호출에 실패했습니다."

# 3. 텔레그램 전송 함수 (이전과 동일)
async def send_telegram(message):
    if not TELEGRAM_TOKEN or not CHAT_ID:
        raise ValueError("텔레그램 설정이 누락되었습니다.")
        
    bot = Bot(token=TELEGRAM_TOKEN)
    await bot.send_message(chat_id=CHAT_ID, text=message)

# 4. 실행 로직
async def main():
    print("🚀 한국경제 뉴스 수집 및 Gemini 요약 시작...")
    try:
        news_data = get_news_content()
        if not news_data.strip():
            print("⚠️ 수집된 뉴스가 없습니다.")
            return
            
        briefing = get_gemini_summary(news_data)
        await send_telegram(briefing)
        print("✅ 한경 브리핑 전송 완료!")
    except Exception as e:
        print(f"❌ 에러 발생: {e}")

if __name__ == "__main__":
    asyncio.run(main())