"""
Streamlit dashboard — main UI for the MY sentiment analyser.
Run with: streamlit run dashboard/app.py
"""

import json
from datetime import datetime, timedelta, timezone

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

# -------------------------------------------------------------------
# Page config
# -------------------------------------------------------------------
st.set_page_config(
    page_title="MY Market Sentiment",
    page_icon="📈",
    layout="wide",
    initial_sidebar_state="expanded",
)

# -------------------------------------------------------------------
# DB imports (lazy — so dashboard works even without scheduler running)
# -------------------------------------------------------------------
@st.cache_resource
def get_db():
    from db.database import init_db
    init_db()
    return True


get_db()

from db.database import (
    fetch_recent,
    fetch_top_movers,
    get_sentiment_summary,
    fetch_by_ticker,
)
from nlp.sentiment import aggregate_sentiment

# -------------------------------------------------------------------
# Sidebar controls
# -------------------------------------------------------------------
st.sidebar.title("🇲🇾 MY Sentiment Analyser")
st.sidebar.markdown("---")

hours_back = st.sidebar.slider("Look-back window (hours)", 6, 168, 24, step=6)
min_impact = st.sidebar.slider("Min |impact| to show", 0.0, 1.0, 0.0, step=0.05)

st.sidebar.markdown("---")
ticker_search = st.sidebar.text_input("Search ticker (e.g. MAYBANK)", "").upper().strip()

st.sidebar.markdown("---")
if st.sidebar.button("🔄 Refresh data"):
    st.cache_data.clear()
    st.rerun()

# -------------------------------------------------------------------
# Load data
# -------------------------------------------------------------------
@st.cache_data(ttl=300)  # cache 5 min
def load_articles(hours, min_imp):
    arts = fetch_recent(hours=hours, limit=1000)
    df = pd.DataFrame(arts)
    if df.empty:
        return df

    df["published_at"] = pd.to_datetime(df["published_at"], utc=True, errors="coerce")
    df["impact_score"] = pd.to_numeric(df["impact_score"], errors="coerce").fillna(0)
    df["sentiment_score"] = pd.to_numeric(df["sentiment_score"], errors="coerce").fillna(0)

    # Filter by min impact
    df = df[df["impact_score"].abs() >= min_imp]

    # Colour mapping
    df["colour"] = df["sentiment_label"].map({
        "positive": "#22c55e",
        "negative": "#ef4444",
        "neutral": "#94a3b8",
    }).fillna("#94a3b8")

    return df


df = load_articles(hours_back, min_impact)
summary = get_sentiment_summary(hours=hours_back)

# -------------------------------------------------------------------
# Header metrics
# -------------------------------------------------------------------
st.title("📊 Malaysia Market Sentiment Dashboard")
st.caption(f"Last {hours_back}h of news · Updated {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M')} UTC")

if summary and summary.get("total", 0) > 0:
    col1, col2, col3, col4, col5 = st.columns(5)
    total = summary.get("total") or 1  # avoid division by zero

    col1.metric("Total articles", f"{summary.get('total', 0):,}")
    col2.metric("🟢 Positive", summary.get("positive", 0),
                delta=f"{summary.get('positive', 0)/total*100:.0f}%")
    col3.metric("🔴 Negative", summary.get("negative", 0),
                delta=f"{summary.get('negative', 0)/total*100:.0f}%")
    col4.metric("⚪ Neutral", summary.get("neutral", 0))

    avg_impact = summary.get("avg_impact") or 0
    col5.metric("Avg impact", f"{avg_impact:+.3f}",
                delta="bullish" if avg_impact > 0.05 else ("bearish" if avg_impact < -0.05 else "neutral"))
else:
    st.warning("No scored articles found. Run the scraper first: `python -m scheduler.scheduler --once`")

st.markdown("---")

if df.empty:
    st.info("No articles to display for this time window yet.")
    st.stop()

# -------------------------------------------------------------------
# Charts row
# -------------------------------------------------------------------
col_a, col_b = st.columns(2)

with col_a:
    st.subheader("Sentiment over time")
    time_df = df.copy()
    time_df["hour"] = time_df["published_at"].dt.floor("h")
    hourly = (
        time_df.groupby(["hour", "sentiment_label"])
        .size()
        .reset_index(name="count")
    )
    if not hourly.empty:
        fig = px.bar(
            hourly, x="hour", y="count", color="sentiment_label",
            color_discrete_map={"positive": "#22c55e", "negative": "#ef4444", "neutral": "#94a3b8"},
            labels={"hour": "", "count": "Articles", "sentiment_label": "Sentiment"},
        )
        fig.update_layout(margin=dict(l=0, r=0, t=0, b=0), height=280,
                          legend=dict(orientation="h", yanchor="bottom", y=1.02))
        st.plotly_chart(fig, use_container_width=True)

with col_b:
    st.subheader("Sentiment by source")
    agg = aggregate_sentiment(df.to_dict("records"), group_by="source")
    agg_df = pd.DataFrame([
        {"source": k, "avg_impact": v["avg_impact"], "articles": v["article_count"]}
        for k, v in agg.items()
    ]).head(12)
    if not agg_df.empty:
        agg_df = agg_df.sort_values("avg_impact")
        fig2 = px.bar(
            agg_df, x="avg_impact", y="source", orientation="h",
            color="avg_impact", color_continuous_scale=["#ef4444", "#94a3b8", "#22c55e"],
            range_color=[-1, 1],
            labels={"avg_impact": "Avg impact score", "source": ""},
        )
        fig2.update_layout(margin=dict(l=0, r=0, t=0, b=0), height=280,
                           coloraxis_showscale=False)
        st.plotly_chart(fig2, use_container_width=True)

# -------------------------------------------------------------------
# Ticker search
# -------------------------------------------------------------------
if ticker_search:
    st.subheader(f"🔍 Articles mentioning {ticker_search}")
    ticker_arts = fetch_by_ticker(ticker_search, limit=30)
    if ticker_arts:
        ticker_df = pd.DataFrame(ticker_arts)
        for _, row in ticker_df.iterrows():
            label_color = {"positive": "🟢", "negative": "🔴", "neutral": "⚪"}.get(
                row.get("sentiment_label", "neutral"), "⚪")
            st.markdown(
                f"{label_color} **[{row['title']}]({row['url']})** "
                f"— {row.get('source', '')} · impact: `{row.get('impact_score', 0):+.2f}`"
            )
    else:
        st.info(f"No articles found for {ticker_search}")
    st.markdown("---")

# -------------------------------------------------------------------
# Top movers
# -------------------------------------------------------------------
st.subheader("⚡ Top impact articles (last 48h)")
movers = fetch_top_movers(limit=15)
if movers:
    for art in movers:
        label = art.get("sentiment_label", "neutral")
        icon = {"positive": "🟢", "negative": "🔴"}.get(label, "⚪")
        tickers = ", ".join(art.get("tickers_mentioned") or []) or "—"
        impact = art.get("impact_score", 0)
        st.markdown(
            f"{icon} **[{art['title']}]({art['url']})** "
            f"| `{impact:+.2f}` | {art.get('source', '')} | tickers: _{tickers}_"
        )

# -------------------------------------------------------------------
# Full article table
# -------------------------------------------------------------------
st.subheader("📋 All articles")
display_cols = ["published_at", "sentiment_label", "impact_score", "title", "source", "tickers_mentioned"]
display_cols = [c for c in display_cols if c in df.columns]
st.dataframe(
    df[display_cols].sort_values("impact_score", key=abs, ascending=False),
    use_container_width=True,
    height=400,
    column_config={
        "impact_score": st.column_config.ProgressColumn("Impact", min_value=-1, max_value=1, format="%+.2f"),
        "sentiment_label": st.column_config.TextColumn("Sentiment"),
        "published_at": st.column_config.DatetimeColumn("Published", format="DD MMM HH:mm"),
        "tickers_mentioned": st.column_config.ListColumn("Tickers"),
    }
)
