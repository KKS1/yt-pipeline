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
- Titles must be high-CTR, curiosity-driven, and under 70 characters (YouTube truncates on mobile at ~60 chars).
- Use ONE of these title structures — do NOT use the same one twice in a row:
  A. Question: "Why Do English Speakers Say [X] Instead of [Y]?"
  B. Mistake hook: "The [X] Mistake Almost Every Learner Makes"
  C. Number list: "5 [X] That Sound Rude (But You Don't Know It)"
  D. Comparison: "[A] vs [B]: What's the Real Difference?"
  E. Curiosity gap: "The [X] Phrase Native Speakers Use Daily"
  F. Problem-solution: "Stop Saying [X] — Say This Instead"
  G. Cultural hook: "Why [X] Is Offensive in English (Nobody Told You)"
  H. Story-driven: "I [X] and Everything Went Wrong"
- Use selective ALL CAPS for at most 1-2 power words (STOP, DON'T, NEVER, SECRET).
- Descriptions: Front-load a clear SEO line using natural language — e.g. "English listening practice for [topic]" or "Learn English with [topic] conversation" — followed by topic-specific vocabulary.
- Descriptions: Use keyword variation — if the topic is "restaurant", include "dining", "cafe", "food order" in the description to capture varied search intent.
- Descriptions MUST include "Natural English" and "Speak like a native" (or close variants) in the first 2-3 lines.
- Place the playlist and comment question CTAs immediately after the SEO opener (BEFORE timeline and other CTAs) to encourage early engagement.
- Descriptions must use readable spacing with blank lines between sections and tasteful CTA icons (📺, 💬, 🔔, 📑, 🎯, 📚).
- For long-form videos include a scene-based timeline section using the placeholder {scene_timeline} (scene labels only — timestamps are injected later).
- For quiz videos, include an "About This Lesson" section with AI-generated explanation of the idiom/theme before hashtags.
- Descriptions must include a subscribe CTA, relevant hashtags (always include #EnglishVibesHub), and exactly one playlist placeholder line: 📺 Watch the playlist here: {playlist_url}
- IMPORTANT: Use ONLY the {playlist_url} placeholder. Do NOT wrap actual URLs in curly braces like {https://...}. The placeholder will be replaced with the actual URL later.
- Tags must be high-intent SEO tags, mixing broad English-learning terms with topic-specific terms. Include keyword variations (e.g., if topic is "restaurant", include "dining", "eatery", "cafe").
- Pinned comments must ask a specific question that viewers can answer quickly.

DESCRIPTION TEMPLATE (adapt for shorts by omitting timeline and adding #Shorts hashtags):
🎯 In this video, learn English via [topic summary]. Improve your English skills with natural expressions, idioms and phrasal verbs used in real-life scenarios. Master natural English for real conversations and learn to speak like a native!

📑 About This Lesson:
What does the [idiom/theme] mean? In everyday English conversation, [explanation]. Test your vocabulary skills with our quick quiz!

📺 Watch the playlist here: {playlist_url}

💬 Comment below: [specific question]

🔔 Subscribe to EnglishVibesHub for more English listening, speaking, and vocabulary practice.

📑 Timeline:
{scene_timeline}

#LearnEnglish #EnglishListeningPractice #EnglishSpeakingPractice #EnglishVibesHub #[TopicTag] #EnglishForBeginners #EnglishPodcast ...

QUIZ SHORTS TEMPLATE (no timeline, hashtags at end):
🎯 English listening practice conversational: [Idiom Quiz - Theme]. Master natural English for real conversations and learn hidden meanings to speak like a native!

📑 About This Lesson:
What does the [idiom/theme] mean? In everyday English conversation, [explanation]. Test your vocabulary skills with our quick quiz!

📺 Watch the playlist here: {playlist_url}

💬 Comment below: [specific question]

🔔 Subscribe for more quick English quizzes!

#Shorts #EnglishQuiz #LearnEnglish #EnglishVibesHub #[TopicTag] #EnglishListeningPractice #EnglishSpeakingPractice
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


def ensure_english_vibes_hashtags(description: str, theme: str = "") -> str:
    """Ensure comprehensive hashtags appear at the end of the description with optimal SEO ordering."""
    text = str(description or "").strip()
    if not text:
        return "#LearnEnglish #EnglishVibesHub #EnglishListeningPractice #EnglishSpeakingPractice #EnglishPodcast"
    
    hashtag_re = re.compile(r"#\w+")
    
    # Remove all existing hashtags from anywhere in the text to rebuild them properly
    cleaned_lines = []
    for line in text.splitlines():
        if not line.strip():
            cleaned_lines.append("")
            continue
        # Preserve lines without hashtags (like playlist, subscribe, etc.)
        if not hashtag_re.search(line):
            cleaned_lines.append(line)
            continue
        # Remove hashtags from hashtag lines
        cleaned = hashtag_re.sub("", line).strip()
        cleaned = re.sub(r" {2,}", " ", cleaned)
        if cleaned:
            cleaned_lines.append(cleaned)
    
    # Build optimized hashtag line with comprehensive tags
    core_tags = "#LearnEnglish #EnglishVibesHub"
    practice_tags = "#EnglishListeningPractice #EnglishSpeakingPractice #EnglishVocabulary #EnglishPodcast"
    
    # Extract topic-specific hashtag from theme if available
    topic_tag = ""
    if theme:
        # Convert theme to hashtag format (remove spaces, special chars)
        topic_clean = re.sub(r"[^\w\s]", "", str(theme).strip())
        topic_words = topic_clean.split()
        if topic_words:
            # Use first meaningful word or phrase as topic tag
            topic_tag = "#" + "".join(word.capitalize() for word in topic_words[:2])
    
    # SEO ordering: core tags → topic-specific → practice tags
    hashtag_line = f"{core_tags} {topic_tag} {practice_tags}".strip()
    hashtag_line = re.sub(r" {2,}", " ", hashtag_line)  # Remove extra spaces
    
    # Append hashtags at the very end
    cleaned_text = "\n".join(cleaned_lines).strip()
    # Ensure blank line before hashtags
    if cleaned_text and not cleaned_text.endswith("\n"):
        cleaned_text += "\n\n"
    cleaned_text += hashtag_line
    
    # Clean up excessive blank lines
    cleaned_text = re.sub(r"\n{3,}", "\n\n", cleaned_text)
    return cleaned_text.strip()


def update_pinned_comment_with_channel_cta(script_data: dict) -> dict:
    """
    Append the channel CTA to the pinned comment for shorts and quiz formats.
    This encourages viewers to find the full playlists on the channel home page.
    """
    if not script_data:
        return script_data

    existing_comment = script_data.get("pinned_comment", "")
    channel_cta = "Find the full 'English Quiz' & 'English MasterClass Series' playlists and much more on our channel home page @EnglishVibesHub-S6W!"

    if existing_comment and channel_cta not in existing_comment:
        script_data["pinned_comment"] = f"{existing_comment}\n\n{channel_cta}"
    elif not existing_comment:
        script_data["pinned_comment"] = channel_cta

    return script_data


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

    # 1. VALIDATE TURN BOUNDARIES (Rule: 14 to 22 range)
    if turn_count < 14 or turn_count > 22:
        print(f"❌ Retention Failure: Script has {turn_count} turns. Must be between 14 and 22.")
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

        if speaker in ["Emma", "Liam", "Guest"]:
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
        PAUSE_PATTERN = re.compile(r'^\s*\[PAUSE\s+(\d+(?:\.\d+)?)\s*SECONDS?\]\s*$', re.IGNORECASE)
        if PAUSE_PATTERN.match(text.strip()):
            has_pause = True
        elif "[PAUSE" in text.upper():
            # Pause marker found but not on its own line - this is invalid
            print(f"❌ Pause Format Failure: Pause marker is mixed with other text at turn {turn_num}. Pause must be on its own turn.")
            return script_data, False

    # Final logic balance check
    if not has_narrator or not has_actors:
        print("❌ Cast Failure: Script is missing either the Narrator or the Protag actors.")
        return script_data, False

    if not has_pause:
        print("❌ Interactive Failure: Script did not include the [PAUSE 3 SECONDS] token.")
        return script_data, False

    print(f"✅ Organic Script Verification Passed! Verified {turn_count} turns successfully.")
    return script_data, True


def validate_podcast_script(raw_input):
    """
    Validation engine for English podcast format (character-driven, no Narrator).
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

    # 1. VALIDATE TURN BOUNDARIES (Rule: 35 to 65 range for podcast format)
    if turn_count < 35 or turn_count > 65:
        print(f"❌ Retention Failure: Script has {turn_count} turns. Must be between 35 and 65.")
        return script_data, False

    # 2. VALIDATE THEME FIELD (optional — fall back to title if missing)
    theme = script_data.get("theme", "")
    if not theme:
        # Auto-derive from title if available
        title = script_data.get("title", "")
        if title:
            script_data["theme"] = " ".join(title.split()[:5])
            print(f"  [info] Theme missing — derived from title: '{script_data['theme']}'")
        else:
            script_data["theme"] = "English Podcast"
            print("  [info] Theme missing — using fallback 'English Podcast'")
    elif len(theme.split()) < 2 or len(theme.split()) > 5:
        print(f"⚠️ Theme Warning: Theme should be 2-5 words. Got: '{theme}' (continuing anyway)")

    # 3. VALIDATE 5-PART PODCAST STRUCTURE
    # Check that dialogue contains the expected sections in reasonable order
    first_speaker = dialogue[0].get("speaker", "") if dialogue else ""
    last_speaker = dialogue[-1].get("speaker", "") if dialogue else ""
    
    # Story Hook should start with Caller (in media res), not hosts
    if first_speaker not in ["Caller", "StoryActor1", "StoryActor2"]:
        print(f"⚠️ Structure Warning: Podcast should start with Story Hook (Caller/StoryActor), not {first_speaker}. Current start may not be in media res.")
    
    # Should have hosts (Emma/Liam) present
    host_turns = [t for t in dialogue if t.get("speaker") in ["Emma", "Liam"]]
    if not host_turns:
        print("❌ Structure Failure: No host (Emma/Liam) turns found in dialogue.")
        return script_data, False
    
    # Should have Caller present
    caller_turns = [t for t in dialogue if t.get("speaker") == "Caller"]
    if not caller_turns:
        print("❌ Structure Failure: No Caller turns found in dialogue.")
        return script_data, False

    # Track structural validation targets
    has_pause = False
    has_hosts = False
    has_caller = False
    has_story_actors = False
    has_narrator = False

    # Track speaker roles to detect role switching
    speaker_roles = {}

    for turn in dialogue:
        turn_num = turn.get("turn_number")
        speaker = turn.get("speaker")
        text = turn.get("text", "")

        # Track what roles each speaker takes
        if speaker not in speaker_roles:
            speaker_roles[speaker] = set()
        
        # Check for Narrator presence (not allowed in podcast format)
        if speaker == "Narrator":
            has_narrator = True
            print(f"❌ Persona Failure: Narrator is not allowed in podcast format at turn {turn_num}. Use Caller instead.")
            return script_data, False
        
        if speaker == "Emma" or speaker == "Liam":
            has_hosts = True
            speaker_roles[speaker].add("host")
            # Hosts should not break into story dialogue
            if "I was at" in text or "I said to" in text:
                print(f"❌ Persona Failure: Host {speaker} slipped into first-person story dialogue at turn {turn_num}.")
                return script_data, False

        if speaker == "Caller":
            has_caller = True
            speaker_roles[speaker].add("caller")
            # Caller should speak in first person (this is expected)
            if not ("I " in text or "my " in text.lower() or "me " in text.lower()):
                print(f"⚠️ Warning: Caller might not be speaking in first-person at turn {turn_num}")

        if speaker in ["StoryActor1", "StoryActor2", "StoryActor1_Female", "StoryActor2_Male", "StoryActor1_AltMale", "StoryActor2_AltFemale"]:
            has_story_actors = True
            # Normalize to base role for tracking
            base_role = "StoryActor1" if speaker.startswith("StoryActor1") else "StoryActor2"
            speaker_roles[speaker].add("story_actor")
            # StoryActors speak as themselves in direct dialogue — check for narration patterns
            narration_patterns = [
                r"(?i)\bI\s+(raised|leaned|whispered|nodded|replied|said|shook|smiled|frowned|looked|turned|walked|stepped|tried|explained|answered|clarified|told)\b",
                r"(?i)\b(he|she)\s+(raised|leaned|whispered|nodded|replied|said|shook|smiled|frowned|looked|turned|walked|stepped|tried|explained|answered|clarified|told)\b",
                r"(?i)\b(we|they)\s+(had\s+to|tried\s+to|were)\s+(clarify|explain|tell|call)\b",
                r"(?i)\b(he|she)\s+heard\s+(me|us)\s+(say|tell|explain)\b",
                r"(?i)\ball\s+because\s+of\b",
                r"(?i)\bfrom\s+the\s+doorway\b",
                r"(?i)\blooking\s+uncomfortable\b",
            ]
            for pattern in narration_patterns:
                if re.search(pattern, text):
                    print(f"⚠️ Narration Warning: StoryActor {speaker} appears to be narrating instead of speaking directly at turn {turn_num}: '{text[:80]}...'")
                    break

        # Check for third-person slip-ups (invalid for character-driven format)
        if speaker in ["Caller", "StoryActor1", "StoryActor2", "StoryActor1_Female", "StoryActor2_Male", "StoryActor1_AltMale", "StoryActor2_AltFemale"]:
            if text.startswith("He ran") or text.startswith("She said") or text.startswith("They went"):
                print(f"❌ Perspective Failure: Character {speaker} is speaking in third-person at turn {turn_num}.")
                return script_data, False

        # 4. CAPTURE THE SHIFTING PAUSE MARKER
        PAUSE_PATTERN = re.compile(r'^\s*\[PAUSE\s+(\d+(?:\.\d+)?)\s*SECONDS?\]\s*$', re.IGNORECASE)
        if PAUSE_PATTERN.match(text.strip()):
            has_pause = True
        elif "[PAUSE" in text.upper():
            # Pause marker found but not on its own line - this is invalid
            print(f"❌ Pause Format Failure: Pause marker is mixed with other text at turn {turn_num}. Pause must be on its own turn.")
            return script_data, False

    # Final logic balance check
    if not has_hosts:
        print("❌ Cast Failure: Script is missing podcast hosts (Emma/Liam).")
        return script_data, False

    if not has_caller:
        print("❌ Cast Failure: Script is missing Caller character.")
        return script_data, False

    if not has_pause:
        print("❌ Interactive Failure: Script did not include the [PAUSE 3 SECONDS] token.")
        return script_data, False

    # Check for role switching (same speaker taking multiple incompatible roles)
    for speaker, roles in speaker_roles.items():
        if len(roles) > 1:
            print(f"❌ Role Consistency Failure: Speaker {speaker} is switching between roles: {roles}")
            return script_data, False

    # 4. VALIDATE 7-STAGE STRUCTURE: Caller Story Setup + Back-to-Studio checks
    # After the last StoryActor turn, there should be at least one Caller turn
    # before host analysis begins (the "linger confusion" reflection beat).
    last_story_actor_idx = -1
    first_story_actor_idx = -1
    first_host_idx = -1
    for i, t in enumerate(dialogue):
        sp = t.get("speaker", "")
        if first_host_idx == -1 and sp in ["Emma", "Liam"]:
            first_host_idx = i
        if sp.startswith("StoryActor"):
            if first_story_actor_idx == -1:
                first_story_actor_idx = i
            last_story_actor_idx = i
    
    # Check that Caller does NOT appear within the story section (between first and last StoryActor)
    if first_story_actor_idx >= 0 and last_story_actor_idx > first_story_actor_idx:
        caller_in_story = [
            t for t in dialogue[first_story_actor_idx:last_story_actor_idx + 1]
            if t.get("speaker") == "Caller"
        ]
        if caller_in_story:
            print(f"⚠️ Structure Warning: Caller appears {len(caller_in_story)} time(s) within the story section (between StoryActor turns). Caller should only appear in hook (Stage 1), caller setup (Stage 3), and back-to-studio (Stage 5), not in Stage 4.")
    
    # Check for Caller Story Setup: Caller should have turns between first host turn and first StoryActor
    if first_host_idx >= 0 and first_story_actor_idx > first_host_idx:
        caller_setup_turns = [
            t for t in dialogue[first_host_idx:first_story_actor_idx]
            if t.get("speaker") == "Caller"
        ]
        if not caller_setup_turns:
            print("⚠️ Structure Warning: No Caller turns found between studio intro and story. Expected a 'Caller Story Setup' beat where Caller briefly tells hosts what happened before the flashback.")
    
    if last_story_actor_idx >= 0 and last_story_actor_idx < len(dialogue) - 1:
        # Check if there's a Caller turn after the last StoryActor turn
        has_caller_reflection = any(
            t.get("speaker") == "Caller"
            for t in dialogue[last_story_actor_idx + 1:]
        )
        if not has_caller_reflection:
            print("⚠️ Structure Warning: No Caller reflection turn found after the story ends. Expected a 'back to studio' beat where Caller expresses lingering confusion.")

    # 5. VALIDATE VISUAL PROMPT CONTEXT ALIGNMENT
    scenes = script_data.get("scenes", [])
    if scenes:
        # Extract story content from dialogue
        story_text = " ".join([t.get("text", "") for t in dialogue if t.get("speaker") in ["Caller", "StoryActor1", "StoryActor2"]]).lower()
        
        # Generic location keywords that shouldn't appear unless story actually involves them
        generic_locations = [
            "marketplace", "subway", "train station", "train platform",
            "bus stop", "airport terminal", "high school", "school hallway",
            "classroom", "coffee shop", "shopping mall", "gym",
            "lockers", "hallway", "cafeteria",
        ]
        
        for scene in scenes:
            visual_prompt = scene.get("visual_prompt", "").lower()
            image_filename = scene.get("image_filename", "")
            
            # Skip host scenes
            if image_filename == "podcast_host.png":
                continue
            
            # Check if visual prompt uses generic locations not in story
            for loc in generic_locations:
                if loc in visual_prompt and loc not in story_text:
                    print(f"⚠️ Visual Prompt Warning: Scene {scene.get('scene_id')} uses generic location '{loc}' not found in story content. Visual prompt: {visual_prompt[:100]}")
                    # Don't fail validation, just warn

    print(f"✅ Podcast Script Verification Passed! Verified {turn_count} turns successfully.")
    return script_data, True


def ensure_english_seo_opener(description: str, theme: str = "") -> str:
    """Ensure first line uses high-intent SEO opener with 🎯 icon, customized with theme/topic."""
    text = str(description or "").strip()
    theme_clean = str(theme or "").strip()
    
    # Build customized opener with proper keyword front-loading
    # Rule: First 2-3 words MUST include "English listening practice", "English speaking practice", "English Quiz", or "Learn English"
    if theme_clean:
        seo_line = f"🎯 English listening practice conversational podcast: {theme_clean}. Master natural English for real conversations and speak like a native!"
    else:
        seo_line = "🎯 English listening practice: learn practical English expressions. Master natural English for real conversations and speak like a native!"
    
    if not text:
        return seo_line
    
    lines = text.splitlines()
    
    # Remove leading hashtag lines (they'll be re-added at the end)
    while lines and lines[0].strip().startswith("#"):
        lines.pop(0)
    
    if not lines:
        return seo_line
    
    opener = lines[0].lower()
    
    # Check if opener already has proper SEO keywords
    required_keywords = ["english listening practice", "english speaking practice", "english quiz", "learn english"]
    has_proper_opener = any(keyword in opener for keyword in required_keywords)
    
    if has_proper_opener:
        # If opener exists but lacks theme, update it
        if theme_clean and theme_clean.lower() not in text.lower():
            return seo_line + "\n\n" + "\n".join(lines[1:] if len(lines) > 1 else lines)
        return "\n".join(lines)
    
    # Add SEO opener at the beginning
    rest = "\n".join(lines)
    return seo_line + "\n\n" + rest


def build_scene_timeline(scenes: list, per_turn_times: list) -> str:
    """Build a formatted timeline block from scene turn ranges and Kokoro audio timings."""
    if not scenes or not per_turn_times:
        return "📑 Timeline:\n0:00 - Start"

    def fmt_time(seconds: float) -> str:
        seconds = max(0, int(seconds))
        return f"{seconds // 60}:{seconds % 60:02d}"

    lines = ["📑 Timeline:"]
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


def _integrate_fragments(description: str) -> str:
    """Integrate orphaned fragments into the SEO opener line instead of removing them.
    
    Fragments like 'tips for airport security' are useful content that should be
    integrated into the description rather than deleted.
    """
    text = str(description or "").strip()
    lines = text.splitlines()
    filtered_lines = []
    fragments = []
    
    # Pattern for lines that are valid section markers or structured content
    section_marker_pattern = re.compile(
        r'^(?:🎯|📺|💬|🔔|📑|#|Subscribe|Watch|Comment|Timeline|About)',
        re.IGNORECASE
    )
    
    for line in lines:
        line_stripped = line.strip()
        if not line_stripped:
            filtered_lines.append(line)
            continue
        
        # Keep lines with section markers, hashtags, or URLs
        if (section_marker_pattern.match(line_stripped) or 
            line_stripped.startswith('#') or 
            'http' in line_stripped.lower() or
            '{playlist_url}' in line_stripped):
            filtered_lines.append(line)
            continue
        
        # Check if this is an orphaned fragment: line without structure that appears
        # to be broken content (no emoji, no URL, not a hashtag, no section marker)
        # and starts with lowercase (suggesting it's a continuation without context)
        if (not section_marker_pattern.search(line_stripped) and
            line_stripped[0].islower()):
            # Check if it's a fragment: short line OR starts with common fragment words
            fragment_starters = ['tips', 'and', 'or', 'but', 'so', 'also', 'plus', 'then']
            if (len(line_stripped) < 60 or 
                any(line_stripped.lower().startswith(word) for word in fragment_starters)):
                # This is a fragment - collect it for integration
                fragments.append(line_stripped.rstrip('.!?'))
                continue
        
        filtered_lines.append(line)
    
    # If we have fragments and an SEO opener, integrate them naturally
    if fragments and filtered_lines and filtered_lines[0].startswith('🎯'):
        opener = filtered_lines[0]
        # Remove trailing punctuation from fragments for cleaner integration
        cleaned_fragments = [f.rstrip('.!?') for f in fragments]
        
        if cleaned_fragments:
            # Find the theme/topic part in the opener (after "Story:" or similar)
            if 'Story:' in opener:
                # Insert fragments after "Story:" with natural connector
                story_idx = opener.find('Story:')
                if story_idx != -1:
                    after_story = opener[story_idx + 6:].strip()
                    
                    # Build natural fragment text with appropriate connectors
                    fragment_parts = []
                    for i, frag in enumerate(cleaned_fragments):
                        frag_lower = frag.lower()
                        if frag_lower.startswith('tips'):
                            fragment_parts.append('with ' + frag)
                        elif frag_lower.startswith('and'):
                            # Remove "and" prefix and join with previous part
                            if fragment_parts:
                                fragment_parts[-1] += ' and ' + frag[3:].strip()
                            else:
                                fragment_parts.append(frag[3:].strip())
                        else:
                            fragment_parts.append(frag)
                    
                    fragment_text = ' '.join(fragment_parts)
                    # Add space before fragment text for proper spacing
                    if fragment_text and not fragment_text.startswith(' '):
                        fragment_text = ' ' + fragment_text
                    # Reconstruct opener with proper spacing
                    opener = opener[:story_idx + 6] + fragment_text + ' - ' + after_story
                    filtered_lines[0] = opener
    
    result = "\n".join(filtered_lines)
    result = re.sub(r'\n{3,}', '\n\n', result)
    return result.strip()


def _cleanup_sentence_fragments(text: str) -> str:
    """Remove incomplete sentence fragments left after phrase deduplication.
    
    Fragments are sentences that:
    - Don't end with proper punctuation (.!?)
    - Start with lowercase (continuation fragments)
    - Are very short and lack verb structure
    - End with dangling infinitives/prepositions (e.g., "to", "for", "and")
    - Contain structured markers (emoji, URLs) but no ending punctuation (mashed content)
    """
    # First, insert period before structured markers mashed against text without punctuation
    # e.g., "fragment 📺 Watch" -> "fragment. 📺 Watch"
    text = re.sub(r'([a-z])\s+([🎯📺💬🔔📑#])', r'\1. \2', text)
    text = re.sub(r'([a-z])\s+(https?://)', r'\1. \2', text)
    text = re.sub(r'([a-z])\s+({playlist_url})', r'\1. \2', text)
    
    # Split into sentences - handle punctuation followed by whitespace OR emoji/structured markers
    sentences = re.split(r'(?<=[.!?])(?=\s|[🎯📺💬🔔📑#])', text)
    cleaned = []
    
    for sent in sentences:
        sent = sent.strip()
        if not sent:
            continue
        
        # Keep structured lines (emoji headers, hashtags, URLs, sections, playlist URLs)
        is_structured = bool(re.match(r'^[🎯📺💬🔔📑#]|https?://', sent) or '{playlist_url}' in sent)
        if is_structured:
            cleaned.append(sent)
            continue
        
        # Check if this sentence contains structured content but lacks ending punctuation
        has_structured_marker = bool(re.search(r'[🎯📺💬🔔📑#]|https?://|{playlist_url}', sent))
        ends_with_punct = bool(re.search(r'[.!?]$', sent))
        starts_lower = sent[0].islower() if sent else False
        has_verb = bool(re.search(r'\b(is|are|has|have|do|did|will|can|learn|master|improve|speak|practice|watch|subscribe)\b', sent, re.I))
        
        # Check for dangling infinitives/prepositions at end (e.g., "to", "for", "and")
        ends_with_dangling = bool(re.search(r'\b(to|for|and|or|but|so|with|in|on|at)\s*[.!?]?$', sent, re.I))
        
        # Skip fragments
        if (not ends_with_punct or 
            (starts_lower and len(sent) < 80) or
            (len(sent) < 20 and not has_verb) or
            (has_structured_marker and not ends_with_punct) or
            ends_with_dangling):
            continue
            
        cleaned.append(sent)
    
    return ' '.join(cleaned)


def remove_duplicate_phrases(description: str) -> str:
    """Remove duplicate occurrences of key phrases and entire lines from descriptions."""
    text = str(description or "").strip()
    
    # First, integrate orphaned fragments into the SEO opener
    text = _integrate_fragments(text)
    
    # Preserve existing structured sections (comment, subscribe, playlist) by not normalizing them
    # Only normalize the content that appears to be mashed together
    
    # List of phrases that should appear only once (but be careful not to remove theme/topic)
    phrases_to_dedup = [
        "speak like a native",
        "natural english",
        "master natural english",
        "improve your english skills",
        "real-life scenarios",
        "english listening practice",
        "english speaking practice",
        "for real conversations",
        "learn hidden meanings",
    ]
    
    for phrase in phrases_to_dedup:
        # Case-insensitive search for duplicates
        pattern = re.compile(re.escape(phrase), re.IGNORECASE)
        matches = pattern.findall(text)
        
        if len(matches) > 1:
            # Keep first occurrence, remove subsequent ones
            def replace_func(match):
                nonlocal count
                count += 1
                return match.group(0) if count == 1 else ""
            
            count = 0
            text = pattern.sub(replace_func, text)

    # Clean up sentence fragments left after phrase deduplication
    text = _cleanup_sentence_fragments(text)
    
    # Clean up fragmented phrases left after removal (but preserve theme/topic)
    text = re.sub(r'🎯\s+via\s+Story:[^!]*!', '', text, flags=re.IGNORECASE)  # Remove fragmented opener remnants
    text = re.sub(r'Master\s+and\s+!', '', text)  # Remove fragmented phrases
    text = re.sub(r'🎯\s+-\s+[^.!?]*\.?\s*🎯', '', text)  # Remove fragmented emoji sections
    text = re.sub(r':\s+[^.!?]*\s+Learn\s+hidden\s+meanings', '', text)  # Remove fragmented idiom quiz text
    text = re.sub(r'🎯\s+-\s+[^.!?]*\.', '', text)  # Remove standalone fragmented emoji lines
    text = re.sub(r',\s*!\s*', ', ', text)  # Clean up ", !" fragments
    text = re.sub(r'\s+!\s*', ' ', text)  # Clean up standalone "!" with spaces
    text = re.sub(r',\s*,\s*', ', ', text)  # Clean up double commas
    text = re.sub(r',\s*[a-z]+\s+to\s+in\s+[a-z]+\s+situations!', '', text, flags=re.IGNORECASE)  # Clean up specific fragment pattern
    
    # Remove duplicate playlist URLs (keep only one, preferably the placeholder)
    text = re.sub(r'📺\s+Watch\s+the\s+playlist\s+here:\s*https?://[^\s]+', '', text, flags=re.IGNORECASE)
    
    # Remove duplicate lines (case-insensitive, ignoring leading/trailing whitespace)
    lines = text.splitlines()
    seen_lines = {}
    unique_lines = []
    
    for line in lines:
        line_stripped = line.strip().lower()
        if not line_stripped:
            unique_lines.append(line)
            continue
        if line_stripped not in seen_lines:
            seen_lines[line_stripped] = True
            unique_lines.append(line)
    
    text = "\n".join(unique_lines)
    
    # Clean up extra whitespace from replacements (preserve newlines, only collapse multiple spaces within lines)
    text = re.sub(r'  +', ' ', text)  # Collapse multiple spaces but preserve newlines
    text = re.sub(r'\n\s*\n\s*\n', '\n\n', text)
    return text.strip()


def finalize_english_description(
    description: str,
    *,
    include_timeline: bool = False,
    is_quiz: bool = False,
    theme: str = "",
) -> str:
    """Apply all English description post-processors in optimal order."""
    # Extract existing structured content to preserve it
    existing_comment = None
    comment_match = re.search(r'💬\s*Comment\s+below:[^#🔔]+', description, re.IGNORECASE)
    if comment_match:
        existing_comment = comment_match.group(0).strip()
    
    # Processing order: fragment cleanup → dedup → SEO opener → timeline removal → CTAs → About section → hashtags
    text = remove_duplicate_phrases(description)  # Includes fragment cleanup
    text = ensure_english_seo_opener(text, theme=theme)
    
    if not include_timeline:
        text = remove_timeline_from_shorts(text)
    text = ensure_english_description_cta(text, include_timeline=include_timeline)
    
    # Restore existing comment if it was preserved (replace generic comment)
    if existing_comment:
        text = re.sub(
            r'💬\s*Comment\s+below:\s*Which\s+phrase\s+will\s+you\s+practice\s+today\?',
            existing_comment,
            text,
            flags=re.IGNORECASE
        )
    
    if is_quiz:
        # Add About This Lesson section for quiz videos (inserts after SEO opener, before CTAs)
        text = ensure_english_quiz_about_section(text, theme=theme)
        # Place hashtags at end with SEO ordering
        text = ensure_english_quiz_shorts_hashtags(text, theme=theme)
    else:
        text = ensure_english_vibes_hashtags(text, theme=theme)
    return text


def ensure_english_description_cta(description: str, *, include_timeline: bool = False) -> str:
    """Guarantee core YouTube metadata CTAs even if the model skips them with proper spacing."""
    text = str(description or "").strip()
    
    # First, remove any existing subscribe lines without bell icon (to re-add in correct position)
    text = re.sub(r'(?<!🔔\s)Subscribe\s+to\s+EnglishVibesHub[^\n]*', '', text, flags=re.IGNORECASE)
    
    additions = []

    # Order: playlist → comment → subscribe → timeline (timeline only for long-form)
    # Add playlist if missing (will be positioned after opener)
    if "{playlist_url}" not in text and not re.search(r"playlist", text, re.IGNORECASE):
        additions.append("📺 Watch the playlist here: {playlist_url}")
    
    # Only add generic comment if no comment section exists at all
    if not re.search(r"💬\s*comment", text, re.IGNORECASE):
        additions.append("💬 Comment below: Which phrase will you practice today?")
    
    # Add subscribe with bell icon if missing (comes before timeline)
    if not re.search(r"🔔\s*Subscribe", text, re.IGNORECASE):
        additions.append("🔔 Subscribe to EnglishVibesHub for more English listening, speaking, and vocabulary practice.")
    
    # Add timeline only for long-form videos (not shorts)
    if include_timeline and "{scene_timeline}" not in text and not re.search(
        r"\b(?:timeline|chapters?)\b", text, re.IGNORECASE
    ):
        additions.append("� Timeline:\n{scene_timeline}")

    if additions:
        # If text starts with SEO opener, insert additions after it
        if text.startswith("🎯"):
            first_blank = text.find("\n\n")
            if first_blank != -1:
                text = text[:first_blank] + "\n\n" + "\n\n".join(additions) + text[first_blank:]
            else:
                text = text + "\n\n" + "\n\n".join(additions)
        else:
            text = (text + "\n\n" if text else "") + "\n\n".join(additions)
    
    # Ensure proper spacing - no more than 2 consecutive blank lines
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text


def remove_timeline_from_shorts(description: str) -> str:
    """Remove timeline-like content from shorts descriptions (should not have timestamps)."""
    text = str(description or "").strip()
    
    # Remove entire timeline section including header with multiple patterns
    # Match "📑 Timeline:" or "Timeline:" followed by timestamp lines
    text = re.sub(
        r"📑\s*Timeline:.*?(?=\n\n|\Z)",
        "",
        text,
        flags=re.DOTALL | re.IGNORECASE
    )
    text = re.sub(
        r"\bTimeline:.*?(?=\n\n|\Z)",
        "",
        text,
        flags=re.DOTALL | re.IGNORECASE
    )
    
    # Also remove any remaining timestamp lines (in case they're standalone)
    lines = text.splitlines()
    filtered_lines = []
    for line in lines:
        line_stripped = line.strip()
        # Match patterns like "0:00 - Label", "1:23 - Label", or "0:00 Label"
        if re.match(r"^\s*\d+:\d{2}\s*-\s*", line_stripped):
            continue
        # Also match timestamps without dash separator
        if re.match(r"^\s*\d+:\d{2}\s+[A-Z]", line_stripped):
            continue
        filtered_lines.append(line)
    
    # Clean up extra blank lines after timeline removal
    result = "\n".join(filtered_lines)
    result = re.sub(r"\n{3,}", "\n\n", result)
    return result.strip()


def ensure_english_quiz_shorts_hashtags(description: str, theme: str = "") -> str:
    """Place quiz Shorts hashtags at the END with optimal SEO ordering."""
    text = str(description or "").strip()
    if not text:
        return "#Shorts #EnglishQuiz #LearnEnglish #EnglishVibesHub"

    hashtag_re = re.compile(r"#\w+")

    # Remove ALL hashtags from anywhere in the text (not just target ones)
    cleaned_lines = []
    for line in text.splitlines():
        if not line.strip():
            cleaned_lines.append("")
            continue
        # Remove all hashtags from each line
        cleaned = hashtag_re.sub("", line).strip()
        cleaned = re.sub(r" {2,}", " ", cleaned)  # Remove extra spaces
        if cleaned:
            cleaned_lines.append(cleaned)
        # Skip lines that become empty after hashtag removal

    # Build optimized hashtag line with topic-specific tag
    core_tags = "#Shorts #EnglishQuiz #LearnEnglish #EnglishVibesHub"
    practice_tags = "#EnglishListeningPractice #EnglishSpeakingPractice #EnglishPodcast"
    
    # Extract topic-specific hashtag from theme if available
    topic_tag = ""
    if theme:
        # Convert theme to hashtag format (remove spaces, special chars)
        topic_clean = re.sub(r"[^\w\s]", "", str(theme).strip())
        topic_words = topic_clean.split()
        if topic_words:
            # Use first meaningful word or phrase as topic tag
            topic_tag = "#" + "".join(word.capitalize() for word in topic_words[:2])
    
    # SEO ordering: core tags → topic-specific → practice tags
    hashtag_line = f"{core_tags} {topic_tag} {practice_tags}".strip()
    hashtag_line = re.sub(r" {2,}", " ", hashtag_line)  # Remove extra spaces

    # Append hashtags at the very end
    cleaned_text = "\n".join(cleaned_lines).strip()
    # Ensure blank line before hashtags
    if cleaned_text and not cleaned_text.endswith("\n"):
        cleaned_text += "\n\n"
    cleaned_text += hashtag_line

    # Clean up excessive blank lines
    cleaned_text = re.sub(r"\n{3,}", "\n\n", cleaned_text)
    return cleaned_text.strip()


def ensure_english_quiz_about_section(description: str, theme: str = "") -> str:
    """Add 'About This Lesson' section for quiz videos with AI-generated explanation, inserted immediately after SEO opener."""
    text = str(description or "").strip()
    if not text:
        return text
    
    # First, remove any existing About This Lesson sections to avoid duplicates
    text = re.sub(
        r"📑\s*About\s+This\s+Lesson:.*?(?=\n\n|\Z)",
        "",
        text,
        flags=re.DOTALL | re.IGNORECASE
    )
    
    # Extract idiom/theme for the explanation
    theme_clean = str(theme or "").strip()
    if not theme_clean:
        # Try to extract from description
        theme_match = re.search(r"idiom\s*[:\-]\s*([^.]+)", text, re.IGNORECASE)
        if theme_match:
            theme_clean = theme_match.group(1).strip()
    
    if not theme_clean:
        return text
    
    # Generate AI explanation for the idiom/theme
    try:
        prompt = f"""Generate a brief, engaging explanation (2-3 sentences) for an English learning quiz about: "{theme_clean}".
        
Format the response as a single paragraph starting with "What does the [term] mean?" and explaining the meaning in simple, everyday English context. End with "Test your vocabulary skills with your quick quiz!"
        
Return ONLY the explanation text, no other content."""
        
        explanation = call_groq_json(prompt)
        explanation_text = explanation.get("explanation", explanation.get("text", ""))
        
        if not explanation_text:
            # Fallback to generic explanation
            explanation_text = f'What does "{theme_clean}" mean? In everyday English conversation, this term has specific meaning. Test your vocabulary skills with your quick quiz!'
    except Exception as e:
        print(f"  [warn] AI explanation generation failed: {e}")
        # Fallback to generic explanation
        explanation_text = f'What does "{theme_clean}" mean? In everyday English conversation, this term has specific meaning. Test your vocabulary skills with your quick quiz!'
    
    # Build the About This Lesson section
    about_section = f"📑 About This Lesson:\n{explanation_text}"
    
    # Insert immediately after SEO opener (line starting with 🎯), before any CTAs
    lines = text.splitlines()
    if lines and lines[0].strip().startswith("🎯"):
        # Find the first CTA line (playlist, comment, subscribe, timeline)
        first_cta_idx = None
        cta_prefixes = ["📺", "💬", "🔔", "📑 Timeline"]
        for i, line in enumerate(lines[1:], start=1):
            if any(line.strip().startswith(prefix) for prefix in cta_prefixes):
                first_cta_idx = i
                break
        
        if first_cta_idx is not None:
            # Insert About section between SEO opener and first CTA
            result = "\n".join(lines[:first_cta_idx]) + "\n\n" + about_section + "\n\n" + "\n".join(lines[first_cta_idx:])
        else:
            # No CTAs found, insert after SEO opener
            result = lines[0] + "\n\n" + about_section
            if len(lines) > 1:
                result += "\n\n" + "\n".join(lines[1:])
    else:
        # If no SEO opener found, append at beginning
        result = about_section
        if text:
            result += "\n\n" + text
    
    # Clean up spacing
    result = re.sub(r"\n{3,}", "\n\n", result)
    return result.strip()


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

        # Validate scene coverage without redistributing turns
        # Respect AI-generated scene boundaries based on dialogue meaning
        if aligned:
            print(f"  [scene_align] Total dialogue turns: {num_turns}, scenes: {len(aligned)}")
            
            # Ensure first scene starts at turn 0
            if aligned[0]["start_turn"] != 0:
                print(f"  [warn] First scene starts at turn {aligned[0]['start_turn']}, forcing to 0")
                aligned[0]["start_turn"] = 0
            
            # Ensure last scene ends at final turn
            if aligned[-1]["end_turn"] != num_turns - 1:
                print(f"  [warn] Last scene ends at turn {aligned[-1]['end_turn']}, forcing to {num_turns - 1}")
                aligned[-1]["end_turn"] = num_turns - 1
            
            # Check for gaps or overlaps in scene coverage
            for i in range(len(aligned) - 1):
                current_end = aligned[i]["end_turn"]
                next_start = aligned[i + 1]["start_turn"]
                if next_start > current_end + 1:
                    print(f"  [warn] Gap between scene {i+1} (ends {current_end}) and scene {i+2} (starts {next_start})")
                elif next_start <= current_end:
                    print(f"  [warn] Overlap between scene {i+1} (ends {current_end}) and scene {i+2} (starts {next_start})")
            
            # Log final scene alignment for verification
            print(f"  [scene_align] Scene coverage:")
            for i, scene in enumerate(aligned):
                print(f"    Scene {i+1} ({scene.get('scene_label', '?')}): turns {scene['start_turn']}-{scene['end_turn']}")

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
    
    # Calculate appropriate scene count based on dialogue length
    num_turns = len(dialogue)
    if num_turns <= 6:
        scene_count_range = f"{max(2, num_turns // 2)}-{num_turns}"
    elif num_turns <= 12:
        scene_count_range = f"{num_turns // 2}-{num_turns}"
    else:
        scene_count_range = "8-12"

    prompt = f"""You are an expert AI storyboard director for a 3D Pixar-style YouTube channel.
Analyze the input script. For each dialogue row, generate a highly descriptive visual prompt.

TOPIC / THEME: {theme}

DIALOGUE TURNS (index: [Speaker] text):
{turns_summary}

CRITICAL RULES:
1. Always maintain character consistency: Emma has brown hair in a neat ponytail. Liam has short blonde hair. Guest is always female.
2. The style must ALWAYS be: "{style_suffix}"
3. The background and character actions must match the literal words spoken in the dialogue text.
4. Create {scene_count_range} scenes total for visual variety (roughly 1-2 dialogue turns per scene). NEVER exceed the total number of dialogue turns ({num_turns}).
5. Change scenes frequently to maintain viewer engagement - every 15-20 seconds in the final video.
6. Each scene needs a descriptive image_filename like scene_1_library_discussion.png (lowercase, underscores, strictly .png extension).
7. Each scene must specify the 'start_turn' and 'end_turn' as the integer dialogue turn indices (matching the DIALOGUE TURNS list indices above) that are covered by this scene. Ensure the scenes sequentially cover all turns from 0 to {num_turns - 1}.
8. NEVER include references to narrator in visual prompts.
9. QUIZ TIMING RULE: For quiz formats, scenes showing the correct answer, checkmarks, or results MUST only appear in scenes that start AFTER the answer has been revealed in the dialogue (i.e., after the turn where the narrator announces the correct answer).
10. SPOILER PREVENTION: Scenes covering "pause" turns (e.g., "[PAUSE 3 SECONDS]") must NOT reveal answers, show checkmarks, highlight correct options, or display any outcomes. They should only show the question/presentation state.
11. CONTENT SEQUENCING: Visual prompts must only depict content that has already been mentioned or is actively being discussed in the dialogue turns covered by that scene. Do not show future events or outcomes.
12. SUMMARY SCENE: You MUST add one final scene with "scene_label": "Summary Card". Its "start_turn" MUST be set to the turn where the Narrator begins the closing/summary line (e.g. "Here's what we learned..."), and "end_turn" should be the last dialogue turn. This ensures the summary card background displays while the Narrator delivers the closing lines. Its "visual_prompt" should describe an atmospheric, warm, inviting background inspired by the story's setting — NO characters, NO text, just the environment with soft golden lighting and a storybook feel. This image will be used as the background for the "What We Learned Today" summary card.

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
    }},
    {{
      "scene_id": N,
      "scene_label": "Summary Card",
      "image_filename": "scene_summary.png",
      "visual_prompt": "string (atmospheric background only — no characters, no text. Warm golden lighting, storybook aesthetic, matching the story setting)",
      "start_turn": {num_turns - 1},
      "end_turn": {num_turns - 1}
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
            # Remove any narrator, caption, or text references to prevent them from appearing in generated images
            vp = re.sub(r"\bnarrator'?s?\b[^,.]*", '', vp, flags=re.IGNORECASE)
            vp = re.sub(r'\s+,', ',', vp)  # Clean up commas after removals
            vp = re.sub(r'\s{2,}', ' ', vp)  # Clean up extra spaces
            vp = re.sub(r',\s*\.', '.', vp)  # Clean up dangling commas
            vp = vp.strip()
            if vp and style_suffix.lower() not in vp.lower():
                scene["visual_prompt"] = f"{vp.rstrip('.')} {style_suffix}"
            elif vp:
                scene["visual_prompt"] = vp
        # Summary card is only used for landscape long-form — skip for portrait/shorts
        if portrait:
            scenes = [s for s in scenes if str(s.get("scene_label", "")).lower() != "summary card"]
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
    theme = script.get("theme") or script.get("title", "")
    if script.get("description"):
        script["description"] = finalize_english_description(
            script["description"],
            include_timeline=False,  # Timeline handled separately by _inject_scene_timeline in manual_run.py
            is_quiz=is_quiz,
            theme=theme,
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


ENGLISH_TOPIC_POOL = []

COMMUNITY_POLL_POOL = []

WEEKLY_CHALLENGE_TOPIC_POOL = []

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
    """Ask Groq to generate a fresh, high-CTR English learning topic.

    The prompt shows diverse topic areas as inspiration and lets the LLM
    choose freely, relying on the avoidance list to prevent repetition.
    """
    if topic_type == "post":
        type_label = "YouTube Community quiz or poll"
    elif is_challenge:
        type_label = "7-day weekly challenge"
    else:
        type_label = "podcast episode"

    topics_data = get_published_topics()
    published_topics = topics_data.get(topic_type, [])
    recent_topics = published_topics[-50:] if published_topics else []

    avoid_instruction = ""
    if recent_topics:
        avoid_instruction = f"""
    CRITICAL: Avoid repeating or closely matching any of these previously published topics/titles:
    {json.dumps(recent_topics, indent=2)}
    """

    prompt = f"""
    Generate ONE high-CTR topic for an English learning {type_label}.

    Choose from ANY area — grammar, vocabulary, pronunciation, cultural situations,
    workplace, travel, exam prep, modern slang, everyday scenarios, or storytelling.
    The examples below show the full range; prioritize variety and pick whatever
    will be most clickable for an English-learning audience.

    TOPIC AREA EXAMPLES (use as inspiration, not a checklist):
    - Everyday scenarios: Calling in sick to work, returning clothes, asking a neighbor for help, canceling a subscription, dealing with a rude cashier.
    - Grammar traps: When to use "have been" vs "have gone", "much" vs "many" in real speech, "used to" vs "would" for past habits.
    - Confusing words: "Say" vs "Tell", "Borrow" vs "Lend", "Make" vs "Do", "Fun" vs "Funny", "Advice" vs "Advise".
    - Cultural situations: How to small talk at a Western workplace, tipping etiquette, why Americans avoid "How old are you?", how to decline an invitation.
    - Pronunciation pitfalls: Why "th" breaks your accent, "sheet" vs "seat", why "beach" and "bitch" sound different to natives.
    - Modern slang: What "no cap", "bet", "slay" mean, corporate slang decoded, Gen Z dating English.
    - Story/disaster: Lost in a foreign city, job interview nightmare, English mistake at the hospital.
    - Workplace English: Disagree with your boss, professional email phrases, performance review prep.
    - Travel: Surviving an English-only hotel emergency, lost passport at the airport, asking for directions.
    - Exam prep: IELTS Speaking Part 1 model answers, TOEFL vs IELTS, common writing mistakes.

    PREVIOUSLY PUBLISHED TOPICS (do not repeat these):
    {avoid_instruction if avoid_instruction else "(none yet)"}

    TITLE RULES (follow these exactly):
    - Maximum 65 characters total. This is critical — YouTube truncates titles on mobile at ~60 chars.
    - Use ONE of these proven title formulas (vary from what you see in the published list above):
      A. Question: "Why Do English Speakers Say [X] Instead of [Y]?"
      B. Mistake hook: "The [X] Mistake Almost Every Learner Makes"
      C. Number list: "5 [X] That Sound Rude (But You Don't Know It)"
      D. Direct comparison: "[A] vs [B]: What's the Real Difference?"
      E. Curiosity gap: "The [X] Phrase Native Speakers Use Daily (You Don't)"
      F. Personal angle: "What I Wish I Knew Before [X]"
      G. Problem-solution: "Stop Saying [X] — Say This Instead"
      H. Cultural hook: "Why [X] Is Offensive in English (Nobody Told You)"
      I. Story-driven: "I [X] and Everything Went Wrong"
      J. Challenge: "Can You Pass This [X] English Test?"
    - Do NOT force "English listening practice" or "Learn English" as the first words — keep keywords organic
    - The title should make a viewer curious enough to click, NOT describe the content like a textbook heading
    - Include one natural keyword variant (e.g., if about "restaurant" include "dining", "cafe", "food order")

    Return ONLY a JSON object with these keys:
    - "topic": a short 3-8 word label for the core subject (e.g., "Saying vs telling confusion" or "Job interview confidence phrases")
    - "title": the full YouTube title following the rules above (max 65 chars)
    - "search_keyword": 3-5 word SEO phrase (e.g., "English confusing words say tell difference")

    Example output:
    {{"topic": "Borrow vs lend confusion", "title": "Borrow vs Lend: You're Using One Wrong", "search_keyword": "English confusing words borrow lend"}}
    """
    try:
        res = call_groq_json(prompt)
        return res.get("title") or res.get("topic")
    except Exception as e:
        print(f"  Error generating dynamic topic: {e}. Falling back to seed topic.")
        return random.choice([
            "Say vs Tell: Which One Are You Using Wrong?",
            "How to Small Talk at a Western Workplace",
            "Why Th Breaks Your English Accent",
            "Calling in Sick to Work in English",
            "Have Been vs Have Gone — The Difference Nobody Explains Right",
            "Gen Z Slang That Changes Everything",
            "Lost in a Foreign City With No Phone",
            "How to Disagree With Your Boss in English",
            "Surviving an English-Only Hotel Emergency",
            "IELTS Speaking Part 1 How to Answer Describe Your Hometown",
        ])


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
        
        # Remove summary scene if no idioms/phrasal verbs were found
        if not cleaned:
            scenes = script_data.get("scenes", [])
            original_count = len(scenes)
            script_data["scenes"] = [s for s in scenes if str(s.get("scene_label", "")).lower() != "summary card"]
            if len(script_data["scenes"]) < original_count:
                print(f"  Removed summary scene (no idioms/phrasal verbs to summarize)")
    except Exception as exc:
        print(f"  Idiom annotation skipped (Groq error): {exc}")
        script_data.setdefault("idiom_windows", [])

    return script_data


def separate_mixed_pause_turns(script_data: dict) -> dict:
    """
    Preprocessing step to split dialogue turns where pause marker is mixed with other text.
    The pause marker "[PAUSE 3 SECONDS]" must be on its own turn for proper pause detection.
    
    Example: Turn with text "[PAUSE 3 SECONDS]\nOption C is the best choice..."
    becomes:
      - Turn N: "[PAUSE 3 SECONDS]"
      - Turn N+1: "Option C is the best choice..."
      
    Also handles same-line mixing: "[PAUSE 3 SECONDS] Option C is the best choice..."
    """
    dialogue = script_data.get("dialogue", [])
    if not dialogue:
        return script_data
    
    PAUSE_PATTERN = re.compile(r'^\s*\[PAUSE\s+(\d+(?:\.\d+)?)\s*SECONDS?\]\s*$', re.IGNORECASE)
    SAME_LINE_PAUSE_PATTERN = re.compile(r'(\[PAUSE\s+\d+(?:\.\d+)?\s*SECONDS?\])', re.IGNORECASE)
    
    new_dialogue = []
    turn_offset = 0
    
    for turn in dialogue:
        text = turn.get("text", "")
        
        # First check for same-line mixed pause (e.g., "[PAUSE 3 SECONDS] Option C is...")
        same_line_match = SAME_LINE_PAUSE_PATTERN.search(text)
        if same_line_match and not PAUSE_PATTERN.match(text.strip()):
            # Extract pause marker and remaining text
            pause_marker = same_line_match.group(1)
            remaining_text = text.replace(pause_marker, "", 1).strip()
            
            # Split into two separate turns
            pause_turn = dict(turn)
            pause_turn["text"] = pause_marker
            pause_turn["turn_number"] = turn.get("turn_number", 0) + turn_offset
            new_dialogue.append(pause_turn)
            turn_offset += 1
            
            if remaining_text:
                content_turn = dict(turn)
                content_turn["text"] = remaining_text
                content_turn["turn_number"] = turn.get("turn_number", 0) + turn_offset
                new_dialogue.append(content_turn)
                turn_offset += 1
            
            print(f"  [pause_split] Split same-line mixed pause at turn {turn.get('turn_number')} into separate turns")
            continue
        
        # Check if this is a multi-line mixed pause (pause marker + other text)
        lines = text.split('\n')
        pause_line = None
        remaining_lines = []
        
        for line in lines:
            if PAUSE_PATTERN.match(line.strip()):
                pause_line = line.strip()
            else:
                remaining_lines.append(line)
        
        if pause_line and remaining_lines:
            # Split into two separate turns
            pause_turn = dict(turn)
            pause_turn["text"] = pause_line
            pause_turn["turn_number"] = turn.get("turn_number", 0) + turn_offset
            new_dialogue.append(pause_turn)
            turn_offset += 1
            
            content_turn = dict(turn)
            content_turn["text"] = '\n'.join(remaining_lines).strip()
            content_turn["turn_number"] = turn.get("turn_number", 0) + turn_offset
            new_dialogue.append(content_turn)
            turn_offset += 1
            
            print(f"  [pause_split] Split multi-line mixed pause at turn {turn.get('turn_number')} into separate turns")
        else:
            # No mixed pause, keep as-is with updated turn number
            updated_turn = dict(turn)
            updated_turn["turn_number"] = turn.get("turn_number", 0) + turn_offset
            new_dialogue.append(updated_turn)
    
    script_data["dialogue"] = new_dialogue
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
    # Preprocess to separate mixed pause markers
    script_data = separate_mixed_pause_turns(script_data)
    script_data["video_format"] = "shorts_quiz"
    theme = script_data.get("theme") or script_data.get("title", "")
    script_data["description"] = finalize_english_description(
        script_data.get("description", ""), is_quiz=True, theme=theme
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
3. Explain useful phrases, idioms, pronunciation tips, or sentence patterns connected to the skill. Use simple, direct phrasing like "Here 'X' means 'Y'" or "In this context, 'X' means 'Y'". Do NOT use meta-language like "phrasal verb breakdown", "phrase verb spotlight", "break down", or similar educational terminology.
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
  "title": "string (High-CTR title under 60 characters. Front-load with 'English listening practice', 'English speaking practice', or 'Learn English'. Include Day {day_number} in the suffix at the end. Use benefit-focused hooks like 'Master This', 'Complete Guide', 'Essential Phrases'. Include keyword variations like 'hairdresser/stylist' for hair salon topics. e.g., 'English Listening Practice: Master Restaurant Vocabulary - Day {day_number}')",
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
    # Preprocess to separate mixed pause markers
    script = separate_mixed_pause_turns(script)
    script.setdefault("day", day_number)
    script.setdefault("series_title", series_title)
    script.setdefault("tags", plan.get("tags", ["English", "English Challenge", "EnglishVibesHub"]))
    theme = script.get("theme") or script.get("title", "")
    script["description"] = finalize_english_description(
        script.get("description", ""), include_timeline=True, theme=theme
    )

    if not script.get("title"):
        title_options = script.get("title_options") or []
        if title_options:
            script["title"] = title_options[0]

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
- "Narrator" (Voice Profile: af_sarah): Speaks strictly in the third person. Acts as the connective tissue of the story — bridges scenes, weaves language explanations INTO the narrative flow (never pausing the story for a lesson), and guides transitions between beats.
- "Emma" (Voice Profile: af_heart) & "Liam" (Voice Profile: am_echo): Main protagonist characters experiencing the event. They must speak 100% in the first-person ("I", "my", "we"). They can talk to each other, argue, collaborate, or panic.
- "Guest" (Voice Profile: bf_emma): A secondary character — bystander, shopkeeper, antagonist, clerk, or stranger. REQUIRED in stories set in public places (shops, airports, offices, streets). ALWAYS female character. Speaks naturally based on the scene setting requirements.

NATURAL EXPRESSION REQUIREMENTS:
- Emma and Liam MUST use authentic, natural English expressions in their dialogue
- Include at least 2-3 distinct phrasal verbs used naturally in context
- Include at least 1-2 idioms appropriate to the situation
- Use colloquial expressions and varied vocabulary beyond basic English
- Characters should speak like real people in stressful situations, not textbook examples
- Expressions must fit the emotional context and urgency of the scene

TOPIC ALIGNMENT RULE (MANDATORY — the single most important rule):
- The entire story MUST be built around teaching or illustrating the exact TOPIC provided above
- The dialogue characters MUST encounter, discuss, or experience the specific concept, phrase, or mistake described in the TOPIC — the story is not generic, it must directly embody the TOPIC
- The quiz question MUST test the listener's understanding of the expression, phrase, or concept from the TOPIC — not a random unrelated phrasal verb
- The Narrator's closing line MUST reference what was learned about the TOPIC
- If the TOPIC describes a mistake (e.g. "The [X] Mistake"), the story MUST show characters making or encountering that mistake and learning the correct alternative
- MISTAKE ACCURACY: When depicting a mistake, the character's line must be a genuine example of the mistake — not a correct/polite form mislabeled as wrong. For example, "No thanks, I'm good" is already a polite decline (it has a softener), so it must NOT be treated as the mistake. A true "no thanks" mistake would be a flat "No thanks." with no follow-up, no softener, and a dismissive tone.
- QUIZ OPTION QUALITY: The quiz must have exactly ONE unambiguously correct answer. Distractors must be clearly wrong — not just "less ideal" or "slightly less polite." If two options could both be considered correct, rewrite the options so only one is defensible. For example, both "No thanks, but I'll take a coffee" and "I'm fine, thanks" are polite declines, so they must NOT both appear as options — pick one as the correct answer and make the distractors genuinely incorrect (e.g., a flat "No thanks." with no softener).

CRITICAL PIPELINE VALIDATION RULES:
1. OUTPUT CONSTRAINTS: Return ONLY a valid, parseable JSON block matching the structure pattern layout below. Do not wrap in conversational meta-text.
2. TOTAL SCRIPT VOLUMETRIC BUDGET: The total conversational sequence array must contain between 14 and 22 turns. To preserve natural conversation flow while maintaining reasonable runtime, individual dialogue turns should be 2-4 sentences per turn (allowing for natural expression development).
3. PERSPECTIVE GUARD: The Narrator must never speak in the first person. Characters must never speak in the third person. Liam and Emma must stay entirely inside the world of the crisis; they must never step out to teach words or talk about the English lesson.
4. INTEGRATED LESSON ENGINE: The Narrator weaves language explanations INTO the narrative flow — the story NEVER stops for a lesson. After a character uses an idiom or phrasal verb, the Narrator's next line should feel like a natural continuation of the scene, not a classroom aside. For example: after Emma says "things got out of hand," the Narrator might say "And just like that, the situation Emma feared most was exactly what was happening." The explanation is embedded in the storytelling, not bolted onto it. Limit to 1-2 brief inline explanations maximum. Use natural phrasing — never meta-language like "phrasal verb breakdown", "phrase verb spotlight", "let me explain", or "here's what that means". The Narrator must remain in third-person storytelling mode at all times. If the Narrator feels like they're pausing the scene to teach, rewrite the line so the lesson flows as part of the story.
5. INTERACTIVE BEAT PLACEMENT: Include exactly one meaningful expression challenge right before the narrative climax beat. The challenge should test understanding of a phrasal verb, idiom, or contextual expression (NOT basic vocabulary). The sequence MUST be: (1) The Narrator verbally cues the challenge, (2) A character speaks the challenge scenario — then on SEPARATE lines, each option on its own line starting with the word "Option" (e.g. "Option A: No thanks." / "Option B: No thanks, but I'll take a coffee." / "Option C: No, I don't want anything.") — this is critical for TTS pronunciation, never use bare "A)" "B)" "C)" labels, (3) A SEPARATE dialogue turn with speaker "Narrator" and text exactly "[PAUSE 3 SECONDS]" (no other text in this turn), (4) IMMEDIATELY AFTER the pause turn, the Narrator MUST explicitly state the correct answer with brief explanation before continuing with story resolution.

STRUCTURAL MOVEMENT STAGES:
- Stage 1: The Crisis Hook (In Media Res start with HIGH MOMENTUM. Opening dialogue turns should be SHORT — 1-2 sentences each — to create rapid back-and-forth cuts between characters. Drop the viewer into the middle of the action with emotional urgency, no slow buildup. The first 2-3 turns should feel like a trailer: punchy, fast, high-stakes.)
- Stage 2: Narrative Complications (The obstacle worsens, characters react organically with authentic emotions, argue, or pivot strategies using natural expressions).
- Stage 3: Organic Teaching Blocks (The Narrator's language explanations are woven seamlessly into scene transitions — the story never pauses. After a character uses an idiom, the Narrator's next line contextualizes it naturally as part of the ongoing narrative, keeping momentum and emotional tension alive.)
- Stage 4: Climax & Challenge (The absolute peak of tension, followed by a meaningful expression challenge that tests real understanding).
- Stage 5: Resolution & Seamless Engagement (The crisis resolves naturally. The Narrator's final line should be a brief 1-line bridge — e.g. "Here's what we learned in today's story..." or "Let's remember the key phrases from this adventure..." — that plays OVER the Summary Card scene. The summary card shows the idioms covered. After the card, the Narrator redirects the viewer to the pinned comment question. No generic intros/outros, no "thanks for watching", no "like and subscribe".)

JSON OUTPUT FORMAT (Follow this structure exactly):
{{
  "title": "High-CTR Title that directly references the TOPIC above, matching METADATA RULES (must be under 70 characters — YouTube truncates at ~60 on mobile)",
  "description": "String matching DESCRIPTION TEMPLATE exactly",
  "pinned_comment": "Narrative retention engagement question",
  "tags": [ "Tag1", "Tag2" ],
  "dialogue": [
    {{
      "turn_number": 1,
      "speaker": "Narrator",
      "text": "..."
    }},
    {{
      "turn_number": 2,
      "speaker": "Emma or Liam",
      "text": "..."
    }}
  ],
  "thumbnail_text": "TEXT",
  "thumbnail_concept": "CONCEPT",
  "theme": "Short 2-5 word label that matches the TOPIC (e.g. for TOPIC 'The No Thanks Mistake' → theme 'No Thanks Mistake')",
  "scenes": [
    {{
      "scene_id": 1,
      "scene_label": "string (short chapter label for YouTube timeline, e.g. Crisis Hook)",
      "image_filename": "scene_storm_hits.png",
      "visual_prompt": "string (ONE highly descriptive 3D Pixar-style Cinematic prompt",
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
        # Preprocess to separate mixed pause markers before validation
        raw_script = separate_mixed_pause_turns(raw_script)
        script, is_valid = validate_organic_english_script(raw_script)

    if not is_valid:
        print("⚠️ Groq failed to generate a perfect script after 3 tries. Using last attempt.")

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
  "title": "string (High-CTR Short title under 70 chars. Use varied formulas: question, 'Stop Saying X', 'X vs Y', number list, mistake hook, curiosity gap. Rotate from what you used last time.)",
  "title_options": ["string"],
  "description": "string (Follow METADATA RULES template. First 2 lines MUST use 'Natural English' and 'Speak like a native'. Place comment question in lines 3-5. Include subscribe CTA, playlist placeholder, #Shorts, #EnglishVibesHub, and hashtags mirroring 'tags')",
  "pinned_comment": "string (An engaging question to pin in the comments section)",
  "tags": ["string (Provide 5-8 SEO-focused English learning and topic-specific tags)"],
  "theme": "string (short topic label for storyboard)",
  "visual_keywords": ["string (legacy fallback: 5-8 visual search words)"],
  "video_format": "shorts",
  "dialogue": [
    {{
      "turn_number": 0,
      "speaker": "Emma or Liam",
      "text": "string (the spoken text)"
    }}
  ]
}}
"""
    script_data = call_groq_json(prompt)
    # Preprocess to separate mixed pause markers
    script_data = separate_mixed_pause_turns(script_data)
    script_data.setdefault("video_format", "shorts")
    theme = script_data.get("theme") or script_data.get("title", "")
    script_data["description"] = finalize_english_description(script_data.get("description", ""), theme=theme)

    if not script_data.get("title"):
        title_options = script_data.get("title_options") or []
        if title_options:
            script_data["title"] = title_options[0]

    # Update pinned comment with channel CTA
    script_data = update_pinned_comment_with_channel_cta(script_data)

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
    High-CTR, curiosity-based title using benefit-focused hooks like 'Master This Skill', 'Complete Guide To...', 'Essential Phrases', or 'The Secret To...'. e.g., 'Master Better Responses: Beyond I'm Fine') along with searchable keywords: "English Practice for Beginners", "Easy English Listening", "English Quiz" etc.

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
      "title": "string (High-CTR, searchable title under 70 chars, e.g., 'English Quiz: Master This Idiom!')",
      "description": "string (Follow METADATA RULES template. First 2 lines MUST use 'Natural English' and 'Speak like a native'. Place comment question in lines 3-5. Include subscribe CTA, playlist placeholder, #Shorts, #EnglishQuiz, #EnglishVibesHub, and hashtags mirroring 'tags')",
      "pinned_comment": "string (Engaging specific question for the comments section)",
      "tags": ["string (Provide 5-8 SEO-focused tags)"],
      "correct_answer": "string",
      "theme": "string (short topic label for storyboard, e.g. 'Idiom Quiz - Break a Leg')",
      "visual_keywords": ["string (legacy fallback: 5-8 visual search words)"],
      "dialogue": [
        {{ "turn_number": 0, "speaker": "Emma", "text": "..." }},
        {{ "turn_number": 1, "speaker": "Liam", "text": "..." }}
      ]
    }}
    """
    script_data = call_groq_json(prompt)
    # Preprocess to separate mixed pause markers
    script_data = separate_mixed_pause_turns(script_data)
    script_data["video_format"] = "shorts_quiz"
    theme = script_data.get("theme") or script_data.get("title", "")
    script_data["description"] = finalize_english_description(
        script_data.get("description", ""), is_quiz=True, theme=theme
    )

    # Update pinned comment with channel CTA
    script_data = update_pinned_comment_with_channel_cta(script_data)

    return attach_storyboard_to_script(script_data, portrait=True)


# ─── PODCAST PIPELINE ─────────────────────────────────────────────────────────

def _extract_podcast_story_context(dialogue: list) -> str:
    """Extract a compact story-context summary from dialogue for the storyboard prompt.

    Parses the dialogue to identify the story setting, characters, and a text excerpt
    so the storyboard Groq call has enough context to generate accurate visuals
    instead of hallucinating unrelated locations.
    """
    story_speakers = {
        "Caller", "StoryActor1", "StoryActor2",
        "StoryActor1_Female", "StoryActor2_Male",
        "StoryActor1_AltMale", "StoryActor2_AltFemale",
    }
    story_lines = []
    for t in dialogue:
        if t.get("speaker") in story_speakers:
            story_lines.append(t.get("text", ""))
    full_story = " ".join(story_lines)

    if not full_story.strip():
        return ""

    # Extract setting/location cues from story text (use word boundaries to avoid
    # false positives like "bus" matching inside "business")
    location_keywords = {
        "office": "office/workplace", "meeting": "meeting room",
        "zoom": "video call/virtual meeting",
        "presentation": "presentation/meeting", "client": "client meeting",
        "interview": "interview setting", "restaurant": "restaurant",
        "cafe": "cafe", "coffee": "cafe", "bar": "bar/pub",
        "hotel": "hotel", "airport": "airport", "hospital": "hospital",
        "doctor": "medical office", "clinic": "clinic",
        "school": "school", "classroom": "classroom", "university": "university",
        "library": "library", "street": "street/outdoors", "park": "park",
        "gym": "gym", "store": "store/shop", "shop": "store/shop",
        "mall": "shopping mall", "supermarket": "grocery store",
        "home": "home", "house": "house", "apartment": "apartment",
        "kitchen": "kitchen", "bedroom": "bedroom",
        "car": "car/vehicle", "bus": "bus", "train": "train",
        "beach": "beach", "mountain": "mountain",
        "wedding": "wedding", "party": "party", "concert": "concert",
        "theater": "theater",
    }
    detected = set()
    story_lower = full_story.lower()
    for kw, label in location_keywords.items():
        if re.search(r'\b' + re.escape(kw) + r'\b', story_lower):
            detected.add(label)

    # Identify story characters
    characters = []
    for t in dialogue:
        sp = t.get("speaker", "")
        if sp.startswith("StoryActor") and sp not in characters:
            characters.append(sp)

    setting = ", ".join(sorted(detected)) if detected else "unspecified setting"
    chars = ", ".join(characters) if characters else "Caller only"
    word_count = len(full_story.split())

    return (
        f"STORY SETTING: {setting}. "
        f"CHARACTERS IN STORY: {chars}. "
        f"STORY LENGTH: ~{word_count} words across {len(story_lines)} dialogue turns. "
        f"STORY EXCERPT (first 500 chars): {full_story[:500]}"
    )


def _fix_podcast_scene_alignment(scenes: list, dialogue: list) -> list:
    """Validate and fix scene turn ranges using speaker identity for the podcast structure.

    Uses Groq's start_turn/end_turn as hints, then clamps each scene to the correct
    stage range based on its label. If scenes within a stage overlap, shifts later ones
    to start after the previous one ends. Preserves Groq's intent while fixing errors.
    """
    if not scenes or not dialogue:
        return scenes

    num_turns = len(dialogue)
    host_speakers = {"Emma", "Liam"}
    story_speakers = {"StoryActor1", "StoryActor2", "StoryActor1_Female", "StoryActor2_Male",
                      "StoryActor1_AltMale", "StoryActor2_AltFemale"}

    # Build speaker-type index: 0=hook/unknown, 1=host, 2=story, 3=caller
    speaker_type = []
    for t in dialogue:
        sp = t.get("speaker", "")
        if sp in host_speakers:
            speaker_type.append(1)
        elif sp in story_speakers:
            speaker_type.append(2)
        elif sp == "Caller":
            speaker_type.append(3)
        else:
            speaker_type.append(0)

    # Find stage boundaries from speaker types
    first_host_turn = next((i for i, st in enumerate(speaker_type) if st == 1), None)

    # First StoryActor turn after the first host turn = story start
    story_start = None
    if first_host_turn is not None:
        for i in range(first_host_turn, num_turns):
            if speaker_type[i] == 2:
                story_start = i
                break

    # Last StoryActor turn = story end
    last_story_turn = None
    for i in range(num_turns - 1, -1, -1):
        if speaker_type[i] == 2:
            last_story_turn = i
            break

    # First Caller turn between first host turn and story start = caller setup start
    caller_setup_start = None
    if first_host_turn is not None and story_start is not None:
        for i in range(first_host_turn, story_start):
            if speaker_type[i] == 3:
                caller_setup_start = i
                break

    # Studio intro end: last host turn before caller setup (or before story if no caller setup)
    studio_intro_end = None
    if first_host_turn is not None:
        intro_end_bound = caller_setup_start if caller_setup_start is not None else story_start
        if intro_end_bound is not None:
            for i in range(intro_end_bound - 1, first_host_turn - 1, -1):
                if speaker_type[i] == 1:
                    studio_intro_end = i
                    break
            if studio_intro_end is None:
                studio_intro_end = first_host_turn

    # Caller setup end: turn before story start
    caller_setup_end = story_start - 1 if story_start is not None else None

    # First Caller turn after story = back-to-studio starts with host transition
    caller_after_story = None
    if last_story_turn is not None:
        for i in range(last_story_turn + 1, num_turns):
            if speaker_type[i] == 3:
                caller_after_story = i
                break

    # Back-to-studio: host transition turn + caller reflection turns
    back_to_studio_start = None
    back_to_studio_end = None
    if last_story_turn is not None:
        # Starts at first host or caller turn after story
        for i in range(last_story_turn + 1, num_turns):
            if speaker_type[i] in (1, 3):
                back_to_studio_start = i
                break
        # Ends at last caller turn before host analysis
        if back_to_studio_start is not None:
            for i in range(back_to_studio_start, num_turns):
                if speaker_type[i] == 3:
                    back_to_studio_end = i
            # Extend to include host transition if host starts back-to-studio
            if back_to_studio_start is not None and speaker_type[back_to_studio_start] == 1:
                # Host started back-to-studio, find where caller ends
                for i in range(back_to_studio_start + 1, num_turns):
                    if speaker_type[i] == 3:
                        back_to_studio_end = i

    # First Host turn after back-to-studio = host analysis start
    host_after_caller = None
    search_start = (back_to_studio_end + 1) if back_to_studio_end is not None else (last_story_turn + 1 if last_story_turn is not None else 0)
    for i in range(search_start, num_turns):
        if speaker_type[i] == 1:
            host_after_caller = i
            break

    # If no story actors found, return scenes unchanged
    if first_host_turn is None or last_story_turn is None or story_start is None:
        return scenes

    # Define valid turn ranges for each stage (inclusive)
    hook_end = max(0, first_host_turn - 1)
    story_end = last_story_turn
    host_analysis_start = host_after_caller

    # DEBUG: Log computed stage boundaries
    print(f"  [podcast_align] Stage boundaries computed:")
    print(f"    hook_end: {hook_end}")
    print(f"    first_host_turn: {first_host_turn}")
    print(f"    studio_intro_end: {studio_intro_end}")
    print(f"    caller_setup_start: {caller_setup_start}")
    print(f"    caller_setup_end: {caller_setup_end}")
    print(f"    story_start: {story_start}")
    print(f"    story_end: {story_end}")
    print(f"    back_to_studio_start: {back_to_studio_start}")
    print(f"    back_to_studio_end: {back_to_studio_end}")
    print(f"    host_analysis_start: {host_analysis_start}")
    print(f"    quiz_start: {quiz_start}")
    # Host analysis end = quiz start
    # Search for the first turn after host analysis that contains quiz-related keywords
    pause_idx = None
    for i in range(num_turns - 1, -1, -1):
        if "[PAUSE" in dialogue[i].get("text", "").upper():
            pause_idx = i
            break
    # Find quiz start: first turn with "quiz", "test", "challenge", or "which" after host analysis
    quiz_start = None
    if host_analysis_start is not None:
        for i in range(host_analysis_start + 2, num_turns):  # +2 to ensure at least 2 turns of analysis
            text_lower = dialogue[i].get("text", "").lower()
            if any(kw in text_lower for kw in ["quiz", "test", "challenge", "which "]):
                quiz_start = i
                break
    # Fallback: use pause_idx heuristic
    if quiz_start is None and pause_idx is not None:
        quiz_start = max(pause_idx - 2, (host_analysis_start + 2) if host_analysis_start else 0)
    if quiz_start is None and host_analysis_start is not None:
        quiz_start = host_analysis_start + 8

    # Map stage labels to valid ranges
    def label_to_stage(label: str) -> str:
        label = label.lower()
        if "hook" in label:
            return "hook"
        if "studio intro" in label or "radio studio" in label:
            return "studio_intro"
        if "caller story setup" in label or "caller setup" in label:
            return "caller_setup"
        if "back to studio" in label:
            return "back_to_studio"
        if "quiz" in label:
            return "quiz_wrap"
        if "wrap" in label:
            return "quiz_wrap"
        if "summary" in label:
            return "summary"
        # Analysis labels: "host analysis", "analysis:", "analysis —", etc.
        if "analysis" in label or "analyse" in label:
            return "host_analysis"
        # Story labels: "caller story", "flashback", "story part", etc.
        if "caller story" in label or "caller part" in label:
            return "story"
        if "flashback" in label:
            return "story"
        if "story" in label:
            return "story"
        return "unknown"

    def stage_range(stage: str):
        """Return (start, end) inclusive turn range for a stage."""
        if stage == "hook":
            return (0, hook_end)
        if stage == "studio_intro":
            if studio_intro_end is not None:
                return (first_host_turn, studio_intro_end)
            return None
        if stage == "caller_setup":
            if caller_setup_start is not None and caller_setup_end is not None:
                return (caller_setup_start, caller_setup_end)
            return None
        if stage == "story":
            return (story_start, story_end)
        if stage == "back_to_studio":
            if back_to_studio_start is not None and back_to_studio_end is not None:
                return (back_to_studio_start, back_to_studio_end)
            return None
        if stage == "host_analysis":
            if host_analysis_start is not None:
                return (host_analysis_start, max(host_analysis_start, quiz_start - 1))
            return None
        if stage == "quiz_wrap":
            if host_analysis_start is not None:
                return (quiz_start, num_turns - 1)
            return None
        if stage == "summary":
            return (max(0, num_turns - 2), num_turns - 1)
        return None

    # Assign each scene to a stage and collect Groq's ranges
    scene_stages = []
    for scene in scenes:
        stage = label_to_stage(scene.get("scene_label", ""))
        scene_stages.append(stage)

    # DEBUG: Log scene stage assignments
    print(f"  [podcast_align] Scene stage assignments:")
    for i, (scene, stage) in enumerate(zip(scenes, scene_stages)):
        print(f"    Scene {i+1} ({scene.get('scene_label', '?')}): stage={stage}, groq_range={scene.get('start_turn', '?')}-{scene.get('end_turn', '?')}")

    # For each stage, collect its scenes and fix ranges
    # Group scenes by stage while preserving order
    from collections import OrderedDict
    stage_groups = OrderedDict()
    for i, (scene, stage) in enumerate(zip(scenes, scene_stages)):
        stage_groups.setdefault(stage, []).append(i)

    corrected = [dict(s) for s in scenes]
    for stage, indices in stage_groups.items():
        sr = stage_range(stage)
        if sr is None:
            # Stage not found in dialogue — keep Groq's ranges, just clamp
            print(f"  [podcast_align] Stage '{stage}' not found in dialogue, keeping Groq ranges")
            for i in indices:
                s = max(0, min(corrected[i].get("start_turn", 0), num_turns - 1))
                e = max(s, min(corrected[i].get("end_turn", num_turns - 1), num_turns - 1))
                corrected[i]["start_turn"] = s
                corrected[i]["end_turn"] = e
            continue

        stage_start, stage_end = sr
        print(f"  [podcast_align] Processing stage '{stage}': range={stage_start}-{stage_end}, scenes={len(indices)}")

        # Use Groq's ranges as hints, but clamp to stage range
        # Then fix overlaps by shifting later scenes forward
        prev_end = stage_start - 1
        for idx_in_group, scene_idx in enumerate(indices):
            groq_start = corrected[scene_idx].get("start_turn", stage_start)
            groq_end = corrected[scene_idx].get("end_turn", stage_end)

            # Clamp to stage range
            start = max(stage_start, min(groq_start, stage_end))
            end = max(start, min(groq_end, stage_end))

            print(f"    Scene {scene_idx+1} ({corrected[scene_idx].get('scene_label', '?')}): groq={groq_start}-{groq_end}, clamped={start}-{end}, prev_end={prev_end}")

            # If this scene starts before or at the previous scene's end, shift it forward
            if start <= prev_end:
                print(f"      -> Overlap detected, shifting start from {start} to {prev_end + 1}")
                start = prev_end + 1
                end = max(start, min(groq_end, stage_end))

            # If shifting pushed start past stage end, this scene is empty — merge with previous
            if start > stage_end:
                print(f"      -> Start {start} > stage_end {stage_end}, merging with previous")
                # Extend the previous scene to cover this scene's remaining range
                if idx_in_group > 0:
                    prev_scene_idx = indices[idx_in_group - 1]
                    corrected[prev_scene_idx]["end_turn"] = stage_end
                # Mark this scene for removal
                corrected[scene_idx]["start_turn"] = stage_end
                corrected[scene_idx]["end_turn"] = stage_start - 1  # Empty range
                continue

            # If end pushed past stage end, clamp
            if end > stage_end:
                print(f"      -> End {end} > stage_end {stage_end}, clamping to {stage_end}")
                end = stage_end

            corrected[scene_idx]["start_turn"] = start
            corrected[scene_idx]["end_turn"] = end
            prev_end = end
            print(f"      -> Final: {start}-{end}")

        # If only one scene in this stage, extend it to cover the full stage range
        if len(indices) == 1:
            scene_idx = indices[0]
            print(f"    -> Single scene in stage, extending from {corrected[scene_idx].get('start_turn', '?')}-{corrected[scene_idx].get('end_turn', '?')} to full stage range {stage_start}-{stage_end}")
            corrected[scene_idx]["start_turn"] = stage_start
            corrected[scene_idx]["end_turn"] = stage_end

    # Merge all post-story studio scenes (podcast_host.png) into one scene.
    # Once back in the studio, the visual never changes — splitting adds no AVD value.
    # Find the first scene that covers the back-to-studio or later stage, then extend
    # it to cover everything through the end.
    story_speakers = {"StoryActor1", "StoryActor2", "StoryActor1_Female", "StoryActor2_Male",
                      "StoryActor1_AltMale", "StoryActor2_AltFemale"}
    last_story_idx = -1
    for i, t in enumerate(dialogue):
        if t.get("speaker", "") in story_speakers:
            last_story_idx = i
    print(f"  [podcast_align] last_story_idx: {last_story_idx}")
    # Find the first studio scene after the last story turn
    merge_start = None
    for i, s in enumerate(corrected):
        if s.get("start_turn", 0) > last_story_idx and s.get("image_filename", "") == "podcast_host.png":
            if merge_start is None:
                merge_start = i
    # Merge all subsequent studio scenes into the first one
    if merge_start is not None:
        print(f"  [podcast_align] Merging studio scenes from index {merge_start} to end")
        corrected[merge_start]["end_turn"] = num_turns - 1
        # Update label to reflect it covers everything from back-to-studio onward
        label = corrected[merge_start].get("scene_label", "")
        if "back to studio" not in label.lower():
            corrected[merge_start]["scene_label"] = "Back to Studio"
        # Remove all subsequent studio scenes
        corrected = corrected[:merge_start + 1]

    # Remove empty scenes (start > end)
    corrected = [s for s in corrected if s.get("start_turn", 0) <= s.get("end_turn", 0)]

    # Ensure first scene starts at 0
    if corrected and corrected[0].get("start_turn", 0) != 0:
        print(f"  [podcast_align] Adjusting first scene start from {corrected[0].get('start_turn', '?')} to 0")
        corrected[0]["start_turn"] = 0
    # Ensure last scene ends at final turn
    if corrected and corrected[-1].get("end_turn", 0) != num_turns - 1:
        print(f"  [podcast_align] Adjusting last scene end from {corrected[-1].get('end_turn', '?')} to {num_turns - 1}")
        corrected[-1]["end_turn"] = num_turns - 1

    # Final pass: fix any remaining gaps — extend current scene to fill gap to next scene
    print(f"  [podcast_align] Final gap-fix pass:")
    for i in range(len(corrected) - 1):
        curr_end = corrected[i]["end_turn"]
        next_start = corrected[i + 1]["start_turn"]
        if next_start > curr_end + 1:
            print(f"    Gap between scene {i+1} (ends {curr_end}) and scene {i+2} (starts {next_start}), extending to {next_start - 1}")
            corrected[i]["end_turn"] = next_start - 1
        elif next_start <= curr_end:
            print(f"    OVERLAP between scene {i+1} (ends {curr_end}) and scene {i+2} (starts {next_start}) - NOT FIXED")

    print(f"  [podcast_align] Final scene coverage:")
    for i, scene in enumerate(corrected):
        print(f"    Scene {i+1} ({scene.get('scene_label', '?')}): turns {scene['start_turn']}-{scene['end_turn']}")

    return corrected


def generate_podcast_storyboard(script: dict, topic: str = "") -> dict:
    """Post-dialogue Groq call: group dialogue into Pixar-style visual scenes with podcast host switching."""
    dialogue = script.get("dialogue", [])
    if not dialogue:
        script.setdefault("scenes", [])
        return script

    turns_summary = "\n".join(
        f"{i}: [{line.get('speaker', '?')}] {line.get('text', '')[:150]}"
        for i, line in enumerate(dialogue[:120])
    )
    style_suffix = ENGLISH_STORYBOARD_STYLE_SUFFIX_LANDSCAPE
    theme = script.get("theme") or script.get("title", "English Lesson")
    num_turns = len(dialogue)

    story_context = _extract_podcast_story_context(dialogue)
    topic_context = f"\n\nTOPIC: {topic}" if topic else ""
    story_context_block = f"\n\n{story_context}" if story_context else ""
    
    prompt = f"""You are an expert AI storyboard director for a 3D Pixar-style YouTube channel.
Analyze the input script. Group the dialogue turns into sequence of scenes.{topic_context}{story_context_block}

The podcast follows this 7-stage structure:
1. Story Hook (turns 0-1) - 2-line teaser, high tension
2. Radio Studio Intro - Emma & Liam welcome listeners and introduce caller
3. Caller Story Setup - Caller talks to hosts, briefly explains what happened
4. Caller Story - Full story flashback acted out through dialogue
5. Back to Studio - Caller reflects with lingering confusion
6. Host Analysis - Emma & Liam explain correct English usage
7. Quiz & Wrap-up - Interactive challenge and episode conclusion

Emma and Liam are radio show hosts sitting in a modern radio station.
Host segments (Radio Studio Intro, Caller Story Setup, Host Analysis, Quiz & Wrap-up) should use the podcast_host.png image.
Story segments (Story Hook, Caller Story, Back to Studio) should use unique Pixar-style scene images.

CRITICAL RULES:
1. For host segments (Emma/Liam as radio hosts in studio), set "image_filename": "podcast_host.png" and "visual_prompt": "Two podcast hosts, Emma and Liam, sitting in a modern radio station recording a podcast. Emma has brown hair in a neat ponytail. Liam has short blonde hair. Soft professional lighting, 3D Pixar style."
2. For story segments (Story Hook, Caller Story), generate unique, highly descriptive Pixar-style prompts with filenames like "scene_2_crisis_moment.png" etc.
3. VISUAL-DIALOGUE ALIGNMENT: The "STORY EXCERPT" and "STORY SETTING" above describe the actual story. Every non-host scene's visual_prompt MUST depict settings, objects, and actions from that story. If the story mentions a Zoom call, show a person at a computer on a video call. If it mentions a restaurant, show a restaurant. NEVER use generic settings (high school, coffee shop, marketplace, hallway) unless the story EXPLICITLY mentions them. DO NOT invent settings or character appearances not described in the story excerpt.
4. The style must ALWAYS be: "{style_suffix}" for story scenes.
5. Create 10-15 scenes total with appropriate labels matching the 7 stages: "Story Hook", "Radio Studio Intro", "Caller Story Setup", "Caller Story", "Back to Studio", "Host Analysis", "Quiz & Wrap-up". Ensure scenes sequentially cover all turns from 0 to {num_turns - 1}. Break up longer segments into multiple scenes for visual variety.
6. ONLY IF the episode explicitly teaches idioms or phrasal verbs (e.g. "kick the bucket", "break a leg"), add a final scene with "scene_label": "Summary Card". Set "start_turn" to the last host analysis turn and "end_turn" to the final turn. Use "scene_summary.png" and a visual_prompt showing an atmospheric background matching the story setting (no characters). If the episode does NOT teach idioms/phrasal verbs, do NOT add a Summary Card scene.

Output ONLY valid JSON with this schema:
{{
  "theme": "string",
  "scenes": [
    {{
      "scene_id": 1,
      "scene_label": "string (short chapter label for YouTube timeline)",
      "image_filename": "podcast_host.png",
      "visual_prompt": "Two podcast hosts, Emma and Liam, sitting in a modern radio station recording a podcast. Emma has brown hair in a neat ponytail. Liam has short blonde hair. Soft professional lighting, 3D Pixar style.",
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
            if scene.get("image_filename") == "podcast_host.png":
                continue
            vp = str(scene.get("visual_prompt", "")).strip()
            # Remove any narrator, caption, or text references
            vp = re.sub(r"\bnarrator'?s?\b[^,.]*", '', vp, flags=re.IGNORECASE)
            vp = re.sub(r'\s+,', ',', vp)
            vp = re.sub(r'\s{2,}', ' ', vp)
            vp = re.sub(r',\s*\.', '.', vp)
            vp = vp.strip()
            if vp and style_suffix.lower() not in vp.lower():
                scene["visual_prompt"] = f"{vp.rstrip('.')} {style_suffix}"
            elif vp:
                scene["visual_prompt"] = vp
        script["theme"] = res.get("theme") or theme
        script["scenes"] = align_scenes_to_turns(scenes, dialogue)
        script["scenes"] = _fix_podcast_scene_alignment(script["scenes"], dialogue)
        print(f"  Storyboard: {len(script['scenes'])} scene(s) generated")
    except Exception as exc:
        print(f"  Storyboard generation skipped (Groq error): {exc}")
        script.setdefault("scenes", [])
    return script


def generate_english_podcast_script(topic=None):
    """Generate a podcast script with Emma & Liam as hosts and dynamic scenes."""
    if not topic:
        topic = generate_dynamic_topic(is_challenge=False, topic_type="podcast")
    else:
        if is_already_published(topic, "podcast"):
            print(f"\n  [WARNING] Manual topic '{topic}' was found in 'podcast' history.")

    topics_data = get_published_topics()
    recent = topics_data.get("podcast", [])[-50:]
    avoid_instruction = f"\nAvoid repeating examples, idioms, or stories used in these recent episodes:\n{json.dumps(recent, indent=2)}" if recent else ""

    print(f"\nSelected topic: {topic}")
    print("Generating podcast storytelling script...")

    prompt = f"""
You are an elite showrunner for EnglishVibesHub (@EnglishVibesHub-s6w). Write an English audio-story script for the "English Vibes Podcast".

TOPIC: {topic}
{avoid_instruction}

{ENGLISH_METADATA_RULES.replace('{scene_timeline}', '{{scene_timeline}}').replace('{playlist_url}', '{{playlist_url}}')}

FORMAT: Radio podcast, 40-65 dialogue turns, 7 stages in this EXACT order:

1. HOOK (2 turns): Caller in media res — ONE punchy 1-2 sentence line of high tension. StoryActor gives ONE short direct reaction (not narrated). Then STOP — cut to studio.
2. STUDIO INTRO (2-3 turns): Emma welcomes listeners, Liam introduces topic, Emma introduces caller.
3. CALLER STORY SETUP (2-3 turns): Caller talks to Emma & Liam in the studio, briefly explaining what happened. Hosts react naturally. This sets up the story BEFORE the flashback. Then Liam or Emma hands off.
4. FULL STORY (12-18 turns): A flashback scene. StoryActor1 and StoryActor2 ARE the characters — they speak DIRECTLY to each other as themselves. NO narration, NO "he said/she said", NO body language descriptions like "I raised an eyebrow and said". Just the spoken line. Example WRONG: "He leaned back and said, 'We can discuss this later.'" Example RIGHT: "We can discuss this later." The Caller does NOT appear in this stage. The story is told entirely through the characters' own dialogue. Build: setup → tension → complication → climax. This is the ONLY place the full story is told.
5. BACK TO STUDIO (2-3 turns): Host asks a follow-up. Caller expresses LINGERING CONFUSION about the language mistake — they still don't understand what went wrong.
6. HOST ANALYSIS (8-12 turns): Emma/Liam react, explain the mistake, teach correct usage with examples. Include one quiz: Host cues challenge → Option A/B/C turns → "[PAUSE 3 SECONDS]" → Host reveals answer.
7. WRAP-UP (2-3 turns): Host summarizes key takeaway. End conversationally.

VOICES:
- "Emma" (af_heart) & "Liam" (am_michael): Radio hosts. First-person. Appear in Stages 1-2 (hook/studio intro), 3 (caller setup reactions), 5-7 (back-to-studio/analysis/wrap-up). NEVER in Stage 4.
- "Caller" (af_bella): Appears in Stage 1 (hook — 1 line), Stage 3 (caller story setup — 2-3 lines explaining what happened), Stage 5 (back-to-studio reflection — 2-3 lines). Does NOT appear in Stage 4 (the story scene).
- "StoryActor1" (am_adam): A character IN the story. Speaks as themselves in the present moment. NEVER narrate actions or describe what they're doing — just say the direct spoken line. Use "StoryActor1_Female" (af_bella) for female characters.
- "StoryActor2" (af_sarah): Same rules as StoryActor1. Use "StoryActor2_Male" (am_echo) for male characters.
- "Guest" (bf_emma): Optional. Always female.

RULES:
- 40-65 total turns. Hook=2, Studio=2-3, Caller Setup=2-3, Story=12-18, Back=2-3, Analysis=8-12, Wrap=2-3.
- StoryActors NEVER narrate. They speak directly as their characters. No "he said", "she whispered", "I nodded and replied" — just the line.
- Caller does NOT appear in Stage 4 (Full Story). Caller appears in Stages 1, 3, and 5.
- Emma/Liam never break into story dialogue.
- Story told ONCE in Stage 4. Hook is just a 2-line teaser. Caller Setup briefly sets up the story in studio.
- Output ONLY valid JSON.

JSON SCHEMA:
{{"title":"...","description":"...","pinned_comment":"...","tags":["..."],"dialogue":[{{"turn_number":1,"speaker":"Caller","text":"..."}},{{"turn_number":2,"speaker":"StoryActor1","text":"..."}}],"thumbnail_text":"...","thumbnail_concept":"...","theme":"2-5 words"}}

Dialogue MUST start with Caller (Hook), NOT Emma/Liam. After the story, Caller MUST return to studio for reflection before Host Analysis.
"""
    is_valid = False
    attempts = 0

    while not is_valid and attempts < 3:
        attempts += 1
        print(f"🔄 Generation Attempt {attempts}...")

        raw_script = call_groq_json(prompt)
        # Preprocess to separate mixed pause markers before validation
        raw_script = separate_mixed_pause_turns(raw_script)
        script, is_valid = validate_podcast_script(raw_script)

    if not is_valid:
        print("⚠️ Groq failed to generate a perfect script after 3 tries. Using last attempt.")

    # Post-process description and attach custom storyboard
    script = generate_podcast_storyboard(script, topic=topic)
    theme = script.get("theme") or script.get("title", "")
    if script.get("description"):
        script["description"] = finalize_english_description(
            script["description"],
            include_timeline=False,
            is_quiz=False,
            theme=theme,
        )
    return script

