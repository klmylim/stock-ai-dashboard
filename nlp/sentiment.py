"""
Sentiment analysis pipeline.

Uses two models:
  1. ProsusAI/finbert          — English finance sentiment (pos/neg/neutral)
  2. intfloat/multilingual-e5-small — BM/EN embeddings for similarity search

Scoring output per article:
  sentiment_label : "positive" | "negative" | "neutral"
  sentiment_score : float  (confidence, 0–1)
  sentiment_raw   : dict   {positive: float, negative: float, neutral: float}
  impact_score    : float  (-1 to +1, signed strength signal)
"""

import logging
from typing import Optional

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Lazy model loading — only download on first use
# ---------------------------------------------------------------------------

_finbert_pipeline = None
_multilingual_pipeline = None


def _load_finbert():
    global _finbert_pipeline
    if _finbert_pipeline is None:
        log.info("Loading FinBERT model (first run may take a moment)...")
        from transformers import pipeline
        _finbert_pipeline = pipeline(
            "text-classification",
            model="ProsusAI/finbert",
            tokenizer="ProsusAI/finbert",
            top_k=None,          # return all label scores
            truncation=True,
            max_length=512,
        )
        log.info("FinBERT loaded.")
    return _finbert_pipeline


def _load_multilingual():
    global _multilingual_pipeline
    if _multilingual_pipeline is None:
        log.info("Loading multilingual model for BM/EN...")
        from transformers import pipeline
        _multilingual_pipeline = pipeline(
            "text-classification",
            model="cardiffnlp/twitter-xlm-roberta-base-sentiment-multilingual",
            tokenizer="cardiffnlp/twitter-xlm-roberta-base-sentiment-multilingual",
            top_k=None,
            truncation=True,
            max_length=512,
        )
        log.info("Multilingual model loaded.")
    return _multilingual_pipeline


# ---------------------------------------------------------------------------
# Text preprocessing
# ---------------------------------------------------------------------------

def _prepare_text(article: dict, max_chars: int = 1500) -> str:
    """
    Combine title + body into a single string for the model.
    Title is weighted more heavily by repeating it.
    Truncated to max_chars to stay within model token limits.
    """
    title = article.get("title", "").strip()
    body = article.get("body", "").strip() or article.get("summary", "").strip()

    # Repeat title so the model pays more attention to it
    combined = f"{title}. {title}. {body}"
    return combined[:max_chars]


def _normalize_finbert_output(raw: list[dict]) -> dict:
    """
    Convert FinBERT's list of label/score dicts to a clean dict.
    FinBERT labels: 'positive', 'negative', 'neutral'
    """
    scores = {item["label"].lower(): round(item["score"], 4) for item in raw}
    return scores


def _normalize_multilingual_output(raw: list[dict]) -> dict:
    """
    twitter-xlm-roberta uses 'Positive', 'Negative', 'Neutral' labels.
    Map them to lowercase finbert-style keys.
    """
    mapping = {"positive": "positive", "negative": "negative", "neutral": "neutral"}
    scores = {}
    for item in raw:
        label = item["label"].lower()
        key = mapping.get(label, label)
        scores[key] = round(item["score"], 4)
    return scores


def _compute_impact(scores: dict) -> float:
    """
    Signed impact score: ranges from -1 (strongly negative) to +1 (strongly positive).
    Formula: (positive - negative) weighted by their combined confidence.
    """
    pos = scores.get("positive", 0)
    neg = scores.get("negative", 0)
    neutral = scores.get("neutral", 0)

    # Discount neutral — a 90% neutral article has low impact either way
    effective_weight = pos + neg + (neutral * 0.2)
    if effective_weight == 0:
        return 0.0

    impact = (pos - neg) / effective_weight
    return round(max(-1.0, min(1.0, impact)), 4)


# ---------------------------------------------------------------------------
# Core scoring function
# ---------------------------------------------------------------------------

def score_article(article: dict) -> dict:
    """
    Run sentiment scoring on a single article dict.
    Returns the article dict enriched with sentiment fields.
    """
    text = _prepare_text(article)
    if not text.strip():
        article.update({
            "sentiment_label": "neutral",
            "sentiment_score": 0.0,
            "sentiment_raw": {},
            "impact_score": 0.0,
            "model_used": "none",
        })
        return article

    language = article.get("language", "en")

    try:
        if language == "ms":
            # Bahasa Malaysia — use multilingual model
            pipe = _load_multilingual()
            raw = pipe(text)[0]
            scores = _normalize_multilingual_output(raw)
            model_used = "xlm-roberta-multilingual"
        else:
            # English — use FinBERT (finance-tuned)
            pipe = _load_finbert()
            raw = pipe(text)[0]
            scores = _normalize_finbert_output(raw)
            model_used = "finbert"

        # Winning label = highest score
        sentiment_label = max(scores, key=scores.get)
        sentiment_score = round(scores[sentiment_label], 4)
        impact_score = _compute_impact(scores)

        article.update({
            "sentiment_label": sentiment_label,
            "sentiment_score": sentiment_score,
            "sentiment_raw": scores,
            "impact_score": impact_score,
            "model_used": model_used,
        })

    except Exception as e:
        log.error(f"Sentiment scoring failed for '{article.get('title', '')}': {e}")
        article.update({
            "sentiment_label": "neutral",
            "sentiment_score": 0.0,
            "sentiment_raw": {},
            "impact_score": 0.0,
            "model_used": "error",
        })

    return article


# ---------------------------------------------------------------------------
# Batch scoring
# ---------------------------------------------------------------------------

def score_articles(articles: list[dict], batch_size: int = 16) -> list[dict]:
    """
    Score a list of articles. Processes in batches for efficiency.
    Returns the same list with sentiment fields added.
    """
    total = len(articles)
    log.info(f"Scoring {total} articles...")

    scored = []
    for i, article in enumerate(articles):
        scored.append(score_article(article))
        if (i + 1) % 10 == 0:
            log.info(f"  Scored {i + 1}/{total}...")

    # Summary stats
    labels = [a["sentiment_label"] for a in scored]
    pos = labels.count("positive")
    neg = labels.count("negative")
    neu = labels.count("neutral")
    log.info(f"Sentiment summary → positive: {pos}, negative: {neg}, neutral: {neu}")

    return scored


# ---------------------------------------------------------------------------
# Aggregate sentiment for a ticker or category
# ---------------------------------------------------------------------------

def aggregate_sentiment(articles: list[dict], group_by: str = "source") -> dict:
    """
    Compute aggregate sentiment score for groups of articles.
    `group_by` can be: 'source', 'category', 'language', or a ticker symbol.

    Returns a dict of { group_key: { avg_impact, article_count, label_counts } }
    """
    from collections import defaultdict

    groups = defaultdict(list)

    for art in articles:
        if group_by == "ticker":
            for ticker in art.get("tickers_mentioned", []):
                groups[ticker].append(art)
        else:
            key = art.get(group_by, "unknown")
            groups[key].append(art)

    result = {}
    for key, arts in groups.items():
        impacts = [a.get("impact_score", 0) for a in arts]
        labels = [a.get("sentiment_label", "neutral") for a in arts]
        result[key] = {
            "avg_impact": round(sum(impacts) / len(impacts), 4) if impacts else 0,
            "article_count": len(arts),
            "label_counts": {
                "positive": labels.count("positive"),
                "negative": labels.count("negative"),
                "neutral": labels.count("neutral"),
            },
        }

    return dict(sorted(result.items(), key=lambda x: abs(x[1]["avg_impact"]), reverse=True))
