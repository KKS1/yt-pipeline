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
from PIL import Image, ImageDraw, ImageFont, ImageFilter
import io

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
# Audio Assets
BUZZER_AUDIO        = ASSETS_DIR / "buzzer.mp3"
FANFARE_AUDIO       = ASSETS_DIR / "fanfare.mp3"
SUSPENSE_TICK_AUDIO = ASSETS_DIR / "suspense_tick.mp3"

# Font Path for Pillow
PILLOW_FONT_PATH = ASSETS_DIR / "DejaVuSans-Bold.ttf"

# Colors
COLOR_BG       = "1a1a2e"
COLOR_ACCENT   = "e94560"
COLOR_TEXT     = "ffffff"
COLOR_OPTION_A = "0f3460"
COLOR_OPTION_B = "533483"
COLOR_ANSWER   = "2ecc71"
COLOR_FUNFACT  = "f39c12"

# RGB Tuples for Gradients
COLOR_GRADIENT_START = (26, 26, 46) 
COLOR_GRADIENT_END   = (15, 15, 25)
COLOR_OPTION_A_GRADIENT_START = (15, 52, 96)
COLOR_OPTION_B_GRADIENT_START = (83, 52, 131)
COLOR_FUNFACT_GRADIENT_START  = (243, 156, 18)
COLOR_FUNFACT_GRADIENT_END    = (211, 84, 0)

CORNER_RADIUS = 30

PEXELS_API_KEY = os.environ.get("PEXELS_API_KEY", "")

# ─────────────────────────────────────────────
# AUDIO HELPERS
# ─────────────────────────────────────────────

def get_duration(path: str) -> float:
    cmd = ["ffprobe", "-v", "quiet", "-print_format", "json", "-show_format", path]
    result = subprocess.run(cmd, capture_output=True, text=True)
    fmt = json.loads(result.stdout).get("format", {})
    return float(fmt.get("duration", 0))


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
        "-filter_complex", f"concat=n={len(inputs)}:v=0:a=1,aresample=44100[out]",
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

# ─────────────────────────────────────────────
# PILLOW HELPERS
# ─────────────────────────────────────────────
def text_wrap(text: str, font: ImageFont.FreeTypeFont, max_width: int) -> str:
    words = text.split()
    lines, current = [], ""
    for word in words:
        test_line = (current + " " + word).strip()
        if font.getlength(test_line) <= max_width:
            current = test_line
        else:
            if current:
                lines.append(current)
            current = word
    if current:
        lines.append(current)
    return "\n".join(lines)

def draw_rounded_rectangle(draw, xy, radius, fill, outline=None, width=0):
    x1, y1, x2, y2 = xy
    draw.ellipse((x1, y1, x1 + 2 * radius, y1 + 2 * radius), fill=fill, outline=outline, width=width)
    draw.ellipse((x2 - 2 * radius, y1, x2, y1 + 2 * radius), fill=fill, outline=outline, width=width)
    draw.ellipse((x1, y2 - 2 * radius, x1 + 2 * radius, y2), fill=fill, outline=outline, width=width)
    draw.ellipse((x2 - 2 * radius, y2 - 2 * radius, x2, y2), fill=fill, outline=outline, width=width)
    draw.rectangle((x1 + radius, y1, x2 - radius, y2), fill=fill, outline=outline, width=width)
    draw.rectangle((x1, y1 + radius, x2, y2 - radius), fill=fill, outline=outline, width=width)

def draw_gradient_background(image, start_color, end_color):
    width, height = image.size
    for y in range(height):
        r = int(start_color[0] + (end_color[0] - start_color[0]) * y / height)
        g = int(start_color[1] + (end_color[1] - start_color[1]) * y / height)
        b = int(start_color[2] + (end_color[2] - start_color[2]) * y / height)
        draw = ImageDraw.Draw(image)
        draw.line([(0, y), (width, y)], fill=(r, g, b))

def get_font(size):
    """
    Attempts to load the preferred font from assets, then tries common system fallbacks.
    Pillow's load_default() does not support scaling, so system fallbacks are preferred.
    """
    # 1. Try preferred asset path
    if PILLOW_FONT_PATH.exists():
        try:
            return ImageFont.truetype(str(PILLOW_FONT_PATH), size)
        except (IOError, OSError):
            pass

    # 2. Try common system font names (Pillow can often find these automatically)
    for font_name in ["DejaVuSans-Bold", "Arial Bold", "Helvetica Bold", "Verdana Bold"]:
        try:
            return ImageFont.truetype(font_name, size)
        except (IOError, OSError):
            continue

    print(f"Warning: Preferred font not found at {PILLOW_FONT_PATH} and no system fallbacks found. Text will be tiny.")
    return ImageFont.load_default()

def add_text_with_outline(draw, xy, text, font, fill_color, outline_color, outline_width=2, anchor="mm"):
    x, y = xy
    # Draw outline
    for dx in [-outline_width, 0, outline_width]:
        for dy in [-outline_width, 0, outline_width]:
            if dx != 0 or dy != 0:
                draw.text((x + dx, y + dy), text, font=font, fill=outline_color, anchor=anchor)
    # Draw main text
    draw.text(xy, text, font=font, fill=fill_color, anchor=anchor)


# ─────────────────────────────────────────────
# PILLOW CARD GENERATORS (output PNGs)
# ─────────────────────────────────────────────

def make_title_card_png(title: str, subtitle: str, output_path: str):
    img = Image.new("RGB", (WIDTH, HEIGHT), COLOR_GRADIENT_START)
    draw_gradient_background(img, COLOR_GRADIENT_START, COLOR_GRADIENT_END)
    draw = ImageDraw.Draw(img)

    # Title box (semi-transparent black)
    box_w, box_h = 1600, 260
    box_x, box_y = (WIDTH - box_w) // 2, 320
    draw_rounded_rectangle(draw, (box_x, box_y, box_x + box_w, box_y + box_h), CORNER_RADIUS, (0, 0, 0, 128))

    font_title = get_font(90)
    font_subtitle = get_font(46)

    # Title text
    add_text_with_outline(draw, (WIDTH // 2, 350 + font_title.getbbox(title)[3] // 2), title, font_title, (255, 255, 255), (0, 0, 0))
    # Subtitle text
    add_text_with_outline(draw, (WIDTH // 2, 480 + font_subtitle.getbbox(subtitle)[3] // 2), subtitle, font_subtitle, (int(COLOR_ACCENT[0:2], 16), int(COLOR_ACCENT[2:4], 16), int(COLOR_ACCENT[4:6], 16)), (0, 0, 0))

    img.save(output_path)


def make_question_card_png(question: str, option_a: str, option_b: str, number: int, output_path: str):
    img = Image.new("RGB", (WIDTH, HEIGHT), COLOR_GRADIENT_START)
    draw_gradient_background(img, COLOR_GRADIENT_START, COLOR_GRADIENT_END)
    draw = ImageDraw.Draw(img)

    font_q_num = get_font(28)
    font_this_or_that = get_font(58)
    font_question = get_font(54)
    font_option_label = get_font(40)
    font_option_text = get_font(50)
    font_vs = get_font(52)

    # Top accent bar
    draw.rectangle((0, 0, WIDTH, 14), fill=f"#{COLOR_ACCENT}")

    # Question number badge
    draw_rounded_rectangle(draw, (80, 55, 280, 113), CORNER_RADIUS // 2, f"#{COLOR_ACCENT}")
    add_text_with_outline(draw, (180, 84), f"Question {number}", font_q_num, (255, 255, 255), (0, 0, 0))

    # THIS OR THAT header
    add_text_with_outline(draw, (WIDTH // 2, 79), "THIS  OR  THAT?", font_this_or_that, f"#{COLOR_ACCENT}", (0, 0, 0))

    # Question text
    wrapped_question = text_wrap(question, font_question, WIDTH - 400)
    bbox = draw.textbbox((0,0), wrapped_question, font=font_question)
    text_height = bbox[3] - bbox[1]
    add_text_with_outline(draw, (WIDTH // 2, 200 + text_height // 2), wrapped_question, font_question, (255, 255, 255), (0, 0, 0))

    # Option A box
    option_box_w, option_box_h = 840, 300
    option_a_x, option_y = 60, 500
    draw_rounded_rectangle(draw, (option_a_x, option_y, option_a_x + option_box_w, option_y + option_box_h), CORNER_RADIUS, COLOR_OPTION_A_GRADIENT_START)
    draw.rectangle((option_a_x + CORNER_RADIUS, option_y, option_a_x + option_box_w - CORNER_RADIUS, option_y + option_box_h), fill=COLOR_OPTION_A_GRADIENT_START) # Fill center
    add_text_with_outline(draw, (option_a_x + 50, option_y + 20), "A", font_option_label, f"#{COLOR_ACCENT}", (0, 0, 0), outline_width=1, anchor="ls")
    wrapped_a = text_wrap(option_a, font_option_text, option_box_w - 100)
    add_text_with_outline(draw, (option_a_x + option_box_w // 2, option_y + option_box_h // 2 + 20), wrapped_a, font_option_text, (255, 255, 255), (0, 0, 0))

    # VS
    add_text_with_outline(draw, (WIDTH // 2, 650), "VS", font_vs, f"#{COLOR_ACCENT}", (0, 0, 0))

    # Option B box
    option_b_x = 1020
    draw_rounded_rectangle(draw, (option_b_x, option_y, option_b_x + option_box_w, option_y + option_box_h), CORNER_RADIUS, COLOR_OPTION_B_GRADIENT_START)
    draw.rectangle((option_b_x + CORNER_RADIUS, option_y, option_b_x + option_box_w - CORNER_RADIUS, option_y + option_box_h), fill=COLOR_OPTION_B_GRADIENT_START) # Fill center
    add_text_with_outline(draw, (option_b_x + 50, option_y + 20), "B", font_option_label, f"#{COLOR_ACCENT}", (0, 0, 0), outline_width=1, anchor="ls")
    wrapped_b = text_wrap(option_b, font_option_text, option_box_w - 100)
    add_text_with_outline(draw, (option_b_x + option_box_w // 2, option_y + option_box_h // 2 + 20), wrapped_b, font_option_text, (255, 255, 255), (0, 0, 0))

    # Bottom bar
    draw.rectangle((0, HEIGHT - 10, WIDTH, HEIGHT), fill=f"#{COLOR_ACCENT}")

    img.save(output_path)


def make_answer_card_png(answer: str, explanation: str, image_path: str, output_path: str):
    img = Image.new("RGB", (WIDTH, HEIGHT), COLOR_GRADIENT_START)
    draw = ImageDraw.Draw(img)

    if image_path and Path(image_path).exists():
        bg_img = Image.open(image_path).resize((WIDTH, HEIGHT), Image.LANCZOS)
        img.paste(bg_img, (0, 0))
        # Add dark overlay
        overlay = Image.new("RGBA", (WIDTH, HEIGHT), (0, 0, 0, int(255 * 0.45)))
        img.paste(overlay, (0, 0), overlay)
        draw = ImageDraw.Draw(img) # Redraw on the new image with overlay
    else:
        draw_gradient_background(img, COLOR_GRADIENT_START, COLOR_GRADIENT_END)

    font_answer = get_font(68)
    font_explanation = get_font(34)

    # Green answer banner
    banner_h = 130
    draw_rounded_rectangle(draw, (0, 400, WIDTH, 400 + banner_h), CORNER_RADIUS, f"#{COLOR_ANSWER}")
    draw.rectangle((CORNER_RADIUS, 400, WIDTH - CORNER_RADIUS, 400 + banner_h), fill=f"#{COLOR_ANSWER}") # Fill center

    add_text_with_outline(draw, (WIDTH // 2, 400 + banner_h // 2), f"ANSWER: {answer}", font_answer, (255, 255, 255), (0, 0, 0))

    # Explanation text
    wrapped_explanation = text_wrap(explanation, font_explanation, WIDTH - 400)
    bbox = draw.textbbox((0,0), wrapped_explanation, font=font_explanation)
    text_height = bbox[3] - bbox[1]
    add_text_with_outline(draw, (WIDTH // 2, 580 + text_height // 2), wrapped_explanation, font_explanation, (255, 255, 255), (0, 0, 0))

    # Bottom accent bar
    draw.rectangle((0, HEIGHT - 10, WIDTH, HEIGHT), fill=f"#{COLOR_ANSWER}")

    img.save(output_path)


def make_funfact_card_png(text: str, output_path: str):
    img = Image.new("RGB", (WIDTH, HEIGHT), (243, 156, 18))
    draw_gradient_background(img, COLOR_FUNFACT_GRADIENT_START, COLOR_FUNFACT_GRADIENT_END)
    draw = ImageDraw.Draw(img)

    font_header = get_font(76)
    font_fact = get_font(42)

    # Top accent bar
    draw.rectangle((0, 0, WIDTH, 14), fill=f"#{COLOR_FUNFACT}")
    # Bottom accent bar
    draw.rectangle((0, HEIGHT - 10, WIDTH, HEIGHT), fill=f"#{COLOR_FUNFACT}")

    # "FUN FACT!" banner
    banner_w, banner_h = 1400, 90
    banner_x, banner_y = (WIDTH - banner_w) // 2, 160
    draw_rounded_rectangle(draw, (banner_x, banner_y, banner_x + banner_w, banner_y + banner_h), CORNER_RADIUS // 2, (0, 0, 0, 50)) # Semi-transparent black
    add_text_with_outline(draw, (WIDTH // 2, banner_y + banner_h // 2), "FUN FACT!", font_header, (255, 255, 255), (0, 0, 0))

    # Fun fact text
    wrapped_fact = text_wrap(text, font_fact, WIDTH - 400)
    bbox = draw.textbbox((0,0), wrapped_fact, font=font_fact)
    text_height = bbox[3] - bbox[1]
    add_text_with_outline(draw, (WIDTH // 2, 330 + text_height // 2), wrapped_fact, font_fact, (255, 255, 255), (0, 0, 0))

    img.save(output_path)


# ─────────────────────────────────────────────
# VIDEO GENERATORS (from PNGs or for overlays)
# ─────────────────────────────────────────────

def make_static_card_video(image_path: str, duration: float, output_path: str):
    """Converts a static PNG image to a video."""
    subprocess.run([
        FFMPEG, "-y",
        "-loop", "1", "-i", image_path,
        "-t", str(duration),
        "-c:v", "libx264", "-preset", "fast", "-crf", "23",
        "-pix_fmt", "yuv420p",
        output_path, "-loglevel", "quiet"
    ], check=True)


def _make_single_countdown_number_video(number: int, duration_per_number: float, output_path: str):
    font_countdown = get_font(200)
    img = Image.new("RGBA", (WIDTH, HEIGHT), (0, 0, 0, 0)) # Transparent background
    draw = ImageDraw.Draw(img)
    add_text_with_outline(draw, (WIDTH // 2, HEIGHT // 2), str(number), font_countdown, (255, 255, 255), (0, 0, 0), outline_width=5)
    frame_path = TEMP_DIR / f"countdown_frame_{number}.png"
    img.save(frame_path)

    subprocess.run([
        FFMPEG, "-y",
        "-loop", "1", "-i", str(frame_path),
        "-t", str(duration_per_number),
        "-c:v", "libx264", "-preset", "fast", "-crf", "23",
        "-pix_fmt", "yuva420p", # For alpha channel
        output_path, "-loglevel", "quiet"
    ], check=True)
    Path(frame_path).unlink(missing_ok=True) # Clean up frame


def make_countdown_numbers_video(countdown_duration: float, output_path: str):
    """Creates a video with numbers 3, 2, 1 appearing sequentially."""
    duration_per_number = 1.0 # Each number shows for 1 second
    if countdown_duration < 3:
        print("Warning: Countdown duration is less than 3 seconds, adjusting.")
        duration_per_number = countdown_duration / 3.0

    segment_paths = []
    for i in range(int(countdown_duration), 0, -1): # Count down from countdown_duration (e.g., 3) to 1
        segment_video_path = TEMP_DIR / f"countdown_segment_{i}.mp4"
        _make_single_countdown_number_video(i, duration_per_number, segment_video_path)
        segment_paths.append(str(segment_video_path))

    countdown_list_path = TEMP_DIR / "countdown_video_list.txt"
    with open(countdown_list_path, "w") as f:
        for seg in segment_paths:
            f.write(f"file '{os.path.abspath(seg)}'\n")

    subprocess.run([
        FFMPEG, "-y",
        "-f", "concat", "-safe", "0", "-i", countdown_list_path,
        "-c:v", "libx264", "-preset", "fast", "-crf", "23",
        "-pix_fmt", "yuva420p",
        output_path, "-loglevel", "quiet"
    ], check=True)

    for seg in segment_paths:
        Path(seg).unlink(missing_ok=True)


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
    print(f"  PEXELS_API_KEY set: {'yes' if PEXELS_API_KEY else 'NO — images will be skipped'}")
    print(f"  ffmpeg binary: {FFMPEG}")
    print(f"  Pillow font path: {PILLOW_FONT_PATH}")

    video_segments = []
    audio_segments = []

    # Pre-generate sounds
    print("\nGenerating sound effects...")
    # Ensure these audio files exist in assets/
    if not SUSPENSE_TICK_AUDIO.exists():
        raise FileNotFoundError(f"Missing {SUSPENSE_TICK_AUDIO}. Please place it in assets/.")
    if not FANFARE_AUDIO.exists():
        raise FileNotFoundError(f"Missing {FANFARE_AUDIO}. Please place it in assets/.")
    if not BUZZER_AUDIO.exists():
        raise FileNotFoundError(f"Missing {BUZZER_AUDIO}. Please place it in assets/.")
    
    suspense_tick_dur = get_duration(SUSPENSE_TICK_AUDIO)
    fanfare_dur       = get_duration(FANFARE_AUDIO)
    buzzer_dur        = get_duration(BUZZER_AUDIO)

    # ── INTRO ──
    print("\nBuilding intro...")
    intro_audio = str(TEMP_DIR / "intro_voice.mp3")
    synthesize(script["intro"], intro_audio, voice="af_sarah", speed=1.1)
    intro_dur = get_duration(intro_audio) + 0.5

    intro_card_png = str(TEMP_DIR / "intro_card.png")
    make_title_card_png("THIS OR THAT?", script.get("title", "Food Edition"), intro_card_png)
    intro_video = str(TEMP_DIR / "intro_card_video.mp4")
    make_static_card_video(intro_card_png, intro_dur, intro_video)
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

        # 2. Generate static question card PNG
        q_card_png = str(TEMP_DIR / f"q{n}_card.png")
        make_question_card_png(q["question"], q["option_a"], q["option_b"], n, q_card_png)

        # 3. Convert static question card PNG to video
        # The total duration for the question phase includes voiceover + 3s countdown + buffer
        countdown_visual_duration = 3.0 # Hardcode 3 seconds for visual countdown
        total_q_phase_duration = q_dur + countdown_visual_duration + 0.5
        q_card_base_video = str(TEMP_DIR / f"q{n}_card_base_video.mp4")
        make_static_card_video(q_card_png, total_q_phase_duration, q_card_base_video)

        # 4. Create countdown numbers video (3, 2, 1)
        countdown_numbers_video = str(TEMP_DIR / f"q{n}_countdown_numbers.mp4")
        make_countdown_numbers_video(countdown_visual_duration, countdown_numbers_video)

        # 5. Overlay countdown numbers onto the base question card video
        q_video_with_countdown = str(TEMP_DIR / f"q{n}_card_with_countdown.mp4")
        subprocess.run([FFMPEG, "-y", "-i", q_card_base_video, "-i", countdown_numbers_video,
                        "-filter_complex", f"[0:v][1:v]overlay=(W-w)/2:(H-h)/2:enable='between(t,{q_dur}, {q_dur + countdown_visual_duration})'",
                        "-c:v", "libx264", "-preset", "fast", "-crf", "23", q_video_with_countdown, "-loglevel", "quiet"], check=True)

        # 6. Combine question audio + suspense tick audio (looped)
        q_combined = str(TEMP_DIR / f"q{n}_combined.aac")
        # Mix question audio with looped suspense_tick for the duration of the question phase
        subprocess.run([FFMPEG, "-y", "-i", q_audio, "-stream_loop", "-1", "-i", str(SUSPENSE_TICK_AUDIO),
                        "-filter_complex", f"[0:a]volume=1.0[narr];[1:a]volume=0.3[suspense];[narr][suspense]amix=inputs=2:dropout_transition=2[out]",
                        "-map", "[out]", "-t", str(total_q_phase_duration), "-c:a", "aac", "-b:a", "192k",
                        q_combined, "-loglevel", "quiet"], check=True)

        video_segments.append(q_video_with_countdown)
        audio_segments.append(q_combined)

        # 3. Fetch animal image
        img_path  = str(TEMP_DIR / f"q{n}_image.jpg")
        has_image = fetch_animal_image(q["image_keyword"], img_path)

        # 7. Answer voiceover
        a_text  = f"The answer is... {q['answer']}! {q['explanation']}"
        a_audio = str(TEMP_DIR / f"q{n}_answer.mp3")
        synthesize(a_text, a_audio, voice="af_sarah", speed=1.05)
        a_dur = get_duration(a_audio)

        # 8. Answer card (Pillow-generated PNG)
        answer_card_png = str(TEMP_DIR / f"q{n}_answer_card.png")
        make_answer_card_png(
            answer=q["answer"],
            explanation=q["explanation"],
            image_path=img_path if has_image else None,
            output_path=answer_card_png,
        )
        # Convert answer card PNG to video
        total_a_dur = fanfare_dur + a_dur + 0.8 # Duration includes fanfare + voiceover + buffer
        a_video = str(TEMP_DIR / f"q{n}_answer_card_video.mp4")
        make_static_card_video(answer_card_png, total_a_dur, a_video)

        # 9. Combine fanfare + answer audio
        a_combined = str(TEMP_DIR / f"q{n}_answer_combined.aac")
        concat_audio([str(FANFARE_AUDIO), a_audio], a_combined, silence_between=0)

        video_segments.append(a_video)
        audio_segments.append(a_combined)

        # 10. Fun fact
        if n in fun_facts:
            print(f"  Adding fun fact after Q{n}...")
            ff_text  = f"Fun fact! {fun_facts[n]}"
            ff_audio = str(TEMP_DIR / f"ff_{n}.mp3")
            synthesize(ff_text, ff_audio, voice="af_sarah", speed=1.0)
            ff_dur = get_duration(ff_audio) + buzzer_dur + 0.5 # Duration includes buzzer + voiceover + buffer

            # Pillow-generated fun fact card PNG
            ff_card_png = str(TEMP_DIR / f"ff_{n}_card.png")
            make_funfact_card_png(fun_facts[n], ff_card_png)
            # Convert fun fact card PNG to video
            ff_video = str(TEMP_DIR / f"ff_{n}_card_video.mp4")
            make_static_card_video(ff_card_png, ff_dur, ff_video)

            # Combine buzzer + fun fact audio
            ff_combined_audio = str(TEMP_DIR / f"ff_{n}_combined.aac")
            concat_audio([str(BUZZER_AUDIO), ff_audio], ff_combined_audio, silence_between=0)

            video_segments.append(ff_video)
            audio_segments.append(ff_combined_audio)

    # ── OUTRO ──
    print("\nBuilding outro...")
    outro_audio = str(TEMP_DIR / "outro_voice.mp3")
    synthesize(script["outro"], outro_audio, voice="af_sarah", speed=1.05)
    outro_dur = get_duration(outro_audio) + 0.5

    outro_card_png = str(TEMP_DIR / "outro_card.png")
    make_title_card_png("THANKS FOR PLAYING!", "Like & Subscribe for more!", outro_card_png)
    outro_video = str(TEMP_DIR / "outro_card_video.mp4")
    make_static_card_video(outro_card_png, outro_dur, outro_video)
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
    