import os
import feedparser
import google.generativeai as genai
import asyncio
from telegram import Bot
from datetime import datetime
from dotenv import load_dotenv
from github import Github
# 새로운 지표 모듈 임포트
from indicators import get_indicators_data, format_to_markdown
import toml

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

async def create_and_save_report(news_items, indicators_md, analysis):
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
    md_content += f"{indicators_md}\n"

    md_content += "\n---\n\n"
    md_content += "## 🤖 AI 분석 및 시장 전망\n"
    md_content += analysis
    
    # 2. 로컬에 파일 저장
    with open(file_path, "w", encoding="utf-8") as f:
        f.write(md_content)
    
    # 웹사이트 URL 반환 (사용자 계정/레포 이름에 맞춰 설정)
    site_url = f"https://4610162.github.io/daily_news/reports/{today_str}.html"
    return site_url

# 텔레그램 상단에 노출할 3줄 핵심 요약 생성
def get_telegram_brief(news_data):
    if not GEMINI_API_KEY:
        raise ValueError("GEMINI_API_KEY가 설정되지 않았습니다.")
        
    genai.configure(api_key=GEMINI_API_KEY)
    model = genai.GenerativeModel('models/gemma-3-27b-it') # RPD 고려하여 gemma 3 27b 모델 사용
    
    prompt = f"""
    다음 뉴스 데이터를 바탕으로 오늘 가장 중요한 경제 소식 3가지를 요약해줘.
    - 각 소식을 넘버링해서 한 줄로 작성할 것.
    - 이모지를 적절히 섞어서 친근하게 작성할 것.
    - 전체 리포트를 읽고 싶게 만드는 핵심 내용 위주로 작성할 것.
    - 한국어로 작성할 것.
    
    뉴스 데이터:
    {news_data}
    """
    
    response = model.generate_content(prompt)
    return response.text.strip()

def update_zensical_nav(report_date):
    """
    zensical.toml의 nav 섹션에 새로운 리포트를 최신순으로 추가합니다.
    """
    toml_path = "zensical.toml"
    
    if not os.path.exists(toml_path):
        print(f"⚠️ {toml_path} 파일을 찾을 수 없습니다.")
        return

    try:
        # 1. TOML 파일 로드
        with open(toml_path, "r", encoding="utf-8") as f:
            config = toml.load(f)

        # 2. 새로운 항목 생성 (예: {"2026-03-03": "reports/2026-03-03.md"})
        new_entry = {report_date: f"reports/{report_date}.md"}
        
        nav_updated = False
        
        # 3. nav 리스트 내부에서 'Daily Reports' 키를 가진 딕셔너리 탐색
        if 'nav' in config and isinstance(config['nav'], list):
            for item in config['nav']:
                if isinstance(item, dict) and "Daily Reports" in item:
                    reports_list = item["Daily Reports"]
                    
                    # 중복 확인: 이미 해당 날짜 항목이 있는지 체크
                    if not any(report_date in r for r in reports_list):
                        # 최신 리포트가 맨 위로 오도록 0번 인덱스에 삽입
                        reports_list.insert(0, new_entry)
                        nav_updated = True
                    break
        
        # 4. 변경사항이 있을 때만 파일 저장
        if nav_updated:
            with open(toml_path, "w", encoding="utf-8") as f:
                toml.dump(config, f)
            print(f"✅ zensical.toml 업데이트 완료: {report_date}")
        else:
            print(f"ℹ️ {report_date} 항목이 이미 존재하거나 구조를 찾을 수 없어 업데이트를 건너뜁니다.")

    except Exception as e:
        print(f"❌ zensical.toml 수정 중 오류 발생: {e}")

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
        print("🚀 데이터 수집 시작...")
        # 1. 데이터 수집 (뉴스 + 경제 지표)
        news_items, news_text_for_ai = get_news_content()
        indicators_raw = get_indicators_data()   # 추가
        indicators_md = format_to_markdown(indicators_raw)  # 추가
        full_analysis = get_gemini_summary(news_text_for_ai)
        telegram_brief = get_telegram_brief(news_text_for_ai)

        # 2. 날짜 및 제목 설정
        
        # report_title = f"📑 데일리 경제 브리핑 ({today_str})"

        # 4. 리포트 생성 (Markdown 저장)
        today_str = datetime.now().strftime("%Y-%m-%d") # 날짜 변수 확보
        site_url = await create_and_save_report(news_items, indicators_md, full_analysis)
        
        # 4.5 내비게이션 업데이트 (목록에 오늘 리포트 추가)
        update_zensical_nav(today_str)

        print("🌐 Zensical 웹사이트 배포 중...")
        # 파이썬 내부 라이브러리를 통해 cli 기능을 직접 호출 (가장 에러 없는 방식)
        deploy_command = "python -c \"import sys; from zensical.cli import cli; sys.argv=['zensical', 'deploy', '--force']; cli(obj={})\""
        exit_code = os.system(deploy_command)

        if exit_code == 0:
            print("✅ 웹사이트 배포 성공!")
        else:
            print("⚠️ 배포 중 문제가 발생했지만, 일단 진행합니다.")

        print("📱 텔레그램 메시지 구성 중...")
        bot = Bot(token=TELEGRAM_TOKEN)

        safe_brief = telegram_brief.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
        # HTML 모드에 최적화된 메시지 구성
        final_message = (
            f"🚀 <b>오늘의 경제 브리핑 ({today_str})</b>\n\n"
            f"{safe_brief}\n\n"
            f"🔗 <a href='{site_url}'>상세 분석 보고서 보기</a>"
        )
        
        await bot.send_message(chat_id=CHAT_ID, text=final_message, parse_mode='HTML')
        print("✅ 텔레그램 전송 완료!")

    except Exception as e:
        print(f"❌ 오류 발생: {e}")

if __name__ == "__main__":
    asyncio.run(main())
