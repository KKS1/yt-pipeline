import json
import os
import random
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from groq_client import groq_chat_json, groq_part_cooldown

# Free tier TPM is 12k; three 7k-cap calls in a row exceed it. Lower cap + pause between parts.
ENGLISH_MAX_TOKENS = int(os.getenv("GROQ_ENGLISH_MAX_TOKENS", "4096"))

ENGLISH_TOPIC_POOL = [
    "Ordering Food at a Restaurant",
    "Discussing Hobbies and Interests",
    "Everyday Office Conversations",
    "Describing People and Personalities",
    "Shopping and Asking for Prices",
    "Talking about Future Plans",
    "Common Idioms for Happiness and Sadness",
    "Discussing Favorite Movies and Books",
    "Talking about Food and Cooking",
    "Giving Advice to a Friend",
    "Phrasal Verbs with 'Get'"
]

WEEKLY_CHALLENGE_TOPIC_POOL = [
    "Speak Confidently in Daily Conversations",
    "Master Essential Phrasal Verbs",
    "Build Better Listening and Speaking Habits",
    "English for Work and Meetings",
    "Travel English Confidence",
    "Small Talk Without Freezing",
    "Tell Better Stories in English",
    "Pronunciation and Natural Rhythm",
]

# Mid-episode sign-offs the model often adds at part boundaries.
_OUTRO_PATTERNS = [
    re.compile(p, re.IGNORECASE)
    for p in (
        r"\bsubscribe\b",
        r"\blike\s+(?:and\s+)?subscribe\b",
        r"\bhit\s+the\s+(?:like|bell)\b",
        r"\bnotification\s+bell\b",
        r"\bthanks?\s+for\s+(?:listening|watching|tuning\s+in|joining)\b",
        r"\btune\s+in\s+(?:next|for\s+more|again)\b",
        r"\bsee\s+you\s+(?:next|soon|later)\b",
        r"\buntil\s+next\s+time\b",
        r"\bdon'?t\s+forget\s+to\s+(?:like|subscribe)\b",
        r"\bEnglishVibesHub\b.*\b(?:bye|goodbye|see\s+you)\b",
        r"\b(?:bye|goodbye)\b.*\bEnglishVibesHub\b",
    )
]

_CTA_PATTERNS = [
    re.compile(p, re.IGNORECASE)
    for p in (
        r"\bsubscribe\b",
        r"\blike\s+(?:and\s+)?subscribe\b",
        r"\bhit\s+the\s+(?:like|bell)\b",
        r"\bnotification\s+bell\b",
        r"\bdon'?t\s+forget\s+to\s+(?:like|subscribe)\b",
        r"\btune\s+in\s+(?:next|for\s+more|again)\b",
        r"\bsee\s+you\s+(?:next|soon|later)\b",
    )
]

_NOT_FINAL_PART_RULES = """
CONTINUITY (THIS IS NOT THE FINAL PART OF THE EPISODE):
- Do NOT thank listeners for watching or say goodbye.
- Do NOT ask viewers to like, subscribe, or hit the bell.
- Do NOT say "see you next time", "tune in next episode", or similar closings.
- End on an open conversation beat so the next part continues naturally.
"""


def is_outro_line(text: str) -> bool:
    return any(p.search(text) for p in _OUTRO_PATTERNS)


def is_cta_line(text: str) -> bool:
    return any(p.search(text) for p in _CTA_PATTERNS)


def generate_dynamic_topic(is_challenge: bool = False) -> str:
    """Ask Groq to generate a fresh, trending English learning topic."""
    type_label = "7-day weekly challenge" if is_challenge else "podcast episode"
    prompt = f"""
    Generate a single, highly engaging topic for an English learning {type_label}.
    The topic should be practical, focused on real-world usage, and appealing to intermediate learners.
    Return ONLY a JSON object with a 'topic' key.
    Example: {{"topic": "Mastering Sarcasm and Irony in English"}}
    """
    try:
        res = call_groq_json(prompt)
        return res.get("topic", random.choice(WEEKLY_CHALLENGE_TOPIC_POOL if is_challenge else ENGLISH_TOPIC_POOL))
    except Exception as e:
        print(f"  Error generating dynamic topic: {e}. Falling back to pool.")
        return random.choice(WEEKLY_CHALLENGE_TOPIC_POOL if is_challenge else ENGLISH_TOPIC_POOL)


def sanitize_dialogue_part(dialogue: list, max_outro_turns_at_end: int = 0, is_intro: bool = False, is_outro: bool = False) -> list:
    """Drop sign-off / CTA lines; Part 3 may keep them only in the last N turns."""
    if not dialogue:
        return []

    # If this is the very first part of the episode, we want to preserve the 
    # intro turns even if they contain "thanks for joining" language.
    prefix = []
    if is_intro:
        keep_prefix = min(3, len(dialogue))
        prefix = [t for t in dialogue[:keep_prefix] if not is_cta_line(t.get("text", ""))]
        dialogue = dialogue[keep_prefix:]

    # If this is the final part of the episode, we want to preserve the 
    # wrap-up turns even if they contain "thanks for listening" language.
    suffix = []
    if is_outro or max_outro_turns_at_end:
        n_to_keep = max(max_outro_turns_at_end, 3)
        keep_suffix = min(n_to_keep, len(dialogue))
        suffix = dialogue[-keep_suffix:]
        dialogue = dialogue[:-keep_suffix]

    # Filter out mid-episode sign-off lines from the remaining body
    body = [t for t in dialogue if not is_outro_line(t.get("text", ""))]
    return prefix + body + suffix


def combine_english_parts(part1_data: dict, part2_data: dict, part3_data: dict, topic: str) -> dict:
    final_script = {
        "title": part1_data.get("title", f"English Conversation: {topic}"),
        "description": part1_data.get(
            "description", f"Learn English with this detailed conversation about {topic}."
        ),
        "tags": part1_data.get("tags", ["English", "Conversation", "Learning", "Phrasal Verbs"]),
        "dialogue": [],
    }

    for i, (part_data, max_outro) in enumerate((
        (part1_data, 0),
        (part2_data, 0),
        (part3_data, 3),
    )):
        cleaned = sanitize_dialogue_part(
            part_data.get("dialogue", []), 
            max_outro, 
            is_intro=(i == 0),
            is_outro=(i == 2)
        )
        removed = len(part_data.get("dialogue", [])) - len(cleaned)
        if removed:
            print(f"  Removed {removed} mid-episode sign-off line(s)")
        final_script["dialogue"].extend(cleaned)

    return final_script


def call_groq_json(user_prompt: str) -> dict:
    res = groq_chat_json(
        messages=[
            {
                "role": "system",
                "content": (
                    "You generate perfect JSON for educational English conversation podcasts. "
                    "Each multi-part episode has exactly ONE closing outro at the very end; "
                    "never add subscribe or goodbye language in middle parts."
                ),
            },
            {"role": "user", "content": user_prompt},
        ],
        max_tokens=ENGLISH_MAX_TOKENS,
        temperature=0.7,
    )
    # Ensure we always return a dictionary; sometimes the LLM returns a list of items directly.
    if isinstance(res, list):
        return {"dialogue": res}
    return res


def _clean_challenge_dialogue(script: dict, day_number: int) -> dict:
    cleaned = dict(script)
    cleaned["dialogue"] = sanitize_dialogue_part(
        script.get("dialogue", []),
        max_outro_turns_at_end=2 if day_number == 7 else 0,
        is_intro=day_number != 7,
        is_outro=day_number == 7,
    )
    return cleaned


def generate_weekly_challenge_plan(topic=None) -> dict:
    if not topic:
        topic = generate_dynamic_topic(is_challenge=True)

    print(f"\nSelected weekly challenge topic: {topic}")
    prompt = f"""
Create a 7-day weekly challenge playlist plan for the YouTube channel 'EnglishVibesHub'.
WEEKLY THEME: {topic}

CRITICAL RULES:
- Output ONLY valid JSON.
- Day 1 through Day 6 must each teach one focused skill and give listeners one clear daily practice task.
- Day 7 must be a recap episode that reviews the entire week, asks challenge questions, and gives listeners a solid foundation to continue.
- Keep the plan practical for English learners at beginner to intermediate levels.

JSON SCHEMA:
{{
  "series_title": "string",
  "description": "string",
  "tags": ["string"],
  "days": [
    {{
      "day": 1,
      "title": "string",
      "focus": "string",
      "practice_task": "string",
      "keywords": ["string"]
    }}
  ]
}}

REQUIREMENTS:
- Exactly 7 days.
- Day values must be 1 through 7.
- Day 7 title must clearly signal recap, questions, or challenge review.
"""
    plan = call_groq_json(prompt)
    days = plan.get("days", [])
    if len(days) != 7:
        raise ValueError(f"Weekly challenge plan must contain exactly 7 days, got {len(days)}")
    return plan


def generate_weekly_challenge_day_script(plan: dict, day: dict) -> dict:
    day_number = int(day.get("day", 1))
    series_title = plan.get("series_title", "EnglishVibesHub Weekly Challenge")
    previous_days = [
        f"Day {d.get('day')}: {d.get('title')} - {d.get('focus')}"
        for d in plan.get("days", [])
        if int(d.get("day", 0)) < day_number
    ]

    if day_number == 7:
        structure = f"""
STRUCTURE & CONTENT:
1. Welcome listeners to Day 7 of the weekly challenge and name the playlist: {series_title}.
2. Recap Days 1-6 using these exact learning points:
{chr(10).join('- ' + item for item in previous_days)}
3. Ask at least 8 practical challenge questions. Include a short pause cue after each question, then have the hosts explain a strong sample answer.
4. End by giving listeners a simple foundation plan for what to review next week.
5. The final 1-2 dialogue turns may thank listeners and invite them to keep learning with EnglishVibesHub.
"""
        outro_rule = "Do NOT use like/subscribe/goodbye language until the final 1-2 turns."
        turn_count = "35-45"
    else:
        structure = f"""
STRUCTURE & CONTENT:
1. Welcome listeners to Day {day_number} of the weekly challenge and name the playlist: {series_title}.
2. Teach the focused skill: {day.get('focus')}.
3. Explain useful phrases, phrasal verbs, idioms, pronunciation tips, or sentence patterns connected to the skill.
4. Include short roleplay moments between Emma and Liam.
5. Give listeners this daily practice task clearly near the end: {day.get('practice_task')}.
6. End by setting up tomorrow's challenge without saying goodbye.
"""
        outro_rule = _NOT_FINAL_PART_RULES
        turn_count = "28-36"

    prompt = f"""
You are writing a standalone video script for a 7-day English learning challenge playlist on 'EnglishVibesHub'.

SERIES: {series_title}
DAY: {day_number}
TITLE: {day.get('title')}
FOCUS: {day.get('focus')}
PRACTICE TASK: {day.get('practice_task')}

CRITICAL RULES:
- Output ONLY valid JSON.
- The `dialogue` array MUST contain around {turn_count} turns.
- Hosts must be Emma (energetic, helpful) and Liam (curious, friendly).
- The script should feel complete as one daily video, but connected to the weekly playlist.
- Keep explanations clear for beginner to intermediate English learners.
- Ask listeners to answer out loud when useful.
{outro_rule}

{structure}

STYLE:
- Warm, conversational, practical, and encouraging.
- Avoid short 1-sentence replies. Each turn should usually be 2-4 sentences.

JSON SCHEMA:
{{
  "title": "string (include Day {day_number} and a clear learning promise)",
  "description": "string (mention this is part of a 7-day English weekly challenge playlist)",
  "tags": ["string"],
  "day": {day_number},
  "series_title": "string",
  "dialogue": [
    {{
      "speaker": "Emma or Liam",
      "text": "string"
    }}
  ]
}}
"""
    script = call_groq_json(prompt)
    script.setdefault("day", day_number)
    script.setdefault("series_title", series_title)
    script.setdefault("tags", plan.get("tags", ["English", "English Challenge", "EnglishVibesHub"]))
    return _clean_challenge_dialogue(script, day_number)


def generate_weekly_challenge_scripts(topic=None) -> dict:
    plan = generate_weekly_challenge_plan(topic)
    scripts = []

    for day in plan["days"]:
        day_number = int(day.get("day", len(scripts) + 1))
        print(f"Generating weekly challenge Day {day_number}: {day.get('title')}")
        scripts.append(generate_weekly_challenge_day_script(plan, day))
        if day_number < 7:
            groq_part_cooldown(f"Day {day_number + 1}")

    return {
        "series_title": plan.get("series_title", "EnglishVibesHub Weekly Challenge"),
        "description": plan.get("description", ""),
        "tags": plan.get("tags", []),
        "days": plan["days"],
        "scripts": scripts,
    }


def generate_english_script(topic=None):
    if not topic:
        topic = generate_dynamic_topic(is_challenge=False)

    print(f"\nSelected topic: {topic}")

    print("Generating Part 1 (Intro & Setup)...")
    prompt_1 = f"""
You are writing PART 1 (of 3) for a massive English conversation podcast script for the YouTube channel 'EnglishVibesHub'.
TOPIC: {topic}

CRITICAL RULES:
- Output ONLY valid JSON
- The `dialogue` array MUST contain around 35-45 turns.

STRUCTURE & CONTENT (PART 1):
1. **Intro**: MUST start by welcoming the audience to "EnglishVibesHub" and introducing the topic of the day.
2. **Setup**: Begin the deep dive discussion into the topic.
3. Use and carefully explain 3-4 phrasal verbs or idioms. The hosts MUST explain what they mean to the listeners with clear examples.
{_NOT_FINAL_PART_RULES}
STYLE:
- Conversational, friendly, and natural.
- Hosts: Emma (energetic, helpful) and Liam (curious, friendly).
- Ensure back-and-forth banter is highly detailed. Avoid short 1-sentence replies; instead, each turn should be a few sentences long to build up the word count.

JSON SCHEMA:
{{
  "title": "string (engaging YouTube title for the episode)",
  "description": "string (video description)",
  "tags": ["string"],
  "dialogue": [
    {{
      "speaker": "Emma or Liam",
      "text": "string (the spoken text)"
    }}
  ]
}}
"""
    part1_data = call_groq_json(prompt_1)
    groq_part_cooldown("Part 2")

    print("Generating Part 2 (Deep Dive & Stories)...")
    d1 = part1_data.get("dialogue", [])
    last_turn = d1[-1] if d1 else {"speaker": "Emma", "text": "Let's continue."}
    prompt_2 = f"""
You are writing PART 2 (of 3) for a massive English conversation podcast script for the YouTube channel 'EnglishVibesHub'.
TOPIC: {topic}

The previous turn ended with {last_turn['speaker']} saying: "{last_turn['text']}"
Pick up the conversation naturally from here.

CRITICAL RULES:
- Output ONLY valid JSON
- The `dialogue` array MUST contain around 35-45 turns.

STRUCTURE & CONTENT (PART 2):
1. **Deep Dive**: Continue the extensive discussion of the topic.
2. **Stories & Roleplay**: The hosts must share long personal stories or do a mock roleplay related to the topic to extend the conversation naturally.
3. Use and carefully explain 4-5 additional phrasal verbs or idioms. The hosts MUST explain what they mean to the listeners with clear examples.
{_NOT_FINAL_PART_RULES}
STYLE:
- Conversational, friendly, and natural.
- Hosts: Emma (energetic, helpful) and Liam (curious, friendly).
- Ensure back-and-forth banter is highly detailed. Avoid short 1-sentence replies.

JSON SCHEMA:
{{
  "dialogue": [
    {{
      "speaker": "Emma or Liam",
      "text": "string (the spoken text)"
    }}
  ]
}}
"""
    part2_data = call_groq_json(prompt_2)
    groq_part_cooldown("Part 3")

    print("Generating Part 3 (Wrap-up & Outro)...")
    d2 = part2_data.get("dialogue", [])
    last_turn_2 = d2[-1] if d2 else {"speaker": "Emma", "text": "Let's wrap up."}
    prompt_3 = f"""
You are writing PART 3 (of 3) for a massive English conversation podcast script for the YouTube channel 'EnglishVibesHub'.
TOPIC: {topic}

The previous turn ended with {last_turn_2['speaker']} saying: "{last_turn_2['text']}"
Pick up the conversation naturally from here.

CRITICAL RULES:
- Output ONLY valid JSON
- The `dialogue` array MUST contain around 30-40 turns.

STRUCTURE & CONTENT (PART 3):
1. **Wrap-up**: Share final thoughts, tips, or examples (most of this part).
2. Use and carefully explain 3-4 final phrasal verbs or idioms. The hosts MUST explain what they mean to the listeners with clear examples.
3. **Outro (LAST 1-2 TURNS ONLY)**: The final 1-2 dialogue turns may thank listeners and ask them to like, subscribe, and tune in for more on EnglishVibesHub. Do NOT use like/subscribe/goodbye/thanks-for-watching language anywhere earlier in Part 3.

STYLE:
- Conversational, friendly, and natural.
- Hosts: Emma (energetic, helpful) and Liam (curious, friendly).
- Ensure back-and-forth banter is highly detailed. Avoid short 1-sentence replies.

JSON SCHEMA:
{{
  "dialogue": [
    {{
      "speaker": "Emma or Liam",
      "text": "string (the spoken text)"
    }}
  ]
}}
"""
    part3_data = call_groq_json(prompt_3)

    return combine_english_parts(part1_data, part2_data, part3_data, topic)
