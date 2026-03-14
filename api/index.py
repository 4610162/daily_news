"""
Telegram Webhook Handler — Vercel Serverless Function

엔드포인트: POST /api/webhook  (vercel.json routing 참조)

처리 흐름:
  1. Telegram Update JSON 파싱
  2. 메시지 텍스트 추출
  3. Intent 분류 (lib.intent_filter)
     - OTHER → 안내 메시지 반환
     - NEWS  → RSS 수집 → 요약 → Telegram 응답
  4. Telegram에 항상 HTTP 200 반환 (재전송 방지)

기존 main.py / indicators.py / GitHub Actions 파이프라인과 완전히 독립적입니다.
"""

import json
import os
import sys
import urllib.request
from http.server import BaseHTTPRequestHandler

# Vercel 환경에서 프로젝트 루트(lib/)를 import path에 추가
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from lib.intent_filter import classify_intent
from lib.news_fetcher import fetch_news
from lib.news_summarizer import summarize_news

# ── 설정 ──────────────────────────────────────────────────────────────────────

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")

NOT_NEWS_MESSAGE = (
    "이 봇은 최신 뉴스 동향 분석만 제공합니다.\n\n"
    "예시 질문:\n"
    "• AI 반도체 최신 뉴스\n"
    "• 미국 금리 최근 동향\n"
    "• 엔비디아 관련 최신 뉴스\n"
    "• 원유 가격 동향"
)

START_MESSAGE = (
    "안녕하세요! 뉴스 동향 분석 봇입니다.\n\n"
    "궁금한 뉴스 주제를 입력해주세요.\n\n"
    "예시 질문:\n"
    "• AI 반도체 최신 뉴스\n"
    "• 미국 금리 최근 동향\n"
    "• 엔비디아 관련 최신 뉴스"
)


# ── Telegram API 전송 (표준 라이브러리만 사용, 의존성 최소화) ─────────────────

def _send_telegram_message(chat_id: int, text: str) -> None:
    """Telegram Bot API sendMessage 호출 (동기, urllib 사용)."""
    if not TELEGRAM_TOKEN:
        print("[webhook] TELEGRAM_TOKEN이 설정되지 않았습니다.")
        return

    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = json.dumps({"chat_id": chat_id, "text": text}).encode("utf-8")

    req = urllib.request.Request(
        url,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            resp.read()
    except Exception as e:
        print(f"[webhook] Telegram 전송 실패: {e}")


# ── 메시지 처리 파이프라인 ────────────────────────────────────────────────────

def _process_message(text: str, chat_id: int) -> None:
    """
    Intent 분류 → RSS 수집 → LLM 요약 → Telegram 응답 파이프라인.
    """
    # Stage 1: Intent 분류
    intent = classify_intent(text)
    print(f"[webhook] intent={intent!r} query={text!r}")

    if intent != "NEWS":
        _send_telegram_message(chat_id, NOT_NEWS_MESSAGE)
        return

    # Stage 2: RSS 뉴스 수집 (relevance scoring + deduplication 포함)
    articles = fetch_news(text, max_articles=5)
    print(f"[webhook] 수집된 기사 수: {len(articles)}")

    # Stage 3: LLM 요약
    summary = summarize_news(text, articles)

    # Stage 4: Telegram 응답
    _send_telegram_message(chat_id, summary)


# ── Vercel Python Serverless Handler ─────────────────────────────────────────

class handler(BaseHTTPRequestHandler):
    """
    Vercel Python serverless function entry point.
    클래스명 'handler'는 Vercel 런타임 규약입니다.
    """

    def do_POST(self) -> None:
        try:
            content_length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(content_length)
            update = json.loads(body)

            # Telegram은 message 또는 edited_message를 보냄
            message = update.get("message") or update.get("edited_message")
            if not message:
                self._respond(200, {"ok": True})
                return

            text = message.get("text", "").strip()
            chat_id = message.get("chat", {}).get("id")

            if not text or not chat_id:
                self._respond(200, {"ok": True})
                return

            # /start 명령어 처리
            if text == "/start":
                _send_telegram_message(chat_id, START_MESSAGE)
                self._respond(200, {"ok": True})
                return

            # 다른 봇 명령어 무시
            if text.startswith("/"):
                self._respond(200, {"ok": True})
                return

            # 일반 메시지 처리
            _process_message(text, chat_id)
            self._respond(200, {"ok": True})

        except Exception as e:
            print(f"[webhook] 처리 중 예외: {e}")
            # Telegram에는 항상 200 반환 (재전송 루프 방지)
            self._respond(200, {"ok": True})

    def do_GET(self) -> None:
        """헬스체크용 GET 엔드포인트."""
        self._respond(200, {"status": "ok", "message": "Telegram webhook is running"})

    def _respond(self, status: int, body: dict) -> None:
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(body).encode("utf-8"))

    def log_message(self, format, *args) -> None:
        # BaseHTTPRequestHandler의 stdout 로그 억제 (Vercel 로그와 충돌 방지)
        pass
