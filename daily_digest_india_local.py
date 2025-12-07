# daily_digest_all_in_one.py
"""
All-in-one India-only daily news digest.

Usage:
  - save file, install requirements, set env vars (examples below), then run:
      python daily_digest_all_in_one.py

Environment variables (all optional; sensible defaults provided):
  FEED_URLS            - comma-separated RSS feed URLs (overrides built-in list)
  ALLOW_DOMAINS         - comma-separated domain allow-list (defaults included)
  INCLUDE_KEYWORDS      - comma-separated keywords (article must match at least one if set)
  EXCLUDE_KEYWORDS      - comma-separated keywords to drop articles containing them
  MAX_ITEMS             - how many articles to include in each digest (default 10)
  MAX_PER_FEED          - how many recent entries to read per feed (default 25)
  MIN_ARTICLE_LENGTH    - minimum chars of article text (or summary) to accept (default 150)
  DRY_RUN               - "true" or "false" (default "true") -- if true prints email body instead of sending
  GOOGLE_API_KEY        - set to use Gemini for summarization (optional)
  SENDER_EMAIL          - gmail address to send from (required if DRY_RUN=false)
  RECEIVER_EMAIL        - recipient email (required if DRY_RUN=false)
  APP_PASSWORD          - Gmail App Password (required if DRY_RUN=false)
  PERSIST_SENT          - "true" or "false" whether to persist sent urls in sent.json (default true)

Notes:
- For Gmail SMTP: create an App Password (if account uses 2FA) and use it as APP_PASSWORD.
- This script uses a light fallback summarizer (first 3 sentences) if GOOGLE_API_KEY or Gemini is not available.
"""

import os
import time
import json
import re
from datetime import datetime
from urllib.parse import urlparse
from typing import Optional, List, Set, Tuple

import feedparser
import requests
from bs4 import BeautifulSoup

# Try import Gemini client; if not present we fallback
try:
    import google.generativeai as genai
    GEMINI_AVAILABLE = True
except Exception:
    GEMINI_AVAILABLE = False

import smtplib
from email.message import EmailMessage

# -------------------- Defaults --------------------
DEFAULT_FEEDS = [
    "https://timesofindia.indiatimes.com/rssfeedstopstories.cms",
    "https://www.thehindu.com/news/national/feeder/default.rss",
    "https://www.hindustantimes.com/rss/topnews/rssfeed.xml",
    "https://indianexpress.com/section/india/feed/",
    "https://feeds.feedburner.com/ndtvnews-top-stories",
    "https://www.indiatoday.in/rss/home",
]

# Default allowlist of Indian domains (used when ALLOW_DOMAINS not set)
DEFAULT_ALLOW_DOMAINS = {
    "timesofindia.indiatimes.com",
    "thehindu.com",
    "hindustantimes.com",
    "indianexpress.com",
    "ndtv.com",
    "indiatoday.in",
    "economictimes.indiatimes.com",
    "news18.com",
}

# -------------------- Configuration from env --------------------
def get_env_list(name: str, default: Optional[List[str]] = None) -> List[str]:
    raw = os.environ.get(name, "")
    if raw.strip():
        return [s.strip() for s in raw.split(",") if s.strip()]
    return list(default or [])

FEED_URLS = get_env_list("FEED_URLS", DEFAULT_FEEDS)
ALLOW_DOMAINS = set(d.strip().lower() for d in os.environ.get("ALLOW_DOMAINS", "").split(",") if d.strip()) or DEFAULT_ALLOW_DOMAINS
INCLUDE_KEYWORDS = [k.strip().lower() for k in os.environ.get("INCLUDE_KEYWORDS", "").split(",") if k.strip()]
EXCLUDE_KEYWORDS = [k.strip().lower() for k in os.environ.get("EXCLUDE_KEYWORDS", "").split(",") if k.strip()]

MAX_ITEMS = int(os.environ.get("MAX_ITEMS", "10"))
MAX_PER_FEED = int(os.environ.get("MAX_PER_FEED", "25"))
MIN_ARTICLE_LENGTH = int(os.environ.get("MIN_ARTICLE_LENGTH", "150"))

DRY_RUN = os.environ.get("DRY_RUN", "false").lower() == "true"

GOOGLE_API_KEY = os.environ.get("GOOGLE_API_KEY", "API_KEY").strip()
SENDER_EMAIL = os.environ.get("SENDER_EMAIL", "sender@gmail.com").strip()
RECEIVER_EMAIL = os.environ.get("RECEIVER_EMAIL", "receiver@gmail.com").strip()
APP_PASSWORD = os.environ.get("APP_PASSWORD", "xxxx xxxx xxxx xxxx").strip()

PERSIST_SENT = os.environ.get("PERSIST_SENT", "true").lower() == "true"
SENT_FILE = os.environ.get("SENT_FILE", "sent.json")

REQUEST_TIMEOUT = 12
SLEEP_BETWEEN_REQUESTS = 1.0

# -------------------- Helpers --------------------
def domain_of(url: str) -> str:
    try:
        return urlparse(url).netloc.lower().replace("www.", "")
    except Exception:
        return ""

def load_sent_set() -> Set[str]:
    if not PERSIST_SENT:
        return set()
    if os.path.exists(SENT_FILE):
        try:
            with open(SENT_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            return set(data if isinstance(data, list) else [])
        except Exception:
            return set()
    return set()

def save_sent_set(sent: Set[str]) -> None:
    if not PERSIST_SENT:
        return
    try:
        with open(SENT_FILE, "w", encoding="utf-8") as f:
            json.dump(sorted(sent), f, indent=2)
    except Exception as e:
        print(f"[save_sent_set] could not write file: {e}")

# -------------------- Extraction --------------------
def fetch_page(url: str) -> Tuple[Optional[str], Optional[str]]:
    """
    Fetches page and returns (extracted_text_or_None, error_message_or_None).
    Uses <article> if present else <p> paragraphs. Limits text to ~6000 chars.
    """
    headers = {"User-Agent": "Mozilla/5.0 (compatible; IndiaDigest/1.0)"}
    try:
        r = requests.get(url, headers=headers, timeout=REQUEST_TIMEOUT)
        r.raise_for_status()
        soup = BeautifulSoup(r.content, "html.parser")
        article_tag = soup.find("article")
        if article_tag:
            paras = article_tag.find_all("p")
        else:
            paras = soup.find_all("p")
        text = " ".join(p.get_text().strip() for p in paras if p.get_text().strip())
        if not text or len(text) < MIN_ARTICLE_LENGTH:
            return None, None  # not enough content (caller may use RSS summary)
        return text[:6000], None
    except requests.exceptions.RequestException as e:
        return None, f"fetch_error: {str(e)}"
    except Exception as e:
        return None, f"extract_error: {str(e)}"

# -------------------- Summarization --------------------
_SENTENCE_SPLIT_RE = re.compile(r'(?<=[\.\?\!])\s+')

def simple_extractive_summary(text: str, max_sentences: int = 3) -> str:
    text = re.sub(r'\s+', ' ', (text or "")).strip()
    if not text:
        return ""
    sentences = _SENTENCE_SPLIT_RE.split(text)
    chosen = sentences[:max_sentences]
    headline = chosen[0] if chosen else (text[:100] + "...")
    bullets = chosen[1:] if len(chosen) > 1 else chosen[:max_sentences]
    bullets_txt = "\n".join(f"- {b.strip()}" for b in bullets) if bullets else ""
    return f"{headline.strip()}\n{bullets_txt}"

def summarize(title: str, text: str) -> str:
    # Use Gemini if key present and client available
    if GOOGLE_API_KEY and GEMINI_AVAILABLE:
        try:
            genai.configure(api_key=GOOGLE_API_KEY)
            model = genai.GenerativeModel("gemini-1.5-flash-latest") #Or any model which you wish to keep
            prompt = (
                "You are a concise, factual summarizer. Output:\n"
                "- One short headline (one line)\n"
                "- Three clear bullet points (each 1 sentence)\n\n"
                f"Article Title: {title}\n\nArticle Text:\n{text}\n\nSummary:"
            )
            resp = model.generate_content(prompt)
            if hasattr(resp, "text") and resp.text:
                return resp.text.strip()
            return str(resp)
        except Exception as e:
            print(f"[summarize] Gemini error: {e} — falling back to extractive summary.")
            return simple_extractive_summary(text)
    else:
        # No Gemini configured -> extractive fallback
        return simple_extractive_summary(text)

# -------------------- Filtering --------------------
def passes_filters(entry, extracted_text: Optional[str]) -> Tuple[bool, str]:
    url = getattr(entry, "link", "") or ""
    title = (getattr(entry, "title", "") or "").lower()
    summary = (getattr(entry, "summary", "") or getattr(entry, "description", "") or "").lower()
    dom = domain_of(url)

    # 1) domain allowlist
    if ALLOW_DOMAINS and not any(allow in dom for allow in ALLOW_DOMAINS):
        return False, f"domain_not_allowed:{dom}"

    # 2) exclude keywords
    combined = f"{title} {summary}"
    for kw in EXCLUDE_KEYWORDS:
        if kw and kw in combined:
            return False, f"exclude_keyword:{kw}"

    # 3) include keywords (if set -> at least one must match)
    if INCLUDE_KEYWORDS:
        if not any(kw in combined for kw in INCLUDE_KEYWORDS):
            return False, "include_keywords_not_matched"

    # 4) length: prefer extracted_text if available, else summary
    effective_len = len(extracted_text or "") if extracted_text else len(summary or "")
    if effective_len < MIN_ARTICLE_LENGTH:
        return False, f"too_short(len={effective_len})"

    return True, "ok"

# -------------------- Collection & Digest --------------------
def collect_and_summarize(max_items: int) -> List[dict]:
    # load previous sent set
    sent = load_sent_set()
    candidates = []
    now = datetime.utcnow()
    for feed in FEED_URLS:
        try:
            parsed = feedparser.parse(feed)
            for e in parsed.entries[:MAX_PER_FEED]:
                # determine published time (best-effort)
                try:
                    published = datetime(*e.published_parsed[:6])
                except Exception:
                    try:
                        published = datetime(*e.updated_parsed[:6])
                    except Exception:
                        published = now
                candidates.append((published, e))
        except Exception as e:
            print(f"[collect] feed parse error {feed}: {e}")

    # newest first
    candidates.sort(key=lambda x: x[0], reverse=True)

    collected = []
    for published, entry in candidates:
        if len(collected) >= max_items:
            break
        url = getattr(entry, "link", "") or ""
        title = getattr(entry, "title", url or "Untitled")
        if not url:
            continue
        if url in sent:
            # skip already sent
            continue

        print(f"[collect] trying: {title} ({url})")
        extracted, err = fetch_page(url)
        if not extracted:
            # fallback to feed-provided summary/description
            fallback = getattr(entry, "summary", None) or getattr(entry, "description", None)
            if fallback:
                print("[collect] using feed summary as fallback")
                extracted = fallback
            else:
                print(f"[collect] skipped: could not fetch nor fallback for {url} ({err})")
                continue

        ok, reason = passes_filters(entry, extracted)
        if not ok:
            print(f"[collect] filtered out ({reason})")
            continue

        summary_txt = summarize(title, extracted)
        collected.append({
            "title": title,
            "url": url,
            "summary": summary_txt,
            "published": published.isoformat()
        })
        # polite pause
        time.sleep(SLEEP_BETWEEN_REQUESTS)

    return collected

# -------------------- Email --------------------
def compose_email_body(items: List[dict]) -> str:
    today = datetime.now().strftime("%B %d, %Y")
    lines = [f"India Daily Digest — {today}", "-" * 40, ""]
    for i, it in enumerate(items, start=1):
        lines.append(f"{i}. {it['title']}")
        lines.append(f"Link: {it['url']}")
        lines.append("Summary:")
        lines.append(it['summary'])
        lines.append("")  # spacer
    return "\n".join(lines)

def send_email(subject: str, body: str) -> None:
    if DRY_RUN:
        print("[send_email] DRY_RUN is true — not sending. Email body below:\n")
        print(body)
        return
    if not (SENDER_EMAIL and RECEIVER_EMAIL and APP_PASSWORD):
        raise RuntimeError("SENDER_EMAIL, RECEIVER_EMAIL and APP_PASSWORD environment variables required to send email.")
    msg = EmailMessage()
    msg["From"] = SENDER_EMAIL
    msg["To"] = RECEIVER_EMAIL
    msg["Subject"] = subject
    msg.set_content(body)
    # SMTP using SSL (465)
    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as smtp:
        smtp.login(SENDER_EMAIL, APP_PASSWORD)
        smtp.send_message(msg)
    print("[send_email] Sent successfully.")

# -------------------- Runner --------------------
def main():
    print("[main] Starting India-only daily digest (DRY_RUN=%s)" % DRY_RUN)
    print("Feeds:", FEED_URLS)
    print("Allow domains:", sorted(list(ALLOW_DOMAINS))[:10])
    print("Max items:", MAX_ITEMS, "Min length:", MIN_ARTICLE_LENGTH)
    sent_before = load_sent_set()
    print("Previously sent URLs:", len(sent_before))

    items = collect_and_summarize(MAX_ITEMS)
    if not items:
        print("[main] No items selected after filtering.")
        return
    body = compose_email_body(items)
    subject = f"India Daily Top {len(items)} — {datetime.now().strftime('%Y-%m-%d')}"
    send_email(subject, body)

    # persist sent urls
    if PERSIST_SENT and not DRY_RUN:
        sent = load_sent_set()
        for it in items:
            sent.add(it["url"])
        save_sent_set(sent)
        print("[main] Updated sent.json")

if __name__ == "__main__":
    main()

