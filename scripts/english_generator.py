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

ENGLISH_METADATA_RULES = """
METADATA RULES:
- Titles must be high-CTR, searchable, curiosity-driven, and punchy.
- Use strong title casing and selective ALL CAPS only for 1-2 hook words such as STOP, DON'T, NEVER, EASY, or FAST.
- Title format: [Hook phrase] | [Level/Topic context]. Example: "DON'T Say 'Room Key' | 5 Levels of Hotel English"
- Descriptions: Front-load keywords: The first 2-3 words MUST include "English listening practice", "English speaking practice", "English Quiz", or "Learn English" followed immediately by topic-specific vocabulary.
- Descriptions: Use natural keyword variation: If the topic is "Hair Salon", include related terms like "hairdresser", "stylist", or "barber shop" in the title or description to capture varied search intent.
- Descriptions MUST start with exactly 2-3 SEO-heavy lines using high-intent phrases "Natural English" and "Speak like a native" (or close variants).
- Place the playlist and comment question CTAs (immediately after the SEO opener, BEFORE timeline and other CTAs) to encourage early engagement.
- Descriptions must use readable spacing with blank lines between sections and tasteful CTA icons (📺, 💬, 🔔, 📑, 🎯, 📚).
- For long-form videos include a scene-based timeline section using the placeholder {scene_timeline} (scene labels only — timestamps are injected later).
- Descriptions must include a subscribe CTA, relevant hashtags (always include #EnglishVibesHub), and exactly one playlist placeholder line: 📺 Watch the playlist here: {playlist_url}
- Tags must be high-intent SEO tags, mixing broad English-learning terms with topic-specific terms. Include keyword variations (e.g., if topic is "restaurant", include "dining", "eatery", "cafe").
- Pinned comments must ask a specific question that viewers can answer quickly.

DESCRIPTION TEMPLATE (adapt for shorts by omitting timeline and adding #Shorts hashtags):
🎯 In this video, learn [topic summary]. Improve your English skills with natural expressions and phrasal verbs used in real-life scenarios. Master natural English for real conversations and learn to speak like a native!

📺 Watch the full travel English playlist here: 
https://www.youtube.com/playlist?list=PLQcVuzsH3e2I

💬 Comment below: [specific question]

📑 Timeline:
{scene_timeline}

🔔 Subscribe to EnglishVibesHub for more English listening, speaking, and vocabulary practice:
https://www.youtube.com/channel/UCcebFzUKUN-bMXcYLBvx8Tg

#EnglishVibesHub #LearnEnglish #EnglishListeningPractice #EnglishForBeginners ...
"""

ENGLISH_STORYBOARD_STYLE_SUFFIX_LANDSCAPE = (
    "3D Pixar animation style, Disney character design, cinematic lighting, 16:9 aspect ratio."
)
ENGLISH_STORYBOARD_STYLE_SUFFIX_PORTRAIT = (
    "3D Pixar animation style, Disney character design, cinematic lighting, 9:16 aspect ratio."
)

_PLAYLIST_LINE_RE = re.compile(
    r"""
    ^\s*
    (?:[-*•▶️🎬📺🎧📚🔥✨]\s*)?
    (?:
        watch|see|view|check\s+out|listen\s+to|catch
    )\s+
    (?:
        the\s+|this\s+|our\s+
    )?
    (?:
        full\s+|complete\s+|entire\s+
    )?
    (?:
        playlist|series
    )
    (?:
        \s+here|\s+playlist
    )?
    \s*:?
    \s*
    (?:
        \{playlist_url\}|https?://\S+|\[[^\]]+\]
    )?
    \s*$
    """,
    re.IGNORECASE | re.VERBOSE,
)


def ensure_english_vibes_hashtags(description: str) -> str:
    """Ensure #EnglishVibesHub appears in the description hashtag block."""
    text = str(description or "").strip()
    if not text:
        return "#EnglishVibesHub #LearnEnglish"
    if re.search(r"#EnglishVibesHub\b", text, re.IGNORECASE):
        return text
    hashtag_lines = [i for i, line in enumerate(text.splitlines()) if "#" in line]
    if hashtag_lines:
        idx = hashtag_lines[-1]
        lines = text.splitlines()
        # Only add if not already present to avoid duplicates
        if not re.search(r"#EnglishVibesHub\b", lines[idx], re.IGNORECASE):
            lines[idx] = lines[idx].rstrip() + " #EnglishVibesHub"
        return "\n".join(lines)
    # Ensure empty line before hashtag block
    return text + "\n\n#EnglishVibesHub #LearnEnglish"


def validate_organic_english_script(raw_input):
    """
    Validation engine tailored for the Organic Multi-Character English Prompt layout.
    Accepts raw JSON text string or a Python dictionary object.
    """
    if isinstance(raw_input, dict):
        script_data = raw_input
    else:
        try:
            script_data = json.loads(raw_input)
        except Exception as e:
            print(f"❌ Structural Failure: Output is not valid parseable JSON. Error: {e}")
            return raw_input, False

    dialogue = script_data.get("dialogue", [])
    turn_count = len(dialogue)

    # 1. VALIDATE TURN BOUNDARIES (Rule: 12 to 18 range)
    if turn_count < 12 or turn_count > 18:
        print(f"❌ Retention Failure: Script has {turn_count} turns. Must be between 12 and 18.")
        return script_data, False

    # Track structural validation targets
    has_pause = False
    has_narrator = False
    has_actors = False

    for turn in dialogue:
        turn_num = turn.get("turn_number")
        speaker = turn.get("speaker")
        text = turn.get("text", "")

        # Check for speaker representation
        if speaker == "Narrator":
            has_narrator = True
            # Narrator shouldn't slip into first person text accidentally
            if text.startswith("I am ") or " my " in text.lower():
                print(f"⚠️ Warning: Narrator might have slipped into first-person at turn {turn_num}")

        if speaker in ["Emma", "Liam"]:
            has_actors = True
            # 2. ENFORCE CHARACTER PERSPECTIVE: Catch third-person character slip-ups
            if text.startswith("He ran") or text.startswith("She said"):
                print(f"❌ Perspective Failure: Character {speaker} is speaking in third-person at turn {turn_num}.")
                return script_data, False

            # 3. ENFORCE CHARACTER RETENTION WALL: Stop meta-talk leaking into actors
            if "phrasal verb" in text.lower() or "expression means" in text.lower():
                print(f"❌ Persona Failure: Actor {speaker} broke character to explain a lesson at turn {turn_num}.")
                return script_data, False

        # 4. CAPTURE THE SHIFTING PAUSE MARKER
        if "[PAUSE 3 SECONDS]" in text:
            has_pause = True

    # Final logic balance check
    if not has_narrator or not has_actors:
        print("❌ Cast Failure: Script is missing either the Narrator or the Protag actors.")
        return script_data, False

    if not has_pause:
        print("❌ Interactive Failure: Script did not include the [PAUSE 3 SECONDS] token.")
        return script_data, False

    print(f"✅ Organic Script Verification Passed! Verified {turn_count} turns successfully.")
    return script_data, True


def ensure_english_seo_opener(description: str) -> str:
    """Ensure first line uses high-intent SEO opener with 🎯 icon."""
    text = str(description or "").strip()
    if not text:
        return (
            "🎯 In this video, learn practical English expressions. Improve your English skills with natural expressions and phrasal verbs used in real-life scenarios. Master natural English for real conversations and learn to speak like a native!"
        )
    lines = text.splitlines()
    opener = lines[0].lower() if lines else ""
    if "🎯" in opener or ("in this video, learn" in opener and "natural english" in text.lower()):
        return text
    seo_line = "🎯 In this video, learn practical English expressions. Improve your English skills with natural expressions and phrasal verbs used in real-life scenarios. Master natural English for real conversations and learn to speak like a native!"
    rest = lines if lines else []
    return seo_line + "\n\n" + "\n".join(rest)


def build_scene_timeline(scenes: list, per_turn_times: list) -> str:
    """Build a formatted timeline block from scene turn ranges and Kokoro audio timings."""
    if not scenes or not per_turn_times:
        return "0:00 - Start"

    def fmt_time(seconds: float) -> str:
        seconds = max(0, int(seconds))
        return f"{seconds // 60}:{seconds % 60:02d}"

    lines = []
    for scene in scenes:
        start_turn = int(scene.get("start_turn", 0))
        end_turn = int(scene.get("end_turn", start_turn))
        start_turn = max(0, min(start_turn, len(per_turn_times) - 1))
        end_turn = max(start_turn, min(end_turn, len(per_turn_times) - 1))
        start_sec = per_turn_times[start_turn][0]
        label = scene.get("scene_label") or scene.get("image_filename", f"Scene {scene.get('scene_id', '?')}")
        label = re.sub(r"^scene_\d+_", "", str(label).replace(".jpg", "").replace(".png", "").replace("_", " ").title())
        lines.append(f"{fmt_time(start_sec)} - {label}")
    return "\n".join(lines)


def inject_scene_timeline(description: str, timeline_block: str) -> str:
    """Replace {scene_timeline} placeholder or upgrade an existing timeline section."""
    text = str(description or "").strip()
    if "{scene_timeline}" in text:
        return text.replace("{scene_timeline}", timeline_block)
    if re.search(r"📑\s*Timeline:", text, re.IGNORECASE):
        return re.sub(
            r"📑\s*Timeline:.*?(?=\n\n|\Z)",
            timeline_block,
            text,
            count=1,
            flags=re.DOTALL | re.IGNORECASE,
        )
    if re.search(r"\bTimeline:\b", text, re.IGNORECASE):
        return re.sub(
            r"Timeline:.*?(?=\n\n|\Z)",
            timeline_block.replace("📑 Timeline:", "Timeline:"),
            text,
            count=1,
            flags=re.DOTALL | re.IGNORECASE,
        )
    # Insert after comment block if present, else after opener
    comment_match = re.search(r"💬[^\n]+\n?", text)
    if comment_match:
        insert_at = comment_match.end()
        return text[:insert_at].rstrip() + "\n\n" + timeline_block + "\n\n" + text[insert_at:].lstrip()
    lines = text.split("\n\n", 1)
    if len(lines) == 2:
        return lines[0] + "\n\n" + timeline_block + "\n\n" + lines[1]
    return text + "\n\n" + timeline_block


def finalize_english_description(
    description: str,
    *,
    include_timeline: bool = False,
    is_quiz: bool = False,
) -> str:
    """Apply all English description post-processors."""
    text = ensure_english_seo_opener(description)
    text = ensure_english_description_cta(text, include_timeline=include_timeline)
    if is_quiz:
        text = ensure_english_quiz_shorts_hashtags(text)
    text = ensure_english_vibes_hashtags(text)
    return text


def ensure_english_description_cta(description: str, *, include_timeline: bool = False) -> str:
    """Guarantee core YouTube metadata CTAs even if the model skips them."""
    text = str(description or "").strip()
    lines = []
    for line in text.splitlines():
        if _PLAYLIST_LINE_RE.match(line):
            continue
        lines.append(line.rstrip())
    text = "\n".join(lines).strip()

    additions = []

    # Comment first, then playlist, then timeline, then subscribe
    if not re.search(r"\bcomment\b", text, re.IGNORECASE):
        additions.append("💬 Comment below: Which phrase will you practice today?")
    if "{playlist_url}" not in text:
        additions.append("📺 Watch the playlist here: {playlist_url}")
    if include_timeline and "{scene_timeline}" not in text and not re.search(
        r"\b(?:timeline|chapters?)\b", text, re.IGNORECASE
    ):
        additions.append("📑 Timeline:\n{scene_timeline}")
    if not re.search(r"\bsubscribe\b", text, re.IGNORECASE):
        additions.append("🔔 Subscribe to EnglishVibesHub for more English listening, speaking, and vocabulary practice.")

    if additions:
        text = (text + "\n\n" if text else "") + "\n\n".join(additions)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text


def ensure_english_quiz_shorts_hashtags(description: str) -> str:
    """Keep quiz Shorts hashtags in a predictable first hashtag line."""
    target_line = "#Shorts #EnglishQuiz #LearnEnglish #EnglishVibesHub"
    text = str(description or "").strip()
    if not text:
        return target_line

    hashtag_re = re.compile(r"#\w+")
    target_re = re.compile(
        r"\s*(?:#Shorts|#EnglishQuiz|#LearnEnglish|#EnglishVibesHub)\b",
        re.IGNORECASE,
    )

    cleaned_lines = []
    first_hashtag_index = None
    for line in text.splitlines():
        if not line.strip():
            cleaned_lines.append("")
            continue
        # Only remove target hashtags from lines that contain hashtags
        # Preserve lines without hashtags (like playlist, subscribe, etc.)
        if not hashtag_re.search(line):
            cleaned_lines.append(line)
            continue
        cleaned = target_re.sub("", line).strip()
        cleaned = re.sub(r" {2,}", " ", cleaned)
        if not cleaned:
            continue
        if first_hashtag_index is None and hashtag_re.search(cleaned):
            first_hashtag_index = len(cleaned_lines)
        cleaned_lines.append(cleaned)

    if first_hashtag_index is None:
        cleaned_lines.append(target_line)
    else:
        cleaned_lines.insert(first_hashtag_index, target_line)

    text = "\n".join(cleaned_lines).strip()
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text


def _normalize_dialogue_text(text: str) -> str:
    return re.sub(r"\s+", " ", str(text or "").strip().lower())


def _speaker_name(line: dict) -> str:
    return str(line.get("speaker") or line.get("character") or "").strip()


def flatten_dialogue(dialogue_list: list) -> list:
    """Recursively flattens nested lists or dictionaries containing dialogue keys."""
    if not dialogue_list:
        return []
    flat = []
    for item in dialogue_list:
        if isinstance(item, dict):
            if "dialogue" in item and isinstance(item["dialogue"], list):
                flat.extend(flatten_dialogue(item["dialogue"]))
            elif "dialogue_list" in item and isinstance(item["dialogue_list"], list):
                flat.extend(flatten_dialogue(item["dialogue_list"]))
            else:
                flat.append(item)
        elif isinstance(item, list):
            flat.extend(flatten_dialogue(item))
        else:
            flat.append(item)
    return flat


def align_scenes_to_turns(scenes: list, dialogue: list) -> list:
    """Attach start_turn/end_turn to each scene, prioritizing direct indices if present."""
    if not scenes or not dialogue:
        return scenes

    # Standardize image filenames to .png extension strictly
    for scene in scenes:
        if isinstance(scene, dict) and "image_filename" in scene and scene["image_filename"]:
            base, _ = os.path.splitext(scene["image_filename"])
            scene["image_filename"] = base + ".png"

    dialogue = flatten_dialogue(dialogue)
    num_turns = len(dialogue)

    # Check if all scenes have direct start_turn and end_turn indices
    has_indices = all("start_turn" in s and "end_turn" in s for s in scenes)
    if has_indices:
        aligned = []
        for scene in scenes:
            scene = dict(scene)
            # Remove repeated dialogues from scene to avoid duplication in JSON
            scene.pop("dialogues", None)
            scene.pop("dialogue_list", None)
            try:
                start = max(0, min(int(scene["start_turn"]), num_turns - 1))
                end = max(start, min(int(scene["end_turn"]), num_turns - 1))
            except (ValueError, TypeError):
                start = 0
                end = 0
            scene["start_turn"] = start
            scene["end_turn"] = end
            aligned.append(scene)

        # Enforce sequential continuity and complete dialogue coverage
        if aligned:
            aligned[0]["start_turn"] = 0
        
        # Redistribute turns evenly across scenes to ensure complete coverage
        if len(aligned) > 0:
            turns_per_scene = max(1, num_turns // len(aligned))
            remainder = num_turns % len(aligned)
            
            for i in range(len(aligned)):
                aligned[i]["start_turn"] = i * turns_per_scene + min(i, remainder)
                aligned[i]["end_turn"] = aligned[i]["start_turn"] + turns_per_scene - 1
                if i < remainder:
                    aligned[i]["end_turn"] += 1
            
            # Ensure the last scene covers to the end
            aligned[-1]["end_turn"] = num_turns - 1

        return aligned

    # Legacy fallback: sequential dialogue matching based on dialogues list
    turn_idx = 0
    aligned = []
    for scene in scenes:
        scene = dict(scene)
        dialogues = scene.get("dialogues") or scene.get("dialogue_list") or []
        if not dialogues:
            aligned.append(scene)
            continue

        start_turn = turn_idx
        for d_line in dialogues:
            if turn_idx >= len(dialogue):
                print(f"  [warn] Scene {scene.get('scene_id')}: ran out of dialogue turns at index {turn_idx}")
                break
            expected_text = _normalize_dialogue_text(d_line.get("text", ""))
            actual_text = _normalize_dialogue_text(dialogue[turn_idx].get("text", ""))
            expected_speaker = _speaker_name(d_line).lower()
            actual_speaker = _speaker_name(dialogue[turn_idx]).lower()
            if expected_text and expected_text != actual_text:
                print(
                    f"  [warn] Scene {scene.get('scene_id')} turn {turn_idx}: "
                    f"dialogue mismatch (expected '{d_line.get('text', '')[:40]}...')"
                )
            if expected_speaker and actual_speaker and expected_speaker != actual_speaker:
                print(
                    f"  [warn] Scene {scene.get('scene_id')} turn {turn_idx}: "
                    f"speaker mismatch (expected {expected_speaker}, got {actual_speaker})"
                )
            turn_idx += 1

        end_turn = max(start_turn, turn_idx - 1)
        scene["start_turn"] = start_turn
        scene["end_turn"] = end_turn
        scene.pop("dialogues", None)
        scene.pop("dialogue_list", None)
        aligned.append(scene)

    if turn_idx < len(dialogue):
        print(f"  [warn] {len(dialogue) - turn_idx} dialogue turn(s) not assigned to any scene")
    return aligned


def generate_english_storyboard(script: dict, *, portrait: bool = False) -> dict:
    """Post-dialogue Groq call: group dialogue into Pixar-style visual scenes."""
    dialogue = script.get("dialogue", [])
    if not dialogue:
        script.setdefault("scenes", [])
        return script

    turns_summary = "\n".join(
        f"{i}: [{line.get('speaker', '?')}] {line.get('text', '')[:150]}"
        for i, line in enumerate(dialogue[:120])
    )
    style_suffix = (
        ENGLISH_STORYBOARD_STYLE_SUFFIX_PORTRAIT
        if portrait
        else ENGLISH_STORYBOARD_STYLE_SUFFIX_LANDSCAPE
    )
    theme = script.get("theme") or script.get("title", "English Lesson")

    prompt = f"""You are an expert AI storyboard director for a 3D Pixar-style YouTube channel.
Analyze the input script. For each dialogue row, generate a highly descriptive visual prompt.

TOPIC / THEME: {theme}

DIALOGUE TURNS (index: [Speaker] text):
{turns_summary}

CRITICAL RULES:
1. Always maintain character consistency: Emma has brown hair in a neat ponytail. Liam has short blonde hair.
2. The style must ALWAYS be: "{style_suffix}"
3. The background and character actions must match the literal words spoken in the dialogue text.
4. Create 8-12 scenes total for visual variety (roughly 1-2 dialogue turns per scene).
5. Change scenes frequently to maintain viewer engagement - every 15-20 seconds in the final video.
6. Each scene needs a descriptive image_filename like scene_1_library_discussion.png (lowercase, underscores, strictly .png extension).
7. Each scene must specify the 'start_turn' and 'end_turn' as the integer dialogue turn indices (matching the DIALOGUE TURNS list indices above) that are covered by this scene. Ensure the scenes sequentially cover all turns.

Output ONLY valid JSON with this schema:
{{
  "theme": "string",
  "scenes": [
    {{
      "scene_id": 1,
      "scene_label": "string (short chapter label for YouTube timeline, e.g. Crisis Hook)",
      "image_filename": "scene_1_library_discussion.png",
      "visual_prompt": "string (ONE highly descriptive 3D Pixar-style prompt ending with: {style_suffix})",
      "start_turn": 0,
      "end_turn": 2
    }}
  ]
}}
"""
    try:
        res = call_groq_json(prompt)
        scenes = res.get("scenes", [])
        if not isinstance(scenes, list):
            scenes = []
        for scene in scenes:
            vp = str(scene.get("visual_prompt", "")).strip()
            if vp and style_suffix.lower() not in vp.lower():
                scene["visual_prompt"] = f"{vp.rstrip('.')} {style_suffix}"
        script["theme"] = res.get("theme") or theme
        script["scenes"] = align_scenes_to_turns(scenes, dialogue)
        print(f"  Storyboard: {len(script['scenes'])} scene(s) generated")
    except Exception as exc:
        print(f"  Storyboard generation skipped (Groq error): {exc}")
        script.setdefault("scenes", [])
    return script


def attach_storyboard_to_script(script: dict, *, portrait: bool = False) -> dict:
    """Generate storyboard scenes and apply description post-processing."""
    script = generate_english_storyboard(script, portrait=portrait)
    is_quiz = script.get("video_format") in ("shorts_quiz", "shorts")
    include_timeline = not portrait and script.get("video_format") not in ("shorts", "shorts_quiz")
    if script.get("description"):
        script["description"] = finalize_english_description(
            script["description"],
            include_timeline=include_timeline,
            is_quiz=is_quiz,
        )
    return script


def get_published_topics() -> dict:
    """Load published English topics grouped by content type."""
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
    "Restaurant Disaster Story",
    "Job Interview Gone Wrong",
    "Travel Mishap at Airport",
    "First Date Disaster",
    "Lost in a Foreign City",
    "Workplace Misunderstanding",
    "Shopping Nightmare",
    "Hotel Check-in Crisis",
    "Phone Call Confusion",
    "Meeting New People Mistake",
    "Ordering Food Disaster",
    "Public Transport Panic"
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
        r"\bstay\s+tuned\b",
        r"\bnext\s+epis(?:ode|ide)\b",
        r"\bin\s+(?:the\s+)?(?:next|future|upcoming)\s+(?:episode|lesson|video|part)\b",
        r"\b(?:we|we'll|we\s+will)\s+(?:explore|cover|talk\s+about|look\s+at|continue)\b.*\bnext\b",
        r"\b(?:next|after\s+the)\s+break\b",
        r"\b(?:take|taking|let'?s\s+take)\s+a\s+(?:quick\s+)?break\b",
        r"\bwe'?ll\s+be\s+right\s+back\b",
        r"\bsee\s+you\s+(?:next|soon|later)\b",
        r"\blooking\s+forward\s+to\s+(?:it|next|seeing\s+you|continuing)\b",
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
        r"\bstay\s+tuned\b",
        r"\bnext\s+epis(?:ode|ide)\b",
        r"\bsee\s+you\s+(?:next|soon|later)\b",
    )
]

# Motivational/preachy patterns that cause viewer drop-off
_MOTIVATIONAL_PATTERNS = [
    re.compile(p, re.IGNORECASE)
    for p in (
        r"\bremember\b.*\bkey\b",
        r"\bkey\s+to\s+mastering\b",
        r"\bpractice.*practice.*practice\b",
        r"\bkeep\s+practicing\b",
        r"\bmove\s+on\s+to\s+(?:more\s+)?advanced\b",
        r"\bthe\s+key\s+is\b",
        r"\bimportant\s+to\s+remember\b",
        r"\bdon'?t\s+give\s+up\b",
        r"\bkeep\s+going\b",
        r"\byou\s+can\s+do\s+it\b",
        r"\bstay\s+motivated\b",
        r"\bnever\s+stop\s+learning\b",
        r"\bconsistency\s+is\s+key\b",
        r"\bpractice\s+makes\s+perfect\b",
        r"\bthe\s+more\s+you\s+practice\b",
        r"\bkeep\s+up\s+the\s+good\s+work\b",
        r"\byou'?re\s+doing\s+great\b",
        r"\bkeep\s+up\s+the\s+momentum\b",
        r"\blet'?s\s+keep\s+practicing\b",
        r"\bremember\s+to\s+practice\b",
    )
]

_NOT_FINAL_PART_RULES = """
CONTINUITY (THIS IS NOT THE FINAL PART OF THE VIDEO):
- Treat this as one invisible chunk inside a single continuous long-form video, not as a standalone episode.
- Do NOT thank listeners for watching or say goodbye.
- Do NOT ask viewers to like, subscribe, or hit the bell.
- Do NOT say "see you next time", "tune in next episode", "stay tuned", "let's take a break", "we'll be right back", "next episode", or similar closings.
- Do NOT preview future videos, future episodes, or a later break.
- Do NOT use motivational or preachy language like "remember the key to mastering", "practice practice practice", "keep practicing", "move on to advanced", "don't give up", "you can do it", "stay motivated", "never stop learning", "consistency is key", "practice makes perfect", "keep up the good work", "you're doing great", or similar encouragement phrases.
- End on an open conversation beat or unfinished teaching moment so the next generated part continues naturally.
"""


def is_outro_line(text: str) -> bool:
    return any(p.search(text) for p in _OUTRO_PATTERNS)


def is_cta_line(text: str) -> bool:
    return any(p.search(text) for p in _CTA_PATTERNS)


def is_motivational_line(text: str) -> bool:
    return any(p.search(text) for p in _MOTIVATIONAL_PATTERNS)


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

    recent_topics = published_topics[-50:] if published_topics else []

    # ------ENABLE BELOW IF NEED ALL TOPICS ACROSS TYPES TO BE CONSIDERED FOR AVOIDANCE IN GROQ PROMPT------
        # Merge history from ALL content types so Groq avoids themes already covered
        # in any format (e.g. a "bank" shorts episode stops "banking" being chosen for podcast).
        # all_published: list = []
        # seen: set = set()
        # for key, entries in topics_data.items():
        #     for entry in entries:
        #         norm = str(entry).strip()
        #         if norm and norm not in seen:
        #             seen.add(norm)
        #             all_published.append(norm)

        # # Keep the most recent 60 unique entries to stay within token budget
        # recent_topics = all_published[-60:] if all_published else []
    # ------ENABLE ABOVE IF NEED ALL TOPICS ACROSS TYPES TO BE CONSIDERED FOR AVOIDANCE IN GROQ PROMPT------

    avoid_instruction = ""
    if recent_topics:
        avoid_instruction = f"""
    CRITICAL: Avoid repeating or closely matching any of these previously published topics/titles:
    {json.dumps(recent_topics, indent=2)}
    """

    prompt = f"""
    Generate a high-CTR single, highly engaging topic for an English learning {type_label}.
    {avoid_instruction}

    STORYTELLING FOCUS (for podcast episodes):
    - The topic MUST be story-driven: a real-world disaster, mistake, conflict, or crisis scenario
    - Examples: Restaurant Disaster, Job Interview Gone Wrong, Travel Mishap, First Date Disaster, Lost in Foreign City
    - Focus on high-stress moments where English mistakes cause problems
    - The story should have a clear problem → solution narrative arc

    CRITICAL TITLE RULES:
    - Title format: [Hook phrase] | [Story context]. Example: "DON'T Say This at a Restaurant | Ordering Disaster Story"
    - Front-load keywords: Start with "English listening practice", "English speaking practice", or "Learn English"
    - Include topic-specific vocabulary immediately after the main keyword phrase
    - Use natural keyword variation (e.g., if topic is "restaurant", include "dining", "eatery", "cafe" in the search_keyword)

    Return ONLY a JSON object with highly engaging high-CTR 'topic' and 'search_keyword' keys.
    Example: {{"topic": "DON'T Say This at a Restaurant | Ordering Disaster Story", "search_keyword": "English Conversation Practice restaurant ordering mistakes"}}
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

    dialogue = flatten_dialogue(dialogue)

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

    # Filter out mid-episode sign-off lines and motivational/preachy lines from the remaining body
    body = [t for t in dialogue if not is_outro_line(t.get("text", "")) and not is_motivational_line(t.get("text", ""))]
    return prefix + body + suffix


# DEPRECATED: combine_english_parts removed - replaced by single storytelling prompt
# def combine_english_parts(part1_data: dict, part2_data: dict, part3_data: dict, topic: str) -> dict:
#     ... (removed as part of storytelling format migration)

def call_groq_json(user_prompt: str) -> dict:
    res = groq_chat_json(
        messages=[
            {
                "role": "system",
                "content": (
                    "You generate perfect JSON for educational English conversation podcasts. "
                    "Each multi-part episode has exactly ONE closing outro at the very end; "
                    "never add subscribe or goodbye language in middle parts. "
                    "Never use motivational or preachy language like 'remember the key to mastering', "
                    "'practice practice practice', 'keep practicing', 'move on to advanced', 'don't give up', "
                    "'you can do it', 'stay motivated', 'never stop learning', 'consistency is key', "
                    "'practice makes perfect', 'keep up the good work', 'you're doing great', or similar encouragement phrases."
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


def annotate_script_with_idiom_windows(script_data: dict) -> dict:
    """
    Post-generation Groq call: given the finalized dialogue, ask Groq to
    identify each idiom / phrasal verb and the dialogue turn index range
    when it is first *introduced and explained* (not just mentioned).

    Mutates script_data in-place by adding:
        script_data["idiom_windows"] = [
            {
              "idiom":       "get out of hand",
              "type":        "phrasal_verb",   # or "idiom"
              "definition":  "to become uncontrollable",
              "start_turn":  4,
              "end_turn":    6,
            },
            ...
        ]

    Returns the (mutated) script_data dict.
    Falls back to an empty list on any Groq error — never blocks the pipeline.
    """
    dialogue = script_data.get("dialogue", [])
    if not dialogue:
        script_data.setdefault("idiom_windows", [])
        return script_data

    # Build a compact dialogue summary for the prompt (index + speaker + text)
    max_turns = min(len(dialogue), 80)  # cap to stay within token budget
    turns_summary = "\n".join(
        f"{i}: [{line.get('speaker','?')}] {line.get('text','')[:120]}"
        for i, line in enumerate(dialogue[:max_turns])
    )

    prompt = f"""You are analysing an English learning podcast dialogue.

DIALOGUE TURNS (index: [Speaker] text):
{turns_summary}

TASK:
Identify every idiom or phrasal verb that is explicitly INTRODUCED AND EXPLAINED to the listener in this dialogue (not just casually mentioned). For each one return:
- "idiom":      the exact phrase
- "type":       "idiom" or "phrasal_verb"
- "definition": one concise sentence explaining its meaning
- "start_turn": dialogue turn index where the explanation STARTS (0-based integer)
- "end_turn":   dialogue turn index where the explanation ENDS (inclusive, 0-based integer)

RULES:
- Only include phrases that are actually taught/explained to the listener.
- start_turn and end_turn must be valid 0-based integers within range 0..{max_turns - 1}.
- end_turn must be >= start_turn.
- If no idioms or phrasal verbs are explained, return an empty array.
- Output ONLY valid JSON.

JSON SCHEMA:
{{
  "idiom_windows": [
    {{
      "idiom": "string",
      "type": "idiom or phrasal_verb",
      "definition": "string",
      "start_turn": 0,
      "end_turn": 2
    }}
  ]
}}
"""
    try:
        res = groq_chat_json(
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are a precise JSON extractor. "
                        "Return only valid JSON with no extra text."
                    ),
                },
                {"role": "user", "content": prompt},
            ],
            max_tokens=1024,
            temperature=0.2,
        )
        windows = res.get("idiom_windows", [])
        if not isinstance(windows, list):
            windows = []

        # Clamp turn indices to valid range
        n = len(dialogue)
        cleaned = []
        for w in windows:
            try:
                st = max(0, min(int(w.get("start_turn", 0)), n - 1))
                et = max(st, min(int(w.get("end_turn", st)), n - 1))
                cleaned.append({
                    "idiom":       str(w.get("idiom", "")).strip(),
                    "type":        str(w.get("type", "idiom")).strip(),
                    "definition":  str(w.get("definition", "")).strip(),
                    "start_turn":  st,
                    "end_turn":    et,
                })
            except (TypeError, ValueError):
                continue

        script_data["idiom_windows"] = cleaned
        print(f"  Idiom annotation: {len(cleaned)} window(s) identified")
    except Exception as exc:
        print(f"  Idiom annotation skipped (Groq error): {exc}")
        script_data.setdefault("idiom_windows", [])

    return script_data


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
Create a high-retention & high-CTR 7-day weekly challenge playlist plan for the YouTube channel 'EnglishVibesHub' (@EnglishVibesHub-s6w).
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
    You are an expert short-form scriptwriter. Generate a high-retention, 25-second YouTube Shorts English quiz loop based on Day {day_num} of the '{series_title}' challenge on @EnglishVibesHub-s6w.

    LESSON FOCUS: {focus}
    {ENGLISH_METADATA_RULES}

    TIME ALLOCATION RULES:
    - [0-3s] Hook: Emma introduces the Day {day_num} Challenge question clearly.
    - [3-13s] Sequential Options: Liam presents Options A, B, and C sequentially. Allocate exactly 3.3 seconds per option (Liam should have 3 separate dialogue turns for these).
    - [13-20s] Context Hint: Liam provides an educational example sentence or hint related to "{focus}".
    - [20-25s] Answer Reveal & Perfect Loop CTA: Emma reveals the answer and cuts instantly into a seamless word loop back to the hook.

    PACING:
    The pacing must allow English learners time to read, but remain engaging enough to prevent swipe-aways.

    LEVERAGE COMMENTS: Generate a 'pinned_comment' question to trigger algorithmic signals.

    JSON SCHEMA:
    {{
      "title": "string (Searchable keyword-rich title under 60 characters. Front-load with 'English Quiz' or 'English listening practice'. Include topic first, then Day {day_num} in the suffix at the end. Use keyword variations. e.g., 'English Quiz: Hair Salon Vocabulary - Day {day_num}')",
      "description": "string (Follow METADATA RULES template. First 2 lines MUST use 'Natural English' and 'Speak like a native'. Place comment question in lines 3-5. Include {{scene_timeline}} placeholder for scene chapters, subscribe CTA, playlist placeholder, #EnglishVibesHub, and hashtags mirroring 'tags')",
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
    script_data["description"] = finalize_english_description(
        script_data.get("description", ""), is_quiz=True
    )
    return attach_storyboard_to_script(script_data, portrait=True)

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
        turn_count = "20-25"
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
        turn_count = "18-22"

    prompt = f"""
You are writing a standalone video script for a 7-day English learning challenge playlist on 'EnglishVibesHub' (@EnglishVibesHub-s6w).

SERIES: {series_title}
DAY: {day_number}
TITLE: {day.get('title')}
{avoid_instruction}
FOCUS: {day.get('focus')}
PRACTICE TASK: {day.get('practice_task')}
{ENGLISH_METADATA_RULES}

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
  "title": "string (High-CTR title under 60 characters. Front-load with 'English listening practice', 'English speaking practice', or 'Learn English'. Include Day {day_number} in the suffix at the end. Use hooks like 'STOP Doing This' or 'DON'T Get Stuck'. Include keyword variations like 'hairdresser/stylist' for hair salon topics. e.g., 'English Listening Practice: Restaurant Vocabulary - Day {day_number}')",
  "title_options": ["string"],
  "description": "string (Follow METADATA RULES template. First 2 lines MUST use 'Natural English' and 'Speak like a native'. Place comment question in lines 3-5. Include {{scene_timeline}} for scene chapters, subscribe CTA, playlist placeholder, #EnglishVibesHub, and hashtags mirroring 'tags')",
  "pinned_comment": "string (An engaging question or call to action to pin in the comments)",
  "tags": ["string (Provide 5-8 SEO-focused tags)"],
  "theme": "string (short topic label for storyboard, e.g. 'Phrasal Verbs at Work')",
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
    script["description"] = finalize_english_description(
        script.get("description", ""), include_timeline=True
    )

    if not script.get("title"):
        title_options = script.get("title_options") or []
        if title_options:
            script["title"] = title_options[0]

    thumbnail = generate_thumbnail_text(f"{day.get('title')} | {series_title}", is_challenge=True)
    script["thumbnail_text"] = thumbnail.get("thumbnail_text") or script.get("title", "")
    script["thumbnail_concept"] = thumbnail.get("thumbnail_concept", "")

    script = _clean_challenge_dialogue(script, day_number)
    return attach_storyboard_to_script(script, portrait=False)


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
    print("Generating storytelling script...")

    prompt_short_story = f"""
You are an elite showrunner and scriptwriter for the multi-character storytelling channel EnglishVibesHub (@EnglishVibesHub-s6w). Write a highly engaging, non-linear, dramatic English audio-story script.

TOPIC: {topic}
{avoid_instruction}

{ENGLISH_METADATA_RULES.replace('{scene_timeline}', '{{scene_timeline}}').replace('{playlist_url}', '{{playlist_url}}')}

VOICE CAST & CHARACTER ASSIGNMENT ROLES:
- "Narrator" (Voice Profile: af_sarah): Speaks strictly in the third person. Sets scenes, creates dramatic transitions, and handles intermediate language definitions.
- "Emma" (Voice Profile: af_heart) & "Liam" (Voice Profile: am_echo): Main protagonist characters experiencing the event. They must speak 100% in the first-person ("I", "my", "we"). They can talk to each other, argue, collaborate, or panic.
- "Guest" (Voice Profile: af_sky): Optional bystander, antagonist, or clerk. Speaks naturally based on the scene setting requirements.

CRITICAL PIPELINE VALIDATION RULES:
1. OUTPUT CONSTRAINTS: Return ONLY a valid, parseable JSON block matching the structure pattern layout below. Do not wrap in conversational meta-text.
2. TOTAL SCRIPT VOLUMETRIC BUDGET: The total conversational sequence array must contain between 12 and 18 turns maximum. To preserve a strict under-3-minute video runtime, individual dialogue turns must be tight and punchy (between 1 and 3 sentences maximum per turn).
3. PERSPECTIVE GUARD: The Narrator must never speak in the first person. Characters must never speak in the third person. Liam and Emma must stay entirely inside the world of the crisis; they must never step out to teach words or talk about the English lesson.
4. INTEGRATED LESSON ENGINE: The Narrator must pause the scene exactly 2 to 3 times to break down a phrasal verb used naturally by a character. The lesson must feel like a tactical observation of the drama, not a school textbook interruption.
5. INTERACTIVE BEAT PLACEMENT: Include exactly one organic fill-in-the-blank vocabulary query challenge right before the narrative climax beat. The answer reveal must happen naturally through the Narrator's tracking lines.

STRUCTURAL MOVEMENT STAGES:
- Stage 1: The Crisis Hook (In Media Res start, high stakes, emotional conflict).
- Stage 2: Narrative Complications (The obstacle worsens, characters react, argue, or pivot strategies).
- Stage 3: Organic Teaching Blocks (Narrator strategically breaks down expressions as they occur naturally in dialogue).
- Stage 4: Climax & Challenge (The absolute peak of tension, followed by the viewer pause-and-guess beat).
- Stage 5: Resolution & Seamless Engagement (The crisis resolves. The Narrator smoothly redirects the viewer directly to the pinned comment question without generic intros/outros).

JSON OUTPUT FORMAT (Follow this structure exactly):
{{
  "title": "High-CTR Title matching METADATA RULES",
  "description": "String matching DESCRIPTION TEMPLATE exactly",
  "pinned_comment": "Narrative retention engagement question",
  "tags": [ "Tag1", "Tag2" ],
  "dialogue": [
    {{
      "turn_number": 1,
      "speaker": "Narrator",
      "text": "The wind howled against the terminal windows as the flight monitors began flipping to canceled."
    }},
    {{
      "turn_number": 2,
      "speaker": "Emma",
      "text": "Are you seeing this, Liam? Our connection is totally gone and my phone has absolutely no cellular service!"
    }}
  ],
  "thumbnail_text": "TEXT",
  "thumbnail_concept": "CONCEPT",
  "theme": "THEME",
  "scenes": [
    {{
      "scene_id": 1,
      "scene_label": "The Storm Hits",
      "image_filename": "scene_storm_hits.png",
      "visual_prompt": "Cinematic shot of a crowded dark airport terminal during a storm.",
      "start_turn": 1,
      "end_turn": 2
    }}
  ]
}}
"""
    is_valid = False
    attempts = 0

    while not is_valid and attempts < 3:
        attempts += 1
        print(f"🔄 Generation Attempt {attempts}...")

        raw_script = call_groq_json(prompt_short_story)
        script, is_valid = validate_organic_english_script(raw_script)

    if not is_valid:
        print("⚠️ Groq failed to generate a perfect script after 3 tries. Using last attempt.")

    thumbnail = generate_thumbnail_text(topic, is_challenge=False)
    script["thumbnail_text"] = thumbnail.get("thumbnail_text") or script.get("title", "")
    script["thumbnail_concept"] = thumbnail.get("thumbnail_concept", "")

    save_published_topic(script.get("title", topic), topic_type="podcast")

    return attach_storyboard_to_script(script, portrait=False)


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
    avoid_instruction = f"\nAvoid welcoming to channel, and avoid repeating concepts or phrasing from these recent shorts:\n{json.dumps(recent, indent=2)}" if recent else ""

    print(f"\nSelected Shorts topic: {topic}")
    prompt = f"""
You are writing a short, snappy English learning podcast script for a high CTR YouTube Short on 'EnglishVibesHub' (@EnglishVibesHub-s6w).
TOPIC: {topic}
{avoid_instruction}
{ENGLISH_METADATA_RULES}

CRITICAL RULES:
- Output ONLY valid JSON
- The `dialogue` array MUST contain around 8-12 turns in total (25-40 seconds of speaking).
- Hosts must be Emma (energetic, helpful) and Liam (curious, friendly).
- Teach 1 or 2 specific phrasal verbs, idioms, or useful expressions related to the topic.
- Use searchable keywords in the title: e.g., "English in 60 Seconds" or "Speak English Like a Native".
- Do NOT use mid-episode sign-offs or long pauses or one saying it was really helpful etc.
- The script must start with a strong hook and end with a phrase that seamlessly loops back to the beginning.
- The final turn should include a quick call to action that encourages re-watching (e.g., "Did you catch that? Let's try another one...").

STYLE:
- Fast-paced, punchy, conversational, and highly engaging.
- Perfect for vertical YouTube Shorts.
- No intro, no outro. The video should feel like it starts mid-conversation and loops perfectly.

JSON SCHEMA:
{{
  "title": "string (High-CTR, curiosity-based Short title under 70 chars using hooks like 'STOP Saying...', 'DON'T Say This', or '1 Mistake All Learners Make')",
  "title_options": ["string"],
  "description": "string (Follow METADATA RULES template. First 2 lines MUST use 'Natural English' and 'Speak like a native'. Place comment question in lines 3-5. Include subscribe CTA, playlist placeholder, #Shorts, #EnglishVibesHub, and hashtags mirroring 'tags')",
  "pinned_comment": "string (An engaging question to pin in the comments section)",
  "tags": ["string (Provide 5-8 SEO-focused English learning and topic-specific tags)"],
  "theme": "string (short topic label for storyboard)",
  "visual_keywords": ["string (legacy fallback: 5-8 visual search words)"],
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
    script_data["description"] = finalize_english_description(script_data.get("description", ""))

    if not script_data.get("title"):
        title_options = script_data.get("title_options") or []
        if title_options:
            script_data["title"] = title_options[0]
    
    save_published_topic(script_data.get("title", topic), topic_type="shorts")
    
    return attach_storyboard_to_script(script_data, portrait=True)

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
            f"\nAvoid welcoming to channel, and avoid repeating or using the same distractors from these recent quizzes:\n"
            + json.dumps(recent, indent=2)
        )
    
    prompt = f"""
    You are an expert short-form scriptwriter. Generate a high-retention, 25-second YouTube Shorts English quiz loop between Emma and Liam for 'EnglishVibesHub' (@EnglishVibesHub-s6w).
    TOPIC: The idiom or expression '{topic}'
    {avoid_instruction}
    {ENGLISH_METADATA_RULES}
    
    HIGH CTR & SEARCH-FOCUSED TITLE STRATEGY:
    High-CTR, curiosity-based title using hooks like 'STOP Making These Mistakes', 'DON'T Use This Wrong', or 'The #1 Way To...'. e.g., 'STOP Saying I'm Fine: Better Ways to Respond') along with searchable keywords: "English Practice for Beginners", "Easy English Listening", "English Quiz" etc.

    TIME ALLOCATION RULES:
    - [0-3s] Hook: Emma introduces the idiom question clearly.
    - [3-13s] Sequential Options: Liam presents Options A, B, and C sequentially. Allocate exactly 3.3 seconds per option (Liam should have 3 separate dialogue turns for these).
    - [13-20s] Context Hint: Liam provides an educational example sentence or hint.
    - [20-25s] Answer Reveal & Perfect Loop CTA: Emma reveals the answer and ends with a phrase that seamlessly loops back to the hook (e.g., "Let's try another one..."). Do NOT repeat the original question.

    PACING:
    The pacing must allow English learners time to read, but remain engaging enough to prevent swipe-aways.

    LEVERAGE COMMENTS: Generate a 'pinned_comment' question to trigger algorithmic signals.

    JSON SCHEMA:
    {{
      "title": "string (High-CTR, searchable title under 70 chars, e.g., 'English Quiz: STOP Making This Mistake!')",
      "description": "string (Follow METADATA RULES template. First 2 lines MUST use 'Natural English' and 'Speak like a native'. Place comment question in lines 3-5. Include subscribe CTA, playlist placeholder, #Shorts, #EnglishQuiz, #EnglishVibesHub, and hashtags mirroring 'tags')",
      "pinned_comment": "string (Engaging specific question for the comments section)",
      "tags": ["string (Provide 5-8 SEO-focused tags)"],
      "correct_answer": "string",
      "theme": "string (short topic label for storyboard, e.g. 'Idiom Quiz - Break a Leg')",
      "visual_keywords": ["string (legacy fallback: 5-8 visual search words)"],
      "dialogue": [
        {{ "speaker": "Emma", "text": "..." }},
        {{ "speaker": "Liam", "text": "..." }}
      ]
    }}
    """
    script_data = call_groq_json(prompt)
    script_data["video_format"] = "shorts_quiz"
    script_data["description"] = finalize_english_description(
        script_data.get("description", ""), is_quiz=True
    )
    save_published_topic(script_data.get("title", topic), topic_type="quiz")
    return attach_storyboard_to_script(script_data, portrait=True)
