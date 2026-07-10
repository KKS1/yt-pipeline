"""
summary_card_renderer.py
────────────────────────
Generates a full-frame "What We Learned Today" summary card for the end
of English podcast videos.  Lists key takeaway phrases with definitions
over a Gemini-generated or gradient background.

Usage
─────
    from summary_card_renderer import render_summary_card

    png_path = render_summary_card(
        idiom_windows=[{"idiom": "get out of hand", "definition": "to become uncontrollable", "type": "phrasal_verb"}, ...],
        scene_visual_prompt="A cozy café with two friends chatting nervously",
        output_dir=Path("/tmp/summary"),
    )
"""

from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Optional

from PIL import Image, ImageDraw, ImageFont

# ─── Constants ────────────────────────────────────────────────────────────────

PROJECT_ROOT = Path(__file__).resolve().parent.parent
ASSETS_DIR = PROJECT_ROOT / "assets"
_FONT_PATH = str(ASSETS_DIR / "DejaVuSans-Bold.ttf")

CARD_W = 1920
CARD_H = 1080

# Colours (RGB)
_COL_GOLD   = (255, 215,   0)
_COL_WHITE  = (255, 255, 255)
_COL_TEAL   = ( 32, 210, 200)
_COL_BLACK  = (  0,   0,   0)
_COL_DARK1  = ( 15,  15,  30)
_COL_DARK2  = ( 30,  20,  50)

# Font sizes
_FS_TITLE   = 64
_FS_LABEL   = 42
_FS_PHRASE  = 48
_FS_DEF     = 34
_FS_COMMENT = 30

_GEMINI_MODEL = os.getenv("GEMINI_IMAGE_MODEL", "gemini-2.5-flash-image")
_SLEEP_BETWEEN = float(os.getenv("GEMINI_IMAGE_SLEEP_SECONDS", "2"))


# ─── Font helper ──────────────────────────────────────────────────────────────

def _font(size: int, bold: bool = True) -> ImageFont.FreeTypeFont:
    try:
        return ImageFont.truetype(_FONT_PATH, size)
    except (OSError, IOError):
        return ImageFont.load_default()


# ─── Gradient background ─────────────────────────────────────────────────────

def _gradient_bg(w: int, h: int, c1: tuple, c2: tuple) -> Image.Image:
    img = Image.new("RGB", (w, h))
    draw = ImageDraw.Draw(img)
    for y in range(h):
        t = y / h
        draw.line([(0, y), (w, y)], fill=tuple(
            int(c1[i] + (c2[i] - c1[i]) * t) for i in range(3)))
    return img


def _dark_overlay(img: Image.Image, alpha: int = 140) -> Image.Image:
    ov = Image.new("RGBA", img.size, (0, 0, 0, alpha))
    return Image.alpha_composite(img.convert("RGBA"), ov).convert("RGB")


# ─── Gemini background generation ────────────────────────────────────────────

def _generate_gemini_bg(scene_visual_prompt: str, output_path: Path) -> bool:
    """Try to generate a summary background via Gemini. Returns True on success."""
    api_key = os.getenv("GEMINI_API_KEY", "").strip()
    if not api_key:
        return False

    try:
        from google import genai
        from google.genai import types
    except ImportError:
        return False

    prompt = (
        f"Warm, inviting Pixar-style illustration inspired by this scene: "
        f"{scene_visual_prompt}. "
        f"Soft golden lighting, slightly blurred background, storybook aesthetic. "
        f"No text, no characters, just the atmospheric setting."
    )

    try:
        client = genai.Client(api_key=api_key)
        response = client.models.generate_content(
            model=_GEMINI_MODEL,
            contents=prompt,
            config=types.GenerateContentConfig(response_modalities=["IMAGE"]),
        )
        if response.candidates:
            for part in response.candidates[0].content.parts:
                if part.inline_data is not None:
                    output_path.write_bytes(part.inline_data.data)
                    time.sleep(_SLEEP_BETWEEN)
                    return True
    except Exception as e:
        print(f"    Gemini summary bg failed: {e}")
    return False


# ─── Text drawing helpers ─────────────────────────────────────────────────────

def _outlined_text(draw: ImageDraw.ImageDraw, x: int, y: int, text: str,
                   font: ImageFont.FreeTypeFont, fill: tuple,
                   outline: tuple = _COL_BLACK, ow: int = 3):
    for dx in range(-ow, ow + 1):
        for dy in range(-ow, ow + 1):
            if dx * dx + dy * dy <= ow * ow:
                draw.text((x + dx, y + dy), text, font=font, fill=outline)
    draw.text((x, y), text, font=font, fill=fill)


def _centered_text(draw: ImageDraw.ImageDraw, text: str,
                   font: ImageFont.FreeTypeFont, y: int,
                   fill: tuple, w: int, outline: tuple = _COL_BLACK, ow: int = 3) -> int:
    bbox = draw.textbbox((0, 0), text, font=font)
    x = (w - (bbox[2] - bbox[0])) // 2
    _outlined_text(draw, x, y, text, font, fill, outline, ow)
    return bbox[3] - bbox[1]


# ─── Main render function ─────────────────────────────────────────────────────

def render_summary_card(
    idiom_windows: list[dict],
    scene_visual_prompt: str = "",
    output_dir: Path | str = ".",
    is_shorts: bool = False,
    bg_image_path: str = None,
) -> str:
    """
    Render a full-frame summary card PNG and return its path.

    Parameters
    ----------
    idiom_windows : list of dicts with keys "idiom", "definition", "type"
    scene_visual_prompt : visual prompt from the script for Gemini background
    output_dir : where to write the PNG
    is_shorts : if True, render at 1080x1920 (portrait)
    bg_image_path : pre-generated background image path (from manifest/Gemini).
                     If provided, skips live Gemini call and uses this directly.
    """
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    out_path = output_dir / "summary_card.png"

    w = 1080 if is_shorts else CARD_W
    h = 1920 if is_shorts else CARD_H

    # ── Background ──
    # Priority: pre-generated image > live Gemini call > gradient fallback
    bg_loaded = False
    if bg_image_path and Path(bg_image_path).exists():
        try:
            bg = Image.open(bg_image_path).convert("RGB").resize((w, h), Image.LANCZOS)
            bg = _dark_overlay(bg, alpha=160)
            bg_loaded = True
            print(f"  Summary card using pre-generated background: {bg_image_path}")
        except Exception as e:
            print(f"  Failed to load pre-generated bg: {e}")

    if not bg_loaded:
        gemini_path = output_dir / "summary_bg.png"
        gemini_ok = False
        if scene_visual_prompt:
            gemini_ok = _generate_gemini_bg(scene_visual_prompt, gemini_path)

        if gemini_ok and gemini_path.exists():
            bg = Image.open(gemini_path).convert("RGB").resize((w, h), Image.LANCZOS)
            bg = _dark_overlay(bg, alpha=160)
        else:
            bg = _gradient_bg(w, h, _COL_DARK1, _COL_DARK2)

    img = bg.convert("RGBA")
    overlay = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)

    # ── Layout ──
    if is_shorts:
        y_cursor = int(h * 0.15)
        pad_x = 60
        max_text_w = w - pad_x * 2
    else:
        y_cursor = int(h * 0.12)
        pad_x = 160
        max_text_w = w - pad_x * 2

    # ── Title ──
    title_fs = int(_FS_TITLE * (0.7 if is_shorts else 1.0))
    th = _centered_text(draw, "What We Learned Today",
                        _font(title_fs), y_cursor, _COL_GOLD, w, ow=4)
    y_cursor += th + (40 if is_shorts else 60)

    # ── Decorative line ──
    line_w = int(w * 0.4)
    line_x = (w - line_w) // 2
    draw.line([(line_x, y_cursor), (line_x + line_w, y_cursor)],
              fill=(*_COL_GOLD, 160), width=3)
    y_cursor += 40

    # ── Idiom list ──
    phrase_fs = int(_FS_PHRASE * (0.7 if is_shorts else 1.0))
    def_fs = int(_FS_DEF * (0.7 if is_shorts else 1.0))
    label_fs = int(_FS_LABEL * (0.7 if is_shorts else 1.0))

    takeaways = idiom_windows[:5] if idiom_windows else []
    if not takeaways:
        # Fallback if no idioms extracted
        takeaways = [{"idiom": "—", "definition": "No idioms captured", "type": ""}]

    for i, item in enumerate(takeaways):
        phrase = item.get("idiom", "").strip()
        definition = item.get("definition", "").strip()
        idiom_type = item.get("type", "").strip()

        # Number badge
        badge_text = f"{i + 1}."
        badge_bbox = draw.textbbox((0, 0), badge_text, font=_font(phrase_fs))
        badge_w = badge_bbox[2] - badge_bbox[0]
        _outlined_text(draw, pad_x, y_cursor, badge_text,
                       _font(phrase_fs), _COL_TEAL, _COL_BLACK, ow=2)

        # Phrase
        phrase_x = pad_x + badge_w + 16
        phrase_bbox = draw.textbbox((0, 0), phrase, font=_font(phrase_fs))
        phrase_w = phrase_bbox[2] - phrase_bbox[0]
        if phrase_x + phrase_w > w - pad_x:
            # Wrap if too long
            phrase_fs_adj = max(28, int(phrase_fs * (max_text_w / (phrase_w + 40))))
            _outlined_text(draw, phrase_x, y_cursor, phrase,
                           _font(phrase_fs_adj), _COL_WHITE, _COL_BLACK, ow=2)
            y_cursor += phrase_bbox[3] - phrase_bbox[1] + 8
        else:
            _outlined_text(draw, phrase_x, y_cursor, phrase,
                           _font(phrase_fs), _COL_WHITE, _COL_BLACK, ow=2)
            y_cursor += phrase_bbox[3] - phrase_bbox[1] + 8

        # Definition
        if definition:
            def_text = f"  — {definition}"
            _outlined_text(draw, pad_x + 20, y_cursor, def_text,
                           _font(def_fs), _COL_GOLD, _COL_BLACK, ow=2)
            def_bbox = draw.textbbox((0, 0), def_text, font=_font(def_fs))
            y_cursor += def_bbox[3] - def_bbox[1]

        y_cursor += 30 if is_shorts else 45

    # ── Bottom CTA line ──
    y_cursor = max(y_cursor, int(h * 0.78))
    draw.line([(line_x, y_cursor), (line_x + line_w, y_cursor)],
              fill=(*_COL_GOLD, 120), width=2)
    y_cursor += 30

    comment_fs = int(_FS_COMMENT * (0.7 if is_shorts else 1.0))
    _centered_text(draw, "Share your answer in the comments!",
                   _font(comment_fs), y_cursor, _COL_GOLD, w, ow=2)

    # ── Composite ──
    img = Image.alpha_composite(img, overlay).convert("RGB")
    img.save(str(out_path), "PNG")
    print(f"  Summary card rendered: {out_path}")
    return str(out_path)
