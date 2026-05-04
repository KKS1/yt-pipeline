"""
FFmpeg Video Assembly Pipeline
Assembles finished YouTube videos from:
  - Narration audio (MP3 from ElevenLabs)
  - Stock video clips (MP4 from Pexels)
  - Background music (MP3)
  - Captions (SRT from Whisper)
  - Intro/outro bumpers
  - Thumbnail image

Requirements:
  pip install requests pydub moviepy --break-system-packages
  ffmpeg must be installed: sudo apt install ffmpeg
"""

import os
import subprocess
import json
import math
import requests
from pathlib import Path


# ─────────────────────────────────────────────
# CONFIG
# ─────────────────────────────────────────────

PEXELS_API_KEY = os.environ.get("PEXELS_API_KEY", "")
ELEVENLABS_API_KEY = os.environ.get("ELEVENLABS_API_KEY", "")
ELEVENLABS_VOICE_ID = os.environ.get("ELEVENLABS_VOICE_ID", "21m00Tcm4TlvDq8ikWAM")  # Rachel

# Always resolve relative to project root (yt-pipeline/), not cwd
PROJECT_ROOT = Path(__file__).parent.parent
OUTPUT_DIR   = PROJECT_ROOT / "output"
ASSETS_DIR   = PROJECT_ROOT / "assets"
TEMP_DIR     = PROJECT_ROOT / "temp"

for d in [OUTPUT_DIR, ASSETS_DIR, TEMP_DIR]:
    d.mkdir(exist_ok=True)

FFMPEG = os.environ.get("FFMPEG_CMD", "ffmpeg")

# Video settings
VIDEO_WIDTH = 1920
VIDEO_HEIGHT = 1080
VIDEO_FPS = 30
BG_MUSIC_VOLUME = 0.08   # Keep background music subtle under narration
NARRATION_VOLUME = 1.0


# ─────────────────────────────────────────────
# 1. TEXT-TO-SPEECH (ElevenLabs)
# ─────────────────────────────────────────────

def generate_voiceover(script_text: str, output_path: str, voice_id: str = None) -> str:
    """Convert script text to MP3 using ElevenLabs API."""

    # Strip screenplay markers before sending to TTS
    clean_script = script_text
    for marker in ["[PAUSE]", "[EMPHASIS]"]:
        clean_script = clean_script.replace(marker, "")
    # Remove [VISUAL: ...] blocks entirely
    import re
    clean_script = re.sub(r'\[VISUAL:[^\]]+\]', '', clean_script)
    clean_script = ' '.join(clean_script.split())  # Normalize whitespace

    vid = voice_id or ELEVENLABS_VOICE_ID
    url = f"https://api.elevenlabs.io/v1/text-to-speech/{vid}"

    headers = {
        "Accept": "audio/mpeg",
        "Content-Type": "application/json",
        "xi-api-key": ELEVENLABS_API_KEY,
    }
    payload = {
        "text": clean_script,
        "model_id": "eleven_monolingual_v1",
        "voice_settings": {
            "stability": 0.5,
            "similarity_boost": 0.75,
            "style": 0.3,
            "use_speaker_boost": True,
        }
    }

    print(f"  Generating voiceover ({len(clean_script)} chars)...")
    response = requests.post(url, json=payload, headers=headers)
    response.raise_for_status()

    with open(output_path, "wb") as f:
        f.write(response.content)

    print(f"  Voiceover saved: {output_path}")
    return output_path


# ─────────────────────────────────────────────
# 2. GET AUDIO DURATION
# ─────────────────────────────────────────────

def get_audio_duration(audio_path: str) -> float:
    """Get duration of an audio file in seconds using ffprobe."""
    cmd = [
        "ffprobe", "-v", "quiet",
        "-print_format", "json",
        "-show_streams", audio_path
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    data = json.loads(result.stdout)
    for stream in data.get("streams", []):
        if "duration" in stream:
            return float(stream["duration"])
    # fallback: read container duration
    cmd2 = [
        "ffprobe", "-v", "quiet",
        "-print_format", "json",
        "-show_format", audio_path
    ]
    result2 = subprocess.run(cmd2, capture_output=True, text=True)
    fmt = json.loads(result2.stdout).get("format", {})
    if "duration" in fmt:
        return float(fmt["duration"])
    return 0.0


# ─────────────────────────────────────────────
# 3. FETCH STOCK VIDEOS (Pexels)
# ─────────────────────────────────────────────

def fetch_stock_videos(query: str, total_duration: float, output_dir: str) -> list[str]:
    """
    Download enough Pexels stock clips to cover total_duration seconds.
    Returns list of downloaded file paths.
    """
    headers = {"Authorization": PEXELS_API_KEY}
    downloaded = []
    accumulated = 0.0
    page = 1

    print(f"  Fetching stock videos for '{query}' (need {total_duration:.0f}s)...")

    Path(output_dir).mkdir(parents=True, exist_ok=True)

    while accumulated < total_duration:
        url = f"https://api.pexels.com/videos/search?query={query}&per_page=10&page={page}&orientation=landscape&size=medium"
        resp = requests.get(url, headers=headers)
        resp.raise_for_status()
        videos = resp.json().get("videos", [])

        if not videos:
            break

        for video in videos:
            if accumulated >= total_duration:
                break

            # Pick highest quality file under 1080p
            best_file = None
            for vf in sorted(video["video_files"], key=lambda x: x.get("width", 0), reverse=True):
                if vf.get("width", 0) <= 1920 and vf.get("file_type") == "video/mp4":
                    best_file = vf
                    break

            if not best_file:
                continue

            filename = Path(output_dir) / f"clip_{len(downloaded):03d}.mp4"
            r = requests.get(best_file["link"], stream=True)
            with open(filename, "wb") as f:
                for chunk in r.iter_content(chunk_size=8192):
                    f.write(chunk)

            duration = float(video.get("duration", 10))
            accumulated += duration
            downloaded.append(str(filename))
            print(f"    Downloaded clip {len(downloaded)}: {duration:.0f}s (total: {accumulated:.0f}s)")

        page += 1
        if page > 5:
            break

    print(f"  Downloaded {len(downloaded)} clips, {accumulated:.0f}s total")
    return downloaded


# ─────────────────────────────────────────────
# 4. GENERATE CAPTIONS (Whisper via subprocess)
# ─────────────────────────────────────────────

def generate_captions(audio_path: str, output_srt: str) -> str:
    """
    Generate SRT captions using OpenAI Whisper (local, free).
    Install: pip install openai-whisper --break-system-packages
    """
    print(f"  Generating captions with Whisper...")
    cmd = [
        "whisper", audio_path,
        "--model", "base",
        "--output_format", "srt",
        "--output_dir", str(Path(output_srt).parent),
        "--language", "en"
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"  Whisper warning: {result.stderr[:200]}")

    # Whisper names the SRT after the input file
    generated_srt = Path(audio_path).with_suffix(".srt")
    if generated_srt.exists() and str(generated_srt) != output_srt:
        generated_srt.rename(output_srt)

    print(f"  Captions saved: {output_srt}")
    return output_srt


# ─────────────────────────────────────────────
# 5. ASSEMBLE VIDEO — TRENDING/FAMILY CHANNELS
# ─────────────────────────────────────────────

def assemble_narrated_video(
    narration_audio: str,
    stock_clips: list[str],
    background_music: str,
    captions_srt: str,
    output_path: str,
    title: str = "",
) -> str:
    """
    Full FFmpeg assembly pipeline for a narrated video.
    
    Flow:
      1. Normalize stock clips to 1080p 30fps
      2. Concatenate clips to match narration length
      3. Mix narration + background music
      4. Burn in captions
      5. Add subtle intro fade
    """

    narration_duration = get_audio_duration(narration_audio)
    print(f"\nAssembling: '{title}'")
    print(f"  Narration duration: {narration_duration:.1f}s ({narration_duration/60:.1f} min)")

    # Step 1: Normalize each stock clip to 1080p 30fps
    normalized_clips = []
    for i, clip in enumerate(stock_clips):
        norm_path = str(TEMP_DIR / f"norm_{i:03d}.mp4")
        cmd = [
            FFMPEG, "-y", "-i", clip,
            "-vf", f"scale={VIDEO_WIDTH}:{VIDEO_HEIGHT}:force_original_aspect_ratio=decrease,"
                   f"pad={VIDEO_WIDTH}:{VIDEO_HEIGHT}:(ow-iw)/2:(oh-ih)/2:black,"
                   f"fps={VIDEO_FPS}",
            "-c:v", "libx264", "-preset", "fast", "-crf", "23",
            "-an",  # Drop original audio from stock clips
            norm_path
        ]
        subprocess.run(cmd, capture_output=True, check=True)
        normalized_clips.append(norm_path)

    # Step 2: Concatenate clips, looping if needed to match narration length
    concat_path = str(TEMP_DIR / "concat.mp4")
    total_clip_duration = sum(get_audio_duration(c) for c in normalized_clips)

    if total_clip_duration < narration_duration:
        # Need to loop — repeat the clip list
        loops_needed = math.ceil(narration_duration / total_clip_duration)
        normalized_clips = normalized_clips * loops_needed

    # Write FFmpeg concat list
    list_path = str(TEMP_DIR / "clips.txt")
    with open(list_path, "w") as f:
        for clip in normalized_clips:
            f.write(f"file '{os.path.abspath(clip)}'\n")

    # Concatenate and trim to exact narration length
    cmd = [
        FFMPEG, "-y",
        "-f", "concat", "-safe", "0", "-i", list_path,
        "-t", str(narration_duration),
        "-c:v", "libx264", "-preset", "fast", "-crf", "23",
        "-an",
        concat_path
    ]
    subprocess.run(cmd, capture_output=True, check=True)
    print(f"  Video track ready: {narration_duration:.1f}s")

    # Step 3: Mix narration + background music
    mixed_audio_path = str(TEMP_DIR / "mixed_audio.mp3")
    cmd = [
        FFMPEG, "-y",
        "-i", narration_audio,
        "-stream_loop", "-1", "-i", background_music,  # Loop BG music
        "-filter_complex",
        f"[0:a]volume={NARRATION_VOLUME}[narr];"
        f"[1:a]volume={BG_MUSIC_VOLUME}[bg];"
        f"[narr][bg]amix=inputs=2:duration=first:dropout_transition=3[out]",
        "-map", "[out]",
        "-t", str(narration_duration),
        "-c:a", "aac", "-b:a", "192k",
        mixed_audio_path
    ]
    subprocess.run(cmd, capture_output=True, check=True)
    print(f"  Audio mixed (narration + background music)")

    # Step 4: Combine video + audio + burn captions
    # Caption style: white text, black outline, bottom center
    caption_style = (
        "FontName=Arial,"
        "FontSize=22,"
        "PrimaryColour=&H00FFFFFF,"   # White text
        "OutlineColour=&H00000000,"   # Black outline
        "BackColour=&H80000000,"      # Semi-transparent background
        "Bold=1,"
        "Outline=2,"
        "Shadow=1,"
        "MarginV=40"
    )

    # Check if captions exist
    has_captions = captions_srt and Path(captions_srt).exists()
    vf_filter = f"subtitles={captions_srt}:force_style='{caption_style}'" if has_captions else "null"

    cmd = [
        FFMPEG, "-y",
        "-i", concat_path,
        "-i", mixed_audio_path,
        "-vf", vf_filter,
        "-map", "0:v", "-map", "1:a",
        # Add fade in at start, fade out at end
        "-vf", f"fade=t=in:st=0:d=1,fade=t=out:st={narration_duration-2}:d=2,"
               + (f"subtitles={captions_srt}:force_style='{caption_style}'" if has_captions else ""),
        "-c:v", "libx264", "-preset", "medium", "-crf", "20",
        "-c:a", "copy",
        "-movflags", "+faststart",  # Web-optimized
        "-metadata", f"title={title}",
        output_path
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        # Fallback without captions if subtitle burn fails
        print(f"  Caption burn failed, assembling without captions...")
        cmd = [
            FFMPEG, "-y",
            "-i", concat_path, "-i", mixed_audio_path,
            "-map", "0:v", "-map", "1:a",
            "-vf", f"fade=t=in:st=0:d=1,fade=t=out:st={narration_duration-2}:d=2",
            "-c:v", "libx264", "-preset", "medium", "-crf", "20",
            "-c:a", "copy", "-movflags", "+faststart",
            output_path
        ]
        subprocess.run(cmd, capture_output=True, check=True)

    size_mb = Path(output_path).stat().st_size / 1024 / 1024
    print(f"  ✓ Video assembled: {output_path} ({size_mb:.1f} MB)")
    return output_path


# ─────────────────────────────────────────────
# 6. ASSEMBLE LOFI VIDEO
# ─────────────────────────────────────────────

def assemble_lofi_video(
    music_tracks: list[str],
    loop_visual: str,          # A short MP4 loop (e.g. animated lofi GIF converted to MP4)
    output_path: str,
    duration_hours: int = 3,
    title: str = "",
    tracklist: list[dict] = None,
) -> str:
    """
    Assemble a multi-hour lofi video.
    
    music_tracks: list of MP3 files (from Suno/Udio)
    loop_visual: short MP4 that will be looped for the full duration
    """

    target_seconds = duration_hours * 3600
    print(f"\nAssembling lofi video: {duration_hours}h = {target_seconds}s")

    # Step 1: Concatenate music tracks
    concat_music_path = str(TEMP_DIR / "lofi_music.mp3")
    list_path = str(TEMP_DIR / "music_list.txt")

    # Calculate how many loops of tracks needed
    total_music_duration = sum(get_audio_duration(t) for t in music_tracks)
    loops = math.ceil(target_seconds / total_music_duration)
    looped_tracks = music_tracks * loops

    with open(list_path, "w") as f:
        for track in looped_tracks:
            f.write(f"file '{os.path.abspath(track)}'\n")

    cmd = [
        FFMPEG, "-y",
        "-f", "concat", "-safe", "0", "-i", list_path,
        "-t", str(target_seconds),
        "-c:a", "libmp3lame", "-b:a", "192k",
        concat_music_path
    ]
    subprocess.run(cmd, capture_output=True, check=True)
    print(f"  Music concatenated: {target_seconds}s")

    # Step 2: Loop the visual for full duration
    looped_video_path = str(TEMP_DIR / "lofi_visual.mp4")
    cmd = [
        FFMPEG, "-y",
        "-stream_loop", "-1", "-i", loop_visual,
        "-t", str(target_seconds),
        "-vf", f"scale={VIDEO_WIDTH}:{VIDEO_HEIGHT}:force_original_aspect_ratio=decrease,"
               f"pad={VIDEO_WIDTH}:{VIDEO_HEIGHT}:(ow-iw)/2:(oh-ih)/2:black,"
               f"fps={VIDEO_FPS}",
        "-c:v", "libx264", "-preset", "fast", "-crf", "23",
        "-an",
        looped_video_path
    ]
    subprocess.run(cmd, capture_output=True, check=True)
    print(f"  Visual looped: {target_seconds}s")

    # Step 3: Add chapter markers (timestamps) as overlaid text if tracklist provided
    # For simplicity, burn track names as subtitles every 30 minutes
    chapters_filter = ""
    if tracklist:
        srt_path = str(TEMP_DIR / "chapters.srt")
        with open(srt_path, "w") as f:
            for i, track in enumerate(tracklist):
                # Parse timestamp "00:30" → seconds
                parts = track["timestamp"].split(":")
                start_s = int(parts[0]) * 3600 + int(parts[1]) * 60
                end_s = start_s + 10  # Show track name for 10 seconds
                if end_s > target_seconds:
                    break
                f.write(f"{i+1}\n")
                f.write(f"{_seconds_to_srt(start_s)} --> {_seconds_to_srt(end_s)}\n")
                f.write(f"♪ {track['name']}\n\n")

        chapters_filter = f"subtitles={srt_path}:force_style='FontSize=16,PrimaryColour=&H80FFFFFF,MarginV=20'"

    # Step 4: Combine
    vf = chapters_filter if chapters_filter else "null"
    cmd = [
        FFMPEG, "-y",
        "-i", looped_video_path,
        "-i", concat_music_path,
        "-map", "0:v", "-map", "1:a",
        "-vf", vf,
        "-c:v", "libx264", "-preset", "slow", "-crf", "22",
        "-c:a", "aac", "-b:a", "192k",
        "-movflags", "+faststart",
        "-metadata", f"title={title}",
        output_path
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        # Fallback without chapter subtitles
        cmd[-10] = "null"
        subprocess.run(cmd, capture_output=True, check=True)

    size_gb = Path(output_path).stat().st_size / 1024 / 1024 / 1024
    print(f"  ✓ Lofi video assembled: {output_path} ({size_gb:.2f} GB)")
    return output_path


def _seconds_to_srt(s: int) -> str:
    h = s // 3600
    m = (s % 3600) // 60
    sec = s % 60
    return f"{h:02d}:{m:02d}:{sec:02d},000"


# ─────────────────────────────────────────────
# 7. GENERATE THUMBNAIL
# ─────────────────────────────────────────────

def create_thumbnail(
    background_image: str,
    title_text: str,
    output_path: str,
    style: str = "trending"  # "trending", "family", "lofi"
) -> str:
    """
    Create a YouTube thumbnail using FFmpeg.
    Background image + bold overlaid text.
    For best results use a 1280x720 background image.
    """

    styles = {
        "trending": {
            "font_color": "white",
            "box_color": "0x000000@0.6",
            "font_size": 72,
        },
        "family": {
            "font_color": "yellow",
            "box_color": "0x1a1a2e@0.7",
            "font_size": 68,
        },
        "lofi": {
            "font_color": "0xE8D5B7",
            "box_color": "0x1a1025@0.75",
            "font_size": 56,
        },
    }

    s = styles.get(style, styles["trending"])
    wrapped_title = title_text[:50]  # Truncate if too long

    cmd = [
        FFMPEG, "-y",
        "-i", background_image,
        "-vf",
        f"scale=1280:720,"
        f"drawbox=x=0:y=ih-200:w=iw:h=200:color={s['box_color']}:t=fill,"
        f"drawtext=text='{wrapped_title}':"
        f"fontcolor={s['font_color']}:"
        f"fontsize={s['font_size']}:"
        f"x=(w-text_w)/2:y=h-140:"
        f"fontfile=/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf:"
        f"shadowcolor=black:shadowx=3:shadowy=3",
        "-frames:v", "1",
        output_path
    ]
    subprocess.run(cmd, capture_output=True, check=True)
    print(f"  ✓ Thumbnail: {output_path}")
    return output_path


# ─────────────────────────────────────────────
# 8. CLEANUP TEMP FILES
# ─────────────────────────────────────────────

def cleanup_temp():
    """Remove all temp files after assembly."""
    import shutil
    if TEMP_DIR.exists():
        shutil.rmtree(TEMP_DIR)
        TEMP_DIR.mkdir()
    print("  Temp files cleaned.")


# ─────────────────────────────────────────────
# FULL PIPELINE RUNNER (example)
# ─────────────────────────────────────────────

def run_full_pipeline(script_data: dict, channel_type: str, bg_music_path: str):
    """
    End-to-end: script_data → finished MP4 ready for upload.
    script_data is the JSON output from claude_prompts.py
    """
    slug = script_data["title_options"][0][:40].replace(" ", "_").lower()
    slug = "".join(c for c in slug if c.isalnum() or c == "_")

    print(f"\n{'='*50}")
    print(f"Pipeline: {channel_type.upper()} | {slug}")
    print(f"{'='*50}")

    # 1. Generate voiceover
    narration_path = str(TEMP_DIR / f"{slug}_narration.mp3")
    generate_voiceover(script_data["script"], narration_path)

    # 2. Get duration, fetch stock video
    duration = get_audio_duration(narration_path)
    clips = fetch_stock_videos(
        query=script_data.get("keywords", ["nature"])[0],
        total_duration=duration + 30,  # Buffer
        output_dir=str(TEMP_DIR)
    )

    # 3. Generate captions
    srt_path = str(TEMP_DIR / f"{slug}.srt")
    try:
        generate_captions(narration_path, srt_path)
    except Exception as e:
        print(f"  Captions skipped: {e}")
        srt_path = None

    # 4. Assemble video
    output_video = str(OUTPUT_DIR / f"{slug}.mp4")
    assemble_narrated_video(
        narration_audio=narration_path,
        stock_clips=clips,
        background_music=bg_music_path,
        captions_srt=srt_path,
        output_path=output_video,
        title=script_data["title_options"][0],
    )

    # 5. Cleanup
    cleanup_temp()

    return {
        "video_path": output_video,
        "title": script_data["title_options"][0],
        "description": script_data["description"],
        "tags": script_data["tags"],
        "thumbnail_text": script_data.get("thumbnail_text", ""),
    }


if __name__ == "__main__":
    print("FFmpeg assembly pipeline loaded.")
    print("Run run_full_pipeline(script_data, channel_type, bg_music) to test.")
