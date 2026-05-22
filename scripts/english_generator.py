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
    "Using Phrasal Verbs with 'Look'",
    "Ordering Food at a Restaurant",
    "Checking in at a Hotel",
    "Talking about the Weather and Seasons",
    "Job Interview Basics in English",
    "Small Talk at a Party",
    "Asking for and Giving Directions",
    "Discussing Hobbies and Interests",
    "Phrasal Verbs for Travel and Holidays",
    "Everyday Office Conversations",
    "Describing People and Personalities",
    "Making Apologies and Excuses",
    "Shopping and Asking for Prices",
    "Talking about Future Plans",
    "Common Idioms for Happiness and Sadness",
    "Discussing Favorite Movies and Books",
    "Making Plans for the Weekend",
    "Talking about Food and Cooking",
    "Giving Advice to a Friend",
    "Phrasal Verbs with 'Get'"
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

_NOT_FINAL_PART_RULES = """
CONTINUITY (THIS IS NOT THE FINAL PART OF THE EPISODE):
- Do NOT thank listeners for watching or say goodbye.
- Do NOT ask viewers to like, subscribe, or hit the bell.
- Do NOT say "see you next time", "tune in next episode", or similar closings.
- End on an open conversation beat so the next part continues naturally.
"""


def is_outro_line(text: str) -> bool:
    return any(p.search(text) for p in _OUTRO_PATTERNS)


def sanitize_dialogue_part(dialogue: list, max_outro_turns_at_end: int = 0) -> list:
    """Drop sign-off / CTA lines; Part 3 may keep them only in the last N turns."""
    if not dialogue:
        return []
    if max_outro_turns_at_end <= 0:
        return [t for t in dialogue if not is_outro_line(t.get("text", ""))]

    keep_tail = min(max_outro_turns_at_end, len(dialogue))
    body = dialogue[:-keep_tail]
    tail = dialogue[-keep_tail:]
    body = [t for t in body if not is_outro_line(t.get("text", ""))]
    return body + tail


def combine_english_parts(part1_data: dict, part2_data: dict, part3_data: dict, topic: str) -> dict:
    final_script = {
        "title": part1_data.get("title", f"English Conversation: {topic}"),
        "description": part1_data.get(
            "description", f"Learn English with this detailed conversation about {topic}."
        ),
        "tags": part1_data.get("tags", ["English", "Conversation", "Learning", "Phrasal Verbs"]),
        "dialogue": [],
    }

    for part_data, max_outro in (
        (part1_data, 0),
        (part2_data, 0),
        (part3_data, 2),
    ):
        cleaned = sanitize_dialogue_part(part_data.get("dialogue", []), max_outro)
        removed = len(part_data.get("dialogue", [])) - len(cleaned)
        if removed:
            print(f"  Removed {removed} mid-episode sign-off line(s)")
        final_script["dialogue"].extend(cleaned)

    return final_script


def call_groq_json(user_prompt: str) -> dict:
    return groq_chat_json(
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


def generate_english_script(topic=None):
    if not topic:
        topic = random.choice(ENGLISH_TOPIC_POOL)

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
    last_turn = part1_data["dialogue"][-1] if part1_data.get("dialogue") else {"speaker": "Emma", "text": "Let's continue."}
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
    last_turn_2 = part2_data["dialogue"][-1] if part2_data.get("dialogue") else {"speaker": "Emma", "text": "Let's wrap up."}
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
