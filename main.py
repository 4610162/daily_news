import os
import feedparser
import google.generativeai as genai
import asyncio
from telegram import Bot
from datetime import datetime
from dotenv import load_dotenv
from github import Github

load_dotenv()

# 환경 변수 설정
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")

def get_news_content():
    urls = [
        "https://www.hankyung.com/feed/economy",
        "https://www.hankyung.com/feed/finance"
    ]
    news_items = []  # 상세 데이터 저장
    news_text_for_ai = ""
    
    for url in urls:
        feed = feedparser.parse(url)
        category = "경제" if "economy" in url else "증권"
        for entry in feed.entries[:5]:
            title = entry.get('title', '제목 없음')
            link = entry.get('link', '#')
            summary = entry.get('summary', entry.get('description', '내용 없음'))
            
            news_items.append({"cat": category, "title": title, "link": link})
            news_text_for_ai += f"제목: {title}\n내용: {summary}\n\n"
            
    return news_items, news_text_for_ai

def get_gemini_summary(news_data):
    if not GEMINI_API_KEY:
        raise ValueError("GEMINI_API_KEY가 설정되지 않았습니다.")
        
    genai.configure(api_key=GEMINI_API_KEY)

    # 💡 현재 날짜를 구해서 프롬프트에 넣어줍니다.
    today_date = datetime.now().strftime("%Y년 %m월 %d일")
    
    # 모델 우선순위 설정: 1순위 Gemini(고성능/20회), 2순위 Gemma(무제한급)
    model_priority = ['gemini-2.5-flash', 'models/gemma-3-27b-it']
    
    prompt = f"""
    역할 : 경제 및 금융 전문 애널리스트
    아래 뉴스 데이터를 분석해서 마크다운 형식으로 보고서를 작성해줘.
    모든 분석의 기준 시점은 반드시 {today_date}이어야 해.
    
    [포함 내용]
    1. 🎯 오늘의 경제 및 시장 핵심 키워드 (3개)
    2. 📈 종합 분석 및 투자 전략 (심도 있게)
    3. ⚠️ 주의 깊게 봐야 할 지표나 일정
    
    전문적이고 신뢰감 있는 톤으로 작성해줘.
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

async def create_and_save_report(news_items, analysis, issue_url=None):
    today_str = datetime.now().strftime("%Y-%m-%d")
    # 폴더 구조를 docs/reports/2026-02-28.md 형태로 생성
    os.makedirs("docs/reports", exist_ok=True)
    file_path = f"docs/reports/{today_str}.md"  # 변수명 통일
    
    # 1. 마크다운 내용 구성
    md_content = f"# 📑 데일리 경제 브리핑 보고서 ({today_str})\n\n"
    md_content += "## 📰 주요 뉴스 헤드라인 (TOP 10)\n"
    for i, item in enumerate(news_items, 1):
        md_content += f"{i}. [{item['cat']}] [{item['title']}]({item['link']})\n"
    
    md_content += "\n---\n\n"
    md_content += "## 🤖 AI 분석 및 시장 전망\n"
    md_content += analysis
    
    # 2. 로컬에 파일 저장
    with open(file_path, "w", encoding="utf-8") as f:
        f.write(md_content)
    
    # 웹사이트 URL 반환 (사용자 계정/레포 이름에 맞춰 설정)
    site_url = f"https://4610162.github.io/daily_news/reports/{today_str}.md"
    return site_url, md_content # 본문도 함께 반환하여 main에서 활용

# 텔레그램 상단에 노출할 3줄 핵심 요약 생성
def get_telegram_brief(news_data):
    if not GEMINI_API_KEY:
        raise ValueError("GEMINI_API_KEY가 설정되지 않았습니다.")
        
    genai.configure(api_key=GEMINI_API_KEY)
    model = genai.GenerativeModel('models/gemma-3-27b-it') # RPD 고려하여 gemma 3 27b 모델 사용
    
    prompt = f"""
    다음 뉴스 데이터를 바탕으로 오늘 가장 중요한 경제 소식 3가지를 요약해줘.
    - 각 소식은 한 줄로 작성할 것.
    - 이모지를 적절히 섞어서 친근하게 작성할 것.
    - 전체 리포트를 읽고 싶게 만드는 핵심 내용 위주로 작성할 것.
    - 한국어로 작성할 것.
    
    뉴스 데이터:
    {news_data}
    """
    
    response = model.generate_content(prompt)
    return response.text.strip()

# 텔레그램 전송 부분 수정
async def send_telegram_summary(summary_text, site_url):
    bot = Bot(token=TELEGRAM_TOKEN)
    
    # 요약문 상단에 배치
    message = (
        f"📅 <b>오늘의 경제 브리핑 ({datetime.now().strftime('%m/%d')})</b>\n\n"
        f"{summary_text}\n\n" # Gemini에게 3줄 요약을 별도로 요청해서 넣으면 베스트!
        f"🔗 <a href='{site_url}'>상세 분석 보고서 보기</a>"
    )
    
    await bot.send_message(
        chat_id=CHAT_ID, 
        text=message, 
        parse_mode='HTML' # 링크가 깔끔하게 걸리도록 설정
    )

# def post_to_github_issues(title, content):
#     gh_token = os.getenv("GH_TOKEN")
#     repo_name = "4610162/daily_news" # 예: 4610162/daily_news
    
#     if not gh_token:
#         print("⚠️ GitHub 토큰이 없어 이슈 게시를 건너뜁니다.")
#         return

#     g = Github(gh_token)
#     repo = g.get_repo(repo_name)
    
#     # 새로운 이슈 생성 (이것이 블로그 포스팅 역할을 함)
#     new_issue =repo.create_issue(title=title, body=content)
#     print(f"🚀 GitHub Issues에 보고서 게시 완료!")

#     # 생성된 이슈의 웹 주소(html_url)를 반환합니다.
#     return new_issue.html_url

async def main():
    try:
        # 1. 데이터 가져오기
        news_items, news_text_for_ai = get_news_content()
        full_analysis = get_gemini_summary(news_text_for_ai)
        telegram_brief = get_telegram_brief(news_text_for_ai)

        # 2. 날짜 및 제목 설정
        today_str = datetime.now().strftime("%Y-%m-%d")
        report_title = f"📑 데일리 경제 브리핑 ({today_str})"

        site_url, report_body = await create_and_save_report(news_items, full_analysis)
        
        # 3. 마크다운 본문(report_body) 내용 구성 (내용 구성 누락 수정)
        report_body = f"# {report_title}\n\n"
        report_body += "## 📰 주요 뉴스 헤드라인 (TOP 10)\n"
        for i, item in enumerate(news_items, 1):
            report_body += f"{i}. [{item['cat']}] [{item['title']}]({item['link']})\n"
        
        report_body += "\n---\n\n"
        report_body += "## 🤖 AI 분석 및 시장 전망\n"
        report_body += full_analysis

        # 4. GitHub Issues에 아카이빙 (웹페이지 역할)
        # issue_url = post_to_github_issues(report_title, report_body)

        # 5. 텔레그램 전송 (함수 내부에서 전송 로직 수행)
        # 만약 웹사이트가 아직 준비 안됐다면 issue_url을 사용하세요.
        final_url = site_url if site_url else issue_url

        bot = Bot(token=TELEGRAM_TOKEN)
        final_message = (
            f"🚀 *오늘의 경제 브리핑 ({today_str})*\n\n"
            f"{telegram_brief}\n\n"
            f"🔗 *상세 분석 보고서 보기:*\n{final_url}"
        )
        
        await bot.send_message(chat_id=CHAT_ID, text=final_message, parse_mode='HTML')
        print("✅ 텔레그램 전송 완료!")

    except Exception as e:
        print(f"❌ 오류 발생: {e}")

if __name__ == "__main__":
    asyncio.run(main())
