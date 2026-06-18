"""
Manual pipeline runner — zero API keys required.
Use this to publish videos for FREE while you validate the pipeline.

Workflow:
  1. You write/paste a script (or use Claude.ai chat to generate one)
  2. This script generates voiceover (free local TTS)
  3. Fetches stock video from Pexels (free API key)
  4. Assembles the video with FFmpeg (free)
  5. Uploads to YouTube (free API)

Run:
  python manual_run.py --channel lofi
  python manual_run.py --channel family
  python manual_run.py --channel trending
"""

import os
import sys
import json
import argparse
import subprocess
import textwrap
import shutil
from pathlib import Path
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
import cProfile
import pstats
import requests
import time
import random


# Add parent dirs to path
sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent / "prompts"))

# Load .env from project root
_env_path = Path(__file__).parent.parent / ".env"
if _env_path.exists():
    with open(_env_path) as _f:
        for _line in _f:
            _line = _line.strip()
            if _line and not _line.startswith("#") and "=" in _line:
                _k, _v = _line.split("=", 1)
                os.environ.setdefault(_k.strip(), _v.strip())

ASSETS_DIR = Path(__file__).parent.parent / "assets"
OUTPUT_DIR = Path(__file__).parent.parent / "output"
OUTPUT_DIR.mkdir(exist_ok=True)

FAMILY_PUBLISHED_FILE = Path(__file__).resolve().parent / "family_published_topics.json"

def get_family_history(tag: str = "family") -> list:
    if FAMILY_PUBLISHED_FILE.exists():
        try:
            with open(FAMILY_PUBLISHED_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, dict):
                    return data.get(tag, [])
                if isinstance(data, list) and tag == "family":
                    return data
        except Exception:
            pass
    return []

def save_family_topic(topic: str, tag: str = "family"):
    data = {}
    if FAMILY_PUBLISHED_FILE.exists():
        try:
            with open(FAMILY_PUBLISHED_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, list):
                    data = {"family": data}
        except Exception:
            pass

    if tag not in data:
        data[tag] = []
    if topic not in data[tag]:
        data[tag].append(topic)
        if len(data[tag]) > 500:
            data[tag] = data[tag][-500:]
        try:
            with open(FAMILY_PUBLISHED_FILE, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
        except Exception:
            pass

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
GROQ_API_KEY = os.getenv("GROQ_API_KEY")

# CONSTANTS

# ─────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────

def prompt_multiline(prompt_text: str) -> str:
    """Read multi-line input until user types END on its own line."""
    print(f"\n{prompt_text}")
    print("(Paste your text, then type END on a new line and press Enter)\n")
    lines = []
    while True:
        line = input()
        if line.strip().upper() == "END":
            break
        lines.append(line)
    return "\n".join(lines)


def prompt_input(prompt_text: str, default: str = "") -> str:
    """Single line input with optional default."""
    val = input(f"{prompt_text} [{default}]: ").strip()
    return val if val else default


def slug(text: str) -> str:
    """Convert text to filename-safe slug."""
    import re
    s = text.lower()[:50]
    s = re.sub(r'[^a-z0-9]+', '_', s)
    return s.strip('_')

def is_weekday_in_regina(schedule_time_utc: str) -> bool:
    from zoneinfo import ZoneInfo
    if schedule_time_utc.endswith("Z"):
        utc_str = schedule_time_utc[:-1] + "+00:00"
    else:
        utc_str = schedule_time_utc
    dt = datetime.fromisoformat(utc_str).astimezone(ZoneInfo("America/Regina"))
    return dt.weekday() < 5

def generate_lofi_metadata_local() -> dict:
    import random

    settings = [
        # Café & Coffee
        ("Rainy Tokyo Café ☕", "rainy Tokyo café with soft jazz and rain on the windows"),
        ("Paris Bistro Morning 🥐", "quiet Paris bistro at dawn with espresso and cobblestone streets outside"),
        ("Rooftop Café at Sunset 🌇", "open rooftop café as the city glows orange at dusk"),
        ("Foggy Seoul Coffee Shop 🌫️", "cozy Seoul coffee shop wrapped in morning fog"),
        ("Venice Canal Café 🛶", "small café beside a quiet Venice canal with lapping water"),

        # Libraries & Study Spaces
        ("Midnight Library 🌙", "vast quiet library at midnight with warm lamp light"),
        ("Old University Library 📚", "grand university library with tall oak shelves and ticking clocks"),
        ("Bookshop in the Rain 📖", "small independent bookshop on a rainy afternoon"),
        ("Reading Room at Dusk 🕯️", "candlelit reading room as evening falls outside"),
        ("Archive Room 🗂️", "forgotten archive room with dusty books and soft amber light"),

        # Nature & Outdoors
        ("Snowy Mountain Cabin 🏔️", "cozy cabin during a snowstorm with a crackling fireplace"),
        ("Autumn Forest Creek 🍂", "peaceful forest path with falling leaves and a babbling creek"),
        ("Rainy Countryside Cottage 🌧️", "stone cottage in the English countryside during a gentle rain"),
        ("Cherry Blossom Garden 🌸", "Japanese garden in full bloom with soft wind and distant temple bells"),
        ("Foggy Lakeside Dock 🌊", "wooden dock on a misty mountain lake at early morning"),
        ("Greenhouse at Dawn 🌿", "sunlit greenhouse with birdsong and dew on the glass"),
        ("Bamboo Forest Path 🎋", "narrow path through a quiet bamboo forest with rustling leaves"),
        ("Lavender Field at Dusk 💜", "open lavender field as the sun dips below the horizon"),

        # City & Urban
        ("City Window at Dusk 🌆", "apartment window overlooking a glowing city at golden hour"),
        ("Subway Station Late Night 🚇", "nearly empty subway station after midnight with distant trains"),
        ("Rainy Night Street 🌃", "narrow city street glistening with rain under yellow streetlights"),
        ("Rooftop After Rain 🏙️", "quiet rooftop garden as the city steams after an evening storm"),
        ("Jazz Club After Hours 🎷", "dimly lit jazz club after closing with chairs on tables"),

        # Home & Interior
        ("Cozy Bedroom Snowfall ❄️", "warm bedroom with fairy lights while snow falls silently outside"),
        ("Attic Studio on a Rainy Day 🎨", "cluttered artist's attic studio with rain drumming on the skylight"),
        ("Kitchen at Midnight 🍵", "quiet kitchen late at night with herbal tea and a sleeping house"),
        ("Beachside Bungalow 🌊", "open bungalow with ocean waves and a warm sea breeze"),

        # Seasonal & Time-of-Day
        ("First Snow Morning ⛄", "waking up to the first snowfall of winter with everything hushed"),
        ("Summer Night Balcony 🌌", "warm balcony on a summer night with crickets and city lights below"),
        ("Rainy April Afternoon 🌦️", "slow April afternoon with rain on the window and nothing to do"),
    ]

    setting_name, setting_desc = random.choice(settings)

    return {
        "title": f"Lofi Study Music — {setting_name} | 1 Hour of Chill Beats",
        "description": (
            f"1 hour of lofi hip hop beats to study and relax to. "
            f"Imagine yourself in a {setting_desc}. "
            "Perfect for studying, homework, focus sessions, and deep work.\n\n"
            "🎵 Lofi beats | Chill music | Study music | Focus music\n\n"
            "Use this mix for:\n"
            "• Studying and homework\n"
            "• Deep work and concentration\n"
            "• Relaxation and unwinding\n"
            "• Reading and journaling\n\n"
            "#lofi #studymusic #chillbeats #focusmusic #lofihiphop"
        ),
        "tags": [
            "lofi hip hop", "study music", "focus music", "chill beats",
            "lofi beats", "homework music", "concentration music",
            "lofi mix", "study beats", "relaxing music"
        ],
        "mood": random.choice(["cozy", "melancholic", "focused", "dreamy"]),
    }

def _get_dynamic_family_topic() -> str:
    """Ask Groq to pick a trending, high-CTR topic for @FamilyFunZone-s9h."""
    print("  Brainstorming a high-CTR topic for @FamilyFunZone-s9h...")
    history = get_family_history()
    recent = history[-50:] if history else []
    
    prompt = f"""
    You are a viral YouTube strategist for @FamilyFunZone-s9h.
    Generate ONE single high-CTR topic for a 'Would You Rather' or 'This or That' game.
    The topic must be visual, exciting, and appealing to families (Luxury Life, Dream House, Superpowers, etc.).
    Recent topics to avoid: {json.dumps(recent)}
    Return ONLY a JSON object with a 'topic' key.
    """
    
    url = "https://api.groq.com/openai/v1/chat/completions"
    headers = {"Authorization": f"Bearer {GROQ_API_KEY}", "Content-Type": "application/json"}
    payload = {
        "model": "llama-3.3-70b-versatile",
        "messages": [{"role": "user", "content": prompt}],
        "response_format": {"type": "json_object"}
    }
    
    try:
        resp = requests.post(url, headers=headers, json=payload, timeout=30)
        data = resp.json()
        raw = data["choices"][0]["message"]["content"]
        return json.loads(raw).get("topic", "Dream Luxury Houses")
    except Exception as e:
        print(f"  Topic generation failed ({e}), using fallback.")
        return "Amazing Dream Houses"


def generate_this_or_that_script(topic=None):
    # Dynamically generate a high-CTR topic if none supplied
    if not topic:
        topic = _get_dynamic_family_topic()

    history = get_family_history()
    recent = history[-50:] if history else []

    avoid_instruction = ""
    if recent:
        avoid_instruction = f"""
    CRITICAL: Avoid repeating or covering the same ground as these recent topics:
    {json.dumps(recent, indent=2)}
    """

    print(f"\nSelected topic: {topic}")
    prompt = f"""
You are generating a viral, high-retention YouTube script for @FamilyFunZone-s9h.
The channel specializes in exciting "Would You Rather?" games that keep viewers watching until the very end.

TOPIC:
{topic}
{avoid_instruction}

CRITICAL RULES:
- Output ONLY valid JSON
- No markdown
- No explanations
- No comments
- No code fences
- JSON must parse perfectly

STYLE:
- Viral YouTube energy
- Highly visual
- Funny
- Exciting
- Family friendly
- Bright colorful ideas
- Great for kids and Shorts content

{{
  "title": "string (High-CTR viral title)",
  "format_label": "WOULD YOU RATHER?",
  "subtitle": "string",
  "description": "string",
  "tags": ["string"],
  "intro": "string",

  "questions": [
    {{
      "number": 1,
      "question": "Would you rather have?",
      "option_a": "string",
      "option_b": "string",
      "image_a": "short image keyword",
      "image_b": "short image keyword",
      "answer": "must exactly match option_a or option_b",
      "explanation": "1 sentence",
      "image_keyword": "short image keyword"
    }}
  ],

  "fun_facts": [
    {{
      "after_question": 3,
      "text": "string"
    }}
  ],

  "outro": "string"
}}

REQUIREMENTS:
- Exactly 15 questions
- Exactly 5 fun facts
- Fun facts after:
  3, 6, 9, 12, 15
- Every question must be unique
- Keep image prompts visual and short
- Avoid repeating concepts

IMPORTANT:
Return ONLY JSON.
"""

    url = "https://api.groq.com/openai/v1/chat/completions"

    headers = {
        "Authorization": f"Bearer {GROQ_API_KEY}",
        "Content-Type": "application/json",
    }

    payload = {
        "model": "llama-3.3-70b-versatile",
        "messages": [
            {
                "role": "system",
                "content": (
                    "You generate perfect JSON "
                    "for YouTube game videos."
                ),
            },
            {
                "role": "user",
                "content": prompt,
            },
        ],
        "temperature": 0.9,
        "max_tokens": 7000,
        "response_format": {
            "type": "json_object"
        },
    }

    response = requests.post(
        url,
        headers=headers,
        json=payload,
        timeout=120,
    )

    if response.status_code != 200:

        raise Exception(
            f"Groq API error "
            f"{response.status_code}: {response.text}"
        )

    data = response.json()

    raw = data["choices"][0]["message"]["content"]

    script = json.loads(raw)

    return script

# ─────────────────────────────────────────────
# LOFI PIPELINE (fully free)
# ─────────────────────────────────────────────

def run_lofi(schedule_time=None):
    import random

    print("\n" + "="*50)
    print("LOFI MUSIC CHANNEL — fully free pipeline")
    print("="*50)

    # ── Generate metadata locally ──────────────────
    print("\nGenerating metadata locally...")
    metadata = generate_lofi_metadata_local()

    title       = metadata["title"]
    description = metadata["description"]
    tags        = metadata["tags"]

    print(f"\n  Title : {title}")
    print(f"  Mood  : {metadata.get('mood', 'n/a')}")
    print(f"  Tags  : {', '.join(tags[:4])}...")

    # ── Check assets ──────────────────────────────────
    lofi_dir    = ASSETS_DIR / "lofi"
    music_files = list(lofi_dir.glob("*.mp3"))
    random.shuffle(music_files)
    if not music_files:
        print(f"\nNo MP3 files found in {lofi_dir}")
        print("Download lofi tracks from suno.ai and place them there.")
        sys.exit(1)

    visuals_dir  = ASSETS_DIR / "lofi_visuals"
    visuals_dir.mkdir(exist_ok=True)
    visual_files = sorted(visuals_dir.glob("*.mp4"))
    if not visual_files:
        fallback = ASSETS_DIR / "lofi_loop.mp4"
        if fallback.exists():
            visual_files = [fallback]
        else:
            print(f"\nNo video files in {visuals_dir}")
            print("Add .mp4 loops to assets/lofi_visuals/")
            sys.exit(1)

    visual_path = random.choice(visual_files)
    print(f"\n  Music tracks : {len(music_files)}")
    print(f"  Visual loop  : {visual_path.name}")

    confirm = prompt_input("\nUse this metadata? (yes/no)", "yes")
    if confirm.lower() not in ("yes", "y"):
        title       = prompt_input("Video title", title)
        description = prompt_multiline("Paste your video description")
        tags_raw    = prompt_input("Tags (comma-separated)", ", ".join(tags))
        tags        = [t.strip() for t in tags_raw.split(",")]

    duration_hours = int(prompt_input("Duration in hours", "1"))
    
    # Update title to reflect actual duration
    title = title.replace("1 Hour", f"{duration_hours} Hour{'s' if duration_hours != 1 else ''}")

    # ── Assemble ──────────────────────────────────────
    out_slug = slug(title)
    out_path = str(OUTPUT_DIR / f"{out_slug}.mp4")

    from ffmpeg_assembler import assemble_lofi_video
    assemble_lofi_video(
        music_tracks   = [str(f) for f in music_files],
        loop_visual    = str(visual_path),
        output_path    = out_path,
        duration_hours = duration_hours,
        title          = title,
        channel        = "lofi",
    )

    _upload_video(out_path, title, description, tags, channel="lofi", schedule_time=schedule_time)

# ─────────────────────────────────────────────
# FAMILY PIPELINE (free with local TTS)
# ─────────────────────────────────────────────

def run_family(topic=None, schedule_time=None):

    from family_assembler import (
        assemble_family_video,
        cleanup_family_temp,
    )

    print("\n" + "=" * 50)
    print("AUTO FAMILY VIDEO GENERATOR")
    print("=" * 50)

    try:

        cleanup_family_temp()

        print("\nGenerating script with Groq...\n")

        script = generate_this_or_that_script(topic)

        Path("scripts").mkdir(exist_ok=True)

        json_file = "scripts/this_or_that.json"

        Path(json_file).write_text(
            json.dumps(script, indent=2),
            encoding="utf-8",
        )

        print(
            f"\nGenerated:\n"
            f"  Title: {script['title']}"
        )

    except Exception as e:

        print(f"\nScript generation failed: {e}")

        sys.exit(1)

    title = script["title"]

    out_slug = slug(title)

    out_path = str(
        OUTPUT_DIR / f"{out_slug}.mp4"
    )

    print("\nAssembling video...\n")

    assemble_family_video(script, out_path)

    cleanup_family_temp()

    save_family_topic(script.get("title", title))

    print("\nUploading video...\n")

    _upload_video(
        out_path,
        title,
        script.get("description", ""),
        script.get("tags", []),
        channel="family",
        schedule_time=schedule_time,
    )

    print("\nDone!\n")

# ─────────────────────────────────────────────
# ENGLISH VIBES HUB PIPELINE
# ─────────────────────────────────────────────

def _english_video_assets(subfolder="english_visuals"):
    """Fetch visuals from a specific subfolder in assets."""
    visuals_dir = ASSETS_DIR / subfolder
    visuals_dir.mkdir(exist_ok=True)
    visual_files = sorted(visuals_dir.glob("*.mp4"))

    if not visual_files:
        print(f"\nNo video files in {visuals_dir}")
        print(f"Please add at least one .mp4 loop to assets/{subfolder}/")
        sys.exit(1)

    bg_music = ASSETS_DIR / "background_music.mp3"
    bg_music_str = str(bg_music) if bg_music.exists() else None
    if not bg_music_str:
        print(f"  Warning: background_music.mp3 not found in {ASSETS_DIR}, proceeding without music.")

    return visual_files, bg_music_str


def _assemble_english_script(script, out_slug, visual_path, bg_music_str):
    from english_assembler import generate_podcast_audio, assemble_english_video, cleanup_english_temp
    from ffmpeg_assembler import generate_captions
    from english_generator import annotate_script_with_idiom_windows

    cleanup_english_temp()

    # Generate audio AND collect per-turn timestamps for idiom overlay timing
    res = generate_podcast_audio(script, return_turn_times=True)
    if isinstance(res, tuple):
        audio_path, per_turn_times = res
    else:
        audio_path, per_turn_times = res, []

    # .srt fallback captions
    srt_path = str(OUTPUT_DIR / f"{out_slug}.srt")
    try:
        generate_captions(audio_path, srt_path)
    except Exception as e:
        print(f"  .srt captions skipped: {e}")
        srt_path = None

    # .ass karaoke captions
    ass_path = str(OUTPUT_DIR / f"{out_slug}.ass")
    try:
        from ass_caption_writer import generate_ass_captions
        # Annotate script with idiom windows before generating captions
        annotate_script_with_idiom_windows(script)
        generate_ass_captions(
            audio_path=audio_path,
            output_ass=ass_path,
            script_data=script,
            idiom_phrases=[w.get("idiom", "") for w in script.get("idiom_windows", [])],
            is_shorts=False,
            per_turn_times=per_turn_times,
        )
    except Exception as e:
        print(f"  .ass captions skipped: {e}")
        ass_path = None

    print(f"\n  Visual loop  : {visual_path.name}")

    out_path = str(OUTPUT_DIR / f"{out_slug}.mp4")
    assemble_english_video(
        podcast_audio=audio_path,
        loop_visual=str(visual_path),
        output_path=out_path,
        captions_srt=srt_path,
        ass_captions=ass_path,
        background_music=bg_music_str,
        title=script["title"],
        channel="english",
        idiom_windows=script.get("idiom_windows"),
        per_turn_times=per_turn_times,
        dialogue=script.get("dialogue", []),
    )

    cleanup_english_temp()
    return out_path


def _challenge_schedule_time(start_date: str = None, day_offset: int = 0, publish_hour: int = 6) -> str:
    timezone_name = os.getenv("LOCAL_TIMEZONE", "America/Regina")
    tz = ZoneInfo(timezone_name)
    now = datetime.now(tz)
    if start_date:
        first_day = datetime.strptime(start_date, "%Y-%m-%d").date()
    else:
        first_day = now.date()
        first_publish = datetime.combine(first_day, datetime.min.time(), tzinfo=tz).replace(hour=publish_hour)
        if first_publish <= now + timedelta(minutes=20):
            first_day += timedelta(days=1)

    publish_at = datetime.combine(
        first_day + timedelta(days=day_offset),
        datetime.min.time(),
        tzinfo=tz,
    ).replace(hour=publish_hour)
    return publish_at.astimezone(ZoneInfo("UTC")).isoformat().replace("+00:00", "Z")


def run_english(topic=None, upload=True, schedule_time=None, notify_subscribers=None):
    from english_assembler import cleanup_english_temp
    from english_generator import generate_english_script
    
    print("\n" + "=" * 50)
    print("ENGLISH VIBES HUB — Podcast Generator")
    print("=" * 50)
    
    try:
        cleanup_english_temp()
        
        print("\nGenerating script with Groq...\n")
        script = generate_english_script(topic)
        
        Path("scripts/output").mkdir(exist_ok=True)
        json_file = "scripts/output/english_podcast.json"
        Path(json_file).write_text(json.dumps(script, indent=2), encoding="utf-8")
        
        print(f"\nGenerated:\n  Title: {script.get('title')}")
        
    except Exception as e:
        print(f"\nScript generation failed: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
        
    title = script["title"]
    out_slug = slug(title)

    visual_files, bg_music_str = _english_video_assets("english_visuals")
    selected_visual = random.choice(visual_files)
    out_path = _assemble_english_script(script, out_slug, selected_visual, bg_music_str)

    if not schedule_time:
        from schedule_ledger import ScheduleLedger
        ledger = ScheduleLedger()
        now_dt = datetime.now(ledger.tz)
        slot_dt, slot_name = ledger.get_next_slot("english", now_dt)
        utc_dt = slot_dt.astimezone(ZoneInfo("UTC"))
        schedule_time = utc_dt.isoformat().replace("+00:00", "Z")
        print(f"  Selected default English slot: {slot_name} ({slot_dt.strftime('%Y-%m-%d %H:%M:%S')} CST)")
    else:
        slot_name = None

    if notify_subscribers is None:
        notify_subscribers = True

    if upload:
        print("\nUploading video...\n")
        _upload_video(
            out_path,
            title,
            script.get("description", ""),
            script.get("tags", []),
            channel="english",
            schedule_time=schedule_time,
            thumbnail_text=script.get("thumbnail_text", title),
            pinned_comment=script.get("pinned_comment"),
            thumbnail_concept=script.get("thumbnail_concept", None),
            notify_subscribers=notify_subscribers,
            command_channel="english",
            slot=slot_name
        )
        print(f"\nPINNED COMMENT: {script.get('pinned_comment')}")
    else:
        print(f"\nVideo assembled without upload: {out_path}")
    
    print("\nDone!\n")


def run_english_challenge(topic=None, upload=True, start_date=None, publish_hour=6, notify_subscribers=None):
    from english_generator import generate_weekly_challenge_scripts, save_published_topic

    print("\n" + "=" * 50)
    print("ENGLISH VIBES HUB — Weekly Challenge Playlist")
    print("=" * 50)

    if not start_date:
        from schedule_ledger import ScheduleLedger
        ledger = ScheduleLedger()
        now_dt = datetime.now(ledger.tz)
        start_dt = ledger.get_next_challenge_start_date(now_dt)
        start_date = start_dt.date().isoformat()
        print(f"  Selected default English Challenge start date: {start_date}")

    try:
        print("\nGenerating 7-day weekly challenge with Groq...\n")
        package = generate_weekly_challenge_scripts(topic=topic)

        Path("scripts/output").mkdir(exist_ok=True)
        json_file = "scripts/output/english_weekly_challenge.json"
        Path(json_file).write_text(json.dumps(package, indent=2), encoding="utf-8")

        print(f"\nGenerated weekly challenge:\n  Series: {package.get('series_title')}")
    except Exception as e:
        print(f"\nWeekly challenge generation failed: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

    playlist_id = None
    quiz_playlist_id = None
    if upload:
        playlist_title = f"{package.get('series_title', 'English Weekly Challenge')} | 7-Day English Challenge"
        playlist_description = (
            f"🚀 {package.get('series_title', 'English Weekly Challenge')}\n\n"
            f"Master your English skills with this intensive 7-day challenge from EnglishVibesHub (@EnglishVibesHub-s6w). "
            f"Each day covers a new focus area with practical tasks, idioms, and phrasal verbs "
            f"to help you build confidence in real-world conversations.\n\n"
            f"Join Emma and Liam as they guide you through this journey!\n\n"
            f"#EnglishLearning #EnglishChallenge #EnglishVibesHub"
        )
        
        quiz_playlist_title = f"{package.get('series_title', 'English Challenge')} | Daily Quizzes"
        quiz_playlist_description = (
            f"Quick quizzes to test your knowledge from the {package.get('series_title')}! "
            f"Master one skill a day with Emma and Liam from @EnglishVibesHub-s6w.\n\n"
            f"#Shorts #EnglishQuiz #EnglishChallenge"
        )
        try:
            from youtube_uploader import create_playlist

            print(f"\nCreating weekly challenge playlist: {playlist_title}")
            playlist = create_playlist(
                title=playlist_title,
                description=playlist_description,
                channel="english",
            )
            playlist_id = playlist["playlist_id"]
            
            print(f"Creating weekly challenge quiz playlist: {quiz_playlist_title}")
            quiz_playlist = create_playlist(
                title=quiz_playlist_title,
                description=quiz_playlist_description,
                channel="english",
            )
            quiz_playlist_id = quiz_playlist["playlist_id"]
        except Exception as e:
            print(f"\nPlaylist creation failed. Videos will still upload without a playlist.")
            print(f"Error: {e}")

    # Use a specific folder for weekly challenges to keep branding consistent
    visual_files, bg_music_str = _english_video_assets("weekly_challenge_visuals")
    # Pick ONE visual to use for the entire 7-day challenge
    weekly_visual = random.choice(visual_files)
    quiz_visual_files, _ = _english_video_assets("english_shorts_visuals")

    for index, script in enumerate(package["scripts"]):
        day_number = script.get("day", index + 1)
        quiz_script = script.get("quiz_script")
        title = script["title"]
        out_slug = slug(f"day_{day_number}_{title}")

        print("\n" + "-" * 50)
        print(f"Assembling Day {day_number}: {title}")
        print("-" * 50)

        # 1. Assemble and Upload Long-Form Video
        out_path = _assemble_english_script(script, out_slug, weekly_visual, bg_music_str)

        long_form_id = None

        if upload:
            schedule_time = _challenge_schedule_time(
                start_date=start_date,
                day_offset=index,
                publish_hour=publish_hour,
            )
            print(f"\nScheduling Day {day_number} for {schedule_time}...\n")
            result = _upload_video(
                out_path,
                title,
                script.get("description", ""),
                script.get("tags", package.get("tags", [])),
                channel="english",
                schedule_time=schedule_time,
                thumbnail_text=script.get("thumbnail_text", title),
                pinned_comment=script.get("pinned_comment"),
                thumbnail_concept=script.get("thumbnail_concept", None),
                notify_subscribers=notify_subscribers if notify_subscribers is not None else True,
                command_channel="english-challenge",
                slot=f"challenge_{publish_hour}am"
            )
            long_form_id = (result or {}).get("youtube_id")
            
            if playlist_id and long_form_id:
                try:
                    from youtube_uploader import add_video_to_playlist
                    add_video_to_playlist(video_id=long_form_id, playlist_id=playlist_id, channel="english")
                except Exception as e:
                    print(f"  Could not add Day {day_number} to playlist: {e}")
        else:
            print(f"\nDay {day_number} assembled without upload: {out_path}")

        # 2. Assemble and Upload Accompanying Quiz Short
        if quiz_script:
            print(f"\nAssembling Quiz Short for Day {day_number}...")
            from english_assembler import generate_podcast_audio, cleanup_english_temp
            from ffmpeg_assembler import assemble_shorts_video, generate_captions

            cleanup_english_temp()
            res = generate_podcast_audio(quiz_script, return_turn_times=True)
            if isinstance(res, tuple):
                quiz_audio, quiz_turn_times = res
            else:
                quiz_audio, quiz_turn_times = res, []
            quiz_slug = slug(f"quiz_day_{day_number}_{quiz_script['title']}")
            quiz_srt = str(OUTPUT_DIR / f"{quiz_slug}.srt")
            quiz_ass = str(OUTPUT_DIR / f"{quiz_slug}.ass")
            try:
                generate_captions(quiz_audio, quiz_srt, max_line_width=20)
            except Exception as e:
                print(f"  .srt captions skipped: {e}")
                quiz_srt = None
            try:
                from ass_caption_writer import generate_ass_captions
                generate_ass_captions(
                    audio_path=quiz_audio, output_ass=quiz_ass,
                    script_data=quiz_script, is_shorts=True,
                    per_turn_times=quiz_turn_times,
                    video_width=1080, video_height=1920,
                )
            except Exception as e:
                print(f"  .ass captions skipped: {e}")
                quiz_ass = None

            quiz_out_path = str(OUTPUT_DIR / f"{quiz_slug}.mp4")
            assemble_shorts_video(
                narration_audio=quiz_audio,
                stock_clips=[str(random.choice(quiz_visual_files))],
                background_music=bg_music_str,
                captions_srt=quiz_srt,
                ass_captions=quiz_ass,
                output_path=quiz_out_path,
                title=quiz_script["title"],
                idiom_windows=quiz_script.get("idiom_windows"),
                per_turn_times=quiz_turn_times,
                dialogue=quiz_script.get("dialogue", []),
            )
            
            if upload:
                # Quiz is published at 10:00 AM CST
                quiz_schedule_time = _challenge_schedule_time(
                    start_date=start_date,
                    day_offset=index,
                    publish_hour=10,
                )

                comment_text = quiz_script.get("pinned_comment", "")
                # Add related video link to pinned comment if available
                if long_form_id and comment_text and "youtu.be" not in comment_text:
                    comment_text += f"\n\nWatch the full lesson here: https://youtu.be/{long_form_id}"

                print(f"Uploading Day {day_number} Quiz Linked to Video {long_form_id}...")
                try:
                    quiz_result = _upload_video(
                        quiz_out_path, quiz_script["title"], quiz_script["description"], quiz_script["tags"],
                        channel="english",
                        schedule_time=quiz_schedule_time,
                        thumbnail_text=f"QUIZ: DAY {day_number}",
                        pinned_comment=comment_text,
                        related_video_id=long_form_id,
                        notify_subscribers=notify_subscribers if notify_subscribers is not None else True,
                        command_channel="english-challenge",
                        slot="challenge_quiz_10am"
                    )
                    quiz_id = (quiz_result or {}).get("youtube_id")
                    if quiz_playlist_id and quiz_id:
                        from youtube_uploader import add_video_to_playlist
                        add_video_to_playlist(video_id=quiz_id, playlist_id=quiz_playlist_id, channel="english")
                    save_published_topic(quiz_script.get("title"), topic_type="quiz")
                except Exception as e:
                    print(f"  Quiz upload failed for Day {day_number}: {e}")
            
            cleanup_english_temp()

    print("\nWeekly challenge pipeline done!\n")

def run_english_challenge_shorts_only(json_path, start_date, publish_hour=6, upload=True, related_video_ids=None, notify_subscribers=None):
    """
    Specialized runner to generate and upload ONLY the quiz shorts 
    from an existing weekly challenge JSON package.
    """
    from english_assembler import cleanup_english_temp, generate_podcast_audio
    from english_generator import generate_weekly_challenge_quiz_script, save_published_topic
    from ffmpeg_assembler import assemble_shorts_video, generate_captions
    from youtube_uploader import add_video_to_playlist

    print("\n" + "=" * 50)
    print("ENGLISH VIBES HUB — Weekly Challenge Quiz Shorts Only")
    print("=" * 50)

    path = Path(json_path)
    if not path.exists():
        print(f"Error: {json_path} not found.")
        sys.exit(1)

    package = json.loads(path.read_text(encoding="utf-8"))
    quiz_playlist_id = None

    if upload:
        quiz_playlist_title = f"{package.get('series_title', 'English Challenge')} | Daily Quizzes"
        quiz_playlist_description = (
            f"Quick quizzes to test your knowledge from the {package.get('series_title')}! "
            f"Master one skill a day with Emma and Liam from @EnglishVibesHub-s6w.\n\n"
            f"#Shorts #EnglishQuiz #EnglishChallenge"
        )
        try:
            from youtube_uploader import create_playlist
            print(f"Creating weekly challenge quiz playlist: {quiz_playlist_title}")
            quiz_playlist = create_playlist(
                title=quiz_playlist_title,
                description=quiz_playlist_description,
                channel="english",
            )
            quiz_playlist_id = quiz_playlist["playlist_id"]
        except Exception as e:
            print(f"Playlist creation failed: {e}")

    quiz_visual_files, _ = _english_video_assets("english_shorts_visuals")
    bg_music = ASSETS_DIR / "background_music.mp3"
    bg_music_str = str(bg_music) if bg_music.exists() else None

    for index, script in enumerate(package["scripts"]):
        day_number = script.get("day", index + 1)
        quiz_script = script.get("quiz_script")
        
        if not quiz_script:
            print(f"\nGenerating missing quiz script for Day {day_number} from challenge content...")
            quiz_script = generate_weekly_challenge_quiz_script(script)

        print(f"\nAssembling Quiz Short for Day {day_number}...")
        cleanup_english_temp()
        res = generate_podcast_audio(quiz_script, return_turn_times=True)
        if isinstance(res, tuple):
            quiz_audio, quiz_turn_times = res
        else:
            quiz_audio, quiz_turn_times = res, []
        quiz_slug = slug(f"quiz_day_{day_number}_{quiz_script['title']}")
        quiz_srt = str(OUTPUT_DIR / f"{quiz_slug}.srt")
        generate_captions(quiz_audio, quiz_srt, max_line_width=20)
        
        quiz_out_path = str(OUTPUT_DIR / f"{quiz_slug}.mp4")
        assemble_shorts_video(
            narration_audio=quiz_audio,
            stock_clips=[str(random.choice(quiz_visual_files))],
            background_music=bg_music_str,
            captions_srt=quiz_srt,
            output_path=quiz_out_path,
            title=quiz_script["title"],
            idiom_windows=quiz_script.get("idiom_windows"),
            per_turn_times=quiz_turn_times,
            dialogue=quiz_script.get("dialogue", []),
        )
        
        if upload:
            # Quiz is published at 10:00 AM CST
            quiz_schedule_time = _challenge_schedule_time(
                start_date=start_date,
                day_offset=index,
                publish_hour=10,
            )

            rel_id = related_video_ids[index] if related_video_ids and index < len(related_video_ids) else None
            print(f"Uploading Day {day_number} Quiz scheduled for {quiz_schedule_time} (linked to {rel_id})...")

            comment_text = quiz_script.get("pinned_comment", "")
            if rel_id and comment_text and "youtu.be" not in comment_text:
                comment_text += f"\n\nWatch the full lesson here: https://youtu.be/{rel_id}"

            try:
                quiz_result = _upload_video(
                    quiz_out_path, quiz_script["title"], quiz_script["description"], quiz_script["tags"],
                    channel="english",
                    schedule_time=quiz_schedule_time,
                    thumbnail_text=f"QUIZ: DAY {day_number}",
                    pinned_comment=comment_text,
                    related_video_id=rel_id,
                    notify_subscribers=notify_subscribers if notify_subscribers is not None else True,
                    command_channel="english-challenge",
                    slot="challenge_quiz_10am"
                )
                quiz_id = (quiz_result or {}).get("youtube_id")
                if quiz_playlist_id and quiz_id:
                    add_video_to_playlist(video_id=quiz_id, playlist_id=quiz_playlist_id, channel="english")
                save_published_topic(quiz_script.get("title"), topic_type="quiz")
            except Exception as e:
                print(f"  Quiz upload failed for Day {day_number}: {e}")
        
        cleanup_english_temp()

    print("\nQuiz Shorts pipeline done!\n")

def run_english_comments_retry(json_path, short_ids_str, related_ids_str, channel="english"):
    """
    Maintenance task: Posts/Retries pinned comments on existing Shorts
    linking them to their respective long-form videos.
    """
    from youtube_uploader import set_pinned_comment
    from english_generator import generate_weekly_challenge_quiz_script

    path = Path(json_path)
    if not path.exists():
        print(f"Error: {json_path} not found.")
        return

    package = json.loads(path.read_text(encoding="utf-8"))
    scripts = package.get("scripts", [])
    if not scripts:
        print(f"Error: No scripts found in {json_path}")
        return

    short_ids = [vid.strip() for vid in short_ids_str.split(",")]
    related_ids = [rid.strip() for rid in related_ids_str.split(",")]

    print(f"\nRetrying pinned comments for {len(short_ids)} videos...")
    for index, script in enumerate(scripts):
        if index >= len(short_ids): break
        
        quiz_script = script.get("quiz_script")
        if not quiz_script:
            print(f"  Day {index+1}: Missing quiz_script in JSON. Generating on the fly...")
            quiz_script = generate_weekly_challenge_quiz_script(script)

        if quiz_script:
            comment_text = quiz_script.get("pinned_comment", "")
            rel_id = related_ids[index] if index < len(related_ids) else None
            
            if rel_id and "youtu.be" not in comment_text:
                comment_text += f"\n\nWatch the full lesson here: https://youtu.be/{rel_id}"
            
            print(f"  Day {index+1}: Posting to https://youtu.be/{short_ids[index]}")
            set_pinned_comment(short_ids[index], comment_text, channel)

def run_english_challenge_fixup(json_path, long_ids_str, short_ids_str, channel="english", related_only=False):
    """
    Maintenance task: Updates descriptions (adding practice tasks) and 
    posts pinned comments for both long-form videos and quiz shorts.
    """
    from youtube_uploader import update_video_description, set_pinned_comment, set_related_video

    path = Path(json_path)
    if not path.exists():
        print(f"Error: {json_path} not found.")
        return

    package = json.loads(path.read_text(encoding="utf-8"))
    scripts = package.get("scripts", [])
    days_info = package.get("days", [])

    long_ids = [vid.strip() for vid in long_ids_str.split(",")]
    short_ids = [vid.strip() for vid in short_ids_str.split(",")]

    print(f"\nFixing metadata for {len(long_ids)} Days of the Challenge...")

    for i, script in enumerate(scripts):
        if i >= len(long_ids): break
        
        long_id = long_ids[i]
        day_num = script.get("day", i + 1)
        
        if not related_only:
            # 1. Update Long-form Video
            print(f"\n[Day {day_num}] Long Video: https://youtu.be/{long_id}")
            
            # Get practice task from the original plan
            day_plan = days_info[i] if i < len(days_info) else {}
            task = day_plan.get("practice_task", "")
            
            # Construct updated description including the practice task
            base_desc = script.get("description", "")
            if task and "PRACTICE TASK" not in base_desc.upper():
                new_desc = f"📝 DAILY PRACTICE TASK: {task}\n\n" + base_desc
            else:
                new_desc = base_desc
            
            update_video_description(long_id, new_desc, channel)
            
            pinned = script.get("pinned_comment")
            if pinned:
                set_pinned_comment(long_id, pinned, channel)
            
        # 2. Update Quiz Short
        if i < len(short_ids):
            short_id = short_ids[i]
            print(f"\n[Day {day_num}] Linking Quiz Short: https://youtu.be/{short_id}")

            # Link the long video as the related video
            set_related_video(short_id, long_id, channel)

            if not related_only:
                quiz_script = script.get("quiz_script", {})
                quiz_pinned = quiz_script.get("pinned_comment", "")
                if quiz_pinned and long_id not in quiz_pinned:
                    quiz_pinned += f"\n\nWatch the full lesson here: https://youtu.be/{long_id}"
                if quiz_pinned:
                    set_pinned_comment(short_id, quiz_pinned, channel)

def run_english_shorts(topic=None, upload=True, schedule_time=None, dynamic_visuals=False, notify_subscribers=None):
    from english_assembler import cleanup_english_temp, generate_podcast_audio
    from english_generator import generate_english_shorts_script
    from ffmpeg_assembler import assemble_shorts_video, generate_captions
    
    if dynamic_visuals and upload:
        raise RuntimeError(
            "Dynamic English visuals are prototype-only and must be run with --no-upload for manual review."
        )

    print("\n" + "=" * 50)
    print("ENGLISH VIBES HUB — Shorts Generator")
    if dynamic_visuals:
        print("Dynamic Emma/Liam visuals: ON (prototype, no-upload only)")
    print("=" * 50)

    if dynamic_visuals:
        from dynamic_english_renderer import preflight_dynamic_english_assets
        preflight_dynamic_english_assets()
    
    try:
        cleanup_english_temp()
        
        print("\nGenerating Shorts script with Groq...\n")
        script = generate_english_shorts_script(topic)
        
        Path("scripts/output").mkdir(exist_ok=True)
        json_file = "scripts/output/english_shorts.json"
        Path(json_file).write_text(json.dumps(script, indent=2), encoding="utf-8")
        
        print(f"\nGenerated:\n  Title: {script.get('title')}")
        
    except Exception as e:
        print(f"\nScript generation failed: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
        
    title = script["title"]
    out_slug = slug(title)

    if dynamic_visuals:
        from dynamic_english_renderer import render_dynamic_english_short
        bg_music = ASSETS_DIR / "background_music.mp3"
        bg_music_str = str(bg_music) if bg_music.exists() else None
        srt_path = str(OUTPUT_DIR / f"{out_slug}.srt")
        out_path = str(OUTPUT_DIR / f"{out_slug}.mp4")

        cleanup_english_temp()
        render_dynamic_english_short(
            script_data=script,
            output_path=out_path,
            captions_srt=srt_path,
            background_music=bg_music_str,
            title=title,
        )
        cleanup_english_temp()

        print(f"\nDynamic video assembled without upload: {out_path}")
        print("Review this MP4 manually before promoting dynamic visuals to publishing.")
        print("\nDone!\n")
        return

    visuals_dir = ASSETS_DIR / "english_shorts_visuals"
    if not visuals_dir.exists():
        visuals_dir.mkdir(parents=True)
        print(f"\nCreated directory: {visuals_dir}")
        print("Falling back to english_visuals since shorts visuals are not yet provided.")
        visual_files, bg_music_str = _english_video_assets("english_visuals")
    else:
        visual_files = sorted(visuals_dir.glob("*.mp4"))
        if not visual_files:
            print(f"\nNo video files in {visuals_dir}, falling back to english_visuals.")
            visual_files, bg_music_str = _english_video_assets("english_visuals")
        else:
            bg_music = ASSETS_DIR / "background_music.mp3"
            bg_music_str = str(bg_music) if bg_music.exists() else None

    selected_visual = random.choice(visual_files)

    # Audio + per-turn timestamps
    cleanup_english_temp()
    res = generate_podcast_audio(script, return_turn_times=True)
    if isinstance(res, tuple):
        audio_path, per_turn_times = res
    else:
        audio_path, per_turn_times = res, []

    # Idiom annotation
    from english_generator import annotate_script_with_idiom_windows
    try:
        annotate_script_with_idiom_windows(script)
    except Exception as e:
        print(f"  Idiom annotation skipped: {e}")

    # .srt captions
    srt_path = str(OUTPUT_DIR / f"{out_slug}.srt")
    try:
        generate_captions(audio_path, srt_path, max_line_width=25, max_line_count=2)
    except Exception as e:
        print(f"  .srt captions skipped: {e}")
        srt_path = None

    # .ass karaoke captions
    ass_path = str(OUTPUT_DIR / f"{out_slug}.ass")
    try:
        from ass_caption_writer import generate_ass_captions
        generate_ass_captions(
            audio_path=audio_path, output_ass=ass_path,
            script_data=script,
            idiom_phrases=[w.get("idiom", "") for w in script.get("idiom_windows", [])],
            is_shorts=True, video_width=1080, video_height=1920,
            per_turn_times=per_turn_times,
        )
    except Exception as e:
        print(f"  .ass captions skipped: {e}")
        ass_path = None

    print(f"\n  Visual loop  : {selected_visual.name}")

    out_path = str(OUTPUT_DIR / f"{out_slug}.mp4")
    assemble_shorts_video(
        narration_audio=audio_path,
        stock_clips=[str(selected_visual)],
        background_music=bg_music_str,
        captions_srt=srt_path,
        ass_captions=ass_path,
        output_path=out_path,
        title=title,
        idiom_windows=script.get("idiom_windows"),
        per_turn_times=per_turn_times,
        dialogue=script.get("dialogue", []),
    )

    cleanup_english_temp()

    if not schedule_time:
        from schedule_ledger import ScheduleLedger
        ledger = ScheduleLedger()
        now_dt = datetime.now(ledger.tz)
        slot_dt, slot_name = ledger.get_next_slot("english-shorts", now_dt)
        utc_dt = slot_dt.astimezone(ZoneInfo("UTC"))
        schedule_time = utc_dt.isoformat().replace("+00:00", "Z")
        print(f"  Selected default English Shorts slot: {slot_name} ({slot_dt.strftime('%Y-%m-%d %H:%M:%S')} CST)")
    else:
        slot_name = None

    if notify_subscribers is None:
        if schedule_time:
            from schedule_ledger import is_weekday_in_regina
            notify_subscribers = is_weekday_in_regina(schedule_time)
        else:
            notify_subscribers = True

    if upload:
        print("\nUploading video...\n")
        # English shorts already have captions overlaid; YouTube Studio auto-generates unique thumbnails
        _upload_video(
            out_path,
            title,
            script.get("description", ""),
            script.get("tags", []),
            channel="english", # Shorts don't use bumpers, but still use 'english' channel creds
            pinned_comment=script.get("pinned_comment"),
            schedule_time=schedule_time,
            notify_subscribers=notify_subscribers,
            command_channel="english-shorts",
            slot=slot_name
        )
    else:
        print(f"\nVideo assembled without upload: {out_path}")
    
    print("\nDone!\n")

def run_english_quiz_shorts(topic=None, upload=True, schedule_time=None, notify_subscribers=None):
    """Manual runner for the new Quiz Shorts strategy."""
    from english_assembler import cleanup_english_temp, generate_podcast_audio
    from english_generator import generate_english_quiz_shorts_script, save_published_topic
    from ffmpeg_assembler import assemble_shorts_video, generate_captions
    
    print("\n" + "=" * 50)
    print("ENGLISH VIBES HUB — Quiz Shorts (Strategy 1)")
    print("=" * 50) 
    
    script = generate_english_quiz_shorts_script(topic)
    title = script["title"]
    out_slug = slug(title)

    visual_files, bg_music_str = _english_video_assets("english_shorts_visuals")
    selected_visual = random.choice(visual_files)
    
    res = generate_podcast_audio(script, return_turn_times=True)
    if isinstance(res, tuple):
        audio_path, per_turn_times = res
    else:
        audio_path, per_turn_times = res, []
    srt_path = str(OUTPUT_DIR / f"{out_slug}.srt")
    ass_path = str(OUTPUT_DIR / f"{out_slug}.ass")
    try:
        generate_captions(audio_path, srt_path, max_line_width=20)
    except Exception as e:
        print(f"  .srt captions skipped: {e}")
        srt_path = None
    try:
        from ass_caption_writer import generate_ass_captions
        # Annotate script with idiom windows before generating captions
        from english_generator import annotate_script_with_idiom_windows
        annotate_script_with_idiom_windows(script)
        
        generate_ass_captions(
            audio_path=audio_path, output_ass=ass_path,
            script_data=script, is_shorts=True,
            video_width=1080, video_height=1920,
            idiom_phrases=[w.get("idiom", "") for w in script.get("idiom_windows", [])],
            per_turn_times=per_turn_times,
        )
    except Exception as e:
        print(f"  .ass captions skipped: {e}")
        ass_path = None

    out_path = str(OUTPUT_DIR / f"{out_slug}.mp4")
    assemble_shorts_video(
        narration_audio=audio_path,
        stock_clips=[str(selected_visual)],
        background_music=bg_music_str,
        captions_srt=srt_path,
        ass_captions=ass_path,
        output_path=out_path,
        title=title,
        idiom_windows=script.get("idiom_windows"),
        per_turn_times=per_turn_times,
        dialogue=script.get("dialogue", []),
    )

    if not schedule_time:
        from schedule_ledger import ScheduleLedger
        ledger = ScheduleLedger()
        now_dt = datetime.now(ledger.tz)
        slot_dt, slot_name = ledger.get_next_slot("english-quiz", now_dt)
        utc_dt = slot_dt.astimezone(ZoneInfo("UTC"))
        schedule_time = utc_dt.isoformat().replace("+00:00", "Z")
        print(f"  Selected default English Quiz slot: {slot_name} ({slot_dt.strftime('%Y-%m-%d %H:%M:%S')} CST)")
    else:
        slot_name = None

    if notify_subscribers is None:
        if schedule_time:
            from schedule_ledger import is_weekday_in_regina
            notify_subscribers = is_weekday_in_regina(schedule_time)
        else:
            notify_subscribers = True

    if upload:
        result = _upload_video(
            out_path, title, script["description"], script["tags"],
            channel="english",
            thumbnail_text="QUIZ TIME!",
            pinned_comment=script.get("pinned_comment"),
            schedule_time=schedule_time,
            notify_subscribers=notify_subscribers,
            command_channel="english-quiz",
            slot=slot_name
        )

        video_id = (result or {}).get("youtube_id")
        if video_id:
            try:
                from youtube_uploader import add_video_to_playlist
                add_video_to_playlist(video_id=video_id, playlist_id="PL1D9QTXOAjU9CjNgVhQq2xlJKwi7MrKwD", channel="english")
            except Exception as e:
                print(f"  Could not add quiz to master playlist: {e}")

        save_published_topic(script.get("title", topic), topic_type="quiz")
        print(f"PINNED COMMENT: {script.get('pinned_comment')}")
    else:
        print(f"\nVideo assembled without upload: {out_path}")

    cleanup_english_temp()

def run_english_community(topic=None, content_type="quiz"):
    """
    Pipeline to generate Community Tab content (Quizzes and Image Polls).
    Uses Pexels for free stock images when creating Image Polls.
    """
    from english_generator import generate_english_community_content
    
    print("\n" + "=" * 50)
    print(f"ENGLISH VIBES HUB — Community {content_type.upper()}")
    print("=" * 50)
    
    # Now calls generate_dynamic_topic internally if topic is None
    data = generate_english_community_content(topic=topic, content_type=content_type)
    
    print(f"\nQUESTION: {data['question']}")
    if content_type == "quiz":
        for i, opt in enumerate(data.get("options", [])):
            prefix = " [CORRECT] " if i == data.get("correct_index") else "           "
            print(f"  {chr(65+i)}){prefix}{opt}")
    else:
        for i, opt in enumerate(data.get("options", [])):
            print(f"  Option {i+1}: {opt}")
    
    print(f"\nEXPLANATION (for pinned comment or post body):")
    print(data.get("correct_explanation", "No explanation generated."))

    image_paths = []
    # Handle Image Generation using Pexels (Free)
    if data.get("image_prompts"):
        print("\nFetching free poll images from Pexels...")
        # Thumbnail overlay is currently disabled; images are downloaded as-is.
        
        prompts = data.get("image_prompts", [])
        options = data.get("options", [])
        
        api_key = os.getenv("PEXELS_API_KEY")
        if not api_key:
            print("  [ERROR] PEXELS_API_KEY not found. Stock images required for Image Polls.")
            return

        for idx, (img_prompt, opt_text) in enumerate(zip(prompts, options)):
            try:
                # Search Pexels for a photo matching the prompt
                resp = requests.get(
                    f"https://api.pexels.com/v1/search?query={img_prompt}&per_page=1",
                    headers={"Authorization": api_key},
                    timeout=15
                )
                resp.raise_for_status()
                photos = resp.json().get("photos", [])
                if not photos:
                    print(f"  No photo found for: {img_prompt}")
                    continue
                
                img_url = photos[0]["src"]["large2x"]
                img_data = requests.get(img_url, timeout=15).content
                img_path = OUTPUT_DIR / f"community_poll_{idx}.jpg"
                img_path.write_bytes(img_data)
                
                # Thumbnail overlay disabled — skip create_thumbnail call.
                image_paths.append(img_path)
                print(f"  ✓ Image {idx+1} ready: {img_path}")
            except Exception as e:
                print(f"  Failed to get image {idx+1} for '{img_prompt}': {e}")

        if image_paths:
            print(f"\nSUCCESS! {len(image_paths)} images generated in {OUTPUT_DIR}")
    
    print("\n" + "-" * 50)
    print("POSTING INSTRUCTIONS:")
    print("1. Go to YouTube Studio -> Content -> Community")
    print(f"2. Copy/Paste the question and options above (Use 'Image Poll' for visual quizzes).")
    if image_paths:
        print(f"3. Upload the {len(image_paths)} generated images from the output folder.")
    print("-" * 50)

# ─────────────────────────────────────────────
# SLOW ENGLISH PIPELINE — dual render + cross-pollination
# ─────────────────────────────────────────────

def _patch_video_description(channel: str, video_id: str, new_description: str) -> None:
    """Update a live YouTube video description after upload.
    Silently skips if no credentials are available (e.g. --no-upload mode)."""
    if not video_id:
        return
    try:
        from youtube_uploader import update_video_description
        update_video_description(video_id, new_description, channel=channel)
    except Exception as e:
        print(f"  Warning: could not patch description for {video_id}: {e}")


def run_english_slow(topic=None, upload=True, schedule_time=None, slow_offset_hours=24, notify_subscribers=None):
    """Dual-render slow English pipeline:

    1. Generate one idiom-focused script (8-12 turns)
    2. Render Normal video  (0.95x TTS, standard captions)
    3. Render Slow   video  (0.80x TTS, large captions + 🐢 badge)
    4. Upload Normal → get normal_yt_id
    5. Upload Slow with Normal's URL in description → get slow_yt_id
    6. Patch Normal's description to add the Slow URL (cross-pollination)
    """
    from english_assembler import (
        cleanup_english_temp,
        generate_podcast_audio,
        assemble_english_video,
        generate_slow_podcast_audio,
        assemble_slow_english_video,
    )
    from english_generator import generate_english_slow_script, annotate_script_with_idiom_windows
    from ffmpeg_assembler import generate_captions

    print("\n" + "=" * 50)
    print("ENGLISH VIBES HUB — Slow English Dual Render")
    print("=" * 50)

    # ── 1. Generate script ────────────────────────────────
    try:
        cleanup_english_temp()
        print("\nGenerating slow idiom script with Groq...\n")
        script = generate_english_slow_script(topic)

        Path("scripts/output").mkdir(exist_ok=True)
        json_file = "scripts/output/english_slow.json"
        Path(json_file).write_text(json.dumps(script, indent=2), encoding="utf-8")
        print(f"\nGenerated:\n  Idiom: {script.get('idiom')}\n  Title: {script.get('title')}")
    except Exception as e:
        print(f"\nScript generation failed: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

    idiom        = script.get("idiom", topic or "English Idiom")
    normal_title = script.get("title_normal", f"{idiom} — What Does It Mean? | English Idioms")
    slow_title   = script.get("title_slow", f"{idiom} 🐢 SLOW English | Idioms for Beginners")

    # Template descriptions (URLs injected after upload)
    desc_normal_template = script.get("description_normal", script.get("description", ""))
    desc_slow_template   = script.get("description_slow",   script.get("description", ""))
    tags                 = script.get("tags", [])

    visual_files, bg_music_str = _english_video_assets("english_visuals")
    selected_visual = random.choice(visual_files)

    normal_slug = slug(normal_title) + "_normal"
    slow_slug   = slug(slow_title)   + "_slow"

    # ── 2. Render Normal video ────────────────────────────
    print("\n" + "-" * 40)
    print("Rendering NORMAL video (0.95x speed)...")
    print("-" * 40)
    cleanup_english_temp()

    # Annotate idiom windows once (shared between both renders)
    try:
        annotate_script_with_idiom_windows(script)
    except Exception as e:
        print(f"  Idiom annotation skipped: {e}")

    res = generate_podcast_audio(script, return_turn_times=True)
    if isinstance(res, tuple):
        normal_audio, normal_turn_times = res
    else:
        normal_audio, normal_turn_times = res, []

    normal_srt = str(OUTPUT_DIR / f"{normal_slug}.srt")
    normal_ass = str(OUTPUT_DIR / f"{normal_slug}.ass")
    try:
        generate_captions(normal_audio, normal_srt)
    except Exception as e:
        print(f"  .srt captions skipped: {e}")
        normal_srt = None
    try:
        from ass_caption_writer import generate_ass_captions
        generate_ass_captions(
            audio_path=normal_audio, output_ass=normal_ass,
            script_data=script,
            idiom_phrases=[w.get("idiom", "") for w in script.get("idiom_windows", [])],
            is_shorts=False,
        )
    except Exception as e:
        print(f"  .ass captions skipped: {e}")
        normal_ass = None

    normal_path = str(OUTPUT_DIR / f"{normal_slug}.mp4")
    assemble_english_video(
        podcast_audio=normal_audio,
        loop_visual=str(selected_visual),
        output_path=normal_path,
        captions_srt=normal_srt,
        ass_captions=normal_ass,
        background_music=bg_music_str,
        title=normal_title,
        channel="english",
        idiom_windows=script.get("idiom_windows"),
        per_turn_times=normal_turn_times,
        dialogue=script.get("dialogue", []),
    )

    # ── 3. Render Slow video ──────────────────────────────
    print("\n" + "-" * 40)
    print("Rendering SLOW video (0.80x speed)...")
    print("-" * 40)
    cleanup_english_temp()
    res = generate_slow_podcast_audio(script, return_turn_times=True)
    if isinstance(res, tuple):
        slow_audio, slow_turn_times = res
    else:
        slow_audio, slow_turn_times = res, []

    slow_srt = str(OUTPUT_DIR / f"{slow_slug}.srt")
    slow_ass = str(OUTPUT_DIR / f"{slow_slug}.ass")
    try:
        generate_captions(slow_audio, slow_srt)
    except Exception as e:
        print(f"  .srt captions skipped: {e}")
        slow_srt = None
    try:
        from ass_caption_writer import generate_ass_captions
        generate_ass_captions(
            audio_path=slow_audio, output_ass=slow_ass,
            script_data=script,
            idiom_phrases=[w.get("idiom", "") for w in script.get("idiom_windows", [])],
            is_shorts=False,
            per_turn_times=slow_turn_times,
        )
    except Exception as e:
        print(f"  .ass captions skipped: {e}")
        slow_ass = None

    slow_path = str(OUTPUT_DIR / f"{slow_slug}.mp4")
    assemble_slow_english_video(
        podcast_audio=slow_audio,
        loop_visual=str(selected_visual),
        output_path=slow_path,
        captions_srt=slow_srt,
        ass_captions=slow_ass,
        background_music=bg_music_str,
        title=slow_title,
        channel="english",
        idiom_windows=script.get("idiom_windows"),
        per_turn_times=slow_turn_times,
        dialogue=script.get("dialogue", []),
    )

    cleanup_english_temp()

    if not schedule_time:
        from schedule_ledger import ScheduleLedger
        ledger = ScheduleLedger()
        now_dt = datetime.now(ledger.tz)
        slot_dt, slot_name = ledger.get_next_slot("english", now_dt)
        utc_dt = slot_dt.astimezone(ZoneInfo("UTC"))
        schedule_time = utc_dt.isoformat().replace("+00:00", "Z")
        print(f"  Selected default English slot for Slow Normal: {slot_name} ({slot_dt.strftime('%Y-%m-%d %H:%M:%S')} CST)")
    else:
        slot_name = None

    if notify_subscribers is None:
        if schedule_time:
            from schedule_ledger import is_weekday_in_regina
            notify_subscribers = is_weekday_in_regina(schedule_time)
        else:
            notify_subscribers = True

    if not upload:
        print(f"\nBoth videos assembled (upload skipped):")
        print(f"  Normal : {normal_path}")
        print(f"  Slow   : {slow_path}")
        print("\nDone!\n")
        return

    # ── 4. Upload Normal (placeholder slow link in description) ──
    print("\n" + "-" * 40)
    print("Uploading NORMAL video...")
    print("-" * 40)
    desc_normal_placeholder = desc_normal_template.format(
        slow_url="[Slow version uploading — link coming soon!]"
    )
    normal_result = _upload_video(
        normal_path,
        normal_title,
        desc_normal_placeholder,
        tags,
        channel="english",
        schedule_time=schedule_time,
        thumbnail_text=script.get("thumbnail_text", normal_title),
        pinned_comment=script.get("pinned_comment"),
        thumbnail_concept=script.get("thumbnail_concept", None),
        notify_subscribers=notify_subscribers,
        command_channel="english",
        slot=slot_name
    )
    normal_yt_id = (normal_result or {}).get("youtube_id", "")
    normal_url   = f"https://youtu.be/{normal_yt_id}" if normal_yt_id else ""

    # ── 5. Upload Slow (Normal URL already known in description) ──
    print("\n" + "-" * 40)
    print("Uploading SLOW video...")
    print("-" * 40)
    
    # Calculate staggered schedule for the slow video
    if schedule_time:
        base_dt = datetime.fromisoformat(schedule_time.replace("Z", "+00:00"))
    else:
        base_dt = datetime.now(ZoneInfo("UTC"))
    
    slow_schedule = (base_dt + timedelta(hours=slow_offset_hours)).isoformat().replace("+00:00", "Z")

    desc_slow_final = desc_slow_template.format(
        normal_url=normal_url or "[see Normal version on EnglishVibesHub]"
    )
    slow_result = _upload_video(
        slow_path,
        slow_title,
        desc_slow_final,
        tags + ["slow english", "slow english learning", "english for beginners"],
        channel="english",
        schedule_time=slow_schedule,
        thumbnail_text=f"🐢 {script.get('thumbnail_text', idiom)}",
        pinned_comment=script.get("pinned_comment"),
        thumbnail_concept=script.get("thumbnail_concept", None),
        notify_subscribers=notify_subscribers,
        command_channel="english",
        slot="slow_stagger"
    )
    slow_yt_id = (slow_result or {}).get("youtube_id", "")
    slow_url   = f"https://youtu.be/{slow_yt_id}" if slow_yt_id else ""
    print(f"\nPINNED COMMENT: {script.get('pinned_comment')}")

    # ── 6. Cross-pollinate: patch Normal description with Slow URL ──
    if normal_yt_id and slow_yt_id:
        print("\nCross-pollinating Normal video description with Slow URL...")
        desc_normal_final = desc_normal_template.format(slow_url=slow_url)
        _patch_video_description("english", normal_yt_id, desc_normal_final)
    elif normal_yt_id:
        print("  Skipping cross-pollination patch (no slow_yt_id available)")

    print("\n" + "=" * 50)
    print("Slow English Dual Render — DONE!")
    if normal_url:
        print(f"  Normal : {normal_url}")
    if slow_url:
        print(f"  Slow   : {slow_url}")
    print("=" * 50)
    print()


# ─────────────────────────────────────────────
# TRENDING PIPELINE (free automated path)
# ─────────────────────────────────────────────

def _preflight_trending(upload: bool = True) -> bool:
    """Validate required free-mode dependencies before doing expensive work."""
    problems = []

    if not GROQ_API_KEY:
        problems.append("Missing GROQ_API_KEY in .env. Add a Groq free-tier API key.")

    if not os.getenv("PEXELS_API_KEY", "").strip():
        problems.append("Missing PEXELS_API_KEY in .env. Create a free key at pexels.com/api.")

    from kokoro_tts import KOKORO_MODEL, KOKORO_VOICES

    if not Path(KOKORO_MODEL).exists() or not Path(KOKORO_VOICES).exists():
        problems.append(
            "Missing Kokoro model files. Download kokoro-v0_19.onnx and voices.bin into the project root."
        )

    ffmpeg_cmd = os.getenv("FFMPEG_CMD", "ffmpeg")
    if not shutil.which(ffmpeg_cmd):
        problems.append(f"FFmpeg not found as '{ffmpeg_cmd}'. Install ffmpeg or set FFMPEG_CMD in .env.")

    if upload:
        creds_path = ASSETS_DIR / "yt_credentials_trending.json"
        if not creds_path.exists():
            problems.append(
                "Missing assets/yt_credentials_trending.json. Start python scripts/server.py and visit "
                "http://localhost:5001/setup-auth/trending once."
            )

    if problems:
        print("\nTrending preflight failed:")
        for problem in problems:
            print(f"  - {problem}")
        return False

    return True


def _ensure_background_music(duration_seconds: float) -> str:
    """Use optional background music, or generate silent audio for narrated assembly."""
    bg_music = ASSETS_DIR / "background_music.mp3"
    if bg_music.exists():
        return str(bg_music)

    silent_path = OUTPUT_DIR / "silent_background.mp3"
    if silent_path.exists():
        return str(silent_path)

    print("  No background_music.mp3 found; generating silent background audio.")
    subprocess.run(
        [
            os.getenv("FFMPEG_CMD", "ffmpeg"),
            "-y",
            "-f",
            "lavfi",
            "-i",
            "anullsrc=r=44100:cl=stereo",
            "-t",
            str(max(int(duration_seconds) + 5, 30)),
            str(silent_path),
        ],
        capture_output=True,
        check=True,
    )
    return str(silent_path)


def _build_trending_video(package: dict, schedule_time=None) -> dict:
    """Generate voiceover, assemble video, and return upload metadata."""
    title = package["title"]
    script = package["script"]
    keyword = package["stock_keyword"]

    print(f"\nGenerated trending package ({package.get('video_format', 'shorts')}):")
    print(f"  Topic : {package.get('chosen_topic', title)}")
    print(f"  Angle : {package.get('angle', '')}")
    print(f"  Title : {title}")
    print(f"  B-roll: {keyword}")
    print(f"  Words : {package.get('word_count', len(script.split()))}")
    print(f"  Format: {package.get('video_format', 'shorts')}")

    out_slug   = slug(title)
    audio_path = str(OUTPUT_DIR / f"{out_slug}_voice.m4a")
    out_path   = str(OUTPUT_DIR / f"{out_slug}.mp4")

    print("\nGenerating free local Kokoro voiceover...")
    from free_tts import generate_tts, clean_script
    generate_tts(clean_script(script), audio_path, voice="af_bella", speed=1.08)

    from ffmpeg_assembler import (
        get_audio_duration, fetch_stock_videos,
        generate_captions, assemble_narrated_video, assemble_shorts_video, cleanup_temp, TEMP_DIR
    )

    duration = get_audio_duration(audio_path)
    bg_music = _ensure_background_music(duration)
    temp_dir = TEMP_DIR
    temp_dir.mkdir(exist_ok=True)
    orientation = "portrait" if package.get("video_format") == "shorts" else "landscape"
    clips    = fetch_stock_videos(keyword, duration + 30, str(temp_dir), orientation=orientation)
    if not clips:
        print("\nNo Pexels clips were downloaded. Try rerunning with --topic and a broader topic.")
        sys.exit(1)

    srt_path = str(OUTPUT_DIR / f"{out_slug}.srt")

    try:
        if package.get("video_format") == "shorts":
            generate_captions(audio_path, srt_path, max_line_width=25, max_line_count=2)
        else:
            generate_captions(audio_path, srt_path)
    except Exception as e:
        print(f"  Captions skipped: {e}")
        srt_path = None

    assembler = assemble_shorts_video if package.get("video_format") == "shorts" else assemble_narrated_video
    assembler(
        narration_audio=audio_path,
        stock_clips=clips,
        background_music=bg_music,
        captions_srt=srt_path,
        output_path=out_path,
        title=title,
        channel="trending",
    )
    cleanup_temp()

    return {
        "video_path": out_path,
        "title": title,
        "description": package["description"],
        "tags": package["tags"],
        "format": package.get("video_format", "shorts"),
        schedule_time: schedule_time,
    }


def run_trending(topic=None, region="CA", upload=True, video_format="shorts", schedule_time=None):
    print("\n" + "="*50)
    print("TRENDING NARRATED CHANNEL — free automated pipeline")
    print("="*50)

    if not _preflight_trending(upload=upload):
        sys.exit(1)

    from trending_generator import generate_trending_package

    if topic:
        print(f"\nUsing provided topic: {topic}")
    else:
        print(f"\nFetching Google Trends for region: {region.upper()}")

    package = generate_trending_package(topic=topic, region=region, video_format=video_format)
    result = _build_trending_video(package)

    if upload:
        _upload_video(
            result["video_path"],
            result["title"],
            result["description"],
            result["tags"],
            channel="trending",
            thumbnail_text=result.get("thumbnail_text", result["title"]),
        )
    else:
        print(f"\nDone. Upload skipped. Video ready at: {result['video_path']}")


def run_trending_pair(topic=None, region="CA", upload=True, schedule_time=None):
    print("\n" + "="*50)
    print("TRENDING CHANNEL — Short + Explainer batch")
    print("="*50)

    if not _preflight_trending(upload=upload):
        sys.exit(1)

    from trending_generator import (
        choose_topic_with_groq,
        fetch_google_trends,
        generate_trending_package,
        normalize_topic_data,
    )

    if topic:
        print(f"\nUsing provided topic for both videos: {topic}")
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
        print(f"\nFetching Google Trends for region: {region.upper()}")
        topics = fetch_google_trends(region)
        if not topics:
            raise RuntimeError(f"No usable Google Trends topics found for region {region}.")
        topic_data = choose_topic_with_groq(topics, region=region)

    results = []
    for video_format in ["shorts", "explainer"]:
        print(f"\nGenerating {video_format} from shared topic...")
        package = generate_trending_package(topic_data=topic_data, video_format=video_format)
        result = _build_trending_video(package, schedule_time=schedule_time)
        results.append(result)

        if upload:
            _upload_video(
                result["video_path"],
                result["title"],
                result["description"],
                result["tags"],
                channel="trending",
                schedule_time=schedule_time,
            )

    if not upload:
        print("\nDone. Upload skipped. Videos ready:")
        for result in results:
            print(f"  {result['format']}: {result['video_path']}")


# ─────────────────────────────────────────────
# SHARED UPLOAD
# ─────────────────────────────────────────────

def _upload_video(
    video_path,
    title,
    description,
    tags,
    channel,
    schedule_time=None,
    thumbnail_text=None,
    thumbnail_concept=None,
    related_video_id=None,
    pinned_comment=None,
    notify_subscribers=True,
    command_channel=None,
    slot=None
):
    print(f"\nVideo ready: {video_path}")
    print(f"Size: {Path(video_path).stat().st_size / 1024 / 1024:.1f} MB")

    creds_path = ASSETS_DIR / f"yt_credentials_{channel}.json"
    if not creds_path.exists():
        print(f"\nNo YouTube credentials found at {creds_path}")
        print("Run the server first and visit: http://localhost:5001/setup-auth/" + channel)
        print(f"Then re-run and choose to upload.")
        return

    thumbnail_path = None
    if thumbnail_text is None:
        thumbnail_text = title

    # Thumbnail generation is currently disabled for all flows.
    # thumbnail_path stays None; YouTube will use the auto-generated frame.

    print("\nUploading to YouTube...")
    try:
        from youtube_uploader import youtube_upload
        result = youtube_upload(
            video_path=str(Path(video_path).absolute()),
            title=title,
            description=description,
            tags=tags,
            channel=channel,
            schedule_time=schedule_time,
            related_video_id=related_video_id,
            pinned_comment=pinned_comment,
            thumbnail_path=str(thumbnail_path) if thumbnail_path else None,
            notify_subscribers=notify_subscribers,
        )
    except Exception as e:
        print(f"\nUpload failed. You can retry after fixing the issue.")
        print(f"Error: {e}")
        return

    if "youtube_id" in result:
        status = "Scheduled" if schedule_time else "Published"
        print(f"\n{status}: https://youtu.be/{result['youtube_id']}")
        
        if schedule_time and command_channel:
            try:
                from schedule_ledger import ScheduleLedger
                ledger = ScheduleLedger()
                ledger.record_upload(
                    channel=command_channel,
                    schedule_time_utc=schedule_time,
                    title=title,
                    youtube_id=result["youtube_id"],
                    slot=slot
                )
            except Exception as e:
                print(f"  Warning: Failed to record upload in ledger: {e}")

        _cleanup_uploaded_video_files(video_path)
        return result
    else:
        print(f"\nUpload response: {result}")
        return result


def _cleanup_uploaded_video_files(video_path):
    video = Path(video_path)
    for path in [
        video,
        video.with_suffix(".srt"),
        video.with_name(f"{video.stem}_voice.m4a"),
        video.with_suffix(".jpg"),
    ]:
        try:
            if path.is_file():
                path.unlink()
        except OSError as e:
            print(f"  Cleanup skipped for {path}: {e}")


def _upload_existing_video(video_path, channel, title=None, description=None, tags=None, schedule_time=None, notify_subscribers=True):
    video = Path(video_path).expanduser()
    if not video.is_absolute():
        video = Path.cwd() / video

    if not video.exists():
        print(f"\nVideo file not found: {video}")
        sys.exit(1)

    if not title:
        title = video.stem.replace("_", " ").replace("-", " ").title()

    if description is None:
        description = prompt_multiline("Paste your video description")

    if tags is None:
        tags_raw = prompt_input("Tags (comma-separated)", "")
        tags = [tag.strip() for tag in tags_raw.split(",") if tag.strip()]

    if not schedule_time and channel in ("english", "english-challenge", "english-shorts", "english-quiz"):
        from schedule_ledger import ScheduleLedger
        ledger = ScheduleLedger()
        now_dt = datetime.now(ledger.tz)
        slot_dt, slot_name = ledger.get_next_slot(channel, now_dt)
        utc_dt = slot_dt.astimezone(ZoneInfo("UTC"))
        schedule_time = utc_dt.isoformat().replace("+00:00", "Z")
        print(f"  Selected default slot for existing upload: {slot_name} ({slot_dt.strftime('%Y-%m-%d %H:%M:%S')} CST)")
    else:
        slot_name = None

    upload_channel = "english" if channel == "english-challenge" else channel
    _upload_video(
        str(video),
        title,
        description,
        tags,
        channel=upload_channel,
        schedule_time=schedule_time,
        notify_subscribers=notify_subscribers,
        command_channel=channel,
        slot=slot_name
    )


# ─────────────────────────────────────────────
# ENTRY POINT
# ─────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Manual YouTube pipeline runner — free mode")
    parser.add_argument("--channel", choices=["lofi", "family", "trending", "english", "english-challenge", "english-shorts", "english-slow", "english-quiz", "english-challenge-shorts", "english-community"],
                        help="Which channel to produce for")
    parser.add_argument("--topic", help="Override trend discovery with a specific trending topic")
    parser.add_argument("--region", default="CA", help="Google Trends region for trending videos (default: CA)")
    parser.add_argument(
        "--video-format",
        choices=["shorts", "explainer", "both"],
        default="shorts",
        help="Trending format: shorts, explainer, or both for one Short plus one 5-7 minute explainer",
    )
    parser.add_argument("--type", choices=["quiz", "image_poll"], default="quiz", help="Type of community post")
    parser.add_argument("--no-upload", action="store_true", help="Assemble the video but skip YouTube upload")
    parser.add_argument("--start-date", help="First publish date for english-challenge, YYYY-MM-DD")
    parser.add_argument("--publish-hour", type=int, default=6, help="Local publish hour for scheduled english-challenge videos")
    parser.add_argument("--upload-existing", help="Upload an existing MP4 without rebuilding it")
    parser.add_argument("--title", help="Title to use with --upload-existing")
    parser.add_argument("--description", help="Description to use with --upload-existing")
    parser.add_argument("--tags", help="Comma-separated tags to use with --upload-existing")
    parser.add_argument("--schedule-time", help="UTC publish time for --upload-existing, e.g. 2026-06-03T15:00:00Z")
    parser.add_argument("--slow-offset-hours", type=int, default=24, help="Hours to stagger the slow version (default 24)")
    parser.add_argument("--json-package", help="Path to a weekly challenge JSON package for --channel english-challenge-shorts")
    parser.add_argument("--related-ids", help="Comma-separated YouTube IDs to link shorts to (Day 1, Day 2, ...)")
    parser.add_argument("--video-ids", help="Comma-separated YouTube IDs for the Shorts (used with --comments-only)")
    parser.add_argument("--comments-only", action="store_true", help="Only post/update pinned comments")
    parser.add_argument("--fix-challenge", action="store_true", help="Fix missing tasks and pinned comments for a challenge run")
    parser.add_argument("--profile", action="store_true", help="Enable cProfile for this run")
    parser.add_argument("--related-only", action="store_true", help="Only update the related video link for shorts during fixup")
    parser.add_argument(
        "--dynamic-visuals",
        action="store_true",
        help="Prototype only: render english-shorts with dynamic Emma/Liam visuals. Requires --no-upload.",
    )
    parser.add_argument("--notify-subs", action="store_true", help="Force notify subscribers")
    parser.add_argument("--no-notify-subs", action="store_true", help="Force do NOT notify subscribers")
    args = parser.parse_args()

    if args.publish_hour < 0 or args.publish_hour > 23:
        parser.error("--publish-hour must be between 0 and 23")

    # Calculate a UTC schedule time if local date/hour are provided
    effective_schedule_time = args.schedule_time
    if not effective_schedule_time and args.start_date:
        effective_schedule_time = _challenge_schedule_time(
            start_date=args.start_date,
            day_offset=0,
            publish_hour=args.publish_hour
        )

    if args.upload_existing and not args.channel:
        parser.error("--upload-existing requires --channel")

    notify_override = None
    if args.notify_subs and args.no_notify_subs:
        parser.error("Cannot specify both --notify-subs and --no-notify-subs")
    elif args.notify_subs:
        notify_override = True
    elif args.no_notify_subs:
        notify_override = False

    if args.upload_existing:
        if args.dynamic_visuals:
            parser.error("--dynamic-visuals cannot be used with --upload-existing")
        tags = None
        if args.tags is not None:
            tags = [tag.strip() for tag in args.tags.split(",") if tag.strip()]
        _upload_existing_video(
            args.upload_existing,
            args.channel,
            title=args.title,
            description=args.description,
            tags=tags,
            schedule_time=effective_schedule_time,
            notify_subscribers=notify_override if notify_override is not None else True
        )
        return

    if not args.channel:
        print("\nWhich channel are you producing for?")
        print("  1. lofi              — study music (fully free)")
        print("  2. family            — family-friendly quiz/facts (free with local TTS)")
        print("  3. trending          — narrated topics (free with local TTS or ElevenLabs)")
        print("  4. english           — english vibes hub podcast (free with dual local TTS)")
        print("  5. english-challenge — 7-day English weekly challenge playlist")
        print("  6. english-shorts    — English shorts using Emma and Liam")
        print("  7. english-slow      — Slow English dual render (normal + 0.80x) with cross-pollination")
        print("  8. english-quiz      — English Quiz Short (NEW)")
        print("  9. english-challenge-shorts — Generate only Quiz Shorts from an existing package")
        print("  10. english-community — English Community Tab Quizzes & Polls")
        choice = prompt_input("Enter 1-10", "10")
        args.channel = {
            "1": "lofi",
            "2": "family",
            "3": "trending",
            "4": "english",
            "5": "english-challenge",
            "6": "english-shorts",
            "7": "english-slow",
            "8": "english-quiz",
            "9": "english-challenge-shorts",
            "10": "english-community"
        }.get(choice, "lofi")

    if args.dynamic_visuals:
        if args.channel != "english-shorts":
            parser.error("--dynamic-visuals is currently supported only with --channel english-shorts")
        if not args.no_upload:
            parser.error("--dynamic-visuals is prototype-only and requires --no-upload")

    if args.channel == "lofi":
        run_lofi(schedule_time=effective_schedule_time)
    elif args.channel == "family":
        run_family(topic=args.topic, schedule_time=effective_schedule_time)
    elif args.channel == "english":
        run_english(topic=args.topic, upload=not args.no_upload, schedule_time=effective_schedule_time, notify_subscribers=notify_override)
    elif args.channel == "english-challenge":
        run_english_challenge(
            topic=args.topic,
            upload=not args.no_upload,
            start_date=args.start_date,
            publish_hour=args.publish_hour,
            notify_subscribers=notify_override,
        )
    elif args.channel == "english-shorts":
        run_english_shorts(
            topic=args.topic,
            upload=not args.no_upload,
            schedule_time=effective_schedule_time,
            dynamic_visuals=args.dynamic_visuals,
            notify_subscribers=notify_override,
        )
    elif args.channel == "english-slow":
        run_english_slow(
            topic=args.topic, 
            upload=not args.no_upload, 
            schedule_time=effective_schedule_time,
            slow_offset_hours=args.slow_offset_hours,
            notify_subscribers=notify_override,
        )
    elif args.channel == "english-community":
        run_english_community(topic=args.topic, content_type=args.type)
    elif args.channel == "english-quiz":
        run_english_quiz_shorts(topic=args.topic, upload=not args.no_upload, schedule_time=effective_schedule_time, notify_subscribers=notify_override)
    elif args.channel == "english-challenge-shorts":
        if args.fix_challenge:
            if not args.related_ids or not args.video_ids:
                print("Error: --fix-challenge requires both --related-ids (Long videos) and --video-ids (Quiz shorts)")
                return
            run_english_challenge_fixup(
                json_path=args.json_package or "scripts/output/english_weekly_challenge.json",
                long_ids_str=args.related_ids,
                short_ids_str=args.video_ids,
                related_only=args.related_only
            )
            return

        if args.comments_only:
            if not args.video_ids or not args.related_ids:
                print("Error: --comments-only requires both --video-ids (Shorts) and --related-ids (Long form)")
                return
            run_english_comments_retry(
                json_path=args.json_package or "scripts/output/english_weekly_challenge.json",
                short_ids_str=args.video_ids,
                related_ids_str=args.related_ids
            )
            return

        related_ids = [rid.strip() for rid in args.related_ids.split(",")] if args.related_ids else None
        run_english_challenge_shorts_only(
            json_path=args.json_package or "scripts/output/english_weekly_challenge.json",
            start_date=args.start_date or "2026-06-11",
            publish_hour=args.publish_hour,
            upload=not args.no_upload,
            related_video_ids=related_ids,
            notify_subscribers=notify_override
        )
    elif args.channel == "trending":
        if args.video_format == "both":
            run_trending_pair(topic=args.topic, region=args.region, upload=not args.no_upload, schedule_time=effective_schedule_time)
        else:
            run_trending(
                topic=args.topic,
                region=args.region,
                upload=not args.no_upload,
                video_format=args.video_format,
                schedule_time=effective_schedule_time,
            )


def profile_script():
    profiler = cProfile.Profile()
    profiler.enable()

    try:
        main()
    finally:
        profiler.disable()
        with open("profile_results.txt", "w") as f:
            stats = pstats.Stats(profiler, stream=f)
            stats.strip_dirs()
            stats.sort_stats("cumulative")
            stats.print_stats()

if __name__ == "__main__":
    # Optimization: Only run profiler if explicitly requested. 
    # Video processing is too heavy for standard profiling and causes massive slowdowns.
    if "--profile" in sys.argv:
        profile_script()
    else:
        main()
