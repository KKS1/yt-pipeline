"""
Free-mode topic and script generation for the trending channel.

Trend discovery uses Google Trends RSS. Script generation uses Groq's
OpenAI-compatible free-tier API when GROQ_API_KEY is configured.
"""

import json
import os
import re
from html import unescape
from urllib.parse import quote
import xml.etree.ElementTree as ET

import requests
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from groq_client import GROQ_MODEL, groq_chat_json, parse_groq_json

PUBLISHED_TOPICS_FILE = Path(__file__).resolve().parent / "trending_published_topics.json"

def get_published_topics() -> list:
    if PUBLISHED_TOPICS_FILE.exists():
        try:
            with open(PUBLISHED_TOPICS_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                return data if isinstance(data, list) else []
        except Exception as e:
            print(f"Error loading published topics: {e}")
    return []

def save_published_topic(topic: str):
    published = get_published_topics()
    if topic not in published:
        published.append(topic)
        # Keep history to a reasonable size
        if len(published) > 500:
            published = published[-500:]
        try:
            with open(PUBLISHED_TOPICS_FILE, "w", encoding="utf-8") as f:
                json.dump(published, f, indent=2, ensure_ascii=False)
        except Exception as e:
            print(f"Error saving published topic: {e}")

DEFAULT_REGION = "CA"
DEFAULT_TRENDS_URL = (
    "https://trends.google.com/trending/rss?geo={region}"
)
DAILY_INSIGHTS_BRAND = """
Channel: Daily Insights Hub
Promise: The world explained — daily.
Editorial lanes: finance, health, AI, true crime, lifestyle, science, culture, and useful facts.
Voice: clear, engaging, intelligent, and time-respectful.
Standard: no fluff, no filler, no hype for its own sake. Explain why the story matters.
"""

UNSAFE_TOPIC_PATTERNS = [
    r"\belection\b",
    r"\bwar\b",
    r"\bshooting\b",
    r"\bmurder\b",
    r"\bterror\b",
    r"\bdead\b",
    r"\bdeath\b",
    r"\btrial\b",
    r"\bscandal\b",
    r"\babuse\b",
    r"\bassault\b",
    r"\bpolitic",
    r"\btrump\b",
    r"\bbiden\b",
    r"\bpoilievre\b",
    r"\btrudeau\b",
]


def parse_google_trends_rss(xml_text: str) -> list[str]:
    """Extract trend titles from Google Trends RSS XML."""
    if not xml_text.strip():
        return []

    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return []

    topics = []
    for item in root.findall(".//item"):
        title = item.findtext("title", default="").strip()
        title = unescape(title)
        title = re.sub(r"\s+", " ", title)
        if title and title.lower() != "google trends":
            topics.append(title)

    return dedupe_preserve_order(topics)


def dedupe_preserve_order(values: list[str]) -> list[str]:
    seen = set()
    deduped = []
    for value in values:
        key = value.casefold()
        if key not in seen:
            seen.add(key)
            deduped.append(value)
    return deduped


def is_safe_trending_topic(topic: str) -> bool:
    text = topic.casefold()
    return not any(re.search(pattern, text) for pattern in UNSAFE_TOPIC_PATTERNS)


def filter_topics(topics: list[str], limit: int = 20) -> list[str]:
    clean = []
    for topic in topics:
        if len(topic) < 3 or len(topic) > 90:
            continue
        if not is_safe_trending_topic(topic):
            continue
        clean.append(topic)
    return dedupe_preserve_order(clean)[:limit]


def fetch_google_trends(region: str = DEFAULT_REGION) -> list[str]:
    """Fetch and filter Google Trends RSS topics for a country/region."""
    url = DEFAULT_TRENDS_URL.format(region=quote(region.upper()))
    response = requests.get(url, timeout=30)
    response.raise_for_status()
    return filter_topics(parse_google_trends_rss(response.text))


def _groq_chat(prompt: str, max_tokens: int, temperature: float = 0.7) -> dict:
    return groq_chat_json(
        messages=[{"role": "user", "content": prompt}],
        max_tokens=max_tokens,
        temperature=temperature,
    )


def choose_topic_with_groq(topics: list[str], region: str = DEFAULT_REGION) -> dict:
    published_topics = get_published_topics()
    recent_topics = published_topics[-50:] if published_topics else []
    avoid_instruction = ""
    if recent_topics:
        avoid_instruction = f"""
    CRITICAL: Avoid repeating or covering the same ground as these recently published topics:
    {json.dumps(recent_topics, indent=2)}
    """

    prompt = f"""
You are a YouTube content strategist for Daily Insights Hub.

{DAILY_INSIGHTS_BRAND}
Pick the SINGLE best topic for a broad English-speaking audience in {region}.
{avoid_instruction}
Avoid politics, tragedy, unverified breaking news, and topics that need live updates.
Prefer topics that can teach viewers something useful or surprising across finance, health,
AI, true crime, lifestyle, science, culture, and high-interest explainers.

Trending topics:
{chr(10).join(f"- {topic}" for topic in topics)}

Return ONLY valid JSON:
{{
  "chosen_topic": "exact topic",
  "angle": "specific curiosity-driven explainer angle",
  "why": "one sentence reason",
  "keywords": ["keyword one", "keyword two", "keyword three", "keyword four", "keyword five"],
  "stock_keyword": "2-4 word Pexels search phrase"
}}
"""
    data = _groq_chat(prompt, max_tokens=1000, temperature=0.4)
    return normalize_topic_data(data, fallback_topic=topics[0] if topics else "Canada trends")


TRENDING_SCRIPT_FORMATS = {
    "shorts": {
        "prompt": """
You are an expert YouTube Shorts scriptwriter for a faceless daily trending insights channel.

{brand}

Topic: {chosen_topic}
Angle: {angle}
Keywords: {keywords}

Write a clear 45-90 second YouTube Short for general viewers.
Tone: clear, engaging, intelligent, current, and conversational.

Rules:
- Generate 3 strong title options and choose the one most likely to maximize CTR for YouTube.
- Titles should be under 70 characters, front-load the main topic or keyword, and use curiosity or benefit language.
- Start with a strong hook in the first 3 seconds.
- Use this pacing: hook, what happened, why it matters, what to watch next.
- Keep the spoken script to 120-230 words.
- Do not present speculation as fact.
- Avoid inflammatory language and political persuasion.
- Use [PAUSE] sparingly and [VISUAL: short vertical cue] for mobile-friendly B-roll moments.
- No markdown and no "in today's video" filler.
- No fluff, no filler, and no vague hype.
- End with one short comment or follow prompt.

Return ONLY valid JSON:
{{
  "title": "YouTube Shorts title under 70 characters",
  "title_options": ["string"],
  "description": "string (80-120 word YouTube description with relevant keywords, a strong first-line hook, #Shorts, and relevant hashtags that mirror the 'tags' list below)",
  "tags": ["string (Provide 5-8 SEO-focused tags)"],
  "thumbnail_text": "3-5 bold words",
  "stock_keyword": "2-4 word Pexels search phrase",
  "script": "full spoken script with visual cues",
  "word_count": 0,
  "estimated_duration_seconds": 0,
  "video_format": "shorts"
}}
""",
        "max_tokens": 1800,
    },
    "explainer": {
        "prompt": """
You are an expert YouTube scriptwriter for a faceless trending explainer channel.

{brand}

Topic: {chosen_topic}
Angle: {angle}
Keywords: {keywords}

Write a clear, calm 5-7 minute explainer that can show up in search the same day a topic peaks.
Tone: clear, engaging, intelligent, informed, accessible, and conversational.

Rules:
- Generate 3 strong title options and choose the one most likely to maximize CTR for YouTube.
- Titles should be under 70 characters, front-load the main topic or keyword, and use curiosity or benefit language.
- Start with a strong hook in the first 15 seconds.
- Use this structure: hook, brief context, 4-5 main points, what happens next, concise CTA.
- Keep the spoken script to 700-980 words.
- Do not present speculation as fact.
- Avoid inflammatory language and political persuasion.
- Use [PAUSE] sparingly and [VISUAL: short cue] for useful B-roll moments.
- No markdown and no "in today's video" filler.
- No fluff, no filler, and no vague hype.
- Respect the viewer's time and intelligence.

Return ONLY valid JSON:
{{
  "title": "YouTube title under 70 characters",
  "title_options": ["string"],
  "description": "string (150-word YouTube description with relevant keywords, a strong first-line hook, one CTA, and relevant hashtags that mirror the 'tags' list below)",
  "tags": ["string (Provide 5-8 SEO-focused tags)"],
  "thumbnail_text": "3-5 bold words",
  "stock_keyword": "2-4 word Pexels search phrase",
  "script": "full spoken script with visual cues",
  "word_count": 0,
  "estimated_duration_seconds": 0,
  "video_format": "explainer"
}}
""",
        "max_tokens": 4200,
    },
}


def generate_script_with_groq(topic_data: dict, video_format: str = "shorts") -> dict:
    script_format = TRENDING_SCRIPT_FORMATS.get(video_format, TRENDING_SCRIPT_FORMATS["shorts"])
    prompt = script_format["prompt"].format(
        brand=DAILY_INSIGHTS_BRAND.strip(),
        chosen_topic=topic_data["chosen_topic"],
        angle=topic_data["angle"],
        keywords=", ".join(topic_data["keywords"]),
    )
    data = _groq_chat(prompt, max_tokens=script_format["max_tokens"], temperature=0.75)
    data.setdefault("video_format", video_format if video_format in TRENDING_SCRIPT_FORMATS else "shorts")
    return normalize_script_data(data, topic_data)


def normalize_topic_data(data: dict, fallback_topic: str) -> dict:
    chosen = str(data.get("chosen_topic") or fallback_topic).strip()
    keywords = data.get("keywords") or [chosen]
    if isinstance(keywords, str):
        keywords = [k.strip() for k in keywords.split(",") if k.strip()]

    return {
        "chosen_topic": chosen,
        "angle": str(data.get("angle") or f"Why {chosen} is trending right now").strip(),
        "why": str(data.get("why") or "").strip(),
        "keywords": [str(k).strip() for k in keywords if str(k).strip()][:8],
        "stock_keyword": str(data.get("stock_keyword") or keywords[0] or chosen).strip(),
    }


def normalize_script_data(data: dict, topic_data: dict) -> dict:
    title_options = data.get("title_options")
    title = data.get("title") or (title_options[0] if title_options else topic_data["chosen_topic"])
    tags = data.get("tags") or topic_data["keywords"]
    if isinstance(tags, str):
        tags = [t.strip() for t in tags.split(",") if t.strip()]

    script = str(data.get("script") or "").strip()
    if not script:
        raise ValueError("Groq response did not include a script.")

    stock_keyword = str(data.get("stock_keyword") or topic_data.get("stock_keyword") or tags[0]).strip()

    return {
        "title": str(title).strip()[:100],
        "description": str(data.get("description") or "").strip(),
        "tags": [str(tag).strip() for tag in tags if str(tag).strip()][:15],
        "thumbnail_text": str(data.get("thumbnail_text") or "").strip(),
        "stock_keyword": stock_keyword,
        "script": script,
        "word_count": int(data.get("word_count") or len(script.split())),
        "estimated_duration_seconds": int(data.get("estimated_duration_seconds") or round(len(script.split()) / 2.4)),
        "video_format": str(data.get("video_format") or "shorts").strip(),
        "chosen_topic": topic_data["chosen_topic"],
        "angle": topic_data["angle"],
        "keywords": topic_data["keywords"],
    }


def generate_trending_package(
    topic: str = None,
    region: str = DEFAULT_REGION,
    video_format: str = "shorts",
    topic_data: dict = None,
) -> dict:
    """Create a complete trending video script package."""
    if topic_data:
        topic_data = normalize_topic_data(topic_data, fallback_topic=topic_data.get("chosen_topic", "Trending topic"))
    elif topic:
        topic_data = normalize_topic_data(
            {
                "chosen_topic": topic,
                "angle": f"Why {topic} is trending right now",
                "keywords": [topic],
                "stock_keyword": topic,
            },
            fallback_topic=topic,
        )
    else:
        topics = fetch_google_trends(region)
        if not topics:
            raise RuntimeError(f"No usable Google Trends topics found for region {region}.")
        topic_data = choose_topic_with_groq(topics, region=region)

    package = generate_script_with_groq(topic_data, video_format=video_format)
    save_published_topic(package.get("chosen_topic", topic_data["chosen_topic"]))
    return package
