"""
Family Channel Video Assembler — Photo-first card format.

Key design:
  - Question cards show REAL PHOTOS for each option side by side
  - Answer card fills screen with winner photo + ken-burns zoom
  - Fun fact cards use relevant image as background
  - Every segment is a self-contained muxed MP4 (sync guaranteed)
  - Animated countdown with pulsing rings
  - Real SFX: tick during countdown, fanfare on reveal

JSON format additions:
  Each question needs:
    "image_a": "keyword for option A photo"
    "image_b": "keyword for option B photo"
    "image_keyword": "keyword for answer/winner photo"
"""

import os
import json
import math
import subprocess
import requests
import textwrap
import hashlib
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

PROJECT_ROOT = Path(__file__).parent.parent
OUTPUT_DIR   = PROJECT_ROOT / "output"
TEMP_DIR     = PROJECT_ROOT / "temp" / f"family_{os.getpid()}"
ASSETS_DIR   = PROJECT_ROOT / "assets"
CACHE_DIR    = PROJECT_ROOT / "cache_images"

for d in [OUTPUT_DIR, TEMP_DIR.parent, TEMP_DIR, ASSETS_DIR, CACHE_DIR]:
    d.mkdir(exist_ok=True)

FFMPEG         = os.environ.get("FFMPEG_CMD", "ffmpeg")
PEXELS_API_KEY = os.environ.get("PEXELS_API_KEY", "")

W, H, FPS = 1920, 1080, 30

SFX_TICK    = str(ASSETS_DIR / "suspense_tick.mp3")
SFX_FANFARE = str(ASSETS_DIR / "fanfare.mp3")
SFX_BUZZER  = str(ASSETS_DIR / "buzzer.mp3")

# ── Palette ───────────────────────────────────────────────────────────────────
BG1    = (10,   8,  35)
BG2    = (25,   8,  55)
ACCENT = (233,  69,  96)
GOLD   = (255, 210,  60)
OPT_A  = (20,   60, 160)   # blue tint for A label
OPT_B  = (100,  30, 180)   # purple tint for B label
GREEN1 = (20,  140,  70)
GREEN2 = (46,  204, 113)
AMBER1 = (160,  85,   0)
AMBER2 = (243, 156,  18)
WHITE  = (255, 255, 255)
GREY   = (160, 160, 180)
BLACK  = (0,   0,   0)


# ── Fonts ─────────────────────────────────────────────────────────────────────
_FONT_PATHS = [
    "/System/Library/Fonts/HelveticaNeue.ttc",
    "/System/Library/Fonts/Helvetica.ttc",
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

# ── Helper to create md5 hash for keywords to avoid redundant downloads
def _cache_path(keyword: str) -> str:
    key = hashlib.md5(keyword.encode()).hexdigest()
    return CACHE_DIR / f"{key}.jpg"
    
# ── Audio Normalization ────────────────────────────────────────────────────

def normalize_audio_to_wav(input_path: str, output_path: str):
    subprocess.run([
        FFMPEG, "-y", "-i", input_path,
        "-ar", "48000",
        "-ac", "2",
        "-c:a", "pcm_s16le",
        output_path,
        "-loglevel", "error"
    ], check=True)

# ── Add Background Music ──────────────────────────────────────────────────

def add_bg_music(video_in: str, music: str, output: str):
    subprocess.run([
        FFMPEG,"-y",
        "-i", video_in,
        "-stream_loop","-1","-i", music,
        "-filter_complex",
        "[0:a]volume=1[a0];"
        "[1:a]volume=0.07[a1];"
        "[a0][a1]amix=inputs=2:duration=first:dropout_transition=2,volume=2[out]",
        "-map","0:v","-map","[out]",
        "-c:v","copy",
        "-c:a","aac","-b:a","192k",
        output
    ],check=True)

# ─────────────────────────────────────────────────────────────────────────────
# PEXELS — fetch single image, return PIL Image or None
# ─────────────────────────────────────────────────────────────────────────────

def fetch_image(keyword: str, output_path: str,
                orientation: str = "landscape") -> "Image.Image | None":
    cache = _cache_path(keyword)
    if cache.exists():
        return Image.open(cache).convert("RGB")
    if not PEXELS_API_KEY:
        return None
    try:
        print(f"    Pexels: '{keyword}'...")
        headers = {"Authorization": PEXELS_API_KEY}
        resp    = requests.get(
            f"https://api.pexels.com/v1/search"
            f"?query={keyword}&per_page=5&orientation={orientation}",
            headers=headers, timeout=10)
        resp.raise_for_status()
        photos = resp.json().get("photos", [])
        if not photos:
            print(f"    No photos for '{keyword}'")
            return None
        import random
        photo = random.choice(photos[:3])
        data = requests.get(photo["src"]["large2x"], timeout=15).content
        with open(output_path, "wb") as f:
            f.write(data)
        return Image.open(output_path).convert("RGB")
    except Exception as e:
        print(f"    Fetch failed '{keyword}': {e}")
        return None


def fit_image(img: Image.Image, w: int, h: int) -> Image.Image:
    """Scale and centre-crop image to exactly w×h."""
    ow, oh = img.size
    scale  = max(w/ow, h/oh)
    nw, nh = int(ow*scale), int(oh*scale)
    img    = img.resize((nw, nh), Image.LANCZOS)
    xo     = (nw-w)//2
    yo     = (nh-h)//2
    return img.crop((xo, yo, xo+w, yo+h))


# ─────────────────────────────────────────────────────────────────────────────
# DRAWING HELPERS
# ─────────────────────────────────────────────────────────────────────────────

def gradient_bg(w: int, h: int, c1: tuple, c2: tuple) -> Image.Image:
    img  = Image.new("RGB", (w, h))
    draw = ImageDraw.Draw(img)
    for y in range(h):
        t = y / h
        draw.line([(0,y),(w,y)], fill=tuple(
            int(c1[i]+(c2[i]-c1[i])*t) for i in range(3)))
    return img


def dark_overlay(img: Image.Image, alpha: int = 120) -> Image.Image:
    """Darken image by blending with black at given alpha (0-255)."""
    ov = Image.new("RGBA", img.size, (0, 0, 0, alpha))
    return Image.alpha_composite(img.convert("RGBA"), ov).convert("RGB")


def semi_rect(img: Image.Image,
              x1: int, y1: int, x2: int, y2: int,
              color: tuple, alpha: int = 180, radius: int = 20,
              border: tuple = None, border_w: int = 3):
    """Draw a semi-transparent rounded rectangle on img (in-place)."""
    ov = Image.new("RGBA", img.size, (0,0,0,0))
    d  = ImageDraw.Draw(ov)
    d.rounded_rectangle([x1,y1,x2,y2], radius=radius,
                        fill=(*color[:3], alpha),
                        outline=(*border[:3],255) if border else None,
                        width=border_w if border else 0)
    result = Image.alpha_composite(img.convert("RGBA"), ov)
    return result.convert("RGB")


def outlined_text(draw: ImageDraw.ImageDraw,
                  x: int, y: int, text: str,
                  font: ImageFont.FreeTypeFont,
                  fill: tuple, outline: tuple = BLACK, ow: int = 3):
    for dx in range(-ow, ow+1):
        for dy in range(-ow, ow+1):
            if dx*dx+dy*dy <= ow*ow:
                draw.text((x+dx,y+dy), text, font=font, fill=outline)
    draw.text((x,y), text, font=font, fill=fill)


def centered_text(draw: ImageDraw.ImageDraw, text: str,
                  font: ImageFont.FreeTypeFont, y: int,
                  fill: tuple, w: int,
                  outline: tuple = BLACK, ow: int = 3) -> int:
    bbox = draw.textbbox((0,0), text, font=font)
    x    = (w-(bbox[2]-bbox[0]))//2
    outlined_text(draw, x, y, text, font, fill, outline, ow)
    return bbox[3]-bbox[1]


def wrapped_text(draw: ImageDraw.ImageDraw, text: str,
                 font: ImageFont.FreeTypeFont, y: int,
                 fill: tuple, w: int, max_w: int = 1700,
                 spacing: int = 10, outline: tuple = BLACK,
                 ow: int = 2) -> int:
    words = text.split()
    lines, cur = [], ""
    for word in words:
        test = (cur+" "+word).strip()
        if draw.textbbox((0,0),test,font=font)[2] <= max_w:
            cur = test
        else:
            if cur: lines.append(cur)
            cur = word
    if cur: lines.append(cur)
    cy = y
    for line in lines:
        lh = centered_text(draw, line, font, cy, fill, w, outline, ow)
        cy += lh+spacing
    return cy


def glow_circle(img: Image.Image, cx: int, cy: int,
                r: int, color: tuple, alpha: int = 40) -> Image.Image:
    ov = Image.new("RGBA", img.size, (0,0,0,0))
    d  = ImageDraw.Draw(ov)
    for i in range(4):
        ri = r - i*16
        if ri > 0:
            d.ellipse([cx-ri,cy-ri,cx+ri,cy+ri],
                      fill=(*color[:3], max(alpha//(i+1),4)))
    return Image.alpha_composite(img.convert("RGBA"), ov).convert("RGB")


def accent_bars(draw: ImageDraw.ImageDraw, color: tuple, thick: int = 14):
    draw.rectangle([0,0,W,thick], fill=color)
    draw.rectangle([0,H-thick,W,H], fill=color)


def dots(draw: ImageDraw.ImageDraw, colors: list,
         count: int = 30, seed: int = 0):
    import random
    rng = random.Random(seed)
    for _ in range(count):
        x   = rng.randint(0,W)
        y   = rng.randint(0,H)
        r   = rng.randint(3,9)
        col = rng.choice(colors)
        draw.ellipse([x-r,y-r,x+r,y+r], fill=col)


# ─────────────────────────────────────────────────────────────────────────────
# CARD GENERATORS
# ─────────────────────────────────────────────────────────────────────────────

def make_intro_card(format_label: str, subtitle: str) -> Image.Image:
    img  = gradient_bg(W, H, BG1, BG2)
    img  = glow_circle(img, W//2, H//2, 430, ACCENT, alpha=38)
    img  = glow_circle(img, W//2, H//2, 260, GOLD,   alpha=20)
    draw = ImageDraw.Draw(img)
    accent_bars(draw, ACCENT, 18)
    dots(draw, [ACCENT, GOLD], count=22, seed=1)

    cx, cy = W//2, H//2
    for r, col, lw in [(395,ACCENT,3),(310,GOLD,2),(225,ACCENT,2)]:
        draw.ellipse([cx-r,cy-r,cx+r,cy+r], outline=col, width=lw)

    centered_text(draw, format_label, _font(96,bold=True), 282, GOLD,  W, ow=5)

    sf   = _font(44, bold=True)
    bbox = draw.textbbox((0,0), subtitle, font=sf)
    sw   = bbox[2]-bbox[0]+72
    draw.rounded_rectangle([W//2-sw//2,418,W//2+sw//2,490],
                           radius=36, fill=ACCENT)
    centered_text(draw, subtitle, sf, 428, WHITE, W, outline=BLACK, ow=2)

    draw.rectangle([W//2-340,520,W//2+340,527], fill=GOLD)
    centered_text(draw, "Pause and pick before the reveal!",
                  _font(34), 546, GREY, W, outline=BLACK, ow=1)
    return img


def make_question_card(question: str, option_a: str, option_b: str,
                       number: int, total: int,
                       img_a: "Image.Image | None",
                       img_b: "Image.Image | None",
                       format_label: str = "THIS OR THAT?") -> Image.Image:
    """
    Split-screen question card.
    Left half = option A photo (or gradient), right half = option B photo.
    Question text floats at the top over a dark band.
    """
    # Half dimensions
    half_w  = W // 2
    gap     = 8   # thin divider between halves

    # ── Left side (Option A) ──────────────────────────────────────────────────
    if img_a:
        left = fit_image(img_a, half_w - gap//2, H)
        left = dark_overlay(left, alpha=100)
    else:
        left = gradient_bg(half_w - gap//2, H, OPT_A, (40,80,180))

    # ── Right side (Option B) ─────────────────────────────────────────────────
    if img_b:
        right = fit_image(img_b, half_w - gap//2, H)
        right = dark_overlay(right, alpha=100)
    else:
        right = gradient_bg(half_w - gap//2, H, OPT_B, (140,50,220))

    # ── Compose onto canvas ───────────────────────────────────────────────────
    canvas = Image.new("RGB", (W, H), BLACK)
    canvas.paste(left,  (0, 0))
    canvas.paste(right, (half_w + gap//2, 0))

    # Centre divider
    d_tmp = ImageDraw.Draw(canvas)
    d_tmp.rectangle([half_w-gap//2, 0, half_w+gap//2, H], fill=BLACK)

    # ── Top question band ─────────────────────────────────────────────────────
    semi_rect(canvas, 0, 0, W, 170, BLACK, alpha=200, radius=0)
    draw = ImageDraw.Draw(canvas)

    # Format label + Q badge
    centered_text(draw, format_label, _font(42,bold=True), 8, GOLD, W, ow=3)
    draw.rounded_rectangle([48,4,265,76], radius=26, fill=ACCENT)
    draw.text((62,14), f"Q {number} / {total}",
              font=_font(30,bold=True), fill=WHITE)

    # Question text
    wrapped_text(draw, question, _font(52,bold=True), 75, WHITE, W,
                 max_w=1720, spacing=10, ow=3)

    # ── Option labels (bottom of each half) ───────────────────────────────────
    label_y1, label_y2 = H-130, H-10
    # A label band
    semi_rect(canvas, 0, label_y1, half_w-gap//2, label_y2,
              OPT_A, alpha=210, radius=0)
    # B label band
    semi_rect(canvas, half_w+gap//2, label_y1, W, label_y2,
              OPT_B, alpha=210, radius=0)

    draw = ImageDraw.Draw(canvas)

    # A circle badge
    ax = (half_w-gap//2)//2
    draw.ellipse([ax-44, label_y1+6, ax+44, label_y1+94], fill=ACCENT)
    draw.ellipse([ax-38, label_y1+12, ax+38, label_y1+88], fill=BG1)
    af   = _font(40, bold=True)
    bbox = draw.textbbox((0,0),"A",font=af)
    outlined_text(draw, ax-(bbox[2]-bbox[0])//2,
                  label_y1+50-(bbox[3]-bbox[1])//2,
                  "A", af, GOLD, BLACK, 2)

    # Option A text
    tf = _font(44, bold=True)
    a_lines = textwrap.wrap(option_a, width=16)
    a_total = sum(draw.textbbox((0,0),l,font=tf)[3]+6 for l in a_lines)
    ay = label_y1 + 100//2 - a_total//2 + 6
    for line in a_lines:
        bbox = draw.textbbox((0,0),line,font=tf)
        lw   = bbox[2]-bbox[0]
        outlined_text(draw, ax-lw//2, ay, line, tf, WHITE, BLACK, 3)
        ay  += bbox[3]-bbox[1]+6

    # B circle badge
    bx = half_w + gap//2 + (half_w-gap//2)//2
    draw.ellipse([bx-44, label_y1+6, bx+44, label_y1+94], fill=ACCENT)
    draw.ellipse([bx-38, label_y1+12, bx+38, label_y1+88], fill=BG1)
    bbox = draw.textbbox((0,0),"B",font=af)
    outlined_text(draw, bx-(bbox[2]-bbox[0])//2,
                  label_y1+50-(bbox[3]-bbox[1])//2,
                  "B", af, GOLD, BLACK, 2)

    # Option B text
    b_lines = textwrap.wrap(option_b, width=16)
    b_total = sum(draw.textbbox((0,0),l,font=tf)[3]+6 for l in b_lines)
    by = label_y1 + 100//2 - b_total//2 + 6
    for line in b_lines:
        bbox = draw.textbbox((0,0),line,font=tf)
        lw   = bbox[2]-bbox[0]
        outlined_text(draw, bx-lw//2, by, line, tf, WHITE, BLACK, 3)
        by  += bbox[3]-bbox[1]+6

    # VS badge in centre
    cx, cy = W//2, H//2
    draw.ellipse([cx-56,cy-56,cx+56,cy+56], fill=ACCENT)
    draw.ellipse([cx-48,cy-48,cx+48,cy+48], fill=BG1)
    vf   = _font(32, bold=True)
    bbox = draw.textbbox((0,0),"VS",font=vf)
    outlined_text(draw, cx-(bbox[2]-bbox[0])//2,
                  cy-(bbox[3]-bbox[1])//2, "VS", vf, GOLD, BLACK, 2)

    return canvas


def make_countdown_frame(number: int, pulse: float = 1.0) -> Image.Image:
    colors = {3: GREY, 2: GOLD, 1: ACCENT}
    color  = colors.get(number, WHITE)

    img  = gradient_bg(W, H, BG1, BG2)
    img  = glow_circle(img, W//2, H//2, int(290*pulse), color, alpha=55)
    draw = ImageDraw.Draw(img)
    accent_bars(draw, color, 14)
    dots(draw, [color], count=16, seed=number*7)

    cx, cy  = W//2, H//2
    base_r  = 215
    pulse_r = int(base_r + 48*pulse)
    draw.ellipse([cx-pulse_r,cy-pulse_r,cx+pulse_r,cy+pulse_r],
                 outline=color, width=10)
    draw.ellipse([cx-base_r+20,cy-base_r+20,cx+base_r-20,cy+base_r-20],
                 outline=color, width=5)

    nf   = _font(220, bold=True)
    bbox = draw.textbbox((0,0), str(number), font=nf)
    nw, nh = bbox[2]-bbox[0], bbox[3]-bbox[1]
    outlined_text(draw, cx-nw//2, cy-nh//2,
                  str(number), nf, color, BLACK, 7)

    hints = {3:"Think carefully...", 2:"Almost time...", 1:"Lock it in!"}
    centered_text(draw, hints.get(number,""), _font(38), cy+232,
                  WHITE, W, outline=BLACK, ow=2)
    return img


def make_answer_card(answer: str, explanation: str,
                     winner_img: "Image.Image | None",
                     is_both: bool = False) -> Image.Image:
    """
    Full-screen winner photo with answer overlay.
    If no image, falls back to green gradient.
    """
    if winner_img:
        bg = fit_image(winner_img, W, H)
        bg = dark_overlay(bg, alpha=115)
    else:
        bg = gradient_bg(W, H, GREEN1, GREEN2)

    draw = ImageDraw.Draw(bg)
    accent_bars(draw, GREEN2, 14)

    # Answer banner
    label = "BOTH! ✓" if is_both else f"✓  {answer}"
    semi_rect(bg, 50, 28, W-50, 132, GREEN2,
              alpha=215, radius=30, border=GOLD, border_w=4)
    draw = ImageDraw.Draw(bg)
    centered_text(draw, label, _font(76,bold=True), 46,
                  BLACK, W, outline=GREEN2, ow=1)

    # Explanation box
    semi_rect(bg, 55, 155, W-55, 590, BLACK,
              alpha=168, radius=22, border=GREEN2, border_w=3)
    draw = ImageDraw.Draw(bg)
    wrapped_text(draw, explanation, _font(44), 180, WHITE, W,
                 max_w=1680, spacing=14, ow=2)

    # Bottom prompt
    semi_rect(bg, W//2-420, 618, W//2+420, 688, BLACK, alpha=130, radius=20)
    draw = ImageDraw.Draw(bg)
    centered_text(draw, "Did you get it right? 🎯",
                  _font(36), 632, GOLD, W, outline=BLACK, ow=2)
    return bg


def make_funfact_card(text: str, number: int,
                      bg_img: "Image.Image | None" = None) -> Image.Image:
    if bg_img:
        img = fit_image(bg_img, W, H)
        img = dark_overlay(img, alpha=160)
    else:
        img = gradient_bg(W, H, AMBER1, AMBER2)

    draw = ImageDraw.Draw(img)
    accent_bars(draw, GOLD, 16)

    # Confetti
    import random
    rng = random.Random(number*17)
    for _ in range(60):
        x   = rng.randint(0,W)
        y   = rng.randint(0,H)
        r   = rng.randint(4,12)
        col = rng.choice([ACCENT,WHITE,GOLD,GREEN2,(255,100,100)])
        draw.ellipse([x-r,y-r,x+r,y+r], fill=col)

    # Burst
    cx, cy = W//2, 155
    for angle in range(0,360,24):
        rad = math.radians(angle)
        draw.line([cx,cy,int(cx+165*math.cos(rad)),
                   int(cy+165*math.sin(rad))], fill=GOLD, width=4)

    # FUN FACT badge
    draw.ellipse([W//2-252,28,W//2+252,290], fill=BG1)
    draw.ellipse([W//2-238,42,W//2+238,276], fill=(*AMBER1,))
    centered_text(draw,"FUN",  _font(76,bold=True), 58, GOLD,  W, ow=3)
    centered_text(draw,"FACT!",_font(76,bold=True),150, WHITE, W, ow=3)

    draw.rectangle([W//2-530,318,W//2+530,326], fill=GOLD)

    semi_rect(img, 52,342,W-52,820, BLACK, alpha=162, radius=22)
    draw = ImageDraw.Draw(img)
    wrapped_text(draw, text, _font(46), 370, WHITE, W,
                 max_w=1680, spacing=16, ow=2)

    centered_text(draw,"How cool is that?! 🤩",
                  _font(36),842,GOLD,W,outline=BLACK,ow=2)
    return img


def make_outro_card() -> Image.Image:
    img  = gradient_bg(W, H, BG1, BG2)
    img  = glow_circle(img, W//2, H//2, 455, GOLD,   alpha=32)
    img  = glow_circle(img, W//2, H//2, 300, ACCENT, alpha=20)
    draw = ImageDraw.Draw(img)
    accent_bars(draw, GOLD, 18)
    dots(draw,[GOLD,ACCENT,WHITE], count=55, seed=99)

    cx, cy = W//2, H//2
    for r,col,lw in [(405,GOLD,3),(320,ACCENT,2),(238,GOLD,2)]:
        draw.ellipse([cx-r,cy-r,cx+r,cy+r], outline=col, width=lw)

    centered_text(draw,"Thanks for watching!", _font(86,bold=True),
                  300, GOLD,  W, ow=5)
    centered_text(draw,"Like & Subscribe for more!", _font(50,bold=True),
                  432, WHITE, W, ow=3)
    draw.rectangle([W//2-360,514,W//2+360,522], fill=ACCENT)
    centered_text(draw,"Drop your score in the comments! 👇",
                  _font(36),540,WHITE,W,outline=BLACK,ow=2)
    centered_text(draw,"LIKE  •  SUBSCRIBE  •  SHARE",
                  _font(34),596,ACCENT,W,outline=BLACK,ow=2)
    return img


# ─────────────────────────────────────────────────────────────────────────────
# IMAGE → VIDEO
# ─────────────────────────────────────────────────────────────────────────────

def img_to_video(img: Image.Image, duration: float, output_path: str,
                 kenburns: bool = False):
    png = output_path.replace(".ts","_src.png")
    img.save(png)

    if kenburns:
        nf = max(round(duration*FPS),2)
        vf = (f"scale={W*2}:{H*2}:force_original_aspect_ratio=increase,"
              f"crop={W*2}:{H*2},"
              f"zoompan=z='min(zoom+0.0015,1.12)':"
              f"x='if(eq(on,1),rand(0,iw-iw/zoom),x)':"
              f"d={nf}:s={W}x{H}:fps={FPS}")
    else:
        vf = (f"scale={W}:{H}:force_original_aspect_ratio=decrease,"
              f"pad={W}:{H}:(ow-iw)/2:(oh-ih)/2:color=black")

    cmd = [
        FFMPEG,"-y",
        "-loop","1","-framerate",str(FPS),"-i",png,
        "-t",str(duration),
        "-vf", vf + f",fps={FPS}",
        "-r", str(FPS),
        "-vsync","cfr",
        "-c:v","libx264","-preset","fast","-crf","23",
        "-pix_fmt","yuv420p",
        "-an",
        output_path,
        "-loglevel","error"
    ]
    r = subprocess.run(cmd, capture_output=True)
    if r.returncode != 0:
        subprocess.run([FFMPEG,"-y","-loop","1","-i",png,
                        "-t",str(duration),"-vf",f"scale={W}:{H}",
                        "-c:v","libx264","-preset","fast","-crf","23",
                        "-pix_fmt","yuv420p","-an",output_path,"-loglevel","error"],
                       check=True)
    Path(png).unlink(missing_ok=True)


def animated_countdown(vid_out: str, aud_out: str) -> float:
    frames_dir = TEMP_DIR / "cd_frames"
    frames_dir.mkdir(exist_ok=True)

    idx = 0
    for number in [3,2,1]:
        for f in range(FPS):
            t     = f/FPS
            pulse = 0.5+0.5*math.sin(t*math.pi*2)
            make_countdown_frame(number,pulse).save(
                str(frames_dir/f"f{idx:04d}.png"))
            idx += 1

    subprocess.run([FFMPEG,"-y","-framerate",str(FPS),
                    "-i",str(frames_dir/"f%04d.png"),
                    "-c:v","libx264","-preset","fast","-crf","23",
                    "-pix_fmt","yuv420p","-an",vid_out,"-loglevel","error"],
                   check=True)

    duration = 3.0
    build_audio_track(None, duration, aud_out, sfx=SFX_TICK, sfx_vol=1.0)

    import shutil; shutil.rmtree(frames_dir)
    return duration


# ─────────────────────────────────────────────────────────────────────────────
# AUDIO HELPERS
# ─────────────────────────────────────────────────────────────────────────────

def get_duration(path: str) -> float:
    FFPROBE = os.environ.get("FFPROBE_CMD", "ffprobe")
    r = subprocess.run([FFPROBE,"-v","error","-print_format","json",
                        "-show_format",path],
                       capture_output=True,text=True)
    return float(json.loads(r.stdout).get("format",{}).get("duration",0))


def frame_dur(dur: float) -> float:
    """Round duration up to the nearest video frame boundary to ensure A/V sync."""
    return math.ceil(dur * FPS) / FPS


def silence(dur: float, out: str):
    subprocess.run([FFMPEG,"-y","-f","lavfi",
                    "-i","anullsrc=r=48000:cl=stereo",
                    "-t",str(dur),"-c:a","pcm_s16le",out,"-loglevel","error"],check=True)


def build_audio_track(voice: str, duration: float, output_wav: str,
                      sfx: str = None, sfx_vol: float = 0.35):
    """Mix voice and optional SFX over a perfectly sized silent pad."""
    pad = str(TEMP_DIR/"pad.wav")
    silence(duration, pad)

    inputs = ["-i", pad]
    filter_complex = ""
    
    if voice and Path(voice).exists():
        v_norm = str(TEMP_DIR/"v_norm.wav")
        normalize_audio_to_wav(voice, v_norm)
        inputs.extend(["-i", v_norm])
        filter_complex += "[1:a]volume=1.0[v]; "
        mix_inputs = "[0:a][v]"
        mix_count = 2
    else:
        mix_inputs = "[0:a]"
        mix_count = 1

    if sfx and Path(sfx).exists():
        s_norm = str(TEMP_DIR/"s_norm.wav")
        normalize_audio_to_wav(sfx, s_norm)
        inputs.extend(["-i", s_norm])
        idx = len(inputs)//2 - 1
        filter_complex += f"[{idx}:a]volume={sfx_vol}[s]; "
        mix_inputs += "[s]"
        mix_count += 1
        
    if mix_count > 1:
        filter_complex += f"{mix_inputs}amix=inputs={mix_count}:duration=first:dropout_transition=1[out]"
        map_args = ["-map", "[out]"]
    else:
        filter_complex = None
        map_args = ["-map", "0:a"]

    cmd = [FFMPEG, "-y"] + inputs
    if filter_complex:
        cmd.extend(["-filter_complex", filter_complex])
    cmd.extend(map_args)
    cmd.extend(["-c:a", "pcm_s16le", output_wav, "-loglevel", "error"])
    
    subprocess.run(cmd, check=True)


# ─────────────────────────────────────────────────────────────────────────────
# SEGMENT BUILDERS — each returns a single muxed MP4
# ─────────────────────────────────────────────────────────────────────────────

def build_intro(script: dict, synth) -> tuple[str, str]:
    print("\nBuilding intro...")
    fmt   = script.get("format_label","THIS OR THAT?")
    sub   = script.get("subtitle", script["title"])
    voice = str(TEMP_DIR/"intro_voice.m4a")
    synth(script["intro"], voice, voice="af_sarah", speed=1.1)
    dur   = frame_dur(get_duration(voice)+0.5)

    video = str(TEMP_DIR/"intro_silent.ts")
    img_to_video(make_intro_card(fmt, sub), dur, video)
    
    audio = str(TEMP_DIR/"intro_audio.wav")
    build_audio_track(voice, dur, audio)
    
    return video, audio


def build_question(q: dict, total: int, synth,
                   format_label: str = "THIS OR THAT?") -> list[tuple[str, str]]:
    n    = q["number"]
    text = (f"Question {n}. {q['question']} "
            f"{q['option_a']}... or {q['option_b']}?")

    print(f"  Fetching option images...")
    img_a = fetch_image(q.get("image_a", q["option_a"]),
                        str(TEMP_DIR/f"q{n}_img_a.jpg"))
    img_b = fetch_image(q.get("image_b", q["option_b"]),
                        str(TEMP_DIR/f"q{n}_img_b.jpg"))

    voice = str(TEMP_DIR/f"q{n}_voice.m4a")
    synth(text, voice, voice="af_sarah", speed=1.05)
    v_dur = frame_dur(get_duration(voice) + 0.3)

    q_vid = str(TEMP_DIR/f"q{n}_card_silent.ts")
    img_to_video(
        make_question_card(q["question"],q["option_a"],q["option_b"],
                           n, total, img_a, img_b, format_label),
        v_dur, q_vid, kenburns=True)
        
    q_aud = str(TEMP_DIR/f"q{n}_card_audio.wav")
    build_audio_track(voice, v_dur, q_aud)

    cd_vid = str(TEMP_DIR/f"q{n}_cd.ts")
    cd_aud = str(TEMP_DIR/f"q{n}_cd.wav")
    animated_countdown(cd_vid, cd_aud)

    return [(q_vid, q_aud), (cd_vid, cd_aud)]


def build_answer(q: dict, synth) -> tuple[str, str]:
    n       = q["number"]
    answer  = q["answer"]
    is_both = answer.strip().lower() in ("both","neither")
    text    = f"The answer is... {answer}! {q['explanation']}"

    # Fetch winner image — use image_keyword for the answer
    winner_img = fetch_image(
        q.get("image_keyword", answer+" food"),
        str(TEMP_DIR/f"q{n}_winner.jpg"))

    voice = str(TEMP_DIR/f"q{n}_ans_voice.m4a")
    synth(text, voice, voice="af_sarah", speed=1.0)
    v_dur = frame_dur(get_duration(voice) + 1.0)

    card  = make_answer_card(answer, q["explanation"], winner_img, is_both)
    c_vid = str(TEMP_DIR/f"q{n}_ans_silent.ts")
    img_to_video(card, v_dur, c_vid, kenburns=bool(winner_img))
    
    c_aud = str(TEMP_DIR/f"q{n}_ans_audio.wav")
    build_audio_track(voice, v_dur, c_aud, sfx=SFX_FANFARE, sfx_vol=0.35)

    return c_vid, c_aud


def build_funfact(text: str, n: int, synth) -> tuple[str, str]:
    print(f"  Fun fact after Q{n}...")
    voice = str(TEMP_DIR/f"ff{n}_voice.m4a")
    synth(f"Fun fact! {text}", voice, voice="af_sarah", speed=0.95)
    dur   = frame_dur(get_duration(voice)+0.5)

    # Try to fetch a relevant image for fun fact background
    import re
    words = re.findall(r'\w+', text.lower())
    keyword = next((w for w in words if len(w) > 4), "nature")
    bg_img  = fetch_image(keyword, str(TEMP_DIR/f"ff{n}_bg.jpg"))

    video = str(TEMP_DIR/f"ff{n}_silent.ts")
    img_to_video(make_funfact_card(text, n, bg_img), dur, video, kenburns=True)

    audio = str(TEMP_DIR/f"ff{n}_audio.wav")
    build_audio_track(voice, dur, audio)

    return video, audio


def build_outro(script: dict, synth) -> tuple[str, str]:
    print("\nBuilding outro...")
    voice = str(TEMP_DIR/"outro_voice.m4a")
    synth(script["outro"], voice, voice="af_sarah", speed=1.05)
    dur   = frame_dur(get_duration(voice)+0.5)

    video = str(TEMP_DIR/"outro_silent.ts")
    img_to_video(make_outro_card(), dur, video)

    audio = str(TEMP_DIR/"outro_audio.wav")
    build_audio_track(voice, dur, audio)

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
    print(f"  PEXELS_API_KEY: {'set ✓' if PEXELS_API_KEY else 'MISSING ✗'}")
    for lbl,p in [("tick",SFX_TICK),("fanfare",SFX_FANFARE),("buzzer",SFX_BUZZER)]:
        print(f"  SFX {lbl}: {'✓' if Path(p).exists() else '✗ missing'}")

    fmt       = script.get("format_label","THIS OR THAT?")
    fun_facts = {ff["after_question"]: ff["text"]
                 for ff in script.get("fun_facts",[])}
    total_q   = len(script["questions"])
    segments  = []

    segments.append(build_intro(script, synthesize))

    for q in script["questions"]:
        n = q["number"]
        print(f"\nQuestion {n}/{total_q}: {q['question'][:55]}...")
        for pair in build_question(q, total_q, synthesize, format_label=fmt):
            segments.append(pair)
        segments.append(build_answer(q, synthesize))
        if n in fun_facts:
            segments.append(build_funfact(fun_facts[n], n, synthesize))

    segments.append(build_outro(script, synthesize))

    print(f"\nFinal concat: {len(segments)} segment pairs...")
    vlist = str(TEMP_DIR/"final_v.txt")
    alist = str(TEMP_DIR/"final_a.txt")
    with open(vlist,"w") as fv, open(alist,"w") as fa:
        for vid, aud in segments:
            fv.write(f"file '{os.path.abspath(vid)}'\n")
            fa.write(f"file '{os.path.abspath(aud)}'\n")

    master_v = str(TEMP_DIR/"master.ts")
    master_a = str(TEMP_DIR/"master.wav")

    print("  Concatenating video track...")
    subprocess.run([
        FFMPEG,"-y",
        "-f","concat","-safe","0","-i",vlist,
        "-c:v","copy",
        master_v,"-loglevel","error"
    ],check=True)

    print("  Concatenating audio track...")
    subprocess.run([
        FFMPEG,"-y",
        "-f","concat","-safe","0","-i",alist,
        "-c:a","copy",
        master_a,"-loglevel","error"
    ],check=True)

    print("  Muxing final video...")
    subprocess.run([
        FFMPEG,"-y",
        "-i", master_v,
        "-i", master_a,
        "-c:v","copy",
        "-c:a","aac","-b:a","192k",
        "-ar","48000","-ac","2",
        "-movflags","+faststart",
        output_path,
        "-loglevel","error"
    ],check=True)

    bg_music = ASSETS_DIR / "background_energetic.wav"
    if bg_music.exists():
        bg_out = str(Path(output_path).with_name("final_with_music.mp4"))
        add_bg_music(output_path, bg_music, bg_out)
        Path(bg_out).replace(output_path)
    else:
        print("  No background music found, skipping...")

    mb = Path(output_path).stat().st_size/1024/1024
    print(f"\n✓  Done: {output_path} ({mb:.1f} MB)")
    return output_path


def cleanup_family_temp():
    import shutil
    if TEMP_DIR.exists():
        shutil.rmtree(TEMP_DIR)
        TEMP_DIR.mkdir()
    print("  Temp files cleaned.")
    