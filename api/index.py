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
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler

# Vercel 환경에서 프로젝트 루트(lib/)를 import path에 추가
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from lib.intent_filter import classify_intent
from lib.news_fetcher import fetch_news
from lib.news_summarizer import summarize_news

# ── 설정 ──────────────────────────────────────────────────────────────────────

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
UPSTASH_REDIS_REST_URL = os.getenv("UPSTASH_REDIS_REST_URL", "").rstrip("/")
UPSTASH_REDIS_REST_TOKEN = os.getenv("UPSTASH_REDIS_REST_TOKEN", "")
ADMIN_IDS = {
    int(value.strip())
    for value in os.getenv("TELEGRAM_ADMIN_IDS", "").split(",")
    if value.strip()
}

APPROVED_USERS_KEY = "tg:approved_users"
PENDING_USERS_KEY = "tg:pending_users"

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

PENDING_MESSAGE = (
    "현재 이 봇은 승인된 사용자만 이용할 수 있습니다.\n"
    "관리자에게 승인 요청을 전달했습니다."
)

REDIS_NOT_CONFIGURED_MESSAGE = (
    "현재 승인 시스템 설정이 완료되지 않아 요청을 처리할 수 없습니다.\n"
    "관리자에게 문의해주세요."
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


# ── Redis / 승인 관리 ─────────────────────────────────────────────────────────

def _redis_is_configured() -> bool:
    return bool(UPSTASH_REDIS_REST_URL and UPSTASH_REDIS_REST_TOKEN)


def _redis_request(command: str, *args: object) -> object | None:
    if not _redis_is_configured():
        print("[webhook] Upstash Redis 설정이 없습니다.")
        return None

    encoded_parts = [urllib.parse.quote(str(part), safe="") for part in (command, *args)]
    url = f"{UPSTASH_REDIS_REST_URL}/{'/'.join(encoded_parts)}"
    req = urllib.request.Request(
        url,
        headers={"Authorization": f"Bearer {UPSTASH_REDIS_REST_TOKEN}"},
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
    except Exception as e:
        print(f"[webhook] Redis 요청 실패 ({command}): {e}")
        return None

    if payload.get("error"):
        print(f"[webhook] Redis 오류 ({command}): {payload['error']}")
        return None

    return payload.get("result")


def _is_admin(user_id: int) -> bool:
    return user_id in ADMIN_IDS


def _is_approved_user(user_id: int) -> bool:
    if _is_admin(user_id):
        return True

    result = _redis_request("SISMEMBER", APPROVED_USERS_KEY, user_id)
    return bool(result == 1)


def _add_pending_user(user_id: int) -> bool:
    result = _redis_request("SADD", PENDING_USERS_KEY, user_id)
    return bool(result == 1)


def _remove_pending_user(user_id: int) -> None:
    _redis_request("SREM", PENDING_USERS_KEY, user_id)


def _approve_user(user_id: int) -> bool:
    added = _redis_request("SADD", APPROVED_USERS_KEY, user_id)
    if added is None:
        return False

    _remove_pending_user(user_id)
    return True


def _reject_user(user_id: int) -> bool:
    result = _redis_request("SREM", PENDING_USERS_KEY, user_id)
    return result is not None


def _get_pending_users() -> list[str] | None:
    result = _redis_request("SMEMBERS", PENDING_USERS_KEY)
    if result is None:
        return None
    return [str(user_id) for user_id in result]


def _notify_admins_new_request(user_id: int, username: str, first_name: str, text: str) -> None:
    display_name = first_name or "(이름 없음)"
    username_text = f"@{username}" if username else "(username 없음)"
    message = (
        "승인 요청이 도착했습니다.\n\n"
        f"이름: {display_name}\n"
        f"사용자명: {username_text}\n"
        f"user_id: {user_id}\n"
        f"첫 메시지: {text}\n\n"
        f"승인: /approve {user_id}\n"
        f"거절: /reject {user_id}"
    )

    for admin_id in ADMIN_IDS:
        _send_telegram_message(admin_id, message)


def _parse_target_user_id(command_text: str) -> int | None:
    parts = command_text.split(maxsplit=1)
    if len(parts) != 2:
        return None

    try:
        return int(parts[1].strip())
    except ValueError:
        return None


def _handle_admin_command(text: str, chat_id: int, user_id: int) -> bool:
    if not text.startswith("/"):
        return False

    command = text.split(maxsplit=1)[0].lower()
    if command not in {"/approve", "/reject", "/pending"}:
        return False

    if not _is_admin(user_id):
        _send_telegram_message(chat_id, "관리자만 사용할 수 있는 명령입니다.")
        return True

    if not _redis_is_configured():
        _send_telegram_message(chat_id, REDIS_NOT_CONFIGURED_MESSAGE)
        return True

    if command == "/pending":
        pending_users = _get_pending_users()
        if pending_users is None:
            _send_telegram_message(chat_id, "대기 목록을 불러오지 못했습니다.")
            return True

        if not pending_users:
            _send_telegram_message(chat_id, "현재 승인 대기 중인 사용자가 없습니다.")
            return True

        pending_text = "\n".join(f"- {pending_user_id}" for pending_user_id in sorted(pending_users))
        _send_telegram_message(chat_id, f"승인 대기 목록:\n{pending_text}")
        return True

    target_user_id = _parse_target_user_id(text)
    if target_user_id is None:
        usage = "/approve <user_id>" if command == "/approve" else "/reject <user_id>"
        _send_telegram_message(chat_id, f"사용법: {usage}")
        return True

    if command == "/approve":
        if not _approve_user(target_user_id):
            _send_telegram_message(chat_id, "사용자 승인 처리 중 오류가 발생했습니다.")
            return True

        _send_telegram_message(chat_id, f"{target_user_id} 사용자를 승인했습니다.")
        _send_telegram_message(
            target_user_id,
            "관리자 승인이 완료되었습니다. 이제 뉴스 질의를 보낼 수 있습니다.",
        )
        return True

    if not _reject_user(target_user_id):
        _send_telegram_message(chat_id, "사용자 거절 처리 중 오류가 발생했습니다.")
        return True

    _send_telegram_message(chat_id, f"{target_user_id} 사용자를 승인 대기 목록에서 제거했습니다.")
    _send_telegram_message(
        target_user_id,
        "관리자 승인 대상에서 제외되었습니다. 필요하면 다시 문의해주세요.",
    )
    return True


def _handle_unapproved_user(
    chat_id: int,
    user_id: int,
    username: str,
    first_name: str,
    text: str,
) -> None:
    if not _redis_is_configured():
        _send_telegram_message(chat_id, REDIS_NOT_CONFIGURED_MESSAGE)
        return

    is_new_pending = _add_pending_user(user_id)
    if is_new_pending:
        _notify_admins_new_request(user_id, username, first_name, text)

    _send_telegram_message(chat_id, PENDING_MESSAGE)


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
            user = message.get("from") or {}
            user_id = user.get("id")
            username = user.get("username", "")
            first_name = user.get("first_name", "")

            if not text or not chat_id or not user_id:
                self._respond(200, {"ok": True})
                return

            if _handle_admin_command(text, chat_id, user_id):
                self._respond(200, {"ok": True})
                return

            # /start 명령어 처리
            if text == "/start":
                if _is_approved_user(user_id):
                    _send_telegram_message(chat_id, START_MESSAGE)
                else:
                    _handle_unapproved_user(chat_id, user_id, username, first_name, text)
                self._respond(200, {"ok": True})
                return

            # 다른 봇 명령어 무시
            if text.startswith("/"):
                self._respond(200, {"ok": True})
                return

            if not _is_approved_user(user_id):
                _handle_unapproved_user(chat_id, user_id, username, first_name, text)
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
