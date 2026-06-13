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

PUBLISHED_TOPICS_FILE = Path(__file__).resolve().parent / "english_published_topics.json"

def get_published_topics() -> dict:
    if PUBLISHED_TOPICS_FILE.exists():
        try:
            with open(PUBLISHED_TOPICS_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, dict):
                    if "quiz" not in data:
                        data["quiz"] = []
                    return data
                # Handle old list format by migrating it to "podcast"
                return {"podcast": data, "shorts": [], "challenge": [], "slow": [], "quiz": [], "post": []}
        except Exception as e:
            print(f"Error loading published topics: {e}")
    return {"podcast": [], "shorts": [], "challenge": [], "slow": [], "quiz": [], "post": []}

def is_already_published(topic: str, topic_type: str) -> bool:
    """Check if a topic or title already exists in the published history for a specific type."""
    topics_data = get_published_topics()
    published = topics_data.get(topic_type, [])
    topic_lower = topic.lower().strip()
    for entry in published:
        entry_lower = str(entry).lower().strip()
        if topic_lower in entry_lower or entry_lower in topic_lower:
            return True
    return False

def save_published_topic(topic: str, topic_type: str = "podcast"):
    topics_data = get_published_topics()
    if topic_type not in topics_data:
        topics_data[topic_type] = []
        
    if topic not in topics_data[topic_type]:
        topics_data[topic_type].append(topic)
        try:
            with open(PUBLISHED_TOPICS_FILE, "w", encoding="utf-8") as f:
                json.dump(topics_data, f, indent=2, ensure_ascii=False)
        except Exception as e:
            print(f"Error saving published topic: {e}")


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

COMMUNITY_POLL_POOL = [
    "Grammar Quiz: Prepositions of Time",
    "Vocabulary Challenge: Synonyms for 'Happy'",
    "Common Mistakes: 'Your' vs 'You're'",
    "Idiom Check: 'Under the weather' meaning",
    "Pronunciation Poll: Which word is the odd one out?",
    "Real-world English: Ordering at a Coffee Shop",
    "Business English: Professional Email Openings",
    "Slang Quiz: What does 'no cap' mean?"
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


def generate_dynamic_topic(is_challenge: bool = False, topic_type: str = "podcast") -> str:
    """Ask Groq to generate a fresh, trending English learning topic."""
    if topic_type == "post":
        type_label = "YouTube Community quiz or poll"
    elif is_challenge:
        type_label = "7-day weekly challenge"
    else:
        type_label = "podcast episode"
    topics_data = get_published_topics()
    published_topics = topics_data.get(topic_type, [])
    
    # Send up to 50 most recent topics to avoid massive token usage
    recent_topics = published_topics[-50:] if published_topics else []
    avoid_instruction = ""
    if recent_topics:
        avoid_instruction = f"""
    CRITICAL: Avoid repeating or closely matching any of these previously published topics/titles:
    {json.dumps(recent_topics, indent=2)}
    """

    prompt = f"""
    Generate a single, highly engaging topic for an English learning {type_label}.
    The topic should be focused on real-world practical everyday usage, and appealing to english learners at intermediate levels.
    {avoid_instruction}

    CRITICAL: For titles, prioritize searchable keywords like "Practice for Beginners", "Easy English Listening", or "Daily Conversation".

    Return ONLY a JSON object with 'topic' and 'search_keyword' keys.
    Example: {{"topic": "Mastering Sarcasm and Irony", "search_keyword": "English Conversation Practice"}}
    """
    try:
        res = call_groq_json(prompt)
        fallback_pool = WEEKLY_CHALLENGE_TOPIC_POOL if is_challenge else (COMMUNITY_POLL_POOL if topic_type == "post" else ENGLISH_TOPIC_POOL)
        return res.get("topic", random.choice(fallback_pool))
    except Exception as e:
        print(f"  Error generating dynamic topic: {e}. Falling back to pool.")
        fallback_pool = WEEKLY_CHALLENGE_TOPIC_POOL if is_challenge else (COMMUNITY_POLL_POOL if topic_type == "post" else ENGLISH_TOPIC_POOL)
        return random.choice(fallback_pool)


def generate_thumbnail_text(topic: str, is_challenge: bool = False) -> dict:
    """Use Groq to create a short mobile-friendly thumbnail headline."""
    type_label = "weekly challenge episode" if is_challenge else "English conversation episode"
    prompt = f"""
    You are writing a mobile-friendly YouTube thumbnail overlay for an {type_label} about "{topic}".
    Return ONLY a JSON object with these keys:
    - thumbnail_text: 3-5 bold, eye-catching words for a mobile thumbnail overlay.
    - thumbnail_concept: one short sentence describing the visual vibe.

    Rules:
    - Keep thumbnail_text short enough to fit on mobile.
    - Do not use more than 5 words.
    - Avoid punctuation except a single ampersand if needed.
    - Use strong action or emotion words.

    Example:
    {{"thumbnail_text": "Speak Confidently Today", "thumbnail_concept": "Bold white text over a blurred cafe background"}}
    """
    try:
        res = call_groq_json(prompt)
        return {
            "thumbnail_text": str(res.get("thumbnail_text", "")).strip(),
            "thumbnail_concept": str(res.get("thumbnail_concept", "")).strip(),
        }
    except Exception as e:
        print(f"  Error generating thumbnail text: {e}. Falling back to title.")
        return {
            "thumbnail_text": topic,
            "thumbnail_concept": "Bold mobile-friendly overlay text.",
        }


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
    title = part1_data.get("title")
    if not title:
        title_options = part1_data.get("title_options") or []
        title = title_options[0] if title_options else f"English Conversation: {topic}"

    description = part1_data.get("description")
    if not description:
        description = f"Learn English with this detailed conversation about {topic}."

    tags = part1_data.get("tags")
    if not tags:
        tags = ["English", "Conversation", "Learning", "Phrasal Verbs"]

    final_script = {
        "title": title,
        "description": description,
        "pinned_comment": part1_data.get("pinned_comment", ""),
        "tags": tags,
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
        topic = generate_dynamic_topic(is_challenge=True, topic_type="challenge")
    else:
        # Check if manual topic is already published
        if is_already_published(topic, "challenge"):
            print(f"\n  [WARNING] Manual challenge topic '{topic}' was found in 'challenge' history.")

    # History injection
    topics_data = get_published_topics()
    recent = topics_data.get("challenge", [])[-50:]
    avoid_instruction = f"\nAvoid repeating content or structure from these recent challenges:\n{json.dumps(recent, indent=2)}" if recent else ""

    print(f"\nSelected weekly challenge topic: {topic} for @EnglishVibesHub-s6w")
    prompt = f"""
Create a 7-day weekly challenge playlist plan for the YouTube channel 'EnglishVibesHub' (@EnglishVibesHub-s6w).
WEEKLY THEME: {topic}
{avoid_instruction}

CRITICAL RULES:
- Output ONLY valid JSON.
- Day 1 through Day 6 must each teach one focused skill and give listeners one clear daily practice task.
- Day 7 must be a recap episode that reviews the entire week, asks challenge questions, and gives listeners a solid foundation to continue.
- Keep the plan practical for English learners at intermediate levels.

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


def generate_weekly_challenge_quiz_script(day_script: dict) -> dict:
    """Generate a quiz short script based on a specific day's challenge content."""
    series_title = day_script.get("series_title", "English Challenge")
    day_num = day_script.get("day", 1)
    focus = day_script.get("focus", "English conversation")

    prompt = f"""
    Write a high-retention YouTube Quiz Short based on Day {day_num} of the '{series_title}' challenge on @EnglishVibesHub-s6w.

    LESSON FOCUS: {focus}

    STRUCTURE:
    - The 'dialogue' array MUST contain around 10-15 turns.
    1. Emma: "Day {day_num} Challenge! Let's see if you remember what we just learned." (Hook)
    2. Liam: Presents a Multiple Choice Question (A, B, or C) testing the lesson focus: {focus}.
    3. [PAUSE] (3-second timer animation cue)
    4. Emma: Reveals the correct answer and gives a 1-sentence explanation.
    5. Liam: "Got it right? Check out the full Day {day_num} lesson to master this focus!" (CTA pointing to the related video)

    JSON SCHEMA:
    {{
      "title": "string (e.g., 'English Quiz Day {day_num}: [Topic] | Test Your English')",
      "description": "string (Include #Shorts, #EnglishChallenge, #EnglishVibesHub, and hashtags mirroring the 'tags' list below)",
      "pinned_comment": "string",
      "tags": ["string (Provide 5-8 SEO-focused English learning tags)"],
      "correct_answer": "string",
      "dialogue": [
        {{ "speaker": "Emma", "text": "..." }},
        {{ "speaker": "Liam", "text": "..." }}
      ]
    }}
    """
    script_data = call_groq_json(prompt)
    script_data["video_format"] = "shorts_quiz"
    return script_data

def generate_english_community_content(topic: str = None, content_type: str = "quiz") -> dict:
    """
    Generates content for YouTube Community Tab: 
    types: 'quiz' (text poll with 1 right answer) or 'image_poll' (visual choices).
    """
    if not topic:
        topic = generate_dynamic_topic(topic_type="post")
    else:
        # Check if manual topic is already published
        if is_already_published(topic, "post"):
            print(f"\n  [WARNING] Manual community topic '{topic}' was found in 'post' history.")

    print(f"\nSelected community topic: {topic}")
    
    prompt = f"""
    Create a highly engaging YouTube Community {content_type.replace('_', ' ')} for 'EnglishVibesHub'.
    TOPIC: {topic}

    REQUIREMENTS:
    - Content must be for intermediate English learners.
    - Provide a question and 4 options. Keep each option extremely concise (max 20 characters) so they fit on mobile image overlays.
    - Provide a 'correct_explanation' that explains WHY the answer is correct (for the pinned comment/post body).
    - Provide 4 'image_prompts' (search keywords for Pexels), one for each option.

    JSON SCHEMA:
    {{
      "question": "string",
      "options": ["string", "string", "string", "string"],
      "correct_index": 0,
      "correct_explanation": "string",
      "image_prompts": ["keyword1", "keyword2", "keyword3", "keyword4"]
    }}
    """
    
    res = call_groq_json(prompt)
    res["content_type"] = content_type
    res["topic"] = topic
    save_published_topic(topic, topic_type="post")
    return res


def generate_weekly_challenge_day_script(plan: dict, day: dict) -> dict:
    day_number = int(day.get("day", 1))
    series_title = plan.get("series_title", "EnglishVibesHub Weekly Challenge")
    previous_days = [
        f"Day {d.get('day')}: {d.get('title')} - {d.get('focus')}"
        for d in plan.get("days", [])
        if int(d.get("day", 0)) < day_number
    ]

    # History injection
    topics_data = get_published_topics()
    recent = topics_data.get("challenge", [])[-50:]
    avoid_instruction = f"\nAvoid repeating content or phrasal verbs/idioms from these recent challenge episodes:\n{json.dumps(recent, indent=2)}" if recent else ""

    if day_number == 7:
        structure = f"""
STRUCTURE & CONTENT:
1. Welcome listeners to Day 7 of the weekly challenge on @EnglishVibesHub-s6w and name the playlist: {series_title}.
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
1. Welcome listeners to Day {day_number} of the weekly challenge on @EnglishVibesHub-s6w and name the playlist: {series_title}.
2. Teach the focused skill: {day.get('focus')}.
3. Explain useful phrases, phrasal verbs, idioms, pronunciation tips, or sentence patterns connected to the skill.
4. Include short roleplay moments between Emma and Liam.
5. Give listeners this daily practice task clearly near the end: {day.get('practice_task')}.
6. End by setting up tomorrow's challenge without saying goodbye.
"""
        outro_rule = _NOT_FINAL_PART_RULES
        turn_count = "28-36"

    prompt = f"""
You are writing a standalone video script for a 7-day English learning challenge playlist on 'EnglishVibesHub' (@EnglishVibesHub-s6w).

SERIES: {series_title}
DAY: {day_number}
TITLE: {day.get('title')}
{avoid_instruction}
FOCUS: {day.get('focus')}
PRACTICE TASK: {day.get('practice_task')}

CRITICAL RULES:
- Output ONLY valid JSON.
- The `dialogue` array MUST contain around {turn_count} turns.
- Hosts must be Emma (energetic, helpful) and Liam (curious, friendly).
- The script should feel complete as one daily video, but connected to the weekly playlist.
- Keep explanations clear for intermediate English learners.
- Ask listeners to answer out loud when useful.
{outro_rule}

{structure}

STYLE:
- Warm, conversational, practical, and encouraging.
- Avoid short 1-sentence replies. Each turn should usually be 2-4 sentences.

JSON SCHEMA:
{{
  "title": "string (include Day {day_number}, a clear learning promise, and a high-CTR hook)",
  "title_options": ["string"],
  "description": "string (YouTube description with a strong first-line hook, relevant keywords, and hashtags mirroring the 'tags' list below)",
  "pinned_comment": "string (An engaging question or call to action to pin in the comments)",
  "tags": ["string (Provide 5-8 SEO-focused tags)"],
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

    if not script.get("title"):
        title_options = script.get("title_options") or []
        if title_options:
            script["title"] = title_options[0]

    thumbnail = generate_thumbnail_text(f"{day.get('title')} | {series_title}", is_challenge=True)
    script["thumbnail_text"] = thumbnail.get("thumbnail_text") or script.get("title", "")
    script["thumbnail_concept"] = thumbnail.get("thumbnail_concept", "")

    return _clean_challenge_dialogue(script, day_number)


def generate_weekly_challenge_scripts(topic=None) -> dict:
    plan = generate_weekly_challenge_plan(topic)
    scripts = []

    for day in plan["days"]:
        day_number = int(day.get("day", len(scripts) + 1))
        print(f"Generating weekly challenge Day {day_number}: {day.get('title')}")
        day_script = generate_weekly_challenge_day_script(plan, day)
        print(f"  Generating accompanying Quiz Short for Day {day_number}...")
        day_script["quiz_script"] = generate_weekly_challenge_quiz_script(day_script)
        scripts.append(day_script)
        if day_number < 7:
            groq_part_cooldown(f"Day {day_number + 1}")

    return_data = {
        "series_title": plan.get("series_title", "EnglishVibesHub Weekly Challenge"),
        "description": plan.get("description", ""),
        "tags": plan.get("tags", []),
        "days": plan["days"],
        "scripts": scripts,
    }
    
    save_published_topic(return_data["series_title"], topic_type="challenge")
    return return_data


def generate_english_script(topic=None):
    if not topic:
        topic = generate_dynamic_topic(is_challenge=False, topic_type="podcast")
    else:
        # Check if manual topic is already published
        if is_already_published(topic, "podcast"):
            print(f"\n  [WARNING] Manual topic '{topic}' was found in 'podcast' history.")

    # History injection
    topics_data = get_published_topics()
    recent = topics_data.get("podcast", [])[-50:]
    avoid_instruction = f"\nAvoid repeating examples, idioms, or stories used in these recent episodes:\n{json.dumps(recent, indent=2)}" if recent else ""

    print(f"\nSelected topic: {topic}")

    print("Generating Part 1 (Intro & Setup)...")
    prompt_1 = f"""
You are writing PART 1 (of 3) for a massive English conversation podcast script for the YouTube channel 'EnglishVibesHub' (@EnglishVibesHub-s6w).
TOPIC: {topic}
{avoid_instruction}

CRITICAL RULES:
- Output ONLY valid JSON
- The `dialogue` array MUST contain around 35-45 turns.

STRUCTURE & CONTENT (PART 1):
1. **Intro**: MUST start by welcoming the audience to "EnglishVibesHub" (@EnglishVibesHub-s6w) and introducing the topic of the day.
2. **Searchability**: The title MUST include high-intent phrases like "English Listening Practice" or "Improve Your Speaking".
3. **Setup**: Begin the deep dive discussion into the topic.
4. Use and carefully explain 3-4 phrasal verbs or idioms. The hosts MUST explain what they mean to the listeners with clear examples.
{_NOT_FINAL_PART_RULES}
STYLE:
- Conversational, friendly, and natural.
- Hosts: Emma (energetic, helpful) and Liam (curious, friendly).
- Ensure back-and-forth banter is highly detailed. Avoid short 1-sentence replies; instead, each turn should be a few sentences long to build up the word count.

JSON SCHEMA:
{{
  "title": "string (SEO-focused title: [Keyword] + [Hook]. e.g., 'English Listening Practice: Mastering {topic}')",
  "title_options": ["string"],
  "description": "string (80-120 words. Include a specific question for the comments section and relevant hashtags mirroring the 'tags' list below)",
  "pinned_comment": "string (A specific engaging question about the topic to trigger comments)",
  "tags": ["string (Provide 5-8 SEO-focused English learning and topic-specific tags)"],
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
You are writing PART 2 (of 3) for a massive English conversation podcast script for the YouTube channel 'EnglishVibesHub' (@EnglishVibesHub-s6w).
TOPIC: {topic}
{avoid_instruction}

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
You are writing PART 3 (of 3) for a massive English conversation podcast script for the YouTube channel 'EnglishVibesHub' (@EnglishVibesHub-s6w).
TOPIC: {topic}
{avoid_instruction}

The previous turn ended with {last_turn_2['speaker']} saying: "{last_turn_2['text']}"
Pick up the conversation naturally from here.

CRITICAL RULES:
- Output ONLY valid JSON
- The `dialogue` array MUST contain around 30-40 turns.

STRUCTURE & CONTENT (PART 3):
1. **Wrap-up**: Share final thoughts, tips, or examples (most of this part).
2. Use and carefully explain 3-4 final phrasal verbs or idioms. The hosts MUST explain what they mean to the listeners with clear examples.
3. **Outro (LAST 1-2 TURNS ONLY)**: The final 1-2 dialogue turns may thank listeners and ask them to like, subscribe, and tune in for more on EnglishVibesHub (@EnglishVibesHub-s6w). Do NOT use like/subscribe/goodbye/thanks-for-watching language anywhere earlier in Part 3.

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

    script = combine_english_parts(part1_data, part2_data, part3_data, topic)
    thumbnail = generate_thumbnail_text(topic, is_challenge=False)
    script["thumbnail_text"] = thumbnail.get("thumbnail_text") or script.get("title", "")
    script["thumbnail_concept"] = thumbnail.get("thumbnail_concept", "")
    
    save_published_topic(script.get("title", topic), topic_type="podcast")
    
    return script


# ─────────────────────────────────────────────
# SLOW ENGLISH PIPELINE — idiom-focused
# ─────────────────────────────────────────────

SLOW_IDIOM_POOL = [
    "Break a leg",
    "Hit the nail on the head",
    "Bite the bullet",
    "Spill the beans",
    "Under the weather",
    "Cost an arm and a leg",
    "Beat around the bush",
    "Burning the midnight oil",
    "Let the cat out of the bag",
    "Once in a blue moon",
    "Piece of cake",
    "Hit the sack",
    "Kick the bucket",
    "The ball is in your court",
    "Better late than never",
    "Don't judge a book by its cover",
    "Bite off more than you can chew",
    "Barking up the wrong tree",
    "Caught between a rock and a hard place",
    "Hit the road",
    "Get out of hand",
    "Pull someone's leg",
    "On the fence",
    "Under the table",
    "Go back to the drawing board",
    "Cut corners",
    "Jump on the bandwagon",
    "Miss the boat",
    "Bite the hand that feeds you",
    "Add fuel to the fire",
    "Back to square one",
    "Blow off steam",
    "Burn bridges",
    "Catch someone red-handed",
    "Cold turkey",
    "Cut to the chase",
    "Devil's advocate",
    "Don't cry over spilled milk",
    "Drop the ball",
    "Every cloud has a silver lining",
    "Face the music",
    "Get cold feet",
    "Give someone the benefit of the doubt",
    "Go the extra mile",
    "Hit the books",
    "In hot water",
    "It takes two to tango",
    "Kill two birds with one stone",
    "Let sleeping dogs lie",
    "On thin ice",
]


def generate_english_slow_script(topic=None):
    """Generate a short idiom-focused script for the slow English pipeline.

    Returns a dict with keys:
        title_normal, title_slow,
        description_normal (template with {slow_url}),
        description_slow   (template with {normal_url}),
        tags, dialogue, idiom, thumbnail_text, thumbnail_concept
    The dialogue contains 10-12 turns (≈60-90 s at 0.95x; ≈75-112 s at 0.80x).
    """
    topics_data = get_published_topics()
    published_slow = topics_data.get("slow", [])

    if not topic:
        # Filter idioms by checking if they appear in any previously published titles
        remaining = [
            i for i in SLOW_IDIOM_POOL 
            if not any(i.lower() in p.lower() for p in published_slow)
        ]
        if not remaining:
            remaining = SLOW_IDIOM_POOL  # cycle back when all done
        topic = random.choice(remaining)
    elif is_already_published(topic, "slow"):
        print(f"\n  [WARNING] Manual idiom '{topic}' was found in 'slow' history.")

    print(f"\nSelected slow idiom: {topic}")

    recent = published_slow[-50:] if published_slow else []
    avoid_instruction = ""
    if recent:
        avoid_instruction = (
            f"\nDo NOT use any of these already-published idioms or titles as the main focus or repeat their examples:\n"
            + json.dumps(recent, indent=2)
        )

    prompt = f"""
You are writing a short English learning podcast script for the YouTube channel 'EnglishVibesHub' (@EnglishVibesHub-s6w).

IDIOM / TOPIC: {topic}
{avoid_instruction}

CRITICAL RULES:
- Output ONLY valid JSON.
- The `dialogue` array MUST contain exactly 10-12 turns total.
- Hosts must be Emma (energetic, helpful) and Liam (curious, friendly).
- Teach the idiom '{topic}' thoroughly: its meaning, origin (if interesting), and 2-3 real-life usage examples.
- Each turn should be 2-3 sentences. No single-sentence turns.
- The FINAL turn should gently invite viewers to try using the idiom in the comments.
- Do NOT add like/subscribe CTAs mid-episode; only a brief mention is allowed in the last turn.
- END-OF-VIDEO REVIEW: The last 3 turns MUST be a 'Test Your Understanding' segment. Emma asks a multiple choice question about the idiom, followed by a 3-second pause cue [PAUSE], then Liam reveals the answer.

STYLE:
- Warm, encouraging, crystal-clear pacing.
- Perfect for ESL learners and absolute beginners.
- Define every word that might be unfamiliar.

SEARCHABLE TITLES REQUIRED:
- title_normal: discovery-friendly, no "slow" branding.
  Must include: "English Practice for Beginners" or "Learn English Idioms".
- title_slow: beginner-targeted, slow-learning branding with the 🐢 emoji.
  Must include: "Slow English Practice" or "Easy English Listening".

TWO DESCRIPTIONS REQUIRED — they must feel like DIFFERENT videos:
- description_normal: 80-100 words. Focus on idiom mastery and conversational English.
  Include hashtags that mirror the 'tags' list below.
- description_slow: 80-100 words. Emphasise the slow-learner benefit (0.8x speed, big captions).
  Include hashtags that mirror the 'tags' list below.

JSON SCHEMA:
{{
  "title_normal": "string",
  "title_slow":   "string",
  "description_normal": "string (Normal speed description with relevant hashtags mirroring the 'tags' list below)",
  "description_slow":   "string (Slow speed description with relevant hashtags mirroring the 'tags' list below)",
  "pinned_comment": "string (A specific 'How would you use this?' question)",
  "tags": ["string (Provide 5-8 SEO-focused tags)"],
  "idiom": "{topic}",
  "dialogue": [
    {{
      "speaker": "Emma or Liam",
      "text": "string (the spoken text)"
    }}
  ]
}}
"""
    script_data = call_groq_json(prompt)
    script_data.setdefault("idiom", topic)
    script_data.setdefault("video_format", "slow")

    # ── Fallback titles ────────────────────────────────────────────
    if not script_data.get("title_normal"):
        script_data["title_normal"] = f"{topic} — What Does It Mean? | English Idioms"
    if not script_data.get("title_slow"):
        script_data["title_slow"] = f"{topic} 🐢 SLOW English | Idioms for Beginners"

    # ── Thumbnail (based on normal title — the "main" video) ──────
    thumbnail = generate_thumbnail_text(f"{topic} — English Idiom", is_challenge=False)
    script_data["thumbnail_text"] = thumbnail.get("thumbnail_text") or topic
    script_data["thumbnail_concept"] = thumbnail.get("thumbnail_concept", "")

    # ── Companion description templates (URLs injected by the pipeline) ──
    idiom = script_data.get("idiom", topic)
    base_normal = script_data.get("description_normal", "")
    base_slow   = script_data.get("description_slow", "")

    # Fallback if Groq returned only one description key
    if not base_normal and not base_slow:
        fallback = script_data.get("description", "")
        base_normal = fallback
        base_slow   = fallback
    elif not base_normal:
        base_normal = script_data.get("description", base_slow)
    elif not base_slow:
        base_slow = script_data.get("description", base_normal)

    script_data["description_normal"] = (
        base_normal.rstrip()
        + "\n\n🐢 Didn't catch that? Watch the Slow English version here:\n{slow_url}"
    )
    script_data["description_slow"] = (
        f"🐢 SLOW English Learning Mode — \"{idiom}\" explained at 0.8x speed "
        f"with large on-screen captions!\n\n"
        + base_slow.rstrip()
        + "\n\n⚡ Ready for the real speed? Watch here:\n{normal_url}"
    )

    save_published_topic(script_data.get("title_normal", topic), topic_type="slow")

    return script_data

def generate_english_shorts_script(topic=None):

    if not topic:
        topic = generate_dynamic_topic(is_challenge=False, topic_type="shorts")
    else:
        # Check if manual topic is already published
        if is_already_published(topic, "shorts"):
            print(f"\n  [WARNING] Manual shorts topic '{topic}' was found in 'shorts' history.")

    # History injection
    topics_data = get_published_topics()
    recent = topics_data.get("shorts", [])[-50:]
    avoid_instruction = f"\nAvoid repeating concepts or phrasing from these recent shorts:\n{json.dumps(recent, indent=2)}" if recent else ""

    print(f"\nSelected Shorts topic: {topic}")
    prompt = f"""
You are writing a short, snappy English learning podcast script for a YouTube Short on 'EnglishVibesHub' (@EnglishVibesHub-s6w).
TOPIC: {topic}
{avoid_instruction}

CRITICAL RULES:
- Output ONLY valid JSON
- The `dialogue` array MUST contain around 8-12 turns in total (45-60 seconds of speaking).
- Hosts must be Emma (energetic, helpful) and Liam (curious, friendly).
- Teach 1 or 2 specific phrasal verbs, idioms, or useful expressions related to the topic.
- Use searchable keywords in the title: e.g., "English in 60 Seconds" or "Speak English Like a Native".
- Do NOT use mid-episode sign-offs or long pauses.
- The final turn should include a quick call to action (e.g., "Subscribe for more daily English tips!").

STYLE:
- Fast-paced, punchy, conversational, and highly engaging.
- Perfect for vertical YouTube Shorts.

JSON SCHEMA:
{{
  "title": "string (SEO-focused Short title)",
  "title_options": ["string"],
  "description": "string (YouTube description with a strong first-line hook, an engaging question for the comments, #Shorts, and relevant hashtags that mirror the 'tags' list below)",
  "pinned_comment": "string (An engaging question to pin in the comments section)",
  "tags": ["string (Provide 5-8 SEO-focused English learning and topic-specific tags)"],
  "video_format": "shorts",
  "dialogue": [
    {{
      "speaker": "Emma or Liam",
      "text": "string (the spoken text)"
    }}
  ]
}}
"""
    script_data = call_groq_json(prompt)
    script_data.setdefault("video_format", "shorts")

    if not script_data.get("title"):
        title_options = script_data.get("title_options") or []
        if title_options:
            script_data["title"] = title_options[0]
    
    save_published_topic(script_data.get("title", topic), topic_type="shorts")
    
    return script_data

def generate_english_quiz_shorts_script(topic: str = None) -> dict:
    """Strategy 1: Generate a MCQ Quiz Short."""
    topics_data = get_published_topics()
    published_quizzes = topics_data.get("quiz", [])

    if not topic:
        # Filter idioms by checking if they appear in any previously published quiz titles
        remaining = [
            i for i in SLOW_IDIOM_POOL 
            if not any(i.lower() in p.lower() for p in published_quizzes)
        ]
        if not remaining:
            remaining = SLOW_IDIOM_POOL  # cycle back when all done
        topic = random.choice(remaining)
    elif is_already_published(topic, "quiz"):
        print(f"\n  [WARNING] Manual quiz idiom '{topic}' was found in 'quiz' history.")

    print(f"\nSelected Quiz idiom: {topic}")

    recent = published_quizzes[-50:] if published_quizzes else []
    avoid_instruction = ""
    if recent:
        avoid_instruction = (
            f"\nAvoid repeating or using the same distractors from these recent quizzes:\n"
            + json.dumps(recent, indent=2)
        )
    
    prompt = f"""
    Write a high-retention YouTube Quiz Short for 'EnglishVibesHub' (@EnglishVibesHub-s6w).
    TOPIC: The idiom or expression '{topic}'
    {avoid_instruction}
    
    SEARCH-FOCUSED TITLE STRATEGY:
    Small channels rely on SEARCH. The title MUST use searchable keywords to help discovery.
    Use phrases like: "English Practice for Beginners", "Easy English Listening", or "English Quiz".
    Examples: "English Quiz: [Idiom] Meaning | English Practice for Beginners", "Do you know this idiom? [Idiom] Quiz #Shorts".
    
    - The 'dialogue' array MUST contain around 10-15 turns.
    STRUCTURE & PACING:
    1. Emma: "Quick Quiz! What does '{topic}' mean?" (Instant hook)
    2. Liam: "Is it A), B), or C)?" (Present 3 plausible multiple-choice options, only one is correct).
    3. [PAUSE] (This cue is for a 3-second countdown timer animation).
    4. Emma: "The answer is... [Correct Option]! [Brief 1-sentence explanation of the meaning]".
    5. Liam: "Did you get it right? Write your score in the comments and subscribe for daily English quizzes!" (Engagement Trigger)

    LEVERAGE COMMENTS: 
    Generate a 'pinned_comment' question to trigger algorithmic signals. 
    Example: "What does '{topic}' mean? Write your guess below!" or "Have you used the phrase '{topic}' recently? Let us know!"

    JSON SCHEMA:
    {{
      "title": "string (Searchable keyword-rich title under 70 characters)",
      "description": "string (High-intent description including #Shorts, #EnglishQuiz, #LearnEnglish, and hashtags mirroring the 'tags' list below)",
      "pinned_comment": "string (Engaging specific question for the comments section)",
      "tags": ["string (Provide 5-8 SEO-focused tags)"],
      "correct_answer": "string",
      "dialogue": [
        {{ "speaker": "Emma", "text": "..." }},
        {{ "speaker": "Liam", "text": "..." }}
      ]
    }}
    """
    script_data = call_groq_json(prompt)
    script_data["video_format"] = "shorts_quiz"
    return script_data
