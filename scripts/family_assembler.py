"""
Family Channel Video Assembler — card-based format.
Builds "This or That" style videos with:
  - Animated question cards (drawbox based, no drawtext dependency for structure)
  - Per-question voiceover (Kokoro af_sarah)
  - Animal images from Pexels matched per question (with ken-burns zoom)
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
            "image_keyword": "tiger wildlife"
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
import subprocess
import requests
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
OUTPUT_DIR   = PROJECT_ROOT / "output"
TEMP_DIR     = PROJECT_ROOT / "output" / "family_temp"
ASSETS_DIR   = PROJECT_ROOT / "assets"

for d in [OUTPUT_DIR, TEMP_DIR]:
    d.mkdir(exist_ok=True)

# Use ffmpeg_static if set in env (needed on Mac — brew ffmpeg lacks drawtext)
FFMPEG = os.environ.get("FFMPEG_CMD", "ffmpeg")

# Video settings
WIDTH  = 1920
HEIGHT = 1080
FPS    = 30
FONT   = "/System/Library/Fonts/HelveticaNeue.ttc"

# Check if drawtext is available in current ffmpeg binary
def _has_drawtext() -> bool:
    result = subprocess.run(
        [FFMPEG, "-filters"],
        capture_output=True, text=True
    )
    return "drawtext" in result.stdout

HAS_DRAWTEXT = _has_drawtext()

# Colors
COLOR_BG       = "1a1a2e"
COLOR_ACCENT   = "e94560"
COLOR_TEXT     = "ffffff"
COLOR_OPTION_A = "0f3460"
COLOR_OPTION_B = "533483"
COLOR_ANSWER   = "2ecc71"
COLOR_FUNFACT  = "f39c12"

PEXELS_API_KEY = os.environ.get("PEXELS_API_KEY", "")


# ─────────────────────────────────────────────
# AUDIO HELPERS
# ─────────────────────────────────────────────

def get_duration(path: str) -> float:
    cmd = ["ffprobe", "-v", "quiet", "-print_format", "json", "-show_format", path]
    result = subprocess.run(cmd, capture_output=True, text=True)
    fmt = json.loads(result.stdout).get("format", {})
    return float(fmt.get("duration", 0))


def make_beep(output_path: str, freq: int = 880, duration: float = 0.15, volume: float = 0.3):
    subprocess.run([
        FFMPEG, "-y", "-f", "lavfi",
        "-i", f"sine=frequency={freq}:duration={duration}",
        "-af", f"volume={volume}",
        output_path, "-loglevel", "quiet"
    ], check=True)


def make_countdown_audio(output_path: str):
    beeps = []
    for i in range(3):
        bp = str(TEMP_DIR / f"beep_{i}.wav")
        make_beep(bp, freq=660 + i * 110, duration=0.25, volume=0.5)
        beeps.append(bp)

    silence = str(TEMP_DIR / "silence_short.wav")
    subprocess.run([
        FFMPEG, "-y", "-f", "lavfi",
        "-i", "anullsrc=r=22050:cl=mono",
        "-t", "0.75", silence, "-loglevel", "quiet"
    ], check=True)

    list_path = str(TEMP_DIR / "countdown_list.txt")
    with open(list_path, "w") as f:
        for bp in beeps:
            f.write(f"file '{os.path.abspath(bp)}'\n")
            f.write(f"file '{os.path.abspath(silence)}'\n")

    subprocess.run([
        FFMPEG, "-y",
        "-f", "concat", "-safe", "0", "-i", list_path,
        "-c:a", "aac", output_path, "-loglevel", "quiet"
    ], check=True)


def make_ding(output_path: str):
    subprocess.run([
        FFMPEG, "-y", "-f", "lavfi",
        "-i", "sine=frequency=1046:duration=0.8",
        "-af", "volume=0.5,afade=t=out:st=0.5:d=0.3",
        output_path, "-loglevel", "quiet"
    ], check=True)


def concat_audio(files: list, output_path: str, silence_between: float = 0.3):
    silence_path = None
    if silence_between > 0 and len(files) > 1:
        silence_path = str(TEMP_DIR / "concat_silence.wav")
        subprocess.run([
            FFMPEG, "-y", "-f", "lavfi",
            "-i", "anullsrc=r=44100:cl=stereo",
            "-t", str(silence_between),
            silence_path, "-loglevel", "quiet"
        ], check=True)

    inputs = []
    for i, fp in enumerate(files):
        inputs.append(fp)
        if silence_path and i < len(files) - 1:
            inputs.append(silence_path)

    cmd = [FFMPEG, "-y"]
    for fp in inputs:
        cmd += ["-i", fp]
    cmd += [
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
        print(f"  No PEXELS_API_KEY — skipping image for '{keyword}'")
        return False
    try:
        print(f"  Fetching image: '{keyword}'...")
        headers = {"Authorization": PEXELS_API_KEY}
        url = f"https://api.pexels.com/v1/search?query={keyword}&per_page=5&orientation=landscape"
        resp = requests.get(url, headers=headers, timeout=10)
        resp.raise_for_status()
        photos = resp.json().get("photos", [])
        if not photos:
            print(f"  No photos found for '{keyword}'")
            return False
        photo_url = photos[0]["src"]["large2x"]
        img = requests.get(photo_url, timeout=15)
        with open(output_path, "wb") as f:
            f.write(img.content)
        print(f"  Image saved: {output_path}")
        return True
    except Exception as e:
        print(f"  Image fetch failed for '{keyword}': {e}")
        return False


def make_image_video(image_path: str, duration: float, output_path: str):
    """
    Convert a still image to a video with ken-burns zoom effect.
    Falls back to static image if zoompan filter fails.
    """
    # Ken-burns: slow zoom in from 1.0 to 1.05 over the duration
    total_frames = int(duration * FPS)
    zoompan = (
        f"zoompan=z='min(zoom+0.0008,1.05)':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':"
        f"d={total_frames}:s={WIDTH}x{HEIGHT}:fps={FPS}"
    )
    cmd = [
        FFMPEG, "-y",
        "-loop", "1", "-i", image_path,
        "-t", str(duration),
        "-vf", f"scale={WIDTH*2}:{HEIGHT*2}:force_original_aspect_ratio=increase,"
               f"crop={WIDTH*2}:{HEIGHT*2},{zoompan}",
        "-c:v", "libx264", "-preset", "fast", "-crf", "23",
        "-pix_fmt", "yuv420p",
        output_path, "-loglevel", "quiet"
    ]
    result = subprocess.run(cmd, capture_output=True)
    if result.returncode != 0:
        # Fallback: static image no zoom
        cmd = [
            FFMPEG, "-y",
            "-loop", "1", "-i", image_path,
            "-t", str(duration),
            "-vf", f"scale={WIDTH}:{HEIGHT}:force_original_aspect_ratio=increase,"
                   f"crop={WIDTH}:{HEIGHT}",
            "-c:v", "libx264", "-preset", "fast", "-crf", "23",
            "-pix_fmt", "yuv420p",
            output_path, "-loglevel", "quiet"
        ]
        subprocess.run(cmd, check=True)


def overlay_answer_text(image_video: str, answer: str, explanation: str,
                        duration: float, output_path: str):
    """
    Overlay answer text on top of animal image video.
    Uses drawtext if available, drawbox fallback otherwise.
    """
    explanation_short = explanation[:80] + ("..." if len(explanation) > 80 else "")
    # Escape special chars for ffmpeg drawtext
    answer_safe = answer.replace("'", "").replace(":", "\\:")
    explanation_safe = explanation_short.replace("'", "").replace(":", "\\:")

    if HAS_DRAWTEXT:
        # Dark overlay + green answer banner + explanation text
        vf = (
            # Dark overlay on image
            f"drawbox=x=0:y=0:w={WIDTH}:h={HEIGHT}:color=0x000000@0.45:t=fill,"
            # Green answer banner
            f"drawbox=x=0:y=400:w={WIDTH}:h=130:color=0x{COLOR_ANSWER}@0.92:t=fill,"
            # Answer text
            f"drawtext=text='ANSWER\\: {answer_safe}':"
            f"fontfile={FONT}:fontsize=68:fontcolor=0x{COLOR_TEXT}:"
            f"x=(w-text_w)/2:y=430,"
            # Explanation text
            f"drawtext=text='{explanation_safe}':"
            f"fontfile={FONT}:fontsize=34:fontcolor=0x{COLOR_TEXT}:"
            f"x=(w-text_w)/2:y=580,"
            # Bottom accent bar
            f"drawbox=x=0:y={HEIGHT-10}:w={WIDTH}:h=10:color=0x{COLOR_ANSWER}@1:t=fill"
        )
    else:
        # drawtext not available — just dark overlay + colored boxes, no text
        vf = (
            f"drawbox=x=0:y=0:w={WIDTH}:h={HEIGHT}:color=0x000000@0.45:t=fill,"
            f"drawbox=x=0:y=400:w={WIDTH}:h=130:color=0x{COLOR_ANSWER}@0.92:t=fill,"
            f"drawbox=x=0:y={HEIGHT-10}:w={WIDTH}:h=10:color=0x{COLOR_ANSWER}@1:t=fill"
        )

    cmd = [
        FFMPEG, "-y",
        "-i", image_video,
        "-t", str(duration),
        "-vf", vf,
        "-c:v", "libx264", "-preset", "fast", "-crf", "22",
        output_path, "-loglevel", "quiet"
    ]
    subprocess.run(cmd, check=True)


# ─────────────────────────────────────────────
# CARD GENERATORS
# ─────────────────────────────────────────────

def wrap_text(text: str, max_chars: int = 35) -> str:
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


def _solid_bg(duration: float, color: str = COLOR_BG) -> list:
    """Return ffmpeg args for a solid color background input."""
    return [
        "-f", "lavfi",
        "-i", f"color=c=0x{color}:size={WIDTH}x{HEIGHT}:rate={FPS}",
        "-t", str(duration),
    ]


def make_question_card(question: str, option_a: str, option_b: str,
                       number: int, duration: float, output_path: str):
    """Question card with two option boxes and question text."""
    q_wrapped = wrap_text(question, 42)
    a_wrapped = wrap_text(option_a, 16)
    b_wrapped = wrap_text(option_b, 16)

    if HAS_DRAWTEXT:
        vf = (
            # Top accent bar
            f"drawbox=x=0:y=0:w={WIDTH}:h=14:color=0x{COLOR_ACCENT}@1:t=fill,"
            # Question number badge
            f"drawbox=x=80:y=55:w=200:h=58:color=0x{COLOR_ACCENT}@1:t=fill,"
            f"drawtext=text='Question {number}':"
            f"fontfile={FONT}:fontsize=28:fontcolor=0x{COLOR_TEXT}:x=90:y=72,"
            # THIS OR THAT header
            f"drawtext=text='THIS  OR  THAT?':"
            f"fontfile={FONT}:fontsize=58:fontcolor=0x{COLOR_ACCENT}:x=(w-text_w)/2:y=50,"
            # Question text
            f"drawtext=text='{q_wrapped}':"
            f"fontfile={FONT}:fontsize=54:fontcolor=0x{COLOR_TEXT}:"
            f"x=(w-text_w)/2:y=200:line_spacing=10,"
            # Option A box
            f"drawbox=x=60:y=500:w=840:h=300:color=0x{COLOR_OPTION_A}@1:t=fill,"
            f"drawbox=x=60:y=500:w=840:h=300:color=0x{COLOR_TEXT}@0.1:t=5,"
            f"drawtext=text='A':"
            f"fontfile={FONT}:fontsize=40:fontcolor=0x{COLOR_ACCENT}:x=110:y=520,"
            f"drawtext=text='{a_wrapped}':"
            f"fontfile={FONT}:fontsize=50:fontcolor=0x{COLOR_TEXT}:"
            f"x=480-text_w/2:y=600:line_spacing=8,"
            # VS
            f"drawtext=text='VS':"
            f"fontfile={FONT}:fontsize=52:fontcolor=0x{COLOR_ACCENT}:x=(w-text_w)/2:y=620,"
            # Option B box
            f"drawbox=x=1020:y=500:w=840:h=300:color=0x{COLOR_OPTION_B}@1:t=fill,"
            f"drawbox=x=1020:y=500:w=840:h=300:color=0x{COLOR_TEXT}@0.1:t=5,"
            f"drawtext=text='B':"
            f"fontfile={FONT}:fontsize=40:fontcolor=0x{COLOR_ACCENT}:x=1070:y=520,"
            f"drawtext=text='{b_wrapped}':"
            f"fontfile={FONT}:fontsize=50:fontcolor=0x{COLOR_TEXT}:"
            f"x=1440-text_w/2:y=600:line_spacing=8,"
            # Bottom bar
            f"drawbox=x=0:y={HEIGHT-10}:w={WIDTH}:h=10:color=0x{COLOR_ACCENT}@1:t=fill"
        )
    else:
        # Boxes only — no text (drawtext unavailable)
        vf = (
            f"drawbox=x=0:y=0:w={WIDTH}:h=14:color=0x{COLOR_ACCENT}@1:t=fill,"
            f"drawbox=x=60:y=500:w=840:h=300:color=0x{COLOR_OPTION_A}@1:t=fill,"
            f"drawbox=x=1020:y=500:w=840:h=300:color=0x{COLOR_OPTION_B}@1:t=fill,"
            f"drawbox=x=0:y={HEIGHT-10}:w={WIDTH}:h=10:color=0x{COLOR_ACCENT}@1:t=fill"
        )

    cmd = [FFMPEG, "-y"] + _solid_bg(duration) + [
        "-vf", vf,
        "-c:v", "libx264", "-preset", "fast", "-crf", "23",
        output_path, "-loglevel", "quiet"
    ]
    subprocess.run(cmd, check=True)


def make_answer_card(answer: str, explanation: str, image_path: str,
                     duration: float, output_path: str):
    """
    Answer reveal card.
    If image available: ken-burns animal image + text overlay.
    If no image: solid color card with text.
    """
    if image_path and Path(image_path).exists():
        # Step 1: image → ken-burns video
        img_video = output_path.replace(".mp4", "_imgbg.mp4")
        make_image_video(image_path, duration, img_video)
        # Step 2: overlay answer text on image video
        overlay_answer_text(img_video, answer, explanation, duration, output_path)
        # Clean up intermediate
        Path(img_video).unlink(missing_ok=True)
    else:
        # Solid color fallback
        explanation_short = explanation[:80] + ("..." if len(explanation) > 80 else "")
        answer_safe = answer.replace("'", "").replace(":", "\\:")
        explanation_safe = explanation_short.replace("'", "").replace(":", "\\:")

        if HAS_DRAWTEXT:
            vf = (
                f"drawbox=x=0:y=400:w={WIDTH}:h=130:color=0x{COLOR_ANSWER}@0.92:t=fill,"
                f"drawtext=text='ANSWER\\: {answer_safe}':"
                f"fontfile={FONT}:fontsize=68:fontcolor=0x{COLOR_TEXT}:"
                f"x=(w-text_w)/2:y=430,"
                f"drawtext=text='{explanation_safe}':"
                f"fontfile={FONT}:fontsize=34:fontcolor=0x{COLOR_TEXT}:"
                f"x=(w-text_w)/2:y=580"
            )
        else:
            vf = f"drawbox=x=0:y=400:w={WIDTH}:h=130:color=0x{COLOR_ANSWER}@0.92:t=fill"

        cmd = [FFMPEG, "-y"] + _solid_bg(duration) + [
            "-vf", vf,
            "-c:v", "libx264", "-preset", "fast", "-crf", "23",
            output_path, "-loglevel", "quiet"
        ]
        subprocess.run(cmd, check=True)


def make_funfact_card(text: str, duration: float, output_path: str):
    """Fun fact interstitial card — amber accented."""
    wrapped = wrap_text(text, 50)
    text_safe = text[:120].replace("'", "\\'").replace(":", "\\:")

    if HAS_DRAWTEXT:
        vf = (
            f"drawbox=x=0:y=0:w={WIDTH}:h=14:color=0x{COLOR_FUNFACT}@1:t=fill,"
            f"drawbox=x=0:y={HEIGHT-10}:w={WIDTH}:h=10:color=0x{COLOR_FUNFACT}@1:t=fill,"
            f"drawbox=x=(iw-1400)/2:y=160:w=1400:h=90:color=0x{COLOR_FUNFACT}@0.2:t=fill,"
            f"drawtext=text='FUN FACT!':"
            f"fontfile={FONT}:fontsize=76:fontcolor=0x{COLOR_FUNFACT}:x=(w-text_w)/2:y=170,"
            f"drawtext=text='{wrapped}':"
            f"fontfile={FONT}:fontsize=42:fontcolor=0x{COLOR_TEXT}:"
            f"x=(w-text_w)/2:y=330:line_spacing=16"
        )
    else:
        vf = (
            f"drawbox=x=0:y=0:w={WIDTH}:h=14:color=0x{COLOR_FUNFACT}@1:t=fill,"
            f"drawbox=x=0:y={HEIGHT-10}:w={WIDTH}:h=10:color=0x{COLOR_FUNFACT}@1:t=fill,"
            f"drawbox=x=(iw-1400)/2:y=160:w=1400:h=90:color=0x{COLOR_FUNFACT}@0.2:t=fill"
        )

    cmd = [FFMPEG, "-y"] + _solid_bg(duration) + [
        "-vf", vf,
        "-c:v", "libx264", "-preset", "fast", "-crf", "23",
        output_path, "-loglevel", "quiet"
    ]
    subprocess.run(cmd, check=True)


def make_title_card(title: str, subtitle: str, duration: float, output_path: str):
    """Intro / outro title card."""
    title_safe    = title.replace("'", "\\'").replace(":", "\\:")
    subtitle_safe = subtitle.replace("'", "\\'").replace(":", "\\:")

    if HAS_DRAWTEXT:
        vf = (
            f"drawbox=x=0:y=0:w={WIDTH}:h=14:color=0x{COLOR_ACCENT}@1:t=fill,"
            f"drawbox=x=0:y={HEIGHT-10}:w={WIDTH}:h=10:color=0x{COLOR_ACCENT}@1:t=fill,"
            f"drawbox=x=(iw-1600)/2:y=320:w=1600:h=260:color=0x000000@0.35:t=fill,"
            f"drawtext=text='{title_safe}':"
            f"fontfile={FONT}:fontsize=90:fontcolor=0x{COLOR_TEXT}:x=(w-text_w)/2:y=350,"
            f"drawtext=text='{subtitle_safe}':"
            f"fontfile={FONT}:fontsize=46:fontcolor=0x{COLOR_ACCENT}:x=(w-text_w)/2:y=480"
        )
    else:
        vf = (
            f"drawbox=x=0:y=0:w={WIDTH}:h=14:color=0x{COLOR_ACCENT}@1:t=fill,"
            f"drawbox=x=0:y={HEIGHT-10}:w={WIDTH}:h=10:color=0x{COLOR_ACCENT}@1:t=fill,"
            f"drawbox=x=(iw-1600)/2:y=320:w=1600:h=260:color=0x000000@0.35:t=fill"
        )

    cmd = [FFMPEG, "-y"] + _solid_bg(duration) + [
        "-vf", vf,
        "-c:v", "libx264", "-preset", "fast", "-crf", "23",
        output_path, "-loglevel", "quiet"
    ]
    subprocess.run(cmd, check=True)


# ─────────────────────────────────────────────
# MAIN ASSEMBLER
# ─────────────────────────────────────────────

def assemble_family_video(script: dict, output_path: str) -> str:
    import sys
    sys.path.insert(0, str(Path(__file__).parent))
    from kokoro_tts import synthesize

    print(f"\n{'='*50}")
    print(f"Family Assembler: {script['title']}")
    print(f"{'='*50}")
    print(f"  drawtext available: {HAS_DRAWTEXT}")
    print(f"  PEXELS_API_KEY set: {'yes' if PEXELS_API_KEY else 'NO — images will be skipped'}")
    print(f"  ffmpeg binary: {FFMPEG}")

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
    make_title_card("THIS OR THAT?", script.get("subtitle", "Animal Edition"),
                    intro_dur, intro_video)
    video_segments.append(intro_video)
    audio_segments.append(intro_audio)

    # ── QUESTIONS ──
    fun_facts = {ff["after_question"]: ff["text"] for ff in script.get("fun_facts", [])}

    for q in script["questions"]:
        n = q["number"]
        print(f"\nBuilding question {n}/{len(script['questions'])}: {q['question'][:50]}...")

        # 1. Question voiceover
        q_text  = f"Question {n}. {q['question']} Is it... {q['option_a']}... or {q['option_b']}?"
        q_audio = str(TEMP_DIR / f"q{n}_question.mp3")
        synthesize(q_text, q_audio, voice="af_sarah", speed=1.05)
        q_dur = get_duration(q_audio)

        # 2. Question card
        total_q_dur = q_dur + countdown_dur + 0.5
        q_video = str(TEMP_DIR / f"q{n}_card.mp4")
        make_question_card(q["question"], q["option_a"], q["option_b"],
                           n, total_q_dur, q_video)

        # Combine question audio + countdown
        q_combined = str(TEMP_DIR / f"q{n}_combined.aac")
        concat_audio([q_audio, countdown_audio], q_combined, silence_between=0.2)

        video_segments.append(q_video)
        audio_segments.append(q_combined)

        # 3. Fetch animal image
        img_path  = str(TEMP_DIR / f"q{n}_image.jpg")
        has_image = fetch_animal_image(q["image_keyword"], img_path)

        # 4. Answer voiceover
        a_text  = f"The answer is... {q['answer']}! {q['explanation']}"
        a_audio = str(TEMP_DIR / f"q{n}_answer.mp3")
        synthesize(a_text, a_audio, voice="af_sarah", speed=1.05)
        a_dur = get_duration(a_audio)

        # 5. Answer card (image + text overlay or solid fallback)
        total_a_dur = ding_dur + a_dur + 0.8
        a_video = str(TEMP_DIR / f"q{n}_answer_card.mp4")
        make_answer_card(
            answer=q["answer"],
            explanation=q["explanation"],
            image_path=img_path if has_image else None,
            duration=total_a_dur,
            output_path=a_video,
        )

        # Combine ding + answer audio
        a_combined = str(TEMP_DIR / f"q{n}_answer_combined.aac")
        concat_audio([ding_audio, a_audio], a_combined, silence_between=0.15)

        video_segments.append(a_video)
        audio_segments.append(a_combined)

        # 6. Fun fact
        if n in fun_facts:
            print(f"  Adding fun fact after Q{n}...")
            ff_text  = f"Fun fact! {fun_facts[n]}"
            ff_audio = str(TEMP_DIR / f"ff_{n}.mp3")
            synthesize(ff_text, ff_audio, voice="af_sarah", speed=1.0)
            ff_dur = get_duration(ff_audio) + 0.5

            ff_video = str(TEMP_DIR / f"ff_{n}_card.mp4")
            make_funfact_card(fun_facts[n], ff_dur, ff_video)
            video_segments.append(ff_video)
            audio_segments.append(ff_audio)

    # ── OUTRO ──
    print("\nBuilding outro...")
    outro_audio = str(TEMP_DIR / "outro_voice.mp3")
    synthesize(script["outro"], outro_audio, voice="af_sarah", speed=1.05)
    outro_dur = get_duration(outro_audio) + 0.5

    outro_video = str(TEMP_DIR / "outro_card.mp4")
    make_title_card("Thanks for watching!", "Like & Subscribe for more!",
                    outro_dur, outro_video)
    video_segments.append(outro_video)
    audio_segments.append(outro_audio)

    # ── FINAL ASSEMBLY ──
    print(f"\nFinal assembly: {len(video_segments)} segments...")

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

    final_audio = str(TEMP_DIR / "final_audio.aac")
    concat_audio(audio_segments, final_audio, silence_between=0.2)

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
    import shutil
    if TEMP_DIR.exists():
        shutil.rmtree(TEMP_DIR)
        TEMP_DIR.mkdir()
    print("  Temp files cleaned.")
    