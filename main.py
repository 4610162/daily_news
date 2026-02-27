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
def get_news_content():
    # 한국경제 RSS 주소
    # 경제: https://www.hankyung.com/feed/economy
    # 증권: https://www.hankyung.com/feed/finance
    urls = [
        "https://www.hankyung.com/feed/economy",
        "https://www.hankyung.com/feed/finance"
    ]
    
    news_text = ""
    for url in urls:
        feed = feedparser.parse(url)
        # 각 섹션의 제목(경제/증권) 표시
        category = "경제" if "economy" in url else "증권"
        news_text += f"\n--- [{category} 섹션 주요 뉴스] ---\n"
        
        for entry in feed.entries[:10]: # 각 섹션당 상위 10개 기사
            # 한국경제 RSS는 summary 항목에 본문 요약이 잘 포함되어 있습니다.
            news_text += f"제목: {entry.title}\n내용: {entry.summary}\n\n"
            
    return news_text

# 2. Gemini AI 요약 함수 (이전과 동일)
def get_gemini_summary(news_data):
    if not GEMINI_API_KEY:
        raise ValueError("GEMINI_API_KEY가 설정되지 않았습니다.")
        
    genai.configure(api_key=GEMINI_API_KEY)
    model = genai.GenerativeModel('gemini-1.5-flash')
    
    prompt = f"""
    너는 금융 및 증권 전문 애널리스트야. 제공된 한국경제 뉴스 목록을 읽고, 
    투자자가 오늘 아침 반드시 체크해야 할 '핵심 브리핑'을 작성해줘.
    
    [지침]
    1. 시장 전체의 흐름을 관통하는 가장 중요한 이슈 3개를 선정할 것.
    2. 각 이슈별로 투자자가 주의해야 할 점이나 기회 요인을 분석할 것.
    3. 텔레그램 가독성을 위해 적절한 이모지와 불렛포인트를 사용할 것.
    4. 분석은 전문적이되 말투는 친절하게 할 것.

    [뉴스 데이터]
    {news_data}
    """
    
    response = model.generate_content(prompt)
    return response.text

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