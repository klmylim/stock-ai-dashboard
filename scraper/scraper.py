"""
Core scraper — handles RSS feeds + full-article extraction.
Fetches articles, deduplicates by URL, and returns clean dicts
ready for the NLP pipeline.
"""

import hashlib
import logging
import time
from datetime import datetime, timezone
from typing import Optional

import feedparser
import requests
from newspaper import Article, Config
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from .sources import RSS_SOURCES, SCRAPE_TARGETS, BURSA_SECTORS

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# HTTP session with retry + polite headers
# ---------------------------------------------------------------------------

def _build_session() -> requests.Session:
    session = requests.Session()
    retry = Retry(total=3, backoff_factor=1.5, status_forcelist=[429, 500, 502, 503, 504])
    adapter = HTTPAdapter(max_retries=retry)
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    session.headers.update({
        "User-Agent": (
            "Mozilla/5.0 (compatible; MYSentimentBot/1.0; "
            "+https://github.com/yourname/my-sentiment-analyser)"
        ),
        "Accept-Language": "en-US,en;q=0.9,ms;q=0.8",
    })
    return session

SESSION = _build_session()

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _url_hash(url: str) -> str:
    """Stable deduplication key from URL."""
    return hashlib.sha256(url.strip().encode()).hexdigest()[:16]


def _tag_tickers(text: str) -> list[str]:
    """Return any Bursa tickers or sector names mentioned in the text."""
    text_upper = text.upper()
    found = []
    for sector, tickers in BURSA_SECTORS.items():
        for ticker in tickers:
            if ticker in text_upper:
                found.append(ticker)
        if sector in text_upper:
            found.append(f"SECTOR:{sector}")
    return list(set(found))


def _parse_date(entry) -> str:
    """Best-effort ISO 8601 date from a feedparser entry."""
    for attr in ("published_parsed", "updated_parsed", "created_parsed"):
        parsed = getattr(entry, attr, None)
        if parsed:
            try:
                return datetime(*parsed[:6], tzinfo=timezone.utc).isoformat()
            except Exception:
                pass
    return datetime.now(timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# Full article extraction via newspaper3k
# ---------------------------------------------------------------------------

def _extract_full_article(url: str, language: str = "en") -> Optional[str]:
    """
    Download and parse the full article body.
    Returns None if extraction fails or article is too short.
    """
    try:
        config = Config()
        config.browser_user_agent = SESSION.headers["User-Agent"]
        config.request_timeout = 15
        config.language = language if language in ("en", "ms") else "en"

        article = Article(url, config=config)
        article.download()
        article.parse()

        text = (article.text or "").strip()
        if len(text) < 100:
            return None
        return text
    except Exception as e:
        log.debug(f"Full article extraction failed for {url}: {e}")
        return None


# ---------------------------------------------------------------------------
# RSS feed scraper
# ---------------------------------------------------------------------------

def scrape_rss_source(source: dict, fetch_full: bool = True, delay: float = 1.0) -> list[dict]:
    """
    Parse a single RSS source and return a list of article dicts.
    `fetch_full=True` tries to download the full article body.
    """
    articles = []
    log.info(f"Scraping RSS: {source['name']}")

    try:
        feed = feedparser.parse(source["url"], agent=SESSION.headers["User-Agent"])
    except Exception as e:
        log.error(f"Failed to fetch RSS {source['url']}: {e}")
        return []

    for entry in feed.entries:
        url = getattr(entry, "link", "")
        if not url:
            continue

        # Build title + summary from RSS
        title = getattr(entry, "title", "").strip()
        summary = getattr(entry, "summary", "") or getattr(entry, "description", "")
        summary = summary.strip()

        # Optionally fetch full body
        full_text = None
        if fetch_full and url:
            full_text = _extract_full_article(url, language=source["language"])
            time.sleep(delay)  # polite crawl delay

        body = full_text or summary

        article = {
            "id": _url_hash(url),
            "url": url,
            "title": title,
            "summary": summary,
            "body": body,
            "source": source["name"],
            "language": source["language"],
            "category": source["category"],
            "published_at": _parse_date(entry),
            "scraped_at": datetime.now(timezone.utc).isoformat(),
            "tickers_mentioned": _tag_tickers(f"{title} {body}"),
            "full_text_fetched": full_text is not None,
        }
        articles.append(article)

    log.info(f"  → {len(articles)} articles from {source['name']}")
    return articles


# ---------------------------------------------------------------------------
# i3investor forum scraper (retail sentiment signal)
# ---------------------------------------------------------------------------

def scrape_i3investor(delay: float = 1.5) -> list[dict]:
    """
    Scrape recent blog/forum posts from i3investor.
    These represent retail investor sentiment — often a leading signal.
    """
    articles = []
    url = "https://klse.i3investor.com/web/blog/latest"
    log.info("Scraping i3investor forum...")

    try:
        resp = SESSION.get(url, timeout=15)
        resp.raise_for_status()

        from bs4 import BeautifulSoup
        soup = BeautifulSoup(resp.text, "html.parser")

        # Each post card contains title, author, date, excerpt
        for card in soup.select("div.content-post, div.blog-post, article")[:30]:
            a_tag = card.find("a", href=True)
            if not a_tag:
                continue

            post_url = a_tag["href"]
            if not post_url.startswith("http"):
                post_url = "https://klse.i3investor.com" + post_url

            title = a_tag.get_text(strip=True)
            if not title or len(title) < 5:
                continue

            # Try to get the post body
            full_text = _extract_full_article(post_url)
            time.sleep(delay)

            article = {
                "id": _url_hash(post_url),
                "url": post_url,
                "title": title,
                "summary": (full_text or "")[:300],
                "body": full_text or title,
                "source": "i3investor",
                "language": "en",
                "category": "retail_sentiment",
                "published_at": datetime.now(timezone.utc).isoformat(),
                "scraped_at": datetime.now(timezone.utc).isoformat(),
                "tickers_mentioned": _tag_tickers(f"{title} {full_text or ''}"),
                "full_text_fetched": full_text is not None,
            }
            articles.append(article)

    except Exception as e:
        log.error(f"i3investor scrape failed: {e}")

    log.info(f"  → {len(articles)} posts from i3investor")
    return articles


# ---------------------------------------------------------------------------
# Main entry point — scrape everything
# ---------------------------------------------------------------------------

def run_all_scrapers(
    fetch_full: bool = True,
    include_i3: bool = True,
    delay: float = 1.2,
) -> list[dict]:
    """
    Run all RSS scrapers + optional i3investor.
    Returns a deduplicated list of article dicts.
    """
    all_articles = []
    seen_ids = set()

    for source in RSS_SOURCES:
        try:
            batch = scrape_rss_source(source, fetch_full=fetch_full, delay=delay)
            for art in batch:
                if art["id"] not in seen_ids:
                    all_articles.append(art)
                    seen_ids.add(art["id"])
        except Exception as e:
            log.error(f"Error scraping {source['name']}: {e}")

    if include_i3:
        try:
            batch = scrape_i3investor(delay=delay)
            for art in batch:
                if art["id"] not in seen_ids:
                    all_articles.append(art)
                    seen_ids.add(art["id"])
        except Exception as e:
            log.error(f"Error scraping i3investor: {e}")

    log.info(f"Total unique articles collected: {len(all_articles)}")
    return all_articles
