"""
News Summarizer — 수집된 기사를 Gemini로 요약하여 Telegram 포맷으로 반환합니다.

출력 포맷:
  [주제 요약]
  한 줄 요약

  핵심 포인트
  - point1
  - point2
  - point3

  Sources
  - 기사 제목 (출처)
"""

import os

import google.generativeai as genai

# 모델 우선순위: quota 절약을 위해 gemma 먼저, 실패 시 gemini-2.5-flash
_MODEL_PRIORITY = ["models/gemma-3-27b-it", "gemini-2.5-flash"]

_SUMMARY_PROMPT_TEMPLATE = """You are a financial news analyst. A user asked: "{query}"

Based on the following recent news articles, provide a concise summary in Korean (한국어).
Keep it brief and suitable for Telegram messaging (avoid excessive markdown).

News Articles:
{articles_text}

Respond EXACTLY in this format (no additional text before or after):

[주제 요약]
(한 줄 요약을 여기에 작성)

핵심 포인트
- (포인트1)
- (포인트2)
- (포인트3)

Sources
- (기사 제목) (출처)
- (기사 제목) (출처)
- (기사 제목) (출처)"""


def _build_articles_text(articles: list) -> str:
    lines = []
    for i, a in enumerate(articles, 1):
        lines.append(f"[{i}] {a['title']} ({a['source']}, {a['pub_date']})")
        if a.get("description"):
            lines.append(f"    {a['description']}")
        lines.append("")
    return "\n".join(lines)


def summarize_news(query: str, articles: list) -> str:
    """
    수집된 기사 목록을 기반으로 LLM 요약을 생성합니다.

    - articles가 비어 있으면 안내 메시지 반환
    - 모든 모델 실패 시 오류 메시지 반환
    """
    if not articles:
        return (
            "관련 뉴스를 찾지 못했습니다.\n"
            "다른 키워드로 다시 질문해주세요.\n\n"
            "예시:\n• NVIDIA 실적 최신 뉴스\n• 미국 금리 동향\n• 원유 가격 동향"
        )

    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        return "❌ API 키가 설정되지 않았습니다. 관리자에게 문의해주세요."

    genai.configure(api_key=api_key)

    articles_text = _build_articles_text(articles)
    prompt = _SUMMARY_PROMPT_TEMPLATE.format(
        query=query,
        articles_text=articles_text,
    )

    for model_name in _MODEL_PRIORITY:
        try:
            model = genai.GenerativeModel(model_name)
            response = model.generate_content(prompt)
            return response.text.strip()
        except Exception as e:
            error_msg = str(e)
            if "429" in error_msg or "404" in error_msg:
                print(f"[news_summarizer] {model_name} 실패 (quota/not found), 다음 모델 시도")
                continue
            print(f"[news_summarizer] {model_name} 예외: {e}")
            return f"❌ 요약 생성 중 오류가 발생했습니다. 잠시 후 다시 시도해주세요."

    return "❌ 현재 AI 서비스를 일시적으로 사용할 수 없습니다. 잠시 후 다시 시도해주세요."
