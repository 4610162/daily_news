"""
News Fetcher — RSS 피드 수집, relevance 스코어링, 중복 제거

처리 흐름:
  1. 각 RSS_SOURCES에서 최근 기사 수집 (stdlib: urllib + xml.etree.ElementTree)
  2. 사용자 질문 키워드 기반 relevance score 계산
  3. score 내림차순 정렬
  4. URL·제목 유사도 기반 중복 제거
  5. 상위 max_articles개 반환
"""

import re
import time
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime

from lib.rss_config import RSS_SOURCES

# 각 소스에서 가져올 최대 기사 수
_FEED_FETCH_LIMIT = 15

# relevance score 가중치
_TITLE_MATCH_WEIGHT = 3.0
_DESC_MATCH_WEIGHT = 1.0
_RECENCY_6H_BONUS = 2.0
_RECENCY_24H_BONUS = 1.0

# 중복 제거: 제목 단어 겹침 임계값
_DEDUP_WORD_OVERLAP_THRESHOLD = 0.6

# 질문 파싱 시 제거할 불용어
_STOPWORDS = {
    # 한국어
    "뉴스", "최신", "동향", "알려줘", "알려", "뭐야", "무엇", "어때",
    "궁금해", "어떻게", "되고", "있어", "있나요", "인가요", "해줘",
    "관련", "대해", "대한", "관해",
    # 영어
    "the", "a", "an", "is", "are", "was", "were", "what", "how",
    "tell", "me", "about", "latest", "recent", "news", "update",
    "any", "some", "please", "can", "you",
}

_ATOM_NS = "http://www.w3.org/2005/Atom"
_DC_NS = "http://purl.org/dc/elements/1.1/"


# ── Minimal stdlib RSS/Atom parser ───────────────────────────────────────────

def _parse_date(date_str: str) -> float:
    """RFC 2822(RSS) 또는 ISO 8601(Atom) 날짜 문자열을 UNIX timestamp로 변환."""
    if not date_str:
        return time.time()
    try:
        return parsedate_to_datetime(date_str.strip()).timestamp()
    except Exception:
        pass
    try:
        s = date_str.strip().rstrip("Z")
        if "+" in s:
            s = s.split("+")[0]
        return datetime.fromisoformat(s).replace(tzinfo=timezone.utc).timestamp()
    except Exception:
        return time.time()


def _text(el) -> str:
    return (el.text or "").strip() if el is not None else ""


def _parse_feed(url: str) -> list:
    """URL에서 RSS/Atom 피드를 가져와 entry dict 목록으로 반환."""
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            content = resp.read()
        root = ET.fromstring(content)
    except Exception as e:
        print(f"[news_fetcher] 피드 파싱 실패 ({url}): {e}")
        return []

    entries = []

    # Atom feed
    if root.tag == f"{{{_ATOM_NS}}}feed" or root.tag.endswith("}feed"):
        ns = _ATOM_NS if root.tag == f"{{{_ATOM_NS}}}feed" else root.tag[1:root.tag.index("}")]
        for item in root.findall(f"{{{ns}}}entry"):
            link_el = item.find(f"{{{ns}}}link")
            link = link_el.get("href", "").strip() if link_el is not None else ""
            date_el = item.find(f"{{{ns}}}updated") or item.find(f"{{{ns}}}published")
            summary_el = item.find(f"{{{ns}}}summary") or item.find(f"{{{ns}}}content")
            entries.append({
                "title": _text(item.find(f"{{{ns}}}title")),
                "link": link,
                "summary": _text(summary_el),
                "pub_ts": _parse_date(_text(date_el)),
            })

    # RSS 2.0 / RSS 1.0
    else:
        channel = root.find("channel") or root
        for item in (channel.findall("item") or root.findall("item")):
            pub_el = item.find("pubDate") or item.find(f"{{{_DC_NS}}}date")
            entries.append({
                "title": _text(item.find("title")),
                "link": _text(item.find("link")),
                "summary": _text(item.find("description")),
                "pub_ts": _parse_date(_text(pub_el)),
            })

    return entries


# ── 내부 유틸리티 ─────────────────────────────────────────────────────────────

def _parse_pub_timestamp(entry: dict) -> float:
    return entry.get("pub_ts", time.time())


def _strip_html(text: str) -> str:
    """HTML 태그 제거."""
    return re.sub(r"<[^>]+>", "", text).strip()


def _extract_keywords(query: str) -> list:
    """
    사용자 질문에서 검색 키워드 추출.
    불용어와 1자 이하 단어를 제거합니다.
    """
    words = re.findall(r"[가-힣A-Za-z0-9]+", query)
    return [w for w in words if w.lower() not in _STOPWORDS and len(w) > 1]


def _score_article(title: str, description: str, pub_ts: float, keywords: list) -> float:
    """
    기사의 relevance score를 계산합니다.

    - 제목에 키워드 포함: +3.0 per keyword
    - 설명에 키워드 포함: +1.0 per keyword
    - 6시간 이내 기사:   +2.0 (recency bonus)
    - 24시간 이내 기사:  +1.0 (recency bonus)
    """
    score = 0.0
    title_lower = title.lower()
    desc_lower = description.lower()

    for kw in keywords:
        kw_lower = kw.lower()
        if kw_lower in title_lower:
            score += _TITLE_MATCH_WEIGHT
        if kw_lower in desc_lower:
            score += _DESC_MATCH_WEIGHT

    age_hours = (time.time() - pub_ts) / 3600
    if age_hours < 6:
        score += _RECENCY_6H_BONUS
    elif age_hours < 24:
        score += _RECENCY_24H_BONUS

    return score


def _is_duplicate(article: dict, seen: list) -> bool:
    """
    이미 선택된 기사 목록(seen)과 비교하여 중복 여부를 판단합니다.

    판단 기준:
      1. URL 완전 일치 (query string 제거 후 비교)
      2. 제목 substring 포함 관계
      3. 제목 단어 겹침 비율 ≥ 60%
    """
    url = article.get("link", "").split("?")[0]
    title = article.get("title", "").lower()

    for s in seen:
        # 1. URL 중복
        if url and url == s.get("url", ""):
            return True

        seen_title = s.get("title", "").lower()
        if not title or not seen_title:
            continue

        # 2. 제목 substring 포함
        if title in seen_title or seen_title in title:
            return True

        # 3. 단어 겹침 비율
        title_words = set(title.split())
        seen_words = set(seen_title.split())
        if title_words and seen_words:
            overlap = len(title_words & seen_words) / min(len(title_words), len(seen_words))
            if overlap >= _DEDUP_WORD_OVERLAP_THRESHOLD:
                return True

    return False


# ── Public API ────────────────────────────────────────────────────────────────

def fetch_news(query: str, max_articles: int = 5) -> list:
    """
    RSS 피드에서 뉴스를 수집하고, 관련도 스코어링 및 중복 제거 후
    상위 max_articles개의 기사를 반환합니다.

    반환값: [
        {
            "title": str,
            "link": str,
            "description": str,   # HTML 태그 제거, 최대 400자
            "pub_date": str,       # "YYYY-MM-DD HH:MM"
            "source": str,         # RSS_SOURCES[*]["name"]
            "score": float,
        },
        ...
    ]
    """
    keywords = _extract_keywords(query)
    if not keywords:
        # fallback: 질문 전체를 단어 단위로 분리해서 처음 3개 사용
        keywords = query.split()[:3]

    all_articles = []

    for source in RSS_SOURCES:
        try:
            feed_entries = _parse_feed(source["url"])
            for entry in feed_entries[:_FEED_FETCH_LIMIT]:
                title = entry.get("title", "").strip()
                link = entry.get("link", "").strip()
                raw_desc = entry.get("summary", "")
                description = _strip_html(raw_desc)[:400]
                pub_ts = _parse_pub_timestamp(entry)
                pub_date = datetime.fromtimestamp(pub_ts).strftime("%Y-%m-%d %H:%M")

                score = _score_article(title, description, pub_ts, keywords)

                all_articles.append(
                    {
                        "title": title,
                        "link": link,
                        "description": description,
                        "pub_date": pub_date,
                        "source": source["name"],
                        "score": score,
                        "_pub_ts": pub_ts,  # 정렬용, 외부 노출 안 함
                    }
                )
        except Exception as e:
            print(f"[news_fetcher] {source['name']} 수집 실패: {e}")
            continue

    # score 내림차순 정렬
    all_articles.sort(key=lambda x: x["score"], reverse=True)

    # 중복 제거 후 상위 max_articles개 선택
    seen: list = []
    unique_articles: list = []

    for article in all_articles:
        if not _is_duplicate(article, seen):
            unique_articles.append(
                {
                    "title": article["title"],
                    "link": article["link"],
                    "description": article["description"],
                    "pub_date": article["pub_date"],
                    "source": article["source"],
                    "score": article["score"],
                }
            )
            seen.append(
                {
                    "url": article["link"].split("?")[0],
                    "title": article["title"].lower(),
                }
            )
        if len(unique_articles) >= max_articles:
            break

    return unique_articles
