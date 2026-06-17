"""
idiom_card_renderer.py
──────────────────────
Generates "Idiom Card" PNG overlays for idioms and phrasal verbs.

Design
------
  • Loads a pre-designed card background from assets/idiom_card_bg.png.
  • Falls back to a programmatic gradient card if the file is not present.
  • Composes three text layers on top:
      ① Type badge  — "💡 IDIOM" or "🔗 PHRASAL VERB"
      ② Phrase      — the idiom / phrasal verb in large bold text
      ③ (Optional)  — short definition if provided
  • Outputs a PNG with transparent areas preserved (RGBA).

Usage
─────
    from idiom_card_renderer import render_idiom_card, render_idiom_cards_batch

    png_path = render_idiom_card(
        idiom      = "get out of hand",
        idiom_type = "phrasal_verb",
        definition = "to become uncontrollable",
        output_dir = temp_dir / "idiom_cards",
    )
"""

from __future__ import annotations

import hashlib
import textwrap
from pathlib import Path
from typing import Optional

# ─── Asset / layout constants ─────────────────────────────────────────────────

# Expected pre-designed background (user places this file)
_DEFAULT_BG_PATH = Path(__file__).resolve().parent.parent / "assets" / "idiom_card_bg.png"

# Card dimensions (will be resized to this after loading bg)
CARD_W = 420
CARD_H = 180

# Text colours (RGB tuples)
_COL_WHITE  = (255, 255, 255)
_COL_GOLD   = (255, 215,   0)
_COL_TEAL   = ( 32, 210, 200)
_COL_SHADOW = (  0,   0,   0, 160)   # RGBA

# Font size targets (Pillow will approximate if truetype not available)
_FS_BADGE  = 15
_FS_PHRASE = 22
_FS_DEF    = 14

# Padding inside the card
_PAD_X = 18
_PAD_Y = 14

# Font paths — prefer bundled DejaVuSans, fallback to system default
_ASSETS_DIR  = Path(__file__).resolve().parent.parent / "assets"
_FONT_BOLD   = _ASSETS_DIR / "DejaVuSans-Bold.ttf"


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _load_font(size: int, bold: bool = False):
    """Load a PIL ImageFont. Falls back to default if no TTF is available."""
    from PIL import ImageFont
    font_path = _FONT_BOLD if bold and _FONT_BOLD.exists() else None
    if font_path:
        try:
            return ImageFont.truetype(str(font_path), size)
        except Exception:
            pass
    try:
        return ImageFont.load_default(size=size)
    except TypeError:
        return ImageFont.load_default()


def _make_fallback_bg() -> "Image.Image":
    """Generate a programmatic gradient card background (RGBA)."""
    from PIL import Image, ImageDraw
    img = Image.new("RGBA", (CARD_W, CARD_H), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    # Dark gradient: top-left dark blue → bottom-right dark teal
    for x in range(CARD_W):
        ratio = x / CARD_W
        r = int(10 + ratio * 5)
        g = int(15 + ratio * 30)
        b = int(45 + ratio * 40)
        draw.line([(x, 0), (x, CARD_H)], fill=(r, g, b, 230))

    # Rounded-corner mask
    _apply_rounded_mask(img, radius=16)

    # Subtle border
    draw2 = ImageDraw.Draw(img)
    draw2.rounded_rectangle([0, 0, CARD_W - 1, CARD_H - 1], radius=16,
                             outline=(255, 255, 255, 60), width=2)
    return img


def _apply_rounded_mask(img: "Image.Image", radius: int = 16) -> None:
    """Apply a rounded-corner mask in-place (modifies alpha channel)."""
    from PIL import Image, ImageDraw
    mask = Image.new("L", img.size, 0)
    draw = ImageDraw.Draw(mask)
    draw.rounded_rectangle([0, 0, img.width - 1, img.height - 1],
                            radius=radius, fill=255)
    img.putalpha(mask)


def _draw_shadow_text(draw, pos, text, font, shadow_col, text_col):
    """Draw text with a 1-pixel drop shadow."""
    x, y = pos
    draw.text((x + 1, y + 1), text, font=font, fill=shadow_col)
    draw.text((x, y),         text, font=font, fill=text_col)


def _card_cache_name(idiom: str, idiom_type: str) -> str:
    key = f"{idiom_type}:{idiom}"
    digest = hashlib.md5(key.encode()).hexdigest()[:8]
    safe = "".join(c if c.isalnum() else "_" for c in idiom[:30])
    return f"card_{safe}_{digest}.png"


# ─── Public API ───────────────────────────────────────────────────────────────

def render_idiom_card(
    idiom: str,
    idiom_type: str = "idiom",
    definition: str = "",
    output_dir: Optional[str | Path] = None,
    bg_path: Optional[str | Path] = None,
    force: bool = False,
) -> str:
    """
    Render a single idiom/phrasal-verb card PNG and return its path.

    Parameters
    ----------
    idiom       : The idiom or phrasal verb string (e.g. "get out of hand").
    idiom_type  : "idiom" or "phrasal_verb".
    definition  : Short definition to display below the phrase (optional).
    output_dir  : Directory to write the PNG into (default: temp/<pid>/idiom_cards/).
    bg_path     : Override path to background PNG. Falls back to assets/idiom_card_bg.png
                  then to programmatic gradient.
    force       : Re-render even if cached file already exists.

    Returns
    -------
    Absolute path string of the rendered PNG.
    """
    from PIL import Image, ImageDraw

    if output_dir is None:
        import os
        output_dir = Path(__file__).resolve().parent.parent / "temp" / str(os.getpid()) / "idiom_cards"
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    out_path = output_dir / _card_cache_name(idiom, idiom_type)
    if out_path.exists() and not force:
        return str(out_path)

    # ── Load / build background ────────────────────────────────────────────
    resolved_bg = Path(bg_path) if bg_path else _DEFAULT_BG_PATH
    if resolved_bg.exists():
        card = Image.open(resolved_bg).convert("RGBA")
        card = card.resize((CARD_W, CARD_H), Image.Resampling.LANCZOS)
    else:
        card = _make_fallback_bg()

    draw = ImageDraw.Draw(card)

    # ── Badge row (type label) ─────────────────────────────────────────────
    is_phrasal = idiom_type.lower().replace(" ", "_") == "phrasal_verb"
    badge_emoji  = "🔗" if is_phrasal else "💡"
    badge_label  = f"{badge_emoji} {'PHRASAL VERB' if is_phrasal else 'IDIOM'}"
    badge_colour = _COL_TEAL if is_phrasal else _COL_GOLD
    badge_font   = _load_font(_FS_BADGE, bold=True)

    _draw_shadow_text(draw, (_PAD_X, _PAD_Y), badge_label,
                      badge_font, _COL_SHADOW, badge_colour)

    # ── Idiom phrase ───────────────────────────────────────────────────────
    phrase_font = _load_font(_FS_PHRASE, bold=True)
    phrase_y    = _PAD_Y + _FS_BADGE + 8

    # Wrap if too long
    max_phrase_chars = 28
    wrapped_phrase = textwrap.fill(f'"{idiom}"', width=max_phrase_chars)

    _draw_shadow_text(draw, (_PAD_X, phrase_y), wrapped_phrase,
                      phrase_font, _COL_SHADOW, _COL_WHITE)

    # ── Definition (optional) ──────────────────────────────────────────────
    if definition:
        def_font = _load_font(_FS_DEF, bold=False)
        line_count = len(wrapped_phrase.split("\n"))
        def_y = phrase_y + (_FS_PHRASE + 4) * line_count + 6
        max_def_chars = 42
        wrapped_def = textwrap.fill(definition, width=max_def_chars)
        _draw_shadow_text(draw, (_PAD_X, def_y), wrapped_def,
                          def_font, _COL_SHADOW, (200, 200, 200))

    card.save(str(out_path), "PNG")
    print(f"  Idiom card rendered: {out_path.name}")
    return str(out_path)


def render_idiom_cards_batch(
    idiom_windows: list[dict],
    output_dir: Optional[str | Path] = None,
    bg_path: Optional[str | Path] = None,
) -> dict[str, str]:
    """
    Render cards for all entries in idiom_windows (from Groq annotation).

    idiom_windows format (from annotate_script_with_idiom_windows):
        [
          {
            "idiom": "get out of hand",
            "type":  "phrasal_verb",
            "definition": "to become uncontrollable",
            "start_turn": 4,
            "end_turn":   6,
          },
          ...
        ]

    Returns a dict: idiom_str → png_path.
    """
    result: dict[str, str] = {}
    for window in idiom_windows:
        idiom  = window.get("idiom", "")
        itype  = window.get("type", "idiom")
        defn   = window.get("definition", "")
        if not idiom:
            continue
        png = render_idiom_card(
            idiom=idiom,
            idiom_type=itype,
            definition=defn,
            output_dir=output_dir,
            bg_path=bg_path,
        )
        result[idiom] = png
    return result
