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
from pathlib import Path
from datetime import datetime
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
    
TOPIC_POOL = [
    "Dream Houses",
    "Animals",
    "Fast Food",
    "Superheroes",
    "Luxury Lifestyle",
    "Fantasy Worlds",
    "Space Adventure",
    "Theme Parks",
    "Magical Schools",
    "Future Technology",
    "Video Games",
    "Dinosaurs",
    "Underwater World",
    "Candy Universe",
    "Jungle Adventure",
    "Pirates",
    "Minecraft Style Builds",
    "Robots",
    "Mythical Creatures",
    "Extreme Weather",
]


def generate_this_or_that_script(topic=None):

    # Auto-pick topic if none supplied
    if not topic:
        topic = random.choice(TOPIC_POOL)

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

    confirm = prompt_input("\nUse this metadata? (yes/no)", "yes")
    if confirm.lower() not in ("yes", "y"):
        title       = prompt_input("Video title", title)
        description = prompt_multiline("Paste your video description")
        tags_raw    = prompt_input("Tags (comma-separated)", ", ".join(tags))
        tags        = [t.strip() for t in tags_raw.split(",")]

    duration_hours = int(prompt_input("Duration in hours", "3"))

    # ── Check assets ──────────────────────────────────
    lofi_dir    = ASSETS_DIR / "lofi"
    music_files = sorted(lofi_dir.glob("*.mp3"))
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
# TRENDING PIPELINE (manual script entry)
# ─────────────────────────────────────────────

def run_trending():
    print("\n" + "="*50)
    print("TRENDING NARRATED CHANNEL — manual script entry")
    print("="*50)
    print("\nTip: Go to claude.ai and ask:")
    print('  "Write a 10-minute YouTube script about [trending topic]"')
    print("Then paste everything below.\n")

    title   = prompt_input("Video title")
    script  = prompt_multiline("Paste your full script")
    desc    = prompt_multiline("Paste your description")
    tags_r  = prompt_input("Tags (comma-separated)")
    tags    = [t.strip() for t in tags_r.split(",")]
    keyword = prompt_input("Stock video keyword (e.g. 'business finance')", "business")

    out_slug   = slug(title)
    audio_path = str(OUTPUT_DIR / f"{out_slug}_voice.m4a")
    out_path   = str(OUTPUT_DIR / f"{out_slug}.mp4")

    # Choose TTS
    print("\nVoiceover options:")
    print("  1. Free local TTS (Coqui) — no cost")
    print("  2. ElevenLabs API — better quality, costs ~$0.002/script")
    choice = prompt_input("Choose (1 or 2)", "1")

    if choice == "2":
        api_key = os.environ.get("ELEVENLABS_API_KEY") or prompt_input("ElevenLabs API key")
        voice_id = os.environ.get("ELEVENLABS_VOICE_ID", "21m00Tcm4TlvDq8ikWAM")
        os.environ["ELEVENLABS_API_KEY"] = api_key
        from ffmpeg_assembler import generate_voiceover
        generate_voiceover(script, audio_path, voice_id)
    else:
        from free_tts import generate_tts, clean_script
        generate_tts(clean_script(script), audio_path)

    bg_music = str(ASSETS_DIR / "background_music.mp3")
    if not Path(bg_music).exists():
        bg_music = None

    from ffmpeg_assembler import (
        get_audio_duration, fetch_stock_videos,
        generate_captions, assemble_narrated_video, cleanup_temp
    )

    duration = get_audio_duration(audio_path)
    temp_dir = OUTPUT_DIR / "temp"
    temp_dir.mkdir(exist_ok=True)
    clips    = fetch_stock_videos(keyword, duration + 30, str(temp_dir))
    srt_path = str(OUTPUT_DIR / f"{out_slug}.srt")

    try:
        generate_captions(audio_path, srt_path)
    except Exception as e:
        print(f"  Captions skipped: {e}")
        srt_path = None

    assemble_narrated_video(
        narration_audio=audio_path,
        stock_clips=clips,
        background_music=bg_music if bg_music else None,
        captions_srt=srt_path,
        output_path=out_path,
        title=title,
    )
    cleanup_temp()

    _upload_video(out_path, title, desc, tags, channel="trending")


# ─────────────────────────────────────────────
# SHARED UPLOAD
# ─────────────────────────────────────────────

def _upload_video(video_path, title, description, tags, channel):
    print(f"\nVideo ready: {video_path}")
    print(f"Size: {Path(video_path).stat().st_size / 1024 / 1024:.1f} MB")

    upload = prompt_input("\nUpload to YouTube now? (yes/no)", "yes")
    if upload.lower() not in ("yes", "y"):
        print(f"\nDone. Upload manually from: {video_path}")
        return

    creds_path = ASSETS_DIR / f"yt_credentials_{channel}.json"
    if not creds_path.exists():
        print(f"\nNo YouTube credentials found at {creds_path}")
        print("Run the server first and visit: http://localhost:5001/setup-auth/" + channel)
        print(f"Then re-run and choose to upload.")
        return

    print("\nUploading to YouTube...")
    try:
        # Call the server upload endpoint
        import requests
        resp = requests.post("http://localhost:5001/upload", json={
            "video_path": str(Path(video_path).absolute()),
            "title": title,
            "description": description,
            "tags": tags,
            "channel": channel,
        })
        result = resp.json()
        if "youtube_id" in result:
            print(f"\nPublished: https://youtu.be/{result['youtube_id']}")
        else:
            print(f"\nUpload response: {result}")
    except Exception as e:
        print(f"\nServer not running. Start it with: python scripts/server.py")
        print(f"Then upload manually or retry.")
        print(f"Error: {e}")


# ─────────────────────────────────────────────
# ENTRY POINT
# ─────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Manual YouTube pipeline runner — free mode")
    parser.add_argument("--channel", choices=["lofi", "family", "trending"],
                        help="Which channel to produce for")
    args = parser.parse_args()

    if not args.channel:
        print("\nWhich channel are you producing for?")
        print("  1. lofi     — study music (fully free)")
        print("  2. family   — family-friendly quiz/facts (free with local TTS)")
        print("  3. trending — narrated topics (free with local TTS or ElevenLabs)")
        choice = prompt_input("Enter 1, 2, or 3", "1")
        args.channel = {"1": "lofi", "2": "family", "3": "trending"}.get(choice, "lofi")

    if args.channel == "lofi":
        run_lofi()
    elif args.channel == "family":
        run_family()
    elif args.channel == "trending":
        run_trending()


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
