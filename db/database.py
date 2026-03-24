"""
Database layer — SQLite storage for articles + sentiment scores.
All reads/writes go through this module.
"""

import json
import logging
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

log = logging.getLogger(__name__)

DB_PATH = Path(__file__).parent.parent / "data" / "sentiment.db"


def _get_conn() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")   # safer concurrent writes
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db():
    """Create tables if they don't exist."""
    with _get_conn() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS articles (
                id                TEXT PRIMARY KEY,
                url               TEXT UNIQUE NOT NULL,
                title             TEXT,
                summary           TEXT,
                body              TEXT,
                source            TEXT,
                language          TEXT DEFAULT 'en',
                category          TEXT,
                published_at      TEXT,
                scraped_at        TEXT,
                tickers_mentioned TEXT,   -- JSON array
                full_text_fetched INTEGER DEFAULT 0,

                -- Sentiment fields (populated after NLP pass)
                sentiment_label   TEXT,
                sentiment_score   REAL,
                sentiment_raw     TEXT,   -- JSON dict
                impact_score      REAL,
                model_used        TEXT,
                scored_at         TEXT
            );

            CREATE INDEX IF NOT EXISTS idx_articles_published  ON articles(published_at DESC);
            CREATE INDEX IF NOT EXISTS idx_articles_source     ON articles(source);
            CREATE INDEX IF NOT EXISTS idx_articles_sentiment  ON articles(sentiment_label);
            CREATE INDEX IF NOT EXISTS idx_articles_impact     ON articles(impact_score);

            CREATE TABLE IF NOT EXISTS scrape_runs (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                started_at  TEXT NOT NULL,
                finished_at TEXT,
                articles_fetched  INTEGER DEFAULT 0,
                articles_new      INTEGER DEFAULT 0,
                articles_scored   INTEGER DEFAULT 0,
                status      TEXT DEFAULT 'running'  -- running | done | error
            );
        """)
    log.info(f"Database ready at {DB_PATH}")


# ---------------------------------------------------------------------------
# Write
# ---------------------------------------------------------------------------

def upsert_articles(articles: list[dict]) -> int:
    """
    Insert or ignore articles (deduplication by id/url).
    Returns count of newly inserted rows.
    """
    if not articles:
        return 0

    rows = []
    for a in articles:
        rows.append((
            a["id"],
            a["url"],
            a.get("title", ""),
            a.get("summary", ""),
            a.get("body", ""),
            a.get("source", ""),
            a.get("language", "en"),
            a.get("category", ""),
            a.get("published_at", ""),
            a.get("scraped_at", ""),
            json.dumps(a.get("tickers_mentioned", [])),
            int(a.get("full_text_fetched", False)),
        ))

    with _get_conn() as conn:
        before = conn.execute("SELECT COUNT(*) FROM articles").fetchone()[0]
        conn.executemany("""
            INSERT OR IGNORE INTO articles
            (id, url, title, summary, body, source, language, category,
             published_at, scraped_at, tickers_mentioned, full_text_fetched)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
        """, rows)
        after = conn.execute("SELECT COUNT(*) FROM articles").fetchone()[0]

    inserted = after - before
    log.info(f"Upserted {len(articles)} articles → {inserted} new rows")
    return inserted


def update_sentiment(articles: list[dict]):
    """Write sentiment scores back to existing rows."""
    rows = []
    now = datetime.now(timezone.utc).isoformat()
    for a in articles:
        if "sentiment_label" not in a:
            continue
        rows.append((
            a["sentiment_label"],
            a.get("sentiment_score", 0),
            json.dumps(a.get("sentiment_raw", {})),
            a.get("impact_score", 0),
            a.get("model_used", ""),
            now,
            a["id"],
        ))

    if not rows:
        return

    with _get_conn() as conn:
        conn.executemany("""
            UPDATE articles
            SET sentiment_label=?, sentiment_score=?, sentiment_raw=?,
                impact_score=?, model_used=?, scored_at=?
            WHERE id=?
        """, rows)
    log.info(f"Sentiment updated for {len(rows)} articles")


# ---------------------------------------------------------------------------
# Read
# ---------------------------------------------------------------------------

def fetch_unscored(limit: int = 200) -> list[dict]:
    """Return articles that haven't been through the NLP pipeline yet."""
    with _get_conn() as conn:
        rows = conn.execute("""
            SELECT * FROM articles
            WHERE sentiment_label IS NULL
            ORDER BY published_at DESC
            LIMIT ?
        """, (limit,)).fetchall()
    return [dict(r) for r in rows]


def fetch_recent(hours: int = 24, limit: int = 500) -> list[dict]:
    """Return articles published in the last N hours."""
    from datetime import timedelta
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()
    with _get_conn() as conn:
        rows = conn.execute("""
            SELECT * FROM articles
            WHERE published_at >= ?
            ORDER BY impact_score DESC, published_at DESC
            LIMIT ?
        """, (cutoff, limit)).fetchall()
    return [_deserialize(dict(r)) for r in rows]


def fetch_by_ticker(ticker: str, limit: int = 50) -> list[dict]:
    """Return articles mentioning a specific Bursa ticker."""
    with _get_conn() as conn:
        rows = conn.execute("""
            SELECT * FROM articles
            WHERE tickers_mentioned LIKE ?
            ORDER BY published_at DESC
            LIMIT ?
        """, (f'%"{ticker}"%', limit)).fetchall()
    return [_deserialize(dict(r)) for r in rows]


def fetch_top_movers(limit: int = 20) -> list[dict]:
    """Return the highest-impact articles (most strongly pos or neg) from last 48h."""
    from datetime import timedelta
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=48)).isoformat()
    with _get_conn() as conn:
        rows = conn.execute("""
            SELECT * FROM articles
            WHERE published_at >= ?
              AND sentiment_label IS NOT NULL
              AND sentiment_label != 'neutral'
            ORDER BY ABS(impact_score) DESC
            LIMIT ?
        """, (cutoff, limit)).fetchall()
    return [_deserialize(dict(r)) for r in rows]


def get_sentiment_summary(hours: int = 24) -> dict:
    """Aggregate sentiment stats for the dashboard overview."""
    from datetime import timedelta
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()
    with _get_conn() as conn:
        row = conn.execute("""
            SELECT
                COUNT(*) as total,
                SUM(CASE WHEN sentiment_label='positive' THEN 1 ELSE 0 END) as positive,
                SUM(CASE WHEN sentiment_label='negative' THEN 1 ELSE 0 END) as negative,
                SUM(CASE WHEN sentiment_label='neutral'  THEN 1 ELSE 0 END) as neutral,
                AVG(impact_score) as avg_impact,
                AVG(CASE WHEN sentiment_label='positive' THEN sentiment_score END) as avg_pos_confidence,
                AVG(CASE WHEN sentiment_label='negative' THEN sentiment_score END) as avg_neg_confidence
            FROM articles
            WHERE published_at >= ?
              AND sentiment_label IS NOT NULL
        """, (cutoff,)).fetchone()
    return dict(row) if row else {}


def _deserialize(row: dict) -> dict:
    """Parse JSON fields back to Python objects."""
    if isinstance(row.get("tickers_mentioned"), str):
        try:
            row["tickers_mentioned"] = json.loads(row["tickers_mentioned"])
        except Exception:
            row["tickers_mentioned"] = []
    if isinstance(row.get("sentiment_raw"), str):
        try:
            row["sentiment_raw"] = json.loads(row["sentiment_raw"])
        except Exception:
            row["sentiment_raw"] = {}
    return row
