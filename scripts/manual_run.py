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


# ─────────────────────────────────────────────
# LOFI PIPELINE (fully free)
# ─────────────────────────────────────────────

def run_lofi():
    print("\n" + "="*50)
    print("LOFI MUSIC CHANNEL — fully free pipeline")
    print("="*50)

    title = prompt_input("Video title", "Lofi Study Music — Rainy Day Café ☕ 3 Hours")
    description = prompt_multiline("Paste your video description")
    tags_raw = prompt_input("Tags (comma-separated)", "lofi hip hop,study music,focus music,chill beats,lofi beats")
    tags = [t.strip() for t in tags_raw.split(",")]
    duration_hours = int(prompt_input("Duration in hours", "3"))

    # Check assets
    lofi_dir = ASSETS_DIR / "lofi"
    music_files = sorted(lofi_dir.glob("*.mp3"))
    if not music_files:
        print(f"\nNo MP3 files found in {lofi_dir}")
        print("Download lofi tracks from suno.ai (free) and place them there.")
        print("Then re-run this script.")
        sys.exit(1)

    visual_path = ASSETS_DIR / "lofi_loop.mp4"
    if not visual_path.exists():
        print(f"\nNo lofi_loop.mp4 found in {ASSETS_DIR}")
        print("Download a free lofi animation from pixabay.com/videos")
        print("Save it as assets/lofi_loop.mp4 and re-run.")
        sys.exit(1)

    print(f"\nFound {len(music_files)} music tracks")
    print(f"Visual loop: {visual_path}")

    out_slug = slug(title)
    out_path = str(OUTPUT_DIR / f"{out_slug}.mp4")

    # Assemble
    from ffmpeg_assembler import assemble_lofi_video
    assemble_lofi_video(
        music_tracks=[str(f) for f in music_files],
        loop_visual=str(visual_path),
        output_path=out_path,
        duration_hours=duration_hours,
        title=title,
    )

    # Upload
    _upload_video(out_path, title, description, tags, channel="lofi")


# ─────────────────────────────────────────────
# FAMILY PIPELINE (free with local TTS)
# ─────────────────────────────────────────────

def run_family():
    print("\n" + "="*50)
    print("FAMILY-FRIENDLY CHANNEL — free with local TTS")
    print("="*50)
    print("\nTip: Go to claude.ai and ask:")
    print('  "Write a family-friendly This or That YouTube script about animals"')
    print("Then paste the script below.\n")

    title   = prompt_input("Video title", "This or That? Animals Edition — Family Fun Quiz!")
    script  = prompt_multiline("Paste your script here")
    desc    = prompt_multiline("Paste your description")
    tags_r  = prompt_input("Tags", "this or that,family quiz,kids trivia,fun for kids,family friendly")
    tags    = [t.strip() for t in tags_r.split(",")]
    keyword = prompt_input("Keyword for stock video search", "animals nature")

    out_slug   = slug(title)
    audio_path = str(OUTPUT_DIR / f"{out_slug}_voice.mp3")
    out_path   = str(OUTPUT_DIR / f"{out_slug}.mp4")

    # Generate free voiceover
    print("\nGenerating voiceover (free local TTS)...")
    from free_tts import generate_tts, clean_script
    generate_tts(clean_script(script), audio_path)

    # Fetch stock video + assemble
    bg_music = str(ASSETS_DIR / "background_music.mp3")
    if not Path(bg_music).exists():
        print(f"\nNo background_music.mp3 in assets/")
        print("Download a free track from pixabay.com/music and save it there.")
        print("Or press Enter to continue without background music.")
        input()
        bg_music = None

    from ffmpeg_assembler import (
        get_audio_duration, fetch_stock_videos,
        generate_captions, assemble_narrated_video, cleanup_temp
    )

    duration    = get_audio_duration(audio_path)
    clips       = fetch_stock_videos(keyword, duration + 30, str(OUTPUT_DIR / "temp"))
    srt_path    = str(OUTPUT_DIR / f"{out_slug}.srt")

    try:
        generate_captions(audio_path, srt_path)
    except Exception as e:
        print(f"  Captions skipped: {e}")
        srt_path = None

    assemble_narrated_video(
        narration_audio=audio_path,
        stock_clips=clips,
        background_music=bg_music or audio_path,
        captions_srt=srt_path,
        output_path=out_path,
        title=title,
    )
    cleanup_temp()

    _upload_video(out_path, title, desc, tags, channel="family")


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
    audio_path = str(OUTPUT_DIR / f"{out_slug}_voice.mp3")
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
        background_music=bg_music or audio_path,
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


if __name__ == "__main__":
    main()
