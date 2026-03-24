"""
Scheduler — runs the full scrape → score → store pipeline on a schedule.
Uses APScheduler for cron-style jobs.

Jobs:
  Every 3 hours  : Full scrape of all RSS sources
  Every 6 hours  : Score any unscored articles in the DB
  Every 24 hours : Scrape i3investor forum (slower, more bandwidth)
"""

import logging
from datetime import datetime, timezone

from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.interval import IntervalTrigger

log = logging.getLogger(__name__)


def job_scrape_and_store(fetch_full: bool = True, include_i3: bool = False):
    """Scrape all RSS sources and store new articles."""
    from scraper.scraper import run_all_scrapers
    from db.database import upsert_articles, init_db

    log.info("=== SCRAPE JOB START ===")
    init_db()
    articles = run_all_scrapers(fetch_full=fetch_full, include_i3=include_i3)
    new_count = upsert_articles(articles)
    log.info(f"=== SCRAPE JOB DONE — {new_count} new articles stored ===")


def job_score_unscored():
    """Pick up any articles not yet through the NLP pipeline and score them."""
    from db.database import fetch_unscored, update_sentiment
    from nlp.sentiment import score_articles

    log.info("=== SCORE JOB START ===")
    articles = fetch_unscored(limit=100)
    if not articles:
        log.info("No unscored articles — skipping.")
        return

    scored = score_articles(articles)
    update_sentiment(scored)
    log.info(f"=== SCORE JOB DONE — {len(scored)} articles scored ===")


def job_scrape_i3():
    """Dedicated i3investor scrape (runs less frequently)."""
    job_scrape_and_store(fetch_full=True, include_i3=True)


def run_once():
    """
    Run the full pipeline once immediately (useful for testing).
    Call this directly: python -m scheduler.scheduler --once
    """
    log.info("Running pipeline once...")
    job_scrape_and_store(fetch_full=True, include_i3=True)
    job_score_unscored()
    log.info("Done.")


def start_scheduler():
    """Start the blocking scheduler (runs forever)."""
    scheduler = BlockingScheduler(timezone="Asia/Kuala_Lumpur")

    # RSS scrape every 3 hours
    scheduler.add_job(
        job_scrape_and_store,
        trigger=IntervalTrigger(hours=3),
        id="rss_scrape",
        name="RSS scrape (all sources)",
        replace_existing=True,
        misfire_grace_time=300,
    )

    # Score unscored articles every 1 hour
    scheduler.add_job(
        job_score_unscored,
        trigger=IntervalTrigger(hours=1),
        id="nlp_score",
        name="NLP scoring pass",
        replace_existing=True,
        misfire_grace_time=300,
    )

    # i3investor forum every 6 hours
    scheduler.add_job(
        job_scrape_i3,
        trigger=IntervalTrigger(hours=6),
        id="i3_scrape",
        name="i3investor forum scrape",
        replace_existing=True,
        misfire_grace_time=600,
    )

    log.info("Scheduler started — running on Asia/Kuala_Lumpur timezone")
    log.info("Jobs: RSS every 3h | Scoring every 1h | i3investor every 6h")

    try:
        # Run once immediately on startup
        job_scrape_and_store(fetch_full=True, include_i3=False)
        job_score_unscored()
        scheduler.start()
    except (KeyboardInterrupt, SystemExit):
        log.info("Scheduler stopped.")


if __name__ == "__main__":
    import sys
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

    if "--once" in sys.argv:
        run_once()
    else:
        start_scheduler()
