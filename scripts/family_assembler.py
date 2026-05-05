"""
Family Channel Video Assembler — Rich Pillow card format.

Every card is generated as a sequence of PNG frames (for animation)
or a single rich PNG, then converted to video with FFmpeg.

Excitement features:
  - Animated countdown (pulsing rings per frame)
  - Slide-in transitions on question options
  - Animal image with slow zoom on answer reveal
  - Confetti-dot pattern on fun facts
  - Bold typography with outlines/shadows
  - Color-coded segments (question=blue, answer=green, funfact=amber)
  - Real sound effects (tick, fanfare, buzzer)
"""

import os
import json
import math
import subprocess
import requests
import textwrap
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont, ImageFilter

PROJECT_ROOT = Path(__file__).parent.parent
OUTPUT_DIR   = PROJECT_ROOT / "output"
TEMP_DIR     = PROJECT_ROOT / "output" / "family_temp"
ASSETS_DIR   = PROJECT_ROOT / "assets"

for d in [OUTPUT_DIR, TEMP_DIR, ASSETS_DIR]:
    d.mkdir(exist_ok=True)

FFMPEG         = os.environ.get("FFMPEG_CMD", "ffmpeg")
PEXELS_API_KEY = os.environ.get("PEXELS_API_KEY", "")

W, H, FPS = 1920, 1080, 30

SFX_TICK    = str(ASSETS_DIR / "suspense_tick.mp3")
SFX_FANFARE = str(ASSETS_DIR / "fanfare.mp3")
SFX_BUZZER  = str(ASSETS_DIR / "buzzer.mp3")

# ── Palette ──────────────────────────────────────────────────────────────────
BG1      = (10,  8,  35)    # very dark navy
BG2      = (25,  8,  55)    # dark purple
ACCENT   = (233, 69, 96)    # hot pink
GOLD     = (255, 210, 60)
OPT_A1   = (10,  40, 100)
OPT_A2   = (20,  80, 180)
OPT_B1   = (60,  20, 110)
OPT_B2   = (110, 50, 190)
GREEN1   = (20, 140,  70)
GREEN2   = (46, 204, 113)
AMBER1   = (180, 100,  0)
AMBER2   = (243, 156, 18)
WHITE    = (255, 255, 255)
OFFWHITE = (230, 230, 245)
GREY     = (160, 160, 180)
BLACK    = (0, 0, 0)
SHADOW   = (0, 0, 0, 180)

# ── Font loader ───────────────────────────────────────────────────────────────
_FONT_PATHS = [
    "/System/Library/Fonts/HelveticaNeue.ttc",
    "/System/Library/Fonts/Helvetica.ttc",
    "/Library/Fonts/Arial Bold.ttf",
    "/Library/Fonts/Arial.ttf",
    "/System/Library/Fonts/Geneva.ttf",
]

def _font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    for path in _FONT_PATHS:
        try:
            idx = 1 if bold and path.endswith(".ttc") else 0
            return ImageFont.truetype(path, size, index=idx)
        except Exception:
            continue
    return ImageFont.load_default()


# ─────────────────────────────────────────────────────────────────────────────
# DRAWING PRIMITIVES
# ─────────────────────────────────────────────────────────────────────────────

def gradient_bg(w: int, h: int, c1: tuple, c2: tuple,
                direction: str = "vertical") -> Image.Image:
    img  = Image.new("RGB", (w, h))
    draw = ImageDraw.Draw(img)
    for i in range(h if direction == "vertical" else w):
        t = i / (h if direction == "vertical" else w)
        r = int(c1[0] + (c2[0]-c1[0]) * t)
        g = int(c1[1] + (c2[1]-c1[1]) * t)
        b = int(c1[2] + (c2[2]-c1[2]) * t)
        if direction == "vertical":
            draw.line([(0, i), (w, i)], fill=(r, g, b))
        else:
            draw.line([(i, 0), (i, h)], fill=(r, g, b))
    return img


def draw_outlined_text(draw: ImageDraw.ImageDraw, pos: tuple, text: str,
                       font: ImageFont.FreeTypeFont, fill: tuple,
                       outline: tuple = BLACK, outline_width: int = 3):
    x, y = pos
    for dx in range(-outline_width, outline_width+1):
        for dy in range(-outline_width, outline_width+1):
            if dx*dx + dy*dy <= outline_width*outline_width:
                draw.text((x+dx, y+dy), text, font=font, fill=outline)
    draw.text((x, y), text, font=font, fill=fill)


def centered_outlined(draw: ImageDraw.ImageDraw, text: str,
                      font: ImageFont.FreeTypeFont, y: int,
                      fill: tuple, w: int,
                      outline: tuple = BLACK, ow: int = 3):
    bbox = draw.textbbox((0, 0), text, font=font)
    x = (w - (bbox[2]-bbox[0])) // 2
    draw_outlined_text(draw, (x, y), text, font, fill, outline, ow)
    return bbox[3] - bbox[1]


def wrapped_centered_outlined(draw: ImageDraw.ImageDraw, text: str,
                               font: ImageFont.FreeTypeFont, y: int,
                               fill: tuple, w: int,
                               max_w: int = 1700, spacing: int = 12,
                               outline: tuple = BLACK, ow: int = 2) -> int:
    words = text.split()
    lines, cur = [], ""
    for word in words:
        test = (cur + " " + word).strip()
        if draw.textbbox((0,0), test, font=font)[2] <= max_w:
            cur = test
        else:
            if cur: lines.append(cur)
            cur = word
    if cur: lines.append(cur)
    cy = y
    for line in lines:
        bbox = draw.textbbox((0,0), line, font=font)
        lh = bbox[3]-bbox[1]
        centered_outlined(draw, line, font, cy, fill, w, outline, ow)
        cy += lh + spacing
    return cy


def accent_bars(draw: ImageDraw.ImageDraw, w: int, h: int,
                color: tuple, thick: int = 16):
    draw.rectangle([0, 0, w, thick], fill=color)
    draw.rectangle([0, h-thick, w, h], fill=color)


def glow_circle(img: Image.Image, cx: int, cy: int, r: int,
                color: tuple, alpha: int = 40):
    overlay = Image.new("RGBA", img.size, (0,0,0,0))
    d = ImageDraw.Draw(overlay)
    for i in range(3):
        ri = r - i*20
        if ri > 0:
            d.ellipse([cx-ri, cy-ri, cx+ri, cy+ri],
                      fill=(*color[:3], alpha//(i+1)))
    return Image.alpha_composite(img.convert("RGBA"), overlay).convert("RGB")


def scattered_dots(draw: ImageDraw.ImageDraw, w: int, h: int,
                   color: tuple, count: int = 50, seed: int = 0):
    import random
    rng = random.Random(seed)
    for _ in range(count):
        x = rng.randint(0, w)
        y = rng.randint(0, h)
        r = rng.randint(2, 6)
        a = rng.randint(30, 120)
        draw.ellipse([x-r, y-r, x+r, y+r], fill=(*color[:3],))


def gradient_rect(img: Image.Image, x1: int, y1: int, x2: int, y2: int,
                  c1: tuple, c2: tuple, radius: int = 20):
    bw, bh = x2-x1, y2-y1
    grad = gradient_bg(bw, bh, c1, c2)
    mask = Image.new("L", (bw, bh), 0)
    md   = ImageDraw.Draw(mask)
    md.rounded_rectangle([0, 0, bw-1, bh-1], radius=radius, fill=255)
    img.paste(grad, (x1, y1), mask=mask)
    # Border
    d = ImageDraw.Draw(img)
    d.rounded_rectangle([x1, y1, x2, y2], radius=radius,
                        outline=(*c2,), width=4, fill=None)


# ─────────────────────────────────────────────────────────────────────────────
# CARD GENERATORS  (return PIL Image)
# ─────────────────────────────────────────────────────────────────────────────

def make_intro_card(title: str, subtitle: str) -> Image.Image:
    img  = gradient_bg(W, H, BG1, BG2)
    img  = glow_circle(img, W//2, H//2, 420, ACCENT, alpha=35)
    img  = glow_circle(img, W//2, H//2, 280, GOLD,   alpha=20)
    draw = ImageDraw.Draw(img)
    accent_bars(draw, W, H, ACCENT, 18)
    scattered_dots(draw, W, H, ACCENT, count=30, seed=1)

    # Decorative rings
    cx, cy = W//2, H//2
    for r, col, w_line in [(380, ACCENT, 3), (300, GOLD, 2), (220, ACCENT, 2)]:
        draw.ellipse([cx-r, cy-r, cx+r, cy+r], outline=col, width=w_line)

    # Main title
    centered_outlined(draw, "THIS OR THAT?", _font(110, bold=True),
                      270, GOLD, W, outline=BLACK, ow=4)

    # Subtitle pill
    sf = _font(48, bold=True)
    bbox = draw.textbbox((0,0), subtitle, font=sf)
    sw = bbox[2]-bbox[0]+60
    draw.rounded_rectangle([W//2-sw//2, 420, W//2+sw//2, 490],
                            radius=35, fill=ACCENT)
    centered_outlined(draw, subtitle, sf, 428, WHITE, W, outline=BLACK, ow=2)

    # Divider
    draw.rectangle([W//2-350, 520, W//2+350, 527], fill=GOLD)

    centered_outlined(draw, "Pause and pick your answer!", _font(38), 545,
                      OFFWHITE, W, outline=BLACK, ow=2)
    centered_outlined(draw, "Keep score — see how you do!", _font(34), 600,
                      GREY, W, outline=BLACK, ow=1)
    return img


def make_question_card(question: str, option_a: str, option_b: str,
                       number: int, total: int,
                       format_label: str = "THIS OR THAT") -> Image.Image:
    img  = gradient_bg(W, H, BG1, BG2)
    img  = glow_circle(img, W//4, H//2, 300, (*OPT_A2,), alpha=25)
    img  = glow_circle(img, 3*W//4, H//2, 300, (*OPT_B2,), alpha=25)
    draw = ImageDraw.Draw(img)
    accent_bars(draw, W, H, ACCENT, 14)
    scattered_dots(draw, W, H, ACCENT, count=15, seed=number)

    # Top bar
    centered_outlined(draw, format_label, _font(52, bold=True), 20, GOLD, W, ow=3)

    # Q badge
    draw.rounded_rectangle([50, 16, 270, 96], radius=30, fill=ACCENT)
    draw.text((66, 26), f"Q {number} of {total}",
              font=_font(32, bold=True), fill=WHITE)

    # Question text
    qf = _font(60, bold=True)
    wrapped_centered_outlined(draw, question, qf, 130, WHITE, W,
                               max_w=1720, spacing=14, ow=3)

    # Option boxes
    gap   = 36
    mid   = W // 2
    by1, by2 = 470, 850

    gradient_rect(img, gap, by1, mid-gap//2, by2, OPT_A1, OPT_A2, radius=28)
    gradient_rect(img, mid+gap//2, by1, W-gap, by2, OPT_B1, OPT_B2, radius=28)
    draw = ImageDraw.Draw(img)

    # A / B labels — big bold pill
    for label, lx in [("A", gap+18), ("B", mid+gap//2+18)]:
        draw.ellipse([lx, by1+16, lx+76, by1+92], fill=ACCENT)
        draw.ellipse([lx+4, by1+20, lx+72, by1+88], fill=BG1)
        lf   = _font(38, bold=True)
        bbox = draw.textbbox((0,0), label, font=lf)
        lw, lh = bbox[2]-bbox[0], bbox[3]-bbox[1]
        draw_outlined_text(draw, (lx+38-lw//2, by1+54-lh//2),
                           label, lf, GOLD, BLACK, 2)

    # Option text
    tf = _font(54, bold=True)
    for text, cx in [(option_a, (gap + mid-gap//2)//2),
                     (option_b, (mid+gap//2 + W-gap)//2)]:
        lines = textwrap.wrap(text, width=13)
        total_h = sum(draw.textbbox((0,0), l, font=tf)[3]+8 for l in lines)
        ty = (by1 + by2) // 2 - total_h // 2 + 16
        for line in lines:
            bbox = draw.textbbox((0,0), line, font=tf)
            lw2  = bbox[2]-bbox[0]
            lh2  = bbox[3]-bbox[1]
            draw_outlined_text(draw, (cx-lw2//2, ty), line, tf, WHITE, BLACK, 3)
            ty += lh2 + 8

    # VS badge
    cx, cy = W//2, (by1+by2)//2
    draw.ellipse([cx-58, cy-58, cx+58, cy+58], fill=ACCENT)
    draw.ellipse([cx-50, cy-50, cx+50, cy+50], fill=BG1)
    vf   = _font(36, bold=True)
    bbox = draw.textbbox((0,0), "VS", font=vf)
    draw_outlined_text(draw,
                       (cx-(bbox[2]-bbox[0])//2, cy-(bbox[3]-bbox[1])//2),
                       "VS", vf, GOLD, BLACK, 2)

    # Bottom hint
    centered_outlined(draw, "Make your choice before the countdown!",
                      _font(30), 878, GREY, W, ow=1)
    return img


def make_countdown_frame(number: int, pulse: float = 1.0) -> Image.Image:
    """
    pulse: 0.0-1.0, controls ring size for animation.
    number: 3=grey, 2=gold, 1=red
    """
    img  = gradient_bg(W, H, BG1, BG2)
    colors = {3: GREY, 2: GOLD, 1: ACCENT}
    color  = colors.get(number, WHITE)

    img = glow_circle(img, W//2, H//2, int(300 * pulse), color, alpha=50)
    draw = ImageDraw.Draw(img)
    accent_bars(draw, W, H, color, 14)
    scattered_dots(draw, W, H, color, count=20, seed=number*7)

    cx, cy = W//2, H//2
    base_r = 220
    pulse_r = int(base_r + 40 * pulse)

    # Animated rings
    draw.ellipse([cx-pulse_r, cy-pulse_r, cx+pulse_r, cy+pulse_r],
                 outline=color, width=10)
    draw.ellipse([cx-base_r+20, cy-base_r+20, cx+base_r-20, cy+base_r-20],
                 outline=color, width=5)

    # Big number
    nf   = _font(220, bold=True)
    bbox = draw.textbbox((0,0), str(number), font=nf)
    nw, nh = bbox[2]-bbox[0], bbox[3]-bbox[1]
    draw_outlined_text(draw, (cx-nw//2, cy-nh//2),
                       str(number), nf, color, BLACK, 6)

    hints = {3: "Think...", 2: "Almost...", 1: "Lock it in!"}
    centered_outlined(draw, hints.get(number, ""), _font(42), cy+240,
                      OFFWHITE, W, ow=2)
    return img


def make_answer_card(answer: str, explanation: str,
                     animal_img: "Image.Image | None",
                     is_both: bool = False) -> Image.Image:
    if animal_img:
        # Fill frame with animal image
        aw, ah = animal_img.size
        scale  = max(W/aw, H/ah)
        nw, nh = int(aw*scale), int(ah*scale)
        bg = animal_img.convert("RGB").resize((nw, nh), Image.LANCZOS)
        x_off = (nw - W) // 2
        y_off = (nh - H) // 2
        bg = bg.crop((x_off, y_off, x_off+W, y_off+H))
        # Dark vignette
        overlay = Image.new("RGB", (W, H), BLACK)
        bg = Image.blend(bg, overlay, alpha=0.50)
    else:
        bg = gradient_bg(W, H, GREEN1, GREEN2)

    draw = ImageDraw.Draw(bg)
    accent_bars(draw, W, H, GREEN2, 14)
    scattered_dots(draw, W, H, GREEN2, count=20, seed=42)

    # Reveal label
    label = "BOTH!" if is_both else "ANSWER!"
    lf    = _font(52, bold=True)
    bbox  = draw.textbbox((0,0), label, font=lf)
    lw    = bbox[2]-bbox[0]+80
    draw.rounded_rectangle([W//2-lw//2, 40, W//2+lw//2, 116],
                            radius=35, fill=GREEN2)
    centered_outlined(draw, label, lf, 52, BLACK, W, outline=BLACK, ow=1)

    # Checkmark + answer
    af   = _font(82, bold=True)
    answer_display = f"✓  {answer}"
    # Answer banner
    draw.rounded_rectangle([60, 155, W-60, 310],
                            radius=28, fill=(0, 0, 0, 200))
    draw.rounded_rectangle([60, 155, W-60, 310],
                            radius=28, outline=GREEN2, width=5, fill=None)
    centered_outlined(draw, answer_display, af, 178, GREEN2, W,
                      outline=BLACK, ow=4)

    # Explanation box
    draw.rounded_rectangle([70, 338, W-70, 760],
                            radius=22, fill=(0, 0, 0, 175))
    draw.rounded_rectangle([70, 338, W-70, 760],
                            radius=22, outline=GREY, width=2, fill=None)

    ef = _font(42)
    wrapped_centered_outlined(draw, explanation, ef, 368, WHITE, W,
                               max_w=1680, spacing=14, ow=2)

    # Bottom encouragement
    centered_outlined(draw, "Did you get it right? 🎯",
                      _font(36), 800, GOLD, W, ow=2)
    return bg


def make_funfact_card(text: str, number: int) -> Image.Image:
    """Bright amber/orange fun fact card with confetti dots."""
    img  = gradient_bg(W, H, AMBER1, AMBER2)
    draw = ImageDraw.Draw(img)
    accent_bars(draw, W, H, GOLD, 16)

    # Confetti dots — multiple colors
    import random
    rng = random.Random(number * 13)
    for _ in range(80):
        x  = rng.randint(0, W)
        y  = rng.randint(0, H)
        r  = rng.randint(4, 14)
        col = rng.choice([ACCENT, WHITE, GOLD, GREEN2, OPT_B2])
        draw.ellipse([x-r, y-r, x+r, y+r], fill=col)

    # Explosion burst lines from center
    cx, cy = W//2, 160
    for angle in range(0, 360, 30):
        rad = math.radians(angle)
        x2  = int(cx + 160 * math.cos(rad))
        y2  = int(cy + 160 * math.sin(rad))
        draw.line([cx, cy, x2, y2], fill=GOLD, width=4)

    # FUN FACT header
    draw.ellipse([W//2-240, 30, W//2+240, 290], fill=BG1)
    draw.ellipse([W//2-225, 45, W//2+225, 275], fill=AMBER1)
    centered_outlined(draw, "FUN", _font(80, bold=True), 60, GOLD, W, ow=3)
    centered_outlined(draw, "FACT!", _font(80, bold=True), 155, WHITE, W, ow=3)

    # Divider
    draw.rectangle([W//2-500, 318, W//2+500, 326], fill=GOLD)

    # Fact text box
    draw.rounded_rectangle([60, 345, W-60, 800],
                            radius=24, fill=(0, 0, 0, 160))
    ef = _font(46)
    wrapped_centered_outlined(draw, text, ef, 375, WHITE, W,
                               max_w=1680, spacing=16, ow=2)

    centered_outlined(draw, "How cool is that?! 🤩", _font(40), 830,
                      GOLD, W, ow=2)
    return img


def make_outro_card(title: str, subtitle: str) -> Image.Image:
    img  = gradient_bg(W, H, BG1, BG2)
    img  = glow_circle(img, W//2, H//2, 450, GOLD,   alpha=30)
    img  = glow_circle(img, W//2, H//2, 300, ACCENT, alpha=20)
    draw = ImageDraw.Draw(img)
    accent_bars(draw, W, H, GOLD, 18)
    scattered_dots(draw, W, H, GOLD, count=60, seed=99)

    cx, cy = W//2, H//2
    for r, col in [(400, GOLD), (320, ACCENT), (240, GOLD)]:
        draw.ellipse([cx-r, cy-r, cx+r, cy+r], outline=col, width=3)

    centered_outlined(draw, title,    _font(92, bold=True), 295, GOLD,  W, ow=5)
    centered_outlined(draw, subtitle, _font(54, bold=True), 425, WHITE, W, ow=3)
    draw.rectangle([W//2-360, 510, W//2+360, 518], fill=ACCENT)
    centered_outlined(draw, "Comment your score below! 👇",
                      _font(40), 538, OFFWHITE, W, ow=2)
    centered_outlined(draw, "LIKE  •  SUBSCRIBE  •  SHARE",
                      _font(38), 596, ACCENT, W, ow=2)
    return img


# ─────────────────────────────────────────────────────────────────────────────
# IMAGE → VIDEO  (static + animated countdown)
# ─────────────────────────────────────────────────────────────────────────────

def img_to_video(img: Image.Image, duration: float, output_path: str,
                 kenburns: bool = False):
    png = output_path.replace(".mp4", "_frame.png")
    img.save(png)

    if kenburns:
        total_frames = max(int(duration * FPS), 2)
        vf = (f"scale={W*2}:{H*2}:force_original_aspect_ratio=increase,"
              f"crop={W*2}:{H*2},"
              f"zoompan=z='min(zoom+0.0004,1.05)':"
              f"x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':"
              f"d={total_frames}:s={W}x{H}:fps={FPS}")
    else:
        vf = (f"scale={W}:{H}:force_original_aspect_ratio=decrease,"
              f"pad={W}:{H}:(ow-iw)/2:(oh-ih)/2:color=black")

    cmd = [FFMPEG, "-y", "-loop", "1", "-i", png,
           "-t", str(duration), "-vf", vf,
           "-c:v", "libx264", "-preset", "fast", "-crf", "23",
           "-pix_fmt", "yuv420p", output_path, "-loglevel", "quiet"]
    result = subprocess.run(cmd, capture_output=True)
    if result.returncode != 0:
        cmd = [FFMPEG, "-y", "-loop", "1", "-i", png,
               "-t", str(duration),
               "-vf", f"scale={W}:{H}",
               "-c:v", "libx264", "-preset", "fast", "-crf", "23",
               "-pix_fmt", "yuv420p", output_path, "-loglevel", "quiet"]
        subprocess.run(cmd, check=True)
    Path(png).unlink(missing_ok=True)


def animated_countdown_video(output_path: str) -> float:
    """
    Build animated countdown: each number gets 8 frames with pulsing ring.
    Total: 3 seconds (8 frames × 3 numbers at ~8fps blended to 30fps).
    """
    frames_dir = TEMP_DIR / "cd_frames"
    frames_dir.mkdir(exist_ok=True)

    frame_idx = 0
    frames_per_num = FPS  # 1 second per number = 30 frames

    for number in [3, 2, 1]:
        for f in range(frames_per_num):
            # pulse oscillates: 0→1→0 over the second
            t     = f / frames_per_num
            pulse = 0.5 + 0.5 * math.sin(t * math.pi * 2)
            img   = make_countdown_frame(number, pulse=pulse)
            img.save(str(frames_dir / f"frame_{frame_idx:04d}.png"))
            frame_idx += 1

    # Compile frames to video
    silent_vid = str(TEMP_DIR / "cd_silent.mp4")
    subprocess.run([
        FFMPEG, "-y",
        "-framerate", str(FPS),
        "-i", str(frames_dir / "frame_%04d.png"),
        "-c:v", "libx264", "-preset", "fast", "-crf", "23",
        "-pix_fmt", "yuv420p",
        silent_vid, "-loglevel", "quiet"
    ], check=True)

    duration = 3.0

    if Path(SFX_TICK).exists():
        subprocess.run([
            FFMPEG, "-y",
            "-i", silent_vid,
            "-stream_loop", "-1", "-i", SFX_TICK,
            "-map", "0:v", "-map", "1:a",
            "-t", str(duration),
            "-c:v", "copy", "-c:a", "aac", "-b:a", "128k",
            output_path, "-loglevel", "quiet"
        ], check=True)
    else:
        import shutil
        shutil.copy(silent_vid, output_path)

    # Cleanup frames
    import shutil
    shutil.rmtree(frames_dir)
    return duration


# ─────────────────────────────────────────────────────────────────────────────
# AUDIO HELPERS
# ─────────────────────────────────────────────────────────────────────────────

def get_duration(path: str) -> float:
    cmd    = ["ffprobe", "-v", "quiet", "-print_format", "json",
              "-show_format", path]
    result = subprocess.run(cmd, capture_output=True, text=True)
    fmt    = json.loads(result.stdout).get("format", {})
    return float(fmt.get("duration", 0))


def make_silence(duration: float, output_path: str):
    subprocess.run([
        FFMPEG, "-y", "-f", "lavfi",
        "-i", "anullsrc=r=44100:cl=stereo",
        "-t", str(duration), output_path, "-loglevel", "quiet"
    ], check=True)


def concat_audio(files: list, output_path: str, gap: float = 0.2):
    sil = str(TEMP_DIR / "sil.wav")
    if gap > 0:
        make_silence(gap, sil)

    inputs = []
    for i, fp in enumerate(files):
        inputs.append(fp)
        if gap > 0 and i < len(files)-1:
            inputs.append(sil)

    cmd = [FFMPEG, "-y"]
    for fp in inputs:
        cmd += ["-i", fp]
    cmd += ["-filter_complex",
            f"concat=n={len(inputs)}:v=0:a=1[out]",
            "-map", "[out]",
            "-c:a", "aac", "-b:a", "192k",
            output_path, "-loglevel", "quiet"]
    subprocess.run(cmd, check=True)


def mux(video: str, audio: str, output: str):
    subprocess.run([
        FFMPEG, "-y", "-i", video, "-i", audio,
        "-map", "0:v", "-map", "1:a",
        "-c:v", "copy", "-c:a", "aac", "-b:a", "192k",
        "-shortest", output, "-loglevel", "quiet"
    ], check=True)


def add_sfx(voice: str, sfx: str, output: str,
            sfx_vol: float = 0.45, voice_vol: float = 1.0):
    if not Path(sfx).exists():
        subprocess.run([FFMPEG, "-y", "-i", voice,
                        "-c:a", "aac", output, "-loglevel", "quiet"],
                       check=True)
        return
    subprocess.run([
        FFMPEG, "-y", "-i", voice, "-i", sfx,
        "-filter_complex",
        f"[0:a]volume={voice_vol}[v];[1:a]volume={sfx_vol}[s];"
        f"[v][s]amix=inputs=2:duration=first:dropout_transition=1[out]",
        "-map", "[out]", "-c:a", "aac", "-b:a", "192k",
        output, "-loglevel", "quiet"
    ], check=True)


# ─────────────────────────────────────────────────────────────────────────────
# PEXELS
# ─────────────────────────────────────────────────────────────────────────────

def fetch_image(keyword: str, output_path: str) -> "Image.Image | None":
    if not PEXELS_API_KEY:
        print(f"  No PEXELS_API_KEY — color card for '{keyword}'")
        return None
    try:
        print(f"  Fetching image: '{keyword}'...")
        headers = {"Authorization": PEXELS_API_KEY}
        url     = (f"https://api.pexels.com/v1/search?query={keyword}"
                   f"&per_page=5&orientation=landscape")
        resp    = requests.get(url, headers=headers, timeout=10)
        resp.raise_for_status()
        photos  = resp.json().get("photos", [])
        if not photos:
            print(f"  No photos for '{keyword}'")
            return None
        data = requests.get(photos[0]["src"]["large2x"], timeout=15).content
        with open(output_path, "wb") as f:
            f.write(data)
        print(f"  Image: {Path(output_path).name}")
        return Image.open(output_path)
    except Exception as e:
        print(f"  Image failed '{keyword}': {e}")
        return None


# ─────────────────────────────────────────────────────────────────────────────
# SEGMENT BUILDERS
# ─────────────────────────────────────────────────────────────────────────────

def build_intro(script: dict, synthesize) -> tuple:
    print("\nBuilding intro...")
    audio = str(TEMP_DIR / "intro_voice.mp3")
    synthesize(script["intro"], audio, voice="af_sarah", speed=1.1)
    dur   = get_duration(audio) + 0.8
    img   = make_intro_card("THIS OR THAT?",
                            script.get("subtitle", script["title"]))
    video = str(TEMP_DIR / "intro.mp4")
    img_to_video(img, dur, video)
    return video, audio


def build_question(q: dict, total: int, synthesize,
                   format_label: str = "THIS OR THAT?") -> tuple:
    n    = q["number"]
    fmt  = format_label
    text = (f"Question {n}. {q['question']} "
            f"Is it... {q['option_a']}... or {q['option_b']}?")

    voice = str(TEMP_DIR / f"q{n}_voice.mp3")
    synthesize(text, voice, voice="af_sarah", speed=1.05)
    v_dur = get_duration(voice)

    img  = make_question_card(q["question"], q["option_a"], q["option_b"],
                              n, total, format_label=fmt)
    qvid = str(TEMP_DIR / f"q{n}_card.mp4")
    img_to_video(img, v_dur + 0.4, qvid)

    # Animated countdown
    cd_vid = str(TEMP_DIR / f"q{n}_countdown.mp4")
    cd_dur = animated_countdown_video(cd_vid)

    # Concat question card + countdown
    vlist = str(TEMP_DIR / f"q{n}_vlist.txt")
    with open(vlist, "w") as f:
        f.write(f"file '{os.path.abspath(qvid)}'\n")
        f.write(f"file '{os.path.abspath(cd_vid)}'\n")

    combined_vid = str(TEMP_DIR / f"q{n}_qseg.mp4")
    subprocess.run([
        FFMPEG, "-y", "-f", "concat", "-safe", "0", "-i", vlist,
        "-c:v", "libx264", "-preset", "fast", "-crf", "23",
        combined_vid, "-loglevel", "quiet"
    ], check=True)

    sil = str(TEMP_DIR / f"q{n}_pad.wav")
    make_silence(cd_dur + 0.4, sil)
    combined_aud = str(TEMP_DIR / f"q{n}_qaudio.aac")
    concat_audio([voice, sil], combined_aud, gap=0.0)
    return combined_vid, combined_aud


def build_answer(q: dict, synthesize) -> tuple:
    n         = q["number"]
    answer    = q["answer"]
    is_both   = answer.strip().lower() in ("both", "neither")
    text      = f"The answer is... {answer}! {q['explanation']}"

    img_path   = str(TEMP_DIR / f"q{n}_img.jpg")
    animal_img = fetch_image(q["image_keyword"], img_path)

    voice = str(TEMP_DIR / f"q{n}_ans_voice.mp3")
    synthesize(text, voice, voice="af_sarah", speed=1.05)
    v_dur = get_duration(voice)

    card_img = make_answer_card(answer, q["explanation"],
                                animal_img, is_both=is_both)
    card_vid = str(TEMP_DIR / f"q{n}_ans_card.mp4")
    img_to_video(card_img, v_dur + 1.2, card_vid, kenburns=bool(animal_img))

    mixed_aud = str(TEMP_DIR / f"q{n}_ans_audio.aac")
    add_sfx(voice, SFX_FANFARE, mixed_aud, sfx_vol=0.40)

    final = str(TEMP_DIR / f"q{n}_ans_seg.mp4")
    mux(card_vid, mixed_aud, final)
    return final, mixed_aud


def build_funfact(text: str, n: int, synthesize) -> tuple:
    print(f"  Fun fact after Q{n}...")
    audio = str(TEMP_DIR / f"ff{n}_voice.mp3")
    synthesize(f"Fun fact! {text}", audio, voice="af_sarah", speed=1.0)
    dur   = get_duration(audio) + 0.8
    img   = make_funfact_card(text, n)
    video = str(TEMP_DIR / f"ff{n}_card.mp4")
    img_to_video(img, dur, video)
    return video, audio


def build_outro(script: dict, synthesize) -> tuple:
    print("\nBuilding outro...")
    audio = str(TEMP_DIR / "outro_voice.mp3")
    synthesize(script["outro"], audio, voice="af_sarah", speed=1.05)
    dur   = get_duration(audio) + 0.8
    img   = make_outro_card("Thanks for watching!",
                            "Like & Subscribe for more!")
    video = str(TEMP_DIR / "outro.mp4")
    img_to_video(img, dur, video)
    return video, audio


# ─────────────────────────────────────────────────────────────────────────────
# MAIN ASSEMBLER
# ─────────────────────────────────────────────────────────────────────────────

def assemble_family_video(script: dict, output_path: str) -> str:
    import sys
    sys.path.insert(0, str(Path(__file__).parent))
    from kokoro_tts import synthesize

    print(f"\n{'='*50}")
    print(f"Family Assembler: {script['title']}")
    print(f"{'='*50}")
    print(f"  ffmpeg:         {FFMPEG}")
    print(f"  PEXELS_API_KEY: {'set' if PEXELS_API_KEY else 'MISSING'}")
    for label, path in [("tick", SFX_TICK), ("fanfare", SFX_FANFARE),
                         ("buzzer", SFX_BUZZER)]:
        print(f"  SFX {label}:{'found' if Path(path).exists() else 'MISSING'}")

    video_segs, audio_segs = [], []
    fun_facts = {ff["after_question"]: ff["text"]
                 for ff in script.get("fun_facts", [])}
    total_q   = len(script["questions"])

    v, a = build_intro(script, synthesize)
    video_segs.append(v); audio_segs.append(a)

    for q in script["questions"]:
        n = q["number"]
        print(f"\nQuestion {n}/{total_q}: {q['question'][:55]}...")
        qv, qa = build_question(q, total_q, synthesize,
                                format_label=script.get("format_label", "THIS OR THAT?"))
        video_segs.append(qv); audio_segs.append(qa)
        av, aa = build_answer(q, synthesize)
        video_segs.append(av); audio_segs.append(aa)
        if n in fun_facts:
            fv, fa = build_funfact(fun_facts[n], n, synthesize)
            video_segs.append(fv); audio_segs.append(fa)

    v, a = build_outro(script, synthesize)
    video_segs.append(v); audio_segs.append(a)

    print(f"\nFinal assembly: {len(video_segs)} segments...")

    vlist = str(TEMP_DIR / "final_vlist.txt")
    with open(vlist, "w") as f:
        for seg in video_segs:
            f.write(f"file '{os.path.abspath(seg)}'\n")

    concat_vid = str(TEMP_DIR / "concat_video.mp4")
    subprocess.run([
        FFMPEG, "-y", "-f", "concat", "-safe", "0", "-i", vlist,
        "-c:v", "libx264", "-preset", "fast", "-crf", "22",
        concat_vid, "-loglevel", "quiet"
    ], check=True)

    concat_aud = str(TEMP_DIR / "concat_audio.aac")
    concat_audio(audio_segs, concat_aud, gap=0.15)

    subprocess.run([
        FFMPEG, "-y", "-i", concat_vid, "-i", concat_aud,
        "-map", "0:v", "-map", "1:a",
        "-c:v", "libx264", "-preset", "medium", "-crf", "20",
        "-c:a", "aac", "-b:a", "192k",
        "-movflags", "+faststart", "-shortest",
        output_path, "-loglevel", "quiet"
    ], check=True)

    size_mb = Path(output_path).stat().st_size / 1024 / 1024
    print(f"\n✓  Done: {output_path} ({size_mb:.1f} MB)")
    return output_path


def cleanup_family_temp():
    import shutil
    if TEMP_DIR.exists():
        shutil.rmtree(TEMP_DIR)
        TEMP_DIR.mkdir()
    print("  Temp files cleaned.")
    