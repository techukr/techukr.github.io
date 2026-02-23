#!/usr/bin/env python3
"""
fetch_rss.py — Fetches RSS feeds, categorizes by keyword, outputs Hugo markdown files.
Runs inside GitHub Actions every 30 minutes.
"""

import os
import re
import json
import hashlib
from datetime import datetime, timezone, timedelta
from pathlib import Path

import yaml
import feedparser
from slugify import slugify

# ============================================================
# CONFIGURATION
# ============================================================

CONTENT_DIR = Path("content/news")
DATA_DIR = Path("data")
SEEN_FILE = DATA_DIR / "seen_articles.json"
MAX_ARTICLE_AGE_DAYS = 3  # Remove articles older than this
MAX_ARTICLES_PER_RUN = 200  # Safety cap

# ============================================================
# KEYWORD → CATEGORY MAPPING
# ============================================================

CATEGORY_KEYWORDS = {
    "uk": [
        "uk", "britain", "british", "england", "scotland", "wales",
        "northern ireland", "london", "nhs", "downing street",
        "westminster", "bbc", "premier league"
    ],
    "world": [
        "us ", "united states", "china", "russia", "ukraine", "europe",
        "asia", "africa", "middle east", "india", "japan", "germany",
        "france", "australia", "brazil", "canada", "mexico", "iran"
    ],
    "politics": [
        "parliament", "election", "vote", "labour", "conservative",
        "democrat", "republican", "senate", "congress", "minister",
        "president", "policy", "government", "legislation", "trump",
        "biden", "starmer", "political"
    ],
    "business": [
        "market", "stock", "economy", "gdp", "ftse", "dow jones",
        "nasdaq", "inflation", "bank", "trade", "revenue", "profit",
        "earnings", "ipo", "acquisition", "merger", "startup",
        "investment", "finance", "crypto", "bitcoin", "oil price"
    ],
    "technology": [
        "ai ", "artificial intelligence", "tech", "software", "apple",
        "google", "microsoft", "amazon", "meta", "openai", "chatgpt",
        "semiconductor", "chip", "nvidia", "smartphone", "app ",
        "cybersecurity", "data breach", "hack", "robot", "quantum"
    ],
    "science": [
        "research", "study finds", "scientists", "nasa", "space",
        "climate", "discovery", "physics", "biology", "medical",
        "vaccine", "gene", "evolution", "mars", "satellite", "telescope"
    ],
    "sport": [
        "football", "soccer", "cricket", "rugby", "tennis", "f1",
        "formula 1", "olympics", "world cup", "champions league",
        "nba", "nfl", "premier league", "transfer", "goal", "match",
        "tournament", "athlete", "coach"
    ],
    "entertainment": [
        "film", "movie", "music", "celebrity", "tv show", "netflix",
        "streaming", "award", "oscar", "grammy", "album", "concert",
        "actor", "actress", "director", "box office"
    ],
    "health": [
        "health", "medical", "covid", "vaccine", "hospital", "drug",
        "disease", "mental health", "cancer", "obesity", "diet",
        "fitness", "surgery", "who ", "pandemic"
    ],
    "environment": [
        "climate change", "global warming", "emission", "renewable",
        "solar", "wind power", "pollution", "wildfire", "flood",
        "drought", "deforestation", "ecosystem", "biodiversity"
    ],
}

# ============================================================
# HELPER FUNCTIONS
# ============================================================
import re

def clean_url(url):
    """Strip markdown link syntax [text](url) → plain url"""
    if url is None:
        return ""
    # Match [anything](url) and extract just the url
    match = re.match(r'^\[.*?\]\((https?://[^)]+)\)$', url.strip())
    if match:
        return match.group(1)
    return url.strip()

def load_seen_articles():
    """Load set of already-processed article hashes."""
    if SEEN_FILE.exists():
        with open(SEEN_FILE, "r") as f:
            data = json.load(f)
        return set(data.get("seen", []))
    return set()


def save_seen_articles(seen: set):
    """Persist seen article hashes to JSON."""
    SEEN_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(SEEN_FILE, "w") as f:
        json.dump({"seen": list(seen), "updated": datetime.now(timezone.utc).isoformat()}, f)


def article_hash(url: str) -> str:
    """Generate a short hash from URL for dedup."""
    return hashlib.md5(url.encode()).hexdigest()[:12]


def categorize_article(title: str) -> list:
    """Match article title against keyword lists, return matching categories."""
    title_lower = f" {title.lower()} "
    matched = []
    for category, keywords in CATEGORY_KEYWORDS.items():
        for kw in keywords:
            if kw.lower() in title_lower:
                matched.append(category)
                break
    if not matched:
        matched.append("general")
    return matched


def time_ago(dt: datetime) -> str:
    """Format a datetime as '5m', '2h', '1d' relative string."""
    now = datetime.now(timezone.utc)
    diff = now - dt
    minutes = int(diff.total_seconds() / 60)
    if minutes < 1:
        return "now"
    elif minutes < 60:
        return f"{minutes}m"
    elif minutes < 1440:
        return f"{minutes // 60}h"
    else:
        return f"{minutes // 1440}d"


def clean_title(title: str) -> str:
    """Remove HTML tags and excess whitespace from title."""
    clean = re.sub(r"<[^>]+>", "", title)
    clean = re.sub(r"\s+", " ", clean).strip()
    return clean


def parse_date(entry) -> datetime:
    """Extract and parse published date from feed entry."""
    for field in ["published_parsed", "updated_parsed"]:
        parsed = entry.get(field)
        if parsed:
            try:
                from time import mktime
                return datetime.fromtimestamp(mktime(parsed), tz=timezone.utc)
            except Exception:
                pass
    return datetime.now(timezone.utc)


# ============================================================
# HUGO MARKDOWN GENERATOR
# ============================================================

def write_hugo_article(article: dict):
    """Write a single article as a Hugo markdown file."""
    slug = slugify(article["title"][:80])
    date_str = article["date"].strftime("%Y-%m-%d")
    filename = f"{date_str}-{slug}.md"
    filepath = CONTENT_DIR / filename

    categories_yaml = "\n".join(f'  - "{c}"' for c in article["categories"])

    frontmatter = f"""---
title: "{article['title'].replace('"', "'")}"
date: {article['date'].isoformat()}
url: "{article['url']}"
link: "{clean_url(article['url'])}"
source: "{clean_url(article['source_url'])}"
source_slug: "{article['source_slug']}"
categories:
{categories_yaml}
time_ago: "{article['time_ago']}"
article_hash: "{article['hash']}"
---
"""
    filepath.parent.mkdir(parents=True, exist_ok=True)
    with open(filepath, "w", encoding="utf-8") as f:
        f.write(frontmatter)

    return filename


# ============================================================
# MAIN: FETCH ALL FEEDS
# ============================================================

def main():
    # Load config
    with open(DATA_DIR / "feeds.yml", "r") as f:
        config = yaml.safe_load(f)

    sources = config.get("sources", [])
    seen = load_seen_articles()
    new_count = 0
    all_articles = []

    print(f"📡 Fetching {len(sources)} RSS sources...")

    for source in sources:
        try:
            feed = feedparser.parse(source["url"])
            entries = feed.entries[:30]  # Cap per source
            print(f"  ✅ {source['name']}: {len(entries)} entries")

            for entry in entries:
                url = entry.get("link", "")
                if not url:
                    continue

                h = article_hash(url)
                if h in seen:
                    continue

                title = clean_title(entry.get("title", "No Title"))
                pub_date = parse_date(entry)

                # Skip articles older than MAX_ARTICLE_AGE_DAYS
                age = datetime.now(timezone.utc) - pub_date
                if age.days > MAX_ARTICLE_AGE_DAYS:
                    continue

                categories = categorize_article(title)

                article = {
                    "title": title,
                    "url": url,
                    "date": pub_date,
                    "source_name": source["name"],
                    "source_slug": source["slug"],
                    "categories": categories,
                    "time_ago": time_ago(pub_date),
                    "hash": h,
                }

                all_articles.append(article)
                seen.add(h)
                new_count += 1

                if new_count >= MAX_ARTICLES_PER_RUN:
                    break

        except Exception as e:
            print(f"  ❌ {source['name']}: {e}")
            continue

        if new_count >= MAX_ARTICLES_PER_RUN:
            break

    # Write Hugo markdown files
    for article in all_articles:
        write_hugo_article(article)

    # Save seen articles (keep last 10000 to prevent unbounded growth)
    seen_list = list(seen)
    if len(seen_list) > 10000:
        seen_list = seen_list[-10000:]
    save_seen_articles(set(seen_list))

    # Clean up old articles from content/news/
    cleanup_old_articles()

    print(f"\n🎉 Done! {new_count} new articles added.")


def cleanup_old_articles():
    """Remove markdown files older than MAX_ARTICLE_AGE_DAYS."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=MAX_ARTICLE_AGE_DAYS)
    cutoff_str = cutoff.strftime("%Y-%m-%d")
    removed = 0

    if CONTENT_DIR.exists():
        for f in CONTENT_DIR.glob("*.md"):
            # Filename starts with date: 2026-02-23-slug.md
            date_part = f.name[:10]
            if date_part < cutoff_str:
                f.unlink()
                removed += 1

    if removed:
        print(f"🗑️  Cleaned up {removed} old articles.")


if __name__ == "__main__":
    main()
