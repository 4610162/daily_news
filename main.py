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
    
    # 모델 우선순위 설정: 1순위 Gemini(고성능/20회), 2순위 Gemma(무제한급)
    model_priority = ['models/gemma-3-27b-it', 'gemini-2.5-flash']
    
    prompt = f"""
    너는 금융 전문 애널리스트야. 아래 뉴스 데이터를 분석해서 마크다운 형식으로 보고서를 작성해줘.
    
    [포함 내용]
    1. 🎯 오늘의 시장 핵심 키워드 (3개)
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

async def create_and_send_md_report(news_items, analysis, issue_url=None):
    today_str = datetime.now().strftime("%Y-%m-%d")
    file_name = f"Economic_Report_{today_str}.md"
    
    # 1. 마크다운 내용 구성
    md_content = f"# 📑 데일리 경제 브리핑 보고서 ({today_str})\n\n"
    md_content += "## 📰 주요 뉴스 헤드라인 (TOP 10)\n"
    for i, item in enumerate(news_items, 1):
        md_content += f"{i}. [{item['cat']}] [{item['title']}]({item['link']})\n"
    
    md_content += "\n---\n\n"
    md_content += "## 🤖 AI 분석 및 시장 전망\n"
    md_content += analysis
    
    # 2. 로컬에 파일 저장
    with open(file_name, "w", encoding="utf-8") as f:
        f.write(md_content)
    
    # 3. 텔레그램 캡션 구성 (링크가 있으면 추가)
    caption_text = f"📅 {today_str} 경제 브리핑 보고서가 발간되었습니다."
    if issue_url:
        caption_text += f"\n\n🌐 웹에서 보기(아카이브):\n{issue_url}"
    
    # 4. 텔레그램 전송 (한 번만 수행)
    bot = Bot(token=TELEGRAM_TOKEN)
    try:
        with open(file_name, "rb") as f:
            await bot.send_document(
                chat_id=CHAT_ID, 
                document=f, 
                caption=caption_text
            )
        print("✅ 텔레그램 보고서 전송 완료!")
    except Exception as e:
        print(f"❌ 텔레그램 전송 중 에러: {e}")
    
    return file_name

def post_to_github_issues(title, content):
    gh_token = os.getenv("GH_TOKEN")
    repo_name = "4610162/daily_news" # 예: 4610162/daily_news
    
    if not gh_token:
        print("⚠️ GitHub 토큰이 없어 이슈 게시를 건너뜁니다.")
        return

    g = Github(gh_token)
    repo = g.get_repo(repo_name)
    
    # 새로운 이슈 생성 (이것이 블로그 포스팅 역할을 함)
    repo.create_issue(title=title, body=content)
    print(f"🚀 GitHub Issues에 보고서 게시 완료!")

    # 생성된 이슈의 웹 주소(html_url)를 반환합니다.
    return new_issue.html_url

async def main():
    try:
        # 1. 데이터 가져오기
        news_items, news_text_for_ai = get_news_content()
        analysis = get_gemini_summary(news_text_for_ai)

        # 2. 날짜 및 제목 설정
        today_str = datetime.now().strftime("%Y-%m-%d")
        report_title = f"📑 데일리 경제 브리핑 ({today_str})"
        
        # 3. 마크다운 본문(report_body) 내용 구성 (내용 구성 누락 수정)
        report_body = f"# {report_title}\n\n"
        report_body += "## 📰 주요 뉴스 헤드라인 (TOP 10)\n"
        for i, item in enumerate(news_items, 1):
            report_body += f"{i}. [{item['cat']}] [{item['title']}]({item['link']})\n"
        
        report_body += "\n---\n\n"
        report_body += "## 🤖 AI 분석 및 시장 전망\n"
        report_body += analysis

        # 4. GitHub Issues에 아카이빙 (웹페이지 역할)
        issue_url = post_to_github_issues(report_title, report_body)

        # 5. 텔레그램 전송 (함수 내부에서 전송 로직 수행)
        await create_and_send_md_report(news_items, analysis, issue_url)
        print("✅ 모든 작업 완료!")

    except Exception as e:
        # except 문도 try와 들여쓰기가 맞아야 합니다.
        print(f"❌ 에러 발생: {e}")

if __name__ == "__main__":
    asyncio.run(main())
    