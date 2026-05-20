"""
Claude Prompting System — YouTube Automation Pipeline
Handles: trending narrated, family-friendly, lofi music channels
"""

import anthropic
import json
import re

client = anthropic.Anthropic()  # uses ANTHROPIC_API_KEY env var
MODEL = "claude-sonnet-4-20250514"

DAILY_INSIGHTS_BRAND = """
Channel: Daily Insights Hub
Promise: The world explained — daily.
Editorial lanes: finance, health, AI, true crime, lifestyle, science, culture, and useful facts.
Voice: clear, engaging, intelligent, and time-respectful.
Standard: no fluff, no filler, no hype for its own sake. Explain why the story matters.
"""


# ─────────────────────────────────────────────
# CHANNEL CONFIGS
# ─────────────────────────────────────────────

CHANNEL_CONFIGS = {
    "trending": {
        "name": "Daily Insights Hub",
        "tone": "clear, engaging, intelligent, time-respectful",
        "audience": "general adults 18-45",
        "video_length_min": 0.75,
        "video_length_max": 1.5,
        "style": "world-explained-daily narrator",
    },
    "family": {
        "name": "Family-Friendly",
        "tone": "fun, energetic, inclusive — enjoyable for kids AND adults",
        "audience": "families, parents with kids 6-14, also fun for adults",
        "video_length_min": 4,
        "video_length_max": 8,
        "style": "game show host energy, clear pacing, lots of suspense before reveals",
    },
    "lofi": {
        "name": "Lofi Study Music",
        "tone": "minimal, atmospheric, no narration needed",
        "audience": "students, remote workers, anyone needing focus music",
        "video_length_min": 120,
        "video_length_max": 180,
        "style": "purely instrumental — generates a scene description + tracklist only",
    },
}


# ─────────────────────────────────────────────
# 1. TOPIC SCORER
# ─────────────────────────────────────────────

def score_and_pick_topic(raw_topics: list[str], channel_type: str) -> dict:
    """
    Given a list of raw trending topics, pick the best one for the channel
    and return structured metadata for script generation.
    """
    config = CHANNEL_CONFIGS[channel_type]

    prompt = f"""You are a YouTube content strategist specializing in {config['name']} channels.

{DAILY_INSIGHTS_BRAND if channel_type == 'trending' else ''}

Given these trending topics, pick the SINGLE best one for a {config['name']} YouTube channel.
Target audience: {config['audience']}

Trending topics:
{chr(10).join(f'- {t}' for t in raw_topics)}

Score each topic on:
1. Search volume potential (1-10)
2. Competition level — lower is better (1-10, 10 = very low competition)
3. Monetization friendliness (1-10)
4. Evergreen potential — will it still get views in 6 months? (1-10)
5. Fit for this channel type (1-10)

Pick the winner and return ONLY valid JSON, no markdown, no explanation:
{{
  "chosen_topic": "exact topic string",
  "angle": "specific angle/hook that makes this video stand out",
  "scores": {{
    "search_volume": 0,
    "low_competition": 0,
    "monetization": 0,
    "evergreen": 0,
    "channel_fit": 0,
    "total": 0
  }},
  "why": "one sentence reason this topic wins",
  "keywords": ["kw1", "kw2", "kw3", "kw4", "kw5"]
}}"""

    response = client.messages.create(
        model=MODEL,
        max_tokens=1000,
        messages=[{"role": "user", "content": prompt}]
    )

    raw = response.content[0].text.strip()
    # Strip any accidental markdown fences
    raw = re.sub(r"```json|```", "", raw).strip()
    return json.loads(raw)


# ─────────────────────────────────────────────
# 2. SCRIPT GENERATOR — TRENDING CHANNEL
# ─────────────────────────────────────────────

def generate_trending_script(topic_data: dict) -> dict:
    """Generate a full narrated script for the trending channel."""

    prompt = f"""You are an expert YouTube Shorts scriptwriter for Daily Insights Hub.
{DAILY_INSIGHTS_BRAND}

Style: {CHANNEL_CONFIGS['trending']['style']}
Tone: {CHANNEL_CONFIGS['trending']['tone']}
Target length: 45–90 seconds when read at about 140–160 words/minute

Topic: {topic_data['chosen_topic']}
Angle: {topic_data['angle']}
Keywords to weave in naturally: {', '.join(topic_data['keywords'])}

Write a complete YouTube Short script with this exact structure:

HOOK (first 3 seconds — must be instantly clear and curiosity-driven):

WHAT HAPPENED (one concise beat):

WHY IT MATTERS (two concise beats):

WHAT TO WATCH NEXT (one useful forward-looking beat):

CALL TO ACTION (one short comment or follow prompt):

Rules:
- Write exactly as it will be spoken — no markdown headers in the final narration
- Use [PAUSE] for dramatic effect
- Use [EMPHASIS] before a word that should be stressed
- Use [VISUAL: description] to suggest mobile-friendly vertical B-roll or images
- No filler phrases like "in today's video" or "don't forget to like"
- No fluff, no filler, and no vague hype
- Respect the viewer's time and intelligence
- Total word count should be 120–230 words
- Include #Shorts in the description

Return ONLY valid JSON:
{{
  "title_options": ["title1 (under 60 chars)", "title2", "title3"],
  "description": "YouTube Shorts description 80-120 words with keywords naturally placed",
  "tags": ["tag1", "tag2", "tag3", "tag4", "tag5", "tag6", "tag7", "tag8"],
  "thumbnail_text": "3-5 bold words for thumbnail overlay",
  "script": "full script text with [PAUSE], [EMPHASIS], [VISUAL:] markers",
  "word_count": 0,
  "estimated_duration_seconds": 0,
  "video_format": "shorts"
}}"""

    response = client.messages.create(
        model=MODEL,
        max_tokens=4000,
        messages=[{"role": "user", "content": prompt}]
    )

    raw = response.content[0].text.strip()
    raw = re.sub(r"```json|```", "", raw).strip()
    return json.loads(raw)


# ─────────────────────────────────────────────
# 3. SCRIPT GENERATOR — FAMILY CHANNEL
# ─────────────────────────────────────────────

FAMILY_FORMATS = [
    "this_or_that",
    "would_you_rather",
    "fun_facts",
    "riddles",
    "guess_the_animal",
    "brain_teasers",
]

def generate_family_script(format_type: str = "this_or_that", topic: str = None) -> dict:
    """Generate a family-friendly video script."""

    format_instructions = {
        "this_or_that": "Present 15–20 'This or That?' choices. Each one has two options. Build from easy/funny to harder/more surprising. Add a fun fact after every 3rd question.",
        "would_you_rather": "Present 12–15 'Would You Rather?' dilemmas. Make them funny, relatable, and safe for all ages. Some should be easy, some genuinely tricky. Encourage pausing to choose.",
        "fun_facts": "Share 20–25 mind-blowing fun facts. Group them by theme. After each fact, add a short '...and did you know?' bridge to keep momentum.",
        "riddles": "Present 15 riddles, ordered easy to hard. Give thinking time [PAUSE 5 SECONDS] after each riddle before revealing the answer with excitement.",
        "guess_the_animal": "Describe 12 animals using 3 clues each, from vague to obvious. Build suspense. Reveal with enthusiasm.",
        "brain_teasers": "Present 10 brain teasers with visual descriptions. Give thinking time. Explain the answer clearly.",
    }

    topic_line = f"Theme/topic: {topic}" if topic else "Choose a fun, universally appealing theme"

    prompt = f"""You are a scriptwriter for a family-friendly YouTube channel watched by kids AND adults together.
Style: {CHANNEL_CONFIGS['family']['style']}
Tone: {CHANNEL_CONFIGS['family']['tone']}
Format: {format_type.replace('_', ' ').title()}

{topic_line}

Format instructions: {format_instructions[format_type]}

CRITICAL positioning rules (keeps full ad monetization):
- Say "for the whole family" not "for kids"  
- Include at least 2 elements adults find genuinely interesting (surprising facts, nostalgia, harder options)
- Never target exclusively at children
- Energy level: excited game show host, not children's TV presenter

Script structure:
- HOOK: Start mid-action ("Okay family, here's a tough one...")
- BRIEF INTRO: 20 seconds max
- MAIN CONTENT: the questions/facts/riddles with [VISUAL:] and [PAUSE] markers
- OUTRO: Fun challenge — tell them to comment their score/answer

Return ONLY valid JSON:
{{
  "title_options": ["title1", "title2", "title3"],
  "description": "150 word YouTube description, family-friendly keywords",
  "tags": ["tag1","tag2","tag3","tag4","tag5","tag6","tag7","tag8"],
  "thumbnail_text": "punchy 3-5 word thumbnail text",
  "script": "full script with [PAUSE], [VISUAL:], [EMPHASIS] markers",
  "word_count": 0,
  "estimated_duration_min": 0
}}"""

    response = client.messages.create(
        model=MODEL,
        max_tokens=4000,
        messages=[{"role": "user", "content": prompt}]
    )

    raw = response.content[0].text.strip()
    raw = re.sub(r"```json|```", "", raw).strip()
    return json.loads(raw)


# ─────────────────────────────────────────────
# 4. LOFI VIDEO METADATA GENERATOR
# ─────────────────────────────────────────────

LOFI_MOODS = [
    "late night study session",
    "rainy day café",
    "cozy winter library",
    "spring morning focus",
    "city lights at midnight",
    "forest cabin study",
    "tokyo night café",
    "cloudy afternoon work",
]

def generate_lofi_metadata(mood: str = None, duration_hours: int = 3) -> dict:
    """Generate title, description, tags, and visual scene for a lofi music video."""

    if not mood:
        import random
        mood = random.choice(LOFI_MOODS)

    prompt = f"""You are a YouTube metadata expert for lofi/study music channels.

Mood/theme: {mood}
Duration: {duration_hours} hours

Generate metadata that will rank well for study music searches.

Key search terms to target: "lofi hip hop", "study music", "focus music", 
"chill beats", "lofi beats to study to", "homework music", "concentration music"

Return ONLY valid JSON:
{{
  "title": "YouTube title under 70 chars, must include mood + duration hint",
  "description": "200 word description. First 2 lines must hook with the mood. Include timestamps every 30min like '00:00 - Track 1 name'. List benefits: focus, study, relax. End with subscribe CTA.",
  "tags": ["lofi hip hop","study music","focus music","chill beats","lofi beats","homework music","concentration","lofi chill","beats to study to","lofi mix"],
  "thumbnail_concept": "Describe the ideal thumbnail scene in 2 sentences — cozy, atmospheric, anime-adjacent",
  "visual_scene": "Describe a 30-second looping animation scene for the video background — what's in the scene, time of day, weather, small animated details like steam from coffee, rain on window, etc.",
  "mood_tags": ["tag1","tag2","tag3"],
  "tracklist": [
    {{"number": 1, "name": "atmospheric track name", "timestamp": "00:00"}},
    {{"number": 2, "name": "atmospheric track name", "timestamp": "00:30"}}
  ]
}}

Generate a full tracklist with one entry per 30 minutes ({duration_hours * 2} total tracks).
Make track names evocative and mood-appropriate."""

    response = client.messages.create(
        model=MODEL,
        max_tokens=2000,
        messages=[{"role": "user", "content": prompt}]
    )

    raw = response.content[0].text.strip()
    raw = re.sub(r"```json|```", "", raw).strip()
    return json.loads(raw)


# ─────────────────────────────────────────────
# 5. WEEKLY DIGEST EMAIL GENERATOR
# ─────────────────────────────────────────────

def generate_weekly_digest(videos_published: list[dict], videos_queued: list[dict], analytics: dict) -> str:
    """Generate your weekly 'what happened' digest email in plain text."""

    prompt = f"""Generate a concise weekly digest email for a YouTube channel owner.
They want minimal reading time — bullet points, key numbers only.

Videos published this week:
{json.dumps(videos_published, indent=2)}

Videos queued for next week:
{json.dumps(videos_queued, indent=2)}

Analytics snapshot:
{json.dumps(analytics, indent=2)}

Write a plain-text email (no HTML) that takes under 2 minutes to read.
Format:
- Subject line
- 3 bullet points: what performed best, any anomalies, action needed (if any)
- Published this week (list with view counts)
- Queued next week (list with expected publish times)
- One recommendation based on the data"""

    response = client.messages.create(
        model=MODEL,
        max_tokens=800,
        messages=[{"role": "user", "content": prompt}]
    )

    return response.content[0].text


# ─────────────────────────────────────────────
# QUICK TEST
# ─────────────────────────────────────────────

if __name__ == "__main__":
    print("Testing topic scorer...")
    sample_topics = [
        "why billionaires don't sleep 8 hours",
        "the truth about seed oils",
        "AI is replacing these 10 jobs by 2026",
        "why gen z is quitting social media",
        "the hidden cost of electric vehicles",
    ]

    result = score_and_pick_topic(sample_topics, "trending")
    print(json.dumps(result, indent=2))

    print("\nTesting family script generator...")
    family = generate_family_script("this_or_that", "animals vs food")
    print(f"Title: {family['title_options'][0]}")
    print(f"Word count: {family['word_count']}")
    print(f"Duration: {family['estimated_duration_min']} min")

    print("\nTesting lofi metadata...")
    lofi = generate_lofi_metadata("rainy day café", 3)
    print(f"Title: {lofi['title']}")
    print(f"Tracks: {len(lofi['tracklist'])}")
    print("All prompts working.")
