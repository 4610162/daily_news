"""
Intent Filter — 사용자 메시지가 뉴스/시장 동향 질문인지 판단합니다.

처리 순서:
  Stage 1: Keyword pre-filter  (빠름, LLM 호출 없음)
  Stage 2: Pattern-based OTHER 조기 거절 (LLM 호출 없음)
  Stage 3: LLM classifier       (Stage 1·2에서 판단 불가한 경우에만)

반환값: 'NEWS' | 'OTHER'
"""

import os
import re

# ── Stage 1: 뉴스 관련 키워드 목록 ────────────────────────────────────────────
NEWS_KEYWORDS = [
    # 한국어
    "뉴스", "동향", "최신", "시장", "금리", "주가", "주식", "경제", "환율",
    "인플레이션", "기업", "실적", "반도체", "채권", "금리차", "달러",
    "원화", "코스피", "코스닥", "나스닥", "다우", "S&P", "유가", "원유",
    "금", "암호화폐", "비트코인", "이더리움", "연준", "기준금리",
    "GDP", "CPI", "PPI", "무역", "관세", "수출", "수입", "경기침체",
    "기술주", "성장주", "배당", "IPO", "상장", "인수합병", "M&A",
    # 기업명 (한국어)
    "엔비디아", "테슬라", "애플", "구글", "아마존", "메타", "마이크로소프트",
    "삼성", "하이닉스", "TSMC", "인텔", "퀄컴", "ARM",
    # 영어
    "news", "market", "stock", "rate", "economy", "economic", "inflation",
    "fed", "federal", "reserve", "earnings", "revenue", "profit", "gdp",
    "nasdaq", "dow", "s&p", "crypto", "bitcoin", "ethereum", "oil", "gold",
    "nvidia", "tesla", "apple", "google", "amazon", "meta", "microsoft",
    "china", "trade", "tariff", "recession", "cpi", "ppi", "interest",
    "bond", "yield", "dollar", "currency", "forex", "ipo", "merger",
    "acquisition", "semiconductor", "chip", "ai", "tech",
]

# ── Stage 2: 명확한 비뉴스 패턴 (LLM 없이 즉시 거절) ──────────────────────────
_NON_NEWS_PATTERNS = [
    r"^(안녕|안녕하세요|hello|hi\b|hey\b|ㅎㅇ|ㅎㅇ요)",
    r"(농담|개그|joke|웃긴|재밌|레시피|recipe|요리|맛있)",
    r"(날씨|weather|기온|비|눈|맑음)",
    r"(사랑해|좋아해|싫어|hate|love you)",
    r"(번역해|translate|영어로|한국어로)",
    r"(코드|프로그래밍|파이썬|python|javascript|java\b|html|css)",
]

_non_news_re = [re.compile(p, re.IGNORECASE) for p in _NON_NEWS_PATTERNS]


def _keyword_match(text: str) -> bool:
    text_lower = text.lower()
    return any(kw.lower() in text_lower for kw in NEWS_KEYWORDS)


def _is_obvious_non_news(text: str) -> bool:
    for pattern in _non_news_re:
        if pattern.search(text):
            return True
    return False


def _llm_classify(text: str) -> str:
    """
    불명확한 경우에만 호출되는 경량 LLM 분류기.
    quota 절약을 위해 gemma-3-27b-it 사용.
    반환값: 'NEWS' | 'OTHER'
    """
    try:
        import google.generativeai as genai

        api_key = os.getenv("GEMINI_API_KEY")
        if not api_key:
            return "NEWS"  # API 키 없으면 NEWS로 허용 (false negative 방지)

        genai.configure(api_key=api_key)
        model = genai.GenerativeModel("models/gemma-3-27b-it")

        prompt = (
            "Classify the following user message as NEWS or OTHER.\n\n"
            "NEWS: questions about financial news, market trends, stock prices, "
            "economic indicators, company performance, crypto, commodities, "
            "interest rates, or any request for recent market/financial information.\n"
            "OTHER: greetings, personal questions, general knowledge, jokes, "
            "cooking, weather, programming help, or anything unrelated to "
            "financial/economic news.\n\n"
            "Respond with ONLY one word: NEWS or OTHER.\n\n"
            f"Message: {text}"
        )

        response = model.generate_content(prompt)
        result = response.text.strip().upper()
        return "NEWS" if "NEWS" in result else "OTHER"

    except Exception as e:
        print(f"[intent_filter] LLM 분류 실패, NEWS로 기본처리: {e}")
        return "NEWS"  # 분류 실패 시 NEWS로 허용 (서비스 가용성 우선)


def classify_intent(text: str) -> str:
    """
    사용자 메시지의 intent를 분류합니다.

    Stage 1: 뉴스 키워드가 포함되어 있으면 → 즉시 NEWS 반환 (LLM 호출 없음)
    Stage 2: 명확한 비뉴스 패턴이면 → 즉시 OTHER 반환 (LLM 호출 없음)
    Stage 3: 판단 불가 → LLM classifier 호출

    반환값: 'NEWS' | 'OTHER'
    """
    text = text.strip()

    if _keyword_match(text):
        return "NEWS"

    if _is_obvious_non_news(text):
        return "OTHER"

    return _llm_classify(text)
