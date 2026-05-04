"""
Family Channel Video Assembler — card-based format.
Builds "This or That" style videos with:
  - Animated question cards
  - Per-question voiceover (Kokoro af_sarah)
  - Animal images from Pexels matched per question
  - Countdown beeps (FFmpeg generated, no sound files needed)
  - Fun fact cards
  - Intro + outro

Input: structured JSON script (see SCRIPT_FORMAT below)
Output: finished MP4

SCRIPT_FORMAT = {
    "title": "This or That? Animals Edition",
    "intro": "Hey welcome back! Today we are playing...",
    "questions": [
        {
            "number": 1,
            "question": "Which animal is bigger?",
            "option_a": "House Cat",
            "option_b": "Tiger",
            "answer": "Tiger",
            "explanation": "A tiger can weigh up to 660 pounds!",
            "image_keyword": "tiger"
        }
    ],
    "fun_facts": [
        {
            "after_question": 3,
            "text": "A group of flamingos is called a flamboyance!"
        }
    ],
    "outro": "Thanks for watching, smash that like button!"
}
"""

import os
import json
import math
import subprocess
import tempfile
import requests
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
OUTPUT_DIR   = PROJECT_ROOT / "output"
TEMP_DIR     = PROJECT_ROOT / "output" / "family_temp"
ASSETS_DIR   = PROJECT_ROOT / "assets"

for d in [OUTPUT_DIR, TEMP_DIR]:
    d.mkdir(exist_ok=True)

FFMPEG = os.environ.get("FFMPEG_CMD", "ffmpeg")

# Video settings
WIDTH        = 1920
HEIGHT       = 1080
FPS          = 30
FONT         = "Arial"

# Colors (FFmpeg drawtext hex)
COLOR_BG         = "1a1a2e"   # Deep navy
COLOR_CARD       = "16213e"   # Slightly lighter navy
COLOR_ACCENT     = "e94560"   # Red/pink accent
COLOR_TEXT       = "ffffff"   # White
COLOR_OPTION_A   = "0f3460"   # Blue
COLOR_OPTION_B   = "533483"   # Purple
COLOR_ANSWER     = "2ecc71"   # Green
COLOR_FUNFACT    = "f39c12"   # Amber

PEXELS_API_KEY = os.environ.get("PEXELS_API_KEY", "")


# ─────────────────────────────────────────────
# AUDIO HELPERS
# ─────────────────────────────────────────────

def get_duration(path: str) -> float:
    """Get audio/video duration in seconds via ffprobe."""
    cmd = [
        "ffprobe", "-v", "quiet",
        "-print_format", "json",
        "-show_format", path
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    fmt = json.loads(result.stdout).get("format", {})
    return float(fmt.get("duration", 0))


def make_beep(output_path: str, freq: int = 880, duration: float = 0.15, volume: float = 0.3):
    """Generate a single beep tone using FFmpeg."""
    cmd = [
        FFMPEG, "-y",
        "-f", "lavfi",
        "-i", f"sine=frequency={freq}:duration={duration}",
        "-af", f"volume={volume}",
        output_path, "-loglevel", "quiet"
    ]
    subprocess.run(cmd, check=True)


def make_countdown_audio(output_path: str):
    """Generate 3 beeps for countdown (3..2..1)."""
    beeps = []
    for i in range(3):
        bp = str(TEMP_DIR / f"beep_{i}.wav")
        make_beep(bp, freq=660, duration=0.2)
        beeps.append(bp)

    # Space beeps 1 second apart with silence between
    silence = str(TEMP_DIR / "silence_short.wav")
    cmd = [
        FFMPEG, "-y", "-f", "lavfi",
        "-i", "anullsrc=r=22050:cl=mono",
        "-t", "0.8", silence, "-loglevel", "quiet"
    ]
    subprocess.run(cmd, check=True)

    # Interleave beep + silence x3
    list_path = str(TEMP_DIR / "countdown_list.txt")
    with open(list_path, "w") as f:
        for bp in beeps:
            f.write(f"file '{os.path.abspath(bp)}'\n")
            f.write(f"file '{os.path.abspath(silence)}'\n")

    cmd = [
        FFMPEG, "-y",
        "-f", "concat", "-safe", "0", "-i", list_path,
        "-c:a", "aac", output_path, "-loglevel", "quiet"
    ]
    subprocess.run(cmd, check=True)


def make_ding(output_path: str):
    """Generate a pleasant ding for correct answer reveal."""
    cmd = [
        FFMPEG, "-y",
        "-f", "lavfi",
        "-i", "sine=frequency=1046:duration=0.6",
        "-af", "volume=0.4,afade=t=out:st=0.3:d=0.3",
        output_path, "-loglevel", "quiet"
    ]
    subprocess.run(cmd, check=True)


def concat_audio(files: list, output_path: str, silence_between: float = 0.3):
    """Concatenate audio files with optional silence between them."""
    inputs = []

    # Make silence clip
    silence_path = None
    if silence_between > 0 and len(files) > 1:
        silence_path = str(TEMP_DIR / "concat_silence.wav")
        cmd = [
            FFMPEG, "-y", "-f", "lavfi",
            "-i", f"anullsrc=r=44100:cl=stereo",
            "-t", str(silence_between),
            silence_path, "-loglevel", "quiet"
        ]
        subprocess.run(cmd, check=True)

    for i, fp in enumerate(files):
        inputs.append(fp)
        if silence_path and i < len(files) - 1:
            inputs.append(silence_path)

    cmd = [
        FFMPEG, "-y",
        *[arg for fp in inputs for arg in ("-i", fp)],
        "-filter_complex", f"concat=n={len(inputs)}:v=0:a=1[out]",
        "-map", "[out]",
        "-c:a", "aac", "-b:a", "192k",
        output_path, "-loglevel", "quiet"
    ]
    subprocess.run(cmd, check=True)


# ─────────────────────────────────────────────
# IMAGE HELPERS
# ─────────────────────────────────────────────

def fetch_animal_image(keyword: str, output_path: str) -> bool:
    """Fetch a single animal image from Pexels. Returns True if successful."""
    if not PEXELS_API_KEY:
        return False
    try:
        headers = {"Authorization": PEXELS_API_KEY}
        url = f"https://api.pexels.com/v1/search?query={keyword}&per_page=3&orientation=landscape"
        resp = requests.get(url, headers=headers, timeout=10)
        resp.raise_for_status()
        photos = resp.json().get("photos", [])
        if not photos:
            return False
        # Pick first photo, landscape large size
        photo_url = photos[0]["src"]["large2x"]
        img = requests.get(photo_url, timeout=15)
        with open(output_path, "wb") as f:
            f.write(img.content)
        return True
    except Exception as e:
        print(f"  Image fetch failed for '{keyword}': {e}")
        return False


# ─────────────────────────────────────────────
# CARD GENERATORS (FFmpeg lavfi + drawtext)
# ─────────────────────────────────────────────

def wrap_text(text: str, max_chars: int = 35) -> str:
    """Wrap text for FFmpeg drawtext — use \\n as line break."""
    words = text.split()
    lines, current = [], ""
    for word in words:
        if len(current) + len(word) + 1 <= max_chars:
            current += (" " if current else "") + word
        else:
            if current:
                lines.append(current)
            current = word
    if current:
        lines.append(current)
    return "\\n".join(lines)


def make_color_bg(output_path: str, duration: float, color: str = COLOR_BG):
    """Generate a solid color background video."""
    cmd = [
        FFMPEG, "-y",
        "-f", "lavfi",
        "-i", f"color=c=0x{color}:size={WIDTH}x{HEIGHT}:rate={FPS}",
        "-t", str(duration),
        "-c:v", "libx264", "-preset", "fast", "-crf", "23",
        output_path, "-loglevel", "quiet"
    ]
    subprocess.run(cmd, check=True)


def make_question_card(
    question: str,
    option_a: str,
    option_b: str,
    number: int,
    duration: float,
    output_path: str,
):
    """
    Build a This or That question card:
    - Top: question number + THIS OR THAT header
    - Middle: question text
    - Bottom: Option A (left) vs Option B (right)
    """
    q_wrapped = wrap_text(question, 40)
    a_wrapped = wrap_text(option_a, 18)
    b_wrapped = wrap_text(option_b, 18)

    vf = (

        # Top accent bar
        f"drawbox=x=0:y=0:w={WIDTH}:h=12:color=0x{COLOR_ACCENT}@1:t=fill,"

        # Question number pill
        f"drawbox=x=80:y=60:w=180:h=60:color=0x{COLOR_ACCENT}@1:t=fill,"
        f"drawtext=text='Question {number}':fontfile=/System/Library/Fonts/HelveticaNeue.ttc:"
        f"fontsize=28:fontcolor=0x{COLOR_TEXT}:x=90:y=78,"

        # THIS OR THAT header
        f"drawtext=text='THIS  OR  THAT':fontfile=/System/Library/Fonts/HelveticaNeue.ttc:"
        f"fontsize=52:fontcolor=0x{COLOR_ACCENT}:x=(w-text_w)/2:y=55,"

        # Question text
        f"drawtext=text='{q_wrapped}':fontfile=/System/Library/Fonts/HelveticaNeue.ttc:"
        f"fontsize=58:fontcolor=0x{COLOR_TEXT}:x=(w-text_w)/2:y=220:line_spacing=12,"

        # Option A box
        f"drawbox=x=80:y=520:w=820:h=280:color=0x{COLOR_OPTION_A}@1:t=fill,"
        f"drawbox=x=80:y=520:w=820:h=280:color=0x{COLOR_TEXT}@0.15:t=4,"
        f"drawtext=text='A':fontfile=/System/Library/Fonts/HelveticaNeue.ttc:"
        f"fontsize=36:fontcolor=0x{COLOR_ACCENT}:x=130:y=540,"
        f"drawtext=text='{a_wrapped}':fontfile=/System/Library/Fonts/HelveticaNeue.ttc:"
        f"fontsize=52:fontcolor=0x{COLOR_TEXT}:x=490-text_w/2:y=610:line_spacing=10,"

        # VS divider
        f"drawtext=text='VS':fontfile=/System/Library/Fonts/HelveticaNeue.ttc:"
        f"fontsize=48:fontcolor=0x{COLOR_ACCENT}:x=(w-text_w)/2:y=630,"

        # Option B box
        f"drawbox=x=1020:y=520:w=820:h=280:color=0x{COLOR_OPTION_B}@1:t=fill,"
        f"drawbox=x=1020:y=520:w=820:h=280:color=0x{COLOR_TEXT}@0.15:t=4,"
        f"drawtext=text='B':fontfile=/System/Library/Fonts/HelveticaNeue.ttc:"
        f"fontsize=36:fontcolor=0x{COLOR_ACCENT}:x=1070:y=540,"
        f"drawtext=text='{b_wrapped}':fontfile=/System/Library/Fonts/HelveticaNeue.ttc:"
        f"fontsize=52:fontcolor=0x{COLOR_TEXT}:x=1430-text_w/2:y=610:line_spacing=10,"

        # Bottom bar
        f"drawbox=x=0:y={HEIGHT-8}:w={WIDTH}:h=8:color=0x{COLOR_ACCENT}@1:t=fill"
    )

    cmd = [
        FFMPEG, "-y",
        "-f", "lavfi", "-i", f"color=c=0x{COLOR_BG}:size={WIDTH}x{HEIGHT}:rate={FPS}",
        "-t", str(duration),
        "-vf", vf,
        "-c:v", "libx264", "-preset", "fast", "-crf", "23",
        output_path, "-loglevel", "quiet"
    ]
    subprocess.run(cmd, check=True)


def make_answer_card(
    answer: str,
    explanation: str,
    image_path: str,
    duration: float,
    output_path: str,
):
    """
    Answer reveal card:
    - Animal image as background (blurred)
    - Answer overlay
    - Explanation text
    """
    explanation_wrapped = wrap_text(explanation, 55)

    if image_path and Path(image_path).exists():
        # Use animal image as blurred background
        vf = (
            f"scale={WIDTH}:{HEIGHT}:force_original_aspect_ratio=increase,"
            f"crop={WIDTH}:{HEIGHT},"
            f"gblur=sigma=3,"

            # Dark overlay
            f"drawbox=x=0:y=0:w={WIDTH}:h={HEIGHT}:color=0x000000@0.55:t=fill,"

            # Answer banner
            f"drawbox=x=0:y=380:w={WIDTH}:h=160:color=0x{COLOR_ANSWER}@0.9:t=fill,"
            f"drawtext=text='ANSWER\: {answer}':fontfile=/System/Library/Fonts/HelveticaNeue.ttc:"
            f"fontsize=72:fontcolor=0x{COLOR_TEXT}:x=(w-text_w)/2:y=420,"

            # Explanation
            f"drawtext=text='{explanation_wrapped}':fontfile=/System/Library/Fonts/HelveticaNeue.ttc:"
            f"fontsize=38:fontcolor=0x{COLOR_TEXT}:x=(w-text_w)/2:y=600:line_spacing=10"
        )
        cmd = [
            FFMPEG, "-y",
            "-loop", "1", "-i", image_path,
            "-t", str(duration),
            "-vf", vf,
            "-c:v", "libx264", "-preset", "fast", "-crf", "23",
            output_path, "-loglevel", "quiet"
        ]
    else:
        # Fallback: solid color card
        vf = (
            f"drawbox=x=0:y=380:w={WIDTH}:h=160:color=0x{COLOR_ANSWER}@0.9:t=fill,"
            f"drawtext=text='ANSWER\: {answer}':fontfile=/System/Library/Fonts/HelveticaNeue.ttc:"
            f"fontsize=72:fontcolor=0x{COLOR_TEXT}:x=(w-text_w)/2:y=420,"
            f"drawtext=text='{explanation_wrapped}':fontfile=/System/Library/Fonts/HelveticaNeue.ttc:"
            f"fontsize=38:fontcolor=0x{COLOR_TEXT}:x=(w-text_w)/2:y=600:line_spacing=10"
        )
        cmd = [
            FFMPEG, "-y",
            "-f", "lavfi", "-i", f"color=c=0x{COLOR_BG}:size={WIDTH}x{HEIGHT}:rate={FPS}",
            "-t", str(duration),
            "-vf", vf,
            "-c:v", "libx264", "-preset", "fast", "-crf", "23",
            output_path, "-loglevel", "quiet"
        ]
    subprocess.run(cmd, check=True)


def make_funfact_card(text: str, duration: float, output_path: str):
    """Fun fact interstitial card."""
    wrapped = wrap_text(text, 50)
    vf = (
        f"drawbox=x=0:y=0:w={WIDTH}:h=12:color=0x{COLOR_FUNFACT}@1:t=fill,"
        f"drawbox=x=0:y={HEIGHT-8}:w={WIDTH}:h=8:color=0x{COLOR_FUNFACT}@1:t=fill,"
        f"drawtext=text='FUN FACT!':fontfile=/System/Library/Fonts/HelveticaNeue.ttc:"
        f"fontsize=72:fontcolor=0x{COLOR_FUNFACT}:x=(w-text_w)/2:y=200,"
        f"drawtext=text='{wrapped}':fontfile=/System/Library/Fonts/HelveticaNeue.ttc:"
        f"fontsize=44:fontcolor=0x{COLOR_TEXT}:x=(w-text_w)/2:y=370:line_spacing=14"
    )
    cmd = [
        FFMPEG, "-y",
        "-f", "lavfi", "-i", f"color=c=0x{COLOR_BG}:size={WIDTH}x{HEIGHT}:rate={FPS}",
        "-t", str(duration),
        "-vf", vf,
        "-c:v", "libx264", "-preset", "fast", "-crf", "23",
        output_path, "-loglevel", "quiet"
    ]
    subprocess.run(cmd, check=True)


def make_title_card(title: str, subtitle: str, duration: float, output_path: str):
    """Intro/outro title card."""
    vf = (
        f"drawbox=x=0:y=0:w={WIDTH}:h=12:color=0x{COLOR_ACCENT}@1:t=fill,"
        f"drawbox=x=0:y={HEIGHT-8}:w={WIDTH}:h=8:color=0x{COLOR_ACCENT}@1:t=fill,"
        f"drawtext=text='{title}':fontfile=/System/Library/Fonts/HelveticaNeue.ttc:"
        f"fontsize=82:fontcolor=0x{COLOR_TEXT}:x=(w-text_w)/2:y=380,"
        f"drawtext=text='{subtitle}':fontfile=/System/Library/Fonts/HelveticaNeue.ttc:"
        f"fontsize=42:fontcolor=0x{COLOR_ACCENT}:x=(w-text_w)/2:y=500"
    )
    cmd = [
        FFMPEG, "-y",
        "-f", "lavfi", "-i", f"color=c=0x{COLOR_BG}:size={WIDTH}x{HEIGHT}:rate={FPS}",
        "-t", str(duration),
        "-vf", vf,
        "-c:v", "libx264", "-preset", "fast", "-crf", "23",
        output_path, "-loglevel", "quiet"
    ]
    subprocess.run(cmd, check=True)


# ─────────────────────────────────────────────
# MAIN ASSEMBLER
# ─────────────────────────────────────────────

def assemble_family_video(script: dict, output_path: str) -> str:
    """
    Full assembly pipeline for family This or That video.
    script: parsed JSON matching SCRIPT_FORMAT above.
    """
    import sys
    sys.path.insert(0, str(Path(__file__).parent))
    from kokoro_tts import synthesize

    print(f"\n{'='*50}")
    print(f"Family Assembler: {script['title']}")
    print(f"{'='*50}")

    video_segments = []
    audio_segments = []

    # Pre-generate sounds
    print("\nGenerating sound effects...")
    countdown_audio = str(TEMP_DIR / "countdown.aac")
    ding_audio      = str(TEMP_DIR / "ding.aac")
    make_countdown_audio(countdown_audio)
    make_ding(ding_audio)
    countdown_dur = get_duration(countdown_audio)
    ding_dur      = get_duration(ding_audio)

    # ── INTRO ──
    print("\nBuilding intro...")
    intro_audio = str(TEMP_DIR / "intro_voice.mp3")
    synthesize(script["intro"], intro_audio, voice="af_sarah", speed=1.1)
    intro_dur = get_duration(intro_audio) + 0.5

    intro_video = str(TEMP_DIR / "intro_card.mp4")
    make_title_card(
        title="THIS OR THAT?",
        subtitle="Animal Edition",
        duration=intro_dur,
        output_path=intro_video,
    )
    video_segments.append(intro_video)
    audio_segments.append(intro_audio)

    # ── QUESTIONS ──
    fun_facts = {ff["after_question"]: ff["text"] for ff in script.get("fun_facts", [])}

    for q in script["questions"]:
        n = q["number"]
        print(f"\nBuilding question {n}/{len(script['questions'])}: {q['question'][:40]}...")

        # 1. Question voiceover
        q_text = f"Question {n}. {q['question']} Is it... {q['option_a']}... or {q['option_b']}?"
        q_audio = str(TEMP_DIR / f"q{n}_question.mp3")
        synthesize(q_text, q_audio, voice="af_sarah", speed=1.05)
        q_dur = get_duration(q_audio)

        # 2. Question card (shown during question audio + countdown)
        total_q_dur = q_dur + countdown_dur + 0.5
        q_video = str(TEMP_DIR / f"q{n}_card.mp4")
        make_question_card(
            question=q["question"],
            option_a=q["option_a"],
            option_b=q["option_b"],
            number=n,
            duration=total_q_dur,
            output_path=q_video,
        )

        # Combine question audio + countdown
        q_combined_audio = str(TEMP_DIR / f"q{n}_combined.aac")
        concat_audio([q_audio, countdown_audio], q_combined_audio, silence_between=0.2)

        video_segments.append(q_video)
        audio_segments.append(q_combined_audio)

        # 3. Fetch animal image for answer card
        img_path = str(TEMP_DIR / f"q{n}_image.jpg")
        has_image = fetch_animal_image(q["image_keyword"], img_path)

        # 4. Answer voiceover
        a_text = f"The answer is... {q['answer']}! {q['explanation']}"
        a_audio = str(TEMP_DIR / f"q{n}_answer.mp3")
        synthesize(a_text, a_audio, voice="af_sarah", speed=1.05)
        a_dur = get_duration(a_audio)

        # 5. Answer card
        total_a_dur = ding_dur + a_dur + 0.5
        a_video = str(TEMP_DIR / f"q{n}_answer_card.mp4")
        make_answer_card(
            answer=q["answer"],
            explanation=q["explanation"],
            image_path=img_path if has_image else None,
            duration=total_a_dur,
            output_path=a_video,
        )

        # Combine ding + answer audio
        a_combined_audio = str(TEMP_DIR / f"q{n}_answer_combined.aac")
        concat_audio([ding_audio, a_audio], a_combined_audio, silence_between=0.1)

        video_segments.append(a_video)
        audio_segments.append(a_combined_audio)

        # 6. Fun fact after every 3rd question
        if n in fun_facts:
            print(f"  Adding fun fact after Q{n}...")
            ff_text = f"Fun fact! {fun_facts[n]}"
            ff_audio = str(TEMP_DIR / f"ff_{n}.mp3")
            synthesize(ff_text, ff_audio, voice="af_sarah", speed=1.0)
            ff_dur = get_duration(ff_audio) + 0.5

            ff_video = str(TEMP_DIR / f"ff_{n}_card.mp4")
            make_funfact_card(
                text=fun_facts[n],
                duration=ff_dur,
                output_path=ff_video,
            )
            video_segments.append(ff_video)
            audio_segments.append(ff_audio)

    # ── OUTRO ──
    print("\nBuilding outro...")
    outro_audio = str(TEMP_DIR / "outro_voice.mp3")
    synthesize(script["outro"], outro_audio, voice="af_sarah", speed=1.05)
    outro_dur = get_duration(outro_audio) + 0.5

    outro_video = str(TEMP_DIR / "outro_card.mp4")
    make_title_card(
        title="Thanks for watching!",
        subtitle="Like & Subscribe for more!",
        duration=outro_dur,
        output_path=outro_video,
    )
    video_segments.append(outro_video)
    audio_segments.append(outro_audio)

    # ── FINAL ASSEMBLY ──
    print(f"\nFinal assembly: {len(video_segments)} segments...")

    # Concat all video segments
    video_list = str(TEMP_DIR / "video_list.txt")
    with open(video_list, "w") as f:
        for seg in video_segments:
            f.write(f"file '{os.path.abspath(seg)}'\n")

    concat_video = str(TEMP_DIR / "concat_video.mp4")
    subprocess.run([
        FFMPEG, "-y",
        "-f", "concat", "-safe", "0", "-i", video_list,
        "-c:v", "libx264", "-preset", "fast", "-crf", "22",
        concat_video, "-loglevel", "quiet"
    ], check=True)

    # Concat all audio segments
    final_audio = str(TEMP_DIR / "final_audio.aac")
    concat_audio(audio_segments, final_audio, silence_between=0.2)

    # Mux video + audio
    subprocess.run([
        FFMPEG, "-y",
        "-i", concat_video,
        "-i", final_audio,
        "-map", "0:v", "-map", "1:a",
        "-c:v", "libx264", "-preset", "medium", "-crf", "20",
        "-c:a", "aac", "-b:a", "192k",
        "-movflags", "+faststart",
        "-shortest",
        output_path, "-loglevel", "quiet"
    ], check=True)

    size_mb = Path(output_path).stat().st_size / 1024 / 1024
    print(f"\n✓ Video assembled: {output_path} ({size_mb:.1f} MB)")
    return output_path


def cleanup_family_temp():
    """Remove family temp files."""
    import shutil
    if TEMP_DIR.exists():
        shutil.rmtree(TEMP_DIR)
        TEMP_DIR.mkdir()
    print("  Temp files cleaned.")
    
