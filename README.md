# MY Market Sentiment Analyser

Scrapes Malaysian financial news (English + Bahasa Malaysia), scores each article
with a finance-tuned NLP model, stores everything locally, and surfaces results
in a Streamlit dashboard.

---

## Project structure

```
my-sentiment-analyser/
├── scraper/
│   ├── sources.py        ← all news sources + Bursa ticker map
│   └── scraper.py        ← RSS + full-article scraper
├── nlp/
│   └── sentiment.py      ← FinBERT + multilingual scoring
├── db/
│   └── database.py       ← SQLite read/write layer
├── scheduler/
│   └── scheduler.py      ← APScheduler jobs
├── dashboard/
│   └── app.py            ← Streamlit UI
├── data/                 ← auto-created; holds sentiment.db
└── requirements.txt
```

---

## Setup

### 1. Create a virtual environment

```bash
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
```

### 2. Install dependencies

```bash
pip install -r requirements.txt
```

> First run will download the FinBERT model (~440 MB) and the multilingual model
> (~120 MB) from HuggingFace. These are cached locally after that.

### 3. Run the pipeline once (to test)

```bash
# From the project root
python -m scheduler.scheduler --once
```

This will:
- Scrape all RSS sources + i3investor
- Score every article for sentiment
- Save everything to `data/sentiment.db`

### 4. Launch the dashboard

```bash
streamlit run dashboard/app.py
```

Open http://localhost:8501 in your browser.

### 5. Run continuously (background scheduler)

```bash
python -m scheduler.scheduler
```

This starts the scheduler:
- RSS scrape every **3 hours**
- NLP scoring every **1 hour**
- i3investor every **6 hours**

---

## Adding more news sources

Edit `scraper/sources.py` and add a dict to `RSS_SOURCES`:

```python
{
    "name": "My Source Name",
    "url": "https://example.com/rss",
    "language": "en",   # or "ms" for Bahasa Malaysia
    "category": "business",
}
```

---

## Adding more Bursa tickers to track

Edit the `BURSA_SECTORS` dict in `scraper/sources.py`:

```python
"TECH": ["INARI", "KESM", "UNISEM", "MPI", "VITROX", "MYNEWCODE"],
```

---

## Interpreting impact scores

| Score range | Meaning |
|---|---|
| +0.5 to +1.0 | Strongly bullish news |
| +0.1 to +0.5 | Mildly positive |
| -0.1 to +0.1 | Neutral / noise |
| -0.1 to -0.5 | Mildly negative |
| -0.5 to -1.0 | Strongly bearish news |

The impact score is computed as: `(positive_conf - negative_conf) / effective_weight`

---

## Tips for personal use

- Use the **ticker search** in the sidebar to monitor specific stocks in your portfolio
- The **48h top movers** section highlights the highest-impact news — check this daily
- Articles from **i3investor** reflect retail investor sentiment, which often leads price moves
- A sudden spike of negative articles on a stock you hold is a useful early warning signal

---

## Tech stack

| Layer | Library | Why |
|---|---|---|
| RSS scraping | feedparser | Handles all RSS/Atom formats cleanly |
| Full articles | newspaper3k | Extracts article body from any news site |
| EN sentiment | ProsusAI/finbert | Finance-tuned BERT, much better than generic models |
| BM/EN sentiment | cardiffnlp/twitter-xlm-roberta | Multilingual, handles mixed BM/EN text |
| Storage | SQLite | Zero-config, runs fully locally |
| Scheduling | APScheduler | Simple cron-style Python scheduler |
| Dashboard | Streamlit | Python-native web UI, no frontend code needed |
| Charts | Plotly | Interactive charts |
