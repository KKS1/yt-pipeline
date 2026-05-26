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

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
GROQ_API_KEY = os.getenv("GROQ_API_KEY")

# CONSTANTS

FAMILY_TOPIC_POOL = [

    # Dream / Luxury
    "Dream Houses",
    "Luxury Lifestyle",
    "Millionaire Life",
    "Private Islands",
    "Future Mansions",
    "Ultimate Bedrooms",
    "Epic Backyards",
    "Crazy Swimming Pools",
    "Fantasy Castles",
    "Celebrity Lifestyle",

    # Food
    "Fast Food",
    "Candy Universe",
    "Desserts",
    "Ice Cream Flavors",
    "Pizza Creations",
    "Chocolate Factory",
    "International Foods",
    "Giant Foods",
    "Weird Food Combos",
    "Restaurant Challenges",

    # Animals
    "Animals",
    "Cute Pets",
    "Wild Jungle Animals",
    "Ocean Creatures",
    "Dinosaurs",
    "Mythical Creatures",
    "Dragons",
    "Zoo Adventures",
    "Animal Superpowers",
    "Tiny vs Giant Animals",

    # Fantasy
    "Fantasy Worlds",
    "Magic Schools",
    "Wizards",
    "Fairy Tales",
    "Pirates",
    "Knights",
    "Mermaids",
    "Elves",
    "Haunted Mansions",
    "Treasure Hunts",

    # Space / Sci-Fi
    "Space Adventure",
    "Aliens",
    "Future Technology",
    "Robots",
    "Time Travel",
    "Flying Cars",
    "Virtual Reality",
    "Mars Colonies",
    "Spaceships",
    "Future Cities",

    # Gaming
    "Video Games",
    "Minecraft Style Builds",
    "Arcade Games",
    "Retro Games",
    "Battle Royale Games",
    "Racing Games",
    "Gaming Rooms",
    "Mobile Games",
    "Virtual Worlds",
    "Pixel Worlds",

    # Adventure
    "Jungle Adventure",
    "Survival Challenges",
    "Treasure Islands",
    "Extreme Weather",
    "Mountain Adventures",
    "Deep Sea Exploration",
    "Safari Adventures",
    "Camping Trips",
    "Secret Missions",
    "Spy Gadgets",

    # School / Kids
    "School Life",
    "Classroom Challenges",
    "Summer Camp",
    "Field Trips",
    "School Lunches",
    "Science Fair",
    "Art Class",
    "Talent Shows",
    "Funny Teachers",
    "Ultimate Playgrounds",

    # Sports / Competition
    "Sports Challenges",
    "Olympic Games",
    "Extreme Sports",
    "Obstacle Courses",
    "Water Sports",
    "Snow Sports",
    "Mini Golf",
    "Theme Park Competitions",
    "Race Challenges",
    "Superhero Training",

    # Entertainment
    "Movies",
    "Cartoon Worlds",
    "Superheroes",
    "Villains",
    "Animated Adventures",
    "Music Videos",
    "Dance Battles",
    "Talent Competitions",
    "TV Game Shows",
    "Circus Adventures",

    # Travel
    "World Travel",
    "Famous Landmarks",
    "Vacation Resorts",
    "Underwater Hotels",
    "Treehouse Hotels",
    "Theme Parks",
    "Safari Lodges",
    "Snow Villages",
    "Tropical Islands",
    "Luxury Cruises",

    # Nature
    "Nature Wonders",
    "Volcanoes",
    "Waterfalls",
    "Rainforests",
    "Arctic Adventures",
    "Desert Survival",
    "Beautiful Beaches",
    "National Parks",
    "Weather Powers",
    "Seasons",

    # Silly / Fun
    "Impossible Choices",
    "Funny Situations",
    "Superpowers",
    "Tiny vs Giant",
    "Invisible Powers",
    "Flying Abilities",
    "Teleportation",
    "Mind Reading",
    "Robot Helpers",
    "Magical Objects",

    # Holiday / Seasonal
    "Christmas",
    "Halloween",
    "Easter",
    "Summer Vacation",
    "Winter Wonderland",
    "Birthday Parties",
    "New Year Celebrations",
    "Valentine's Day",
    "Holiday Foods",
    "Spooky Adventures",

    # Vehicles
    "Supercars",
    "Monster Trucks",
    "Motorcycles",
    "Luxury Yachts",
    "Private Jets",
    "Construction Vehicles",
    "Emergency Vehicles",
    "Trains",
    "Rocket Ships",
    "Submarines",

    # Creative / Imagination
    "Build Your Own World",
    "Design Your Dream City",
    "Invent Crazy Gadgets",
    "Create Your Theme Park",
    "Design Your Superhero",
    "Magical Powers",
    "Secret Laboratories",
    "Crazy Inventions",
    "Ultimate Treehouses",
    "Future Schools",

    # Challenge / Puzzle style
    "Riddles",
    "Mystery Challenges",
    "Escape Rooms",
    "Brain Teasers",
    "Impossible Puzzles",
    "Logic Challenges",
    "Guess the Object",
    "Secret Doors",
    "Hidden Treasure",
    "Choose Your Path",

    # Viral / YouTube-friendly
    "TikTok Trends",
    "YouTube Challenges",
    "24 Hour Challenges",
    "Last To Leave",
    "Impossible Decisions",
    "Rich vs Poor",
    "Gold vs Diamond",
    "Luxury vs Survival",
    "Future vs Ancient",
    "Kids vs Adults",

    # Misc Viral Concepts
    "Rainbow World",
    "Glow in the Dark",
    "Candy Land",
    "Neon Cities",
    "Sky Islands",
    "Underwater Cities",
    "Cloud Kingdoms",
    "Miniature Worlds",
    "Giant Worlds",
    "Secret Underground Bases",
]

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
        "title": f"Lofi Study Music — {setting_name} | 3 Hours of Chill Beats",
        "description": (
            f"3 hours of lofi hip hop beats to study and relax to. "
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

def generate_this_or_that_script(topic=None):

    # Auto-pick topic if none supplied
    if not topic:
        topic = random.choice(FAMILY_TOPIC_POOL)

    print(f"\nSelected topic: {topic}")

    prompt = f"""
You are generating a viral YouTube
family-friendly "Would You Rather?" video.

TOPIC:
{topic}

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

JSON SCHEMA:

{{
  "title": "string",
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

def run_lofi():
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

    duration_hours = int(prompt_input("Duration in hours", "3"))

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
    )

    _upload_video(out_path, title, description, tags, channel="lofi")

# ─────────────────────────────────────────────
# FAMILY PIPELINE (free with local TTS)
# ─────────────────────────────────────────────

def run_family():

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

        script = generate_this_or_that_script()

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

    print("\nUploading video...\n")

    _upload_video(
        out_path,
        title,
        script.get("description", ""),
        script.get("tags", []),
        channel="family",
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

    cleanup_english_temp()
    audio_path = generate_podcast_audio(script)

    srt_path = str(OUTPUT_DIR / f"{out_slug}.srt")
    try:
        generate_captions(audio_path, srt_path)
    except Exception as e:
        print(f"  Captions skipped: {e}")
        srt_path = None

    print(f"\n  Visual loop  : {visual_path.name}")

    out_path = str(OUTPUT_DIR / f"{out_slug}.mp4")
    assemble_english_video(
        podcast_audio=audio_path,
        loop_visual=str(visual_path),
        captions_srt=srt_path,
        background_music=bg_music_str,
        title=script["title"]
    )

    cleanup_english_temp()
    return out_path


def _challenge_schedule_time(start_date: str = None, day_offset: int = 0, publish_hour: int = 9) -> str:
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


def run_english(upload=True):
    from english_assembler import cleanup_english_temp
    from english_generator import generate_english_script
    
    print("\n" + "=" * 50)
    print("ENGLISH VIBES HUB — Podcast Generator")
    print("=" * 50)
    
    try:
        cleanup_english_temp()
        
        print("\nGenerating script with Groq...\n")
        script = generate_english_script()
        
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

    if upload:
        print("\nUploading video...\n")
        _upload_video(
            out_path,
            title,
            script.get("description", ""),
            script.get("tags", []),
            channel="english",
        )
    else:
        print(f"\nVideo assembled without upload: {out_path}")
    
    print("\nDone!\n")


def run_english_challenge(topic=None, upload=True, start_date=None, publish_hour=9):
    from english_generator import generate_weekly_challenge_scripts

    print("\n" + "=" * 50)
    print("ENGLISH VIBES HUB — Weekly Challenge Playlist")
    print("=" * 50)

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

    # Use a specific folder for weekly challenges to keep branding consistent
    visual_files, bg_music_str = _english_video_assets("weekly_challenge_visuals")
    # Pick ONE visual to use for the entire 7-day challenge
    weekly_visual = random.choice(visual_files)

    for index, script in enumerate(package["scripts"]):
        day_number = script.get("day", index + 1)
        title = script["title"]
        out_slug = slug(f"day_{day_number}_{title}")

        print("\n" + "-" * 50)
        print(f"Assembling Day {day_number}: {title}")
        print("-" * 50)

        out_path = _assemble_english_script(script, out_slug, weekly_visual, bg_music_str)

        if upload:
            schedule_time = _challenge_schedule_time(
                start_date=start_date,
                day_offset=index,
                publish_hour=publish_hour,
            )
            print(f"\nScheduling Day {day_number} for {schedule_time}...\n")
            _upload_video(
                out_path,
                title,
                script.get("description", ""),
                script.get("tags", package.get("tags", [])),
                channel="english",
                schedule_time=schedule_time,
            )
        else:
            print(f"\nDay {day_number} assembled without upload: {out_path}")

    print("\nWeekly challenge pipeline done!\n")

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


def _build_trending_video(package: dict) -> dict:
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
    )
    cleanup_temp()

    return {
        "video_path": out_path,
        "title": title,
        "description": package["description"],
        "tags": package["tags"],
        "format": package.get("video_format", "shorts"),
    }


def run_trending(topic=None, region="CA", upload=True, video_format="shorts"):
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
        )
    else:
        print(f"\nDone. Upload skipped. Video ready at: {result['video_path']}")


def run_trending_pair(topic=None, region="CA", upload=True):
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
        result = _build_trending_video(package)
        results.append(result)

        if upload:
            _upload_video(
                result["video_path"],
                result["title"],
                result["description"],
                result["tags"],
                channel="trending",
            )

    if not upload:
        print("\nDone. Upload skipped. Videos ready:")
        for result in results:
            print(f"  {result['format']}: {result['video_path']}")


# ─────────────────────────────────────────────
# SHARED UPLOAD
# ─────────────────────────────────────────────

def _upload_video(video_path, title, description, tags, channel, schedule_time=None):
    print(f"\nVideo ready: {video_path}")
    print(f"Size: {Path(video_path).stat().st_size / 1024 / 1024:.1f} MB")

    creds_path = ASSETS_DIR / f"yt_credentials_{channel}.json"
    if not creds_path.exists():
        print(f"\nNo YouTube credentials found at {creds_path}")
        print("Run the server first and visit: http://localhost:5001/setup-auth/" + channel)
        print(f"Then re-run and choose to upload.")
        return

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
        )
    except Exception as e:
        print(f"\nUpload failed. You can retry after fixing the issue.")
        print(f"Error: {e}")
        return

    if "youtube_id" in result:
        status = "Scheduled" if schedule_time else "Published"
        print(f"\n{status}: https://youtu.be/{result['youtube_id']}")
        _cleanup_uploaded_video_files(video_path)
    else:
        print(f"\nUpload response: {result}")


def _cleanup_uploaded_video_files(video_path):
    video = Path(video_path)
    for path in [
        video,
        video.with_suffix(".srt"),
        video.with_name(f"{video.stem}_voice.m4a"),
    ]:
        try:
            if path.is_file():
                path.unlink()
        except OSError as e:
            print(f"  Cleanup skipped for {path}: {e}")


def _upload_existing_video(video_path, channel, title=None, description=None, tags=None):
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

    upload_channel = "english" if channel == "english-challenge" else channel
    _upload_video(str(video), title, description, tags, channel=upload_channel)


# ─────────────────────────────────────────────
# ENTRY POINT
# ─────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Manual YouTube pipeline runner — free mode")
    parser.add_argument("--channel", choices=["lofi", "family", "trending", "english", "english-challenge"],
                        help="Which channel to produce for")
    parser.add_argument("--topic", help="Override trend discovery with a specific trending topic")
    parser.add_argument("--region", default="CA", help="Google Trends region for trending videos (default: CA)")
    parser.add_argument(
        "--video-format",
        choices=["shorts", "explainer", "both"],
        default="shorts",
        help="Trending format: shorts, explainer, or both for one Short plus one 5-7 minute explainer",
    )
    parser.add_argument("--no-upload", action="store_true", help="Assemble the video but skip YouTube upload")
    parser.add_argument("--start-date", help="First publish date for english-challenge, YYYY-MM-DD")
    parser.add_argument("--publish-hour", type=int, default=9, help="Local publish hour for scheduled english-challenge videos")
    parser.add_argument("--upload-existing", help="Upload an existing MP4 without rebuilding it")
    parser.add_argument("--title", help="Title to use with --upload-existing")
    parser.add_argument("--description", help="Description to use with --upload-existing")
    parser.add_argument("--tags", help="Comma-separated tags to use with --upload-existing")
    args = parser.parse_args()

    if args.publish_hour < 0 or args.publish_hour > 23:
        parser.error("--publish-hour must be between 0 and 23")

    if args.upload_existing and not args.channel:
        parser.error("--upload-existing requires --channel")

    if args.upload_existing:
        tags = None
        if args.tags is not None:
            tags = [tag.strip() for tag in args.tags.split(",") if tag.strip()]
        _upload_existing_video(
            args.upload_existing,
            args.channel,
            title=args.title,
            description=args.description,
            tags=tags,
        )
        return

    if not args.channel:
        print("\nWhich channel are you producing for?")
        print("  1. lofi     — study music (fully free)")
        print("  2. family   — family-friendly quiz/facts (free with local TTS)")
        print("  3. trending — narrated topics (free with local TTS or ElevenLabs)")
        print("  4. english  — english vibes hub podcast (free with dual local TTS)")
        print("  5. english-challenge — 7-day English weekly challenge playlist")
        choice = prompt_input("Enter 1, 2, 3, 4, or 5", "1")
        args.channel = {
            "1": "lofi",
            "2": "family",
            "3": "trending",
            "4": "english",
            "5": "english-challenge",
        }.get(choice, "lofi")

    if args.channel == "lofi":
        run_lofi()
    elif args.channel == "family":
        run_family()
    elif args.channel == "english":
        run_english(upload=not args.no_upload)
    elif args.channel == "english-challenge":
        run_english_challenge(
            topic=args.topic,
            upload=not args.no_upload,
            start_date=args.start_date,
            publish_hour=args.publish_hour,
        )
    elif args.channel == "trending":
        if args.video_format == "both":
            run_trending_pair(topic=args.topic, region=args.region, upload=not args.no_upload)
        else:
            run_trending(
                topic=args.topic,
                region=args.region,
                upload=not args.no_upload,
                video_format=args.video_format,
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
    profile_script()
