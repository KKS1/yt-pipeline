"""
ass_caption_writer.py
─────────────────────
Generates Advanced Sub Station Alpha (.ass) subtitle files with:
  • Karaoke word-level highlighting (\\k tags) — words light up as spoken
  • Emma / Liam avatar badge drawn left of each caption line
  • Character-specific highlight colours (Emma=coral, Liam=sky-blue)
  • Idiom / phrasal-verb chunks in golden accent with slightly larger font

The .ass filter is natively supported by FFmpeg via:
    -vf "ass=captions.ass"

Usage
─────
    from ass_caption_writer import generate_ass_captions

    ass_path = generate_ass_captions(
        audio_path   = "temp/1234/full.m4a",
        output_ass   = "output/my_video.ass",
        script_data  = script_dict,          # has "dialogue" list with speaker/text
        idiom_phrases= ["get out of hand"],  # optional pre-identified idioms
        is_shorts    = False,
    )
"""

from __future__ import annotations

import math
import os
import re
import sys
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).resolve().parent))

# ─── Constants ────────────────────────────────────────────────────────────────

# Subtitle style names written into the [V4+ Styles] section
STYLE_EMMA   = "Emma"
STYLE_LIAM   = "Liam"
STYLE_IDIOM  = "Idiom"
STYLE_IDIOM_CARD = "IdiomCard"

# ASS colour format: &HBBGGRR  (alpha=00 = fully opaque)
COLOUR_WHITE     = "&H00FFFFFF"
COLOUR_BLACK     = "&H00000000"
COLOUR_BG_SEMI   = "&H00000000"   # opaque black for sharp shadows

COLOUR_EMMA_HL   = "&H6666FF"     # coral-pink (BGR) highlights for Emma's spoken words
COLOUR_LIAM_HL   = "&HFF9966"     # sky-blue (BGR) highlights for Liam's spoken words
COLOUR_IDIOM_HL  = "&H00D7FF"     # gold (BGR) for idiom chunks

# Badge colours drawn in the ASS vector path (ASS drawing primary colour)
BADGE_EMMA_FILL  = "&H6666FF"     # coral
BADGE_LIAM_FILL  = "&HFF9966"     # sky-blue

# Regex patterns that identify idiom / phrasal-verb chunks in text
_PHRASAL_VERB_PREFIXES = (
    "get ", "give ", "take ", "make ", "put ", "set ", "look ", "go ", "come ",
    "run ", "turn ", "bring ", "break ", "call ", "pick ", "pull ", "push ",
    "cut ", "fall ", "hold ", "keep ", "let ", "move ", "pass ", "play ",
    "show ", "sit ", "stand ", "work ", "carry ", "catch ",
)

# Keywords from the English generator idiom pool — used for local detection fallback
_IDIOM_KEYWORDS = {
    "break a leg", "hit the nail", "bite the bullet", "spill the beans",
    "under the weather", "cost an arm", "beat around", "burning the midnight",
    "let the cat", "once in a blue moon", "piece of cake", "hit the sack",
    "kick the bucket", "ball is in your court", "better late than never",
    "bite off more", "barking up the wrong", "caught between", "hit the road",
    "get out of hand", "pull someone's leg", "on the fence", "under the table",
    "go back to the drawing", "cut corners", "jump on the bandwagon",
    "miss the boat", "bite the hand", "add fuel to the fire", "back to square one",
    "blow off steam", "burn bridges", "catch someone red-handed", "cold turkey",
    "cut to the chase", "devil's advocate", "drop the ball", "every cloud",
    "face the music", "get cold feet", "go the extra mile", "hit the books",
    "in hot water", "it takes two", "kill two birds", "let sleeping dogs",
    "on thin ice",
}


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _is_idiom_chunk(text: str, extra_phrases: list[str]) -> bool:
    """Return True if this text chunk looks like an idiom or phrasal verb."""
    lower = text.lower().strip()
    for phrase in extra_phrases:
        if phrase.lower() in lower:
            return True
    for kw in _IDIOM_KEYWORDS:
        if kw in lower:
            return True
    for prefix in _PHRASAL_VERB_PREFIXES:
        if lower.startswith(prefix):
            return True
    return False


def _cs(seconds: float) -> str:
    """Convert seconds to ASS centiseconds string (used in \\k tags)."""
    return str(max(0, int(round(seconds * 100))))


def _ass_timestamp(seconds: float) -> str:
    """Convert seconds to ASS timestamp H:MM:SS.cc"""
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    cs = int(round((seconds - int(seconds)) * 100))
    return f"{h}:{m:02d}:{s:02d}.{cs:02d}"


def _speaker_for_turn(dialogue: list[dict], turn_start_time: float, per_turn_times: list[tuple[float, float]]) -> str:
    """Return the speaker name for the turn that contains turn_start_time."""
    for i, (start, _end) in enumerate(per_turn_times):
        if abs(start - turn_start_time) < 0.1:
            if i < len(dialogue):
                return dialogue[i].get("speaker", "Emma")
    return "Emma"


def _load_face_badge(name: str, size: int = 44) -> Optional[str]:
    """
    Return the absolute path to the face PNG for `name` (Emma or Liam),
    or None if the file does not exist yet.
    """
    from pathlib import Path
    project_root = Path(__file__).resolve().parent.parent
    path = project_root / "assets" / "characters" / name.lower() / "face.png"
    return str(path) if path.exists() else None


# ─── ASS Header ───────────────────────────────────────────────────────────────

def _build_ass_header(
    video_width: int,
    video_height: int,
    font_size_normal: int,
    font_size_idiom: int,
    is_shorts: bool = False,
) -> str:
    """Build the [Script Info] and [V4+ Styles] sections of the ASS file."""
    if is_shorts:
        margin_v_bottom = 850
        margin_v_top = 160
        margin_l = 80
        margin_r = 80
        card_font_size = 80
    else:
        margin_v_bottom = 140
        margin_v_top = 100
        margin_l = 300
        margin_r = 300
        card_font_size = 60

    # ASS colour: &HAABBGGRR  (AA=alpha, 00=opaque)
    header = f"""\
[Script Info]
ScriptType: v4.00+
PlayResX: {video_width}
PlayResY: {video_height}
ScaledBorderAndShadow: yes
WrapStyle: 0

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: {STYLE_EMMA},{_eff_fontname()},{font_size_normal},{COLOUR_WHITE},{COLOUR_EMMA_HL},{COLOUR_BLACK},{COLOUR_BG_SEMI},1,0,0,0,100,100,0,0,1,4,2,2,{margin_l},{margin_r},{margin_v_bottom},1
Style: {STYLE_LIAM},{_eff_fontname()},{font_size_normal},{COLOUR_WHITE},{COLOUR_LIAM_HL},{COLOUR_BLACK},{COLOUR_BG_SEMI},1,0,0,0,100,100,0,0,1,4,2,2,{margin_l},{margin_r},{margin_v_bottom},1
Style: {STYLE_IDIOM},{_eff_fontname()},{font_size_idiom},{COLOUR_IDIOM_HL},{COLOUR_IDIOM_HL},{COLOUR_BLACK},{COLOUR_BG_SEMI},1,0,0,0,100,100,0,0,1,4,2,2,{margin_l},{margin_r},{margin_v_bottom},1
Style: {STYLE_IDIOM_CARD},{_eff_fontname()},{card_font_size},{COLOUR_IDIOM_HL},{COLOUR_WHITE},{COLOUR_BLACK},&HAA000000,1,0,0,0,100,100,0,0,3,2,0,8,80,80,{margin_v_top},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    return header


def _eff_fontname() -> str:
    """Return the best available subtitle font name."""
    return "Arial"


# ─── Badge drawing ────────────────────────────────────────────────────────────

def _badge_override(speaker: str) -> str:
    """
    Return an ASS \an (alignment) + \pos tweak or inline colour tag that
    simulates a small 'E' / 'L' badge to the left of the caption.

    Because libass (used by FFmpeg's `ass` filter) does NOT support embedded
    bitmaps, we use a coloured letter prefix styled as an ASS inline override.
    When face.png files are placed, the FFmpeg `movie` source overlay adds the
    real face icon; the text badge is a nice fallback.
    """
    # If face PNGs are available, they will be overlayed via FFmpeg, so we don't draw text badges.
    if _load_face_badge("emma") and _load_face_badge("liam"):
        return ""
    if speaker.lower() == "emma":
        # coral background on 'E'
        return r"{\c&H6666FF&\bord0\shad0\p0}{\1c&H6666FF&}[E] {\r}"
    else:
        # sky-blue background on 'L'
        return r"{\c&HFF9966&\bord0\shad0\p0}{\1c&HFF9966&}[L] {\r}"


def _karaoke_line(words: list[dict], speaker: str, extra_idiom_phrases: list[str]) -> str:
    """
    Build the ASS Text field for one dialogue caption chunk.

    words: list of {"word": str, "start": float, "end": float}
    Returns the full ASS text string including karaoke \\k tags.
    """
    badge = _badge_override(speaker)
    parts = []

    # Heuristic for multiline: split at approx middle word if chunk is long enough
    total_chars = sum(len(w["word"]) for w in words)
    split_at = -1
    if total_chars > 15 and len(words) > 2:
        split_at = len(words) // 2

    for i, w in enumerate(words):
        word_text = w["word"].strip()
        if not word_text:
            continue
        dur_cs = _cs(w["end"] - w["start"])

        line_break = r"\N" if i == split_at else ""

        if _is_idiom_chunk(word_text, extra_idiom_phrases):
            # Golden accent style override for idiom words
            parts.append(
                rf"{line_break}{{\k{dur_cs}\c{COLOUR_IDIOM_HL}&\b1\fs+2}}{word_text}{{\r}} "
            )
        else:
            # Normal karaoke: word highlight in speaker colour when spoken
            highlight = COLOUR_EMMA_HL if speaker.lower() == "emma" else COLOUR_LIAM_HL
            parts.append(rf"{line_break}{{\k{dur_cs}\2c{highlight}&}}{word_text} ")

    return badge + "".join(parts).rstrip()


def _add_idiom_card_events(events: list[str], script_data: dict, turn_times: list[tuple[float, float]], video_width: int, margin_v: int):
    """Add top-of-screen Idiom Box events based on script_data['idiom_windows']."""
    # Avoid showing idiom card captions in English quizzes, as it reveals the answer
    if script_data and script_data.get("video_format") == "shorts_quiz":
        return

    if not script_data:
        return
    windows = script_data.get("idiom_windows", [])
    for w in windows:
        st_idx = w.get("start_turn", 0)
        et_idx = w.get("end_turn", st_idx)
        if st_idx < len(turn_times) and et_idx < len(turn_times):
            start_t = turn_times[st_idx][0]
            end_t   = turn_times[et_idx][1]
            idiom   = str(w.get("idiom", "")).upper()
            defn    = w.get("definition", "")
            center_x = video_width // 2
            # Slide from Y=-150 to target margin_v over 500ms
            text    = rf"{{\move({center_x},-150,{center_x},{margin_v},0,500)}}{idiom}\N{{\b0\i1\fs-15}}{defn}"
            # Layer 1 ensures it prints over Layer 0 dialogue if they ever overlapped
            events.append(f"Dialogue: 1,{_ass_timestamp(start_t)},{_ass_timestamp(end_t)},{STYLE_IDIOM_CARD},,0,0,0,,{text}")


# ─── Core grouping ────────────────────────────────────────────────────────────

_MAX_CHARS_NORMAL  = 50
_MAX_CHARS_SHORTS  = 30


def _group_words_into_chunks(
    words: list[dict],
    max_chars: int,
) -> list[list[dict]]:
    """Group Whisper word objects into caption-sized display chunks."""
    chunks = []
    current: list[dict] = []
    char_count = 0

    for word in words:
        wtext = word["word"].strip()
        if not wtext:
            continue
        if char_count + len(wtext) + 1 > max_chars and current:
            chunks.append(current)
            current = [word]
            char_count = len(wtext)
        else:
            current.append(word)
            char_count += len(wtext) + 1

    if current:
        chunks.append(current)
    return chunks


# ─── Public API ───────────────────────────────────────────────────────────────

def generate_ass_captions(
    audio_path: str,
    output_ass: str,
    script_data: Optional[dict] = None,
    idiom_phrases: Optional[list[str]] = None,
    is_shorts: bool = False,
    video_width: int = 1920,
    video_height: int = 1080,
) -> str:
    """
    Transcribe `audio_path` with faster-whisper at word level and write an
    .ass subtitle file to `output_ass`.

    Parameters
    ----------
    audio_path     : Path to the mixed/narration audio file.
    output_ass     : Destination .ass file path.
    script_data    : The script dict (dialogue list) used to associate speaker
                     names with timestamp ranges.
    idiom_phrases  : Explicit list of idiom/phrasal-verb strings from Groq
                     annotation (used for golden highlighting).
    is_shorts      : If True, uses tighter max_chars for vertical video.
    video_width/height : Canvas size — written into [Script Info].

    Returns
    -------
    The path to the written .ass file.
    """
    try:
        from faster_whisper import WhisperModel
    except ImportError:
        raise RuntimeError(
            "faster-whisper not installed. Run: pip install faster-whisper --break-system-packages"
        )

    extra_idioms: list[str] = idiom_phrases or []
    max_chars = _MAX_CHARS_SHORTS if is_shorts else _MAX_CHARS_NORMAL
    if is_shorts:
        font_size_normal = 120
        font_size_idiom  = 135
    else:
        font_size_normal = 85
        font_size_idiom  = 95

    print("  Transcribing audio with faster-whisper (word timestamps)...")
    model = WhisperModel("base", device="cpu", compute_type="int8")
    segments, _info = model.transcribe(audio_path, language="en", word_timestamps=True)

    # Build a flat list of word dicts from all segments
    all_words: list[dict] = []
    for seg in segments:
        for w in (seg.words or []):
            all_words.append({
                "word":  w.word,
                "start": w.start,
                "end":   w.end,
            })

    # Build per-turn speaker lookup from script_data
    # Maps (approx_start, approx_end) → speaker
    turn_speaker_map: list[tuple[float, float, str]] = []
    events: list[str] = []

    if script_data:
        # We'll build this after the caller populates per_turn_times via
        # the optional keyword; for now we use a simple heuristic: split the
        # full audio into equal chunks per dialogue turn.
        dialogue = script_data.get("dialogue", [])
        total_dur = all_words[-1]["end"] if all_words else 0.0
        turn_dur = total_dur / max(len(dialogue), 1)
        for i, line in enumerate(dialogue):
            s = i * turn_dur
            e = (i + 1) * turn_dur
            spk = line.get("speaker", "Emma")
            turn_speaker_map.append((s, e, spk))

    # Add Idiom Box events (Top of screen)
    margin_v_top = 160 if is_shorts else 100
    _add_idiom_card_events(events, script_data, [(s, e) for s, e, _ in turn_speaker_map], video_width, margin_v_top)

    def _speaker_at(t: float) -> str:
        for s, e, spk in turn_speaker_map:
            if s <= t < e:
                return spk
        return "Emma"

    # Group words into caption chunks
    chunks = _group_words_into_chunks(all_words, max_chars)

    for chunk in chunks:
        if not chunk:
            continue
        start_t = chunk[0]["start"]
        end_t   = chunk[-1]["end"]
        speaker = _speaker_at(start_t)
        style   = STYLE_IDIOM if _is_idiom_chunk(
            " ".join(w["word"] for w in chunk), extra_idioms
        ) else (STYLE_EMMA if speaker.lower() == "emma" else STYLE_LIAM)

        text = _karaoke_line(chunk, speaker, extra_idioms)
        event = (
            f"Dialogue: 0,{_ass_timestamp(start_t)},{_ass_timestamp(end_t)},"
            f"{style},,0,0,0,,{text}"
        )
        events.append(event)

    header = _build_ass_header(video_width, video_height, font_size_normal, font_size_idiom, is_shorts=is_shorts)

    Path(output_ass).parent.mkdir(parents=True, exist_ok=True)
    with open(output_ass, "w", encoding="utf-8") as fh:
        fh.write(header)
        fh.write("\n".join(events))
        fh.write("\n")

    print(f"  .ass captions written: {output_ass} ({len(events)} events)")
    return output_ass


def generate_ass_captions_from_words(
    words: list[dict],
    output_ass: str,
    dialogue: list[dict],
    per_turn_times: list[tuple[float, float]],
    idiom_phrases: Optional[list[str]] = None,
    is_shorts: bool = False,
    video_width: int = 1080,
    video_height: int = 1920,
) -> str:
    """
    Lower-level variant: accepts pre-computed Whisper word list + per-turn
    timing (from dynamic renderer where TTS is done per line).

    words            : [{"word": str, "start": float, "end": float}, ...]
    dialogue         : script_data["dialogue"] list
    per_turn_times   : [(abs_start, abs_end), ...] matching dialogue indices
    """
    extra_idioms: list[str] = idiom_phrases or []
    max_chars = _MAX_CHARS_SHORTS if is_shorts else _MAX_CHARS_NORMAL
    if is_shorts:
        font_size_normal = 120
        font_size_idiom  = 135
    else:
        font_size_normal = 85
        font_size_idiom  = 95

    # Build per-turn speaker lookup
    turn_speaker_map: list[tuple[float, float, str]] = []
    events: list[str] = []

    for i, (s, e) in enumerate(per_turn_times):
        if i < len(dialogue):
            turn_speaker_map.append((s, e, dialogue[i].get("speaker", "Emma")))

    # Add Idiom Box events (Top of screen)
    margin_v_top = 160 if is_shorts else 100
    _add_idiom_card_events(events, {"idiom_windows": dialogue[0].get("idiom_windows", []) if isinstance(dialogue, list) and dialogue and "idiom_windows" in dialogue[0] else []}, per_turn_times, video_width, margin_v_top)

    def _speaker_at(t: float) -> str:
        for s, e, spk in turn_speaker_map:
            if s <= t < e:
                return spk
        return "Emma"

    chunks = _group_words_into_chunks(words, max_chars)

    for chunk in chunks:
        if not chunk:
            continue
        start_t = chunk[0]["start"]
        end_t   = chunk[-1]["end"]
        speaker = _speaker_at(start_t)
        style   = STYLE_IDIOM if _is_idiom_chunk(
            " ".join(w["word"] for w in chunk), extra_idioms
        ) else (STYLE_EMMA if speaker.lower() == "emma" else STYLE_LIAM)

        text = _karaoke_line(chunk, speaker, extra_idioms)
        event = (
            f"Dialogue: 0,{_ass_timestamp(start_t)},{_ass_timestamp(end_t)},"
            f"{style},,0,0,0,,{text}"
        )
        events.append(event)

    header = _build_ass_header(video_width, video_height, font_size_normal, font_size_idiom, is_shorts=is_shorts)

    Path(output_ass).parent.mkdir(parents=True, exist_ok=True)
    with open(output_ass, "w", encoding="utf-8") as fh:
        fh.write(header)
        fh.write("\n".join(events))
        fh.write("\n")

    print(f"  .ass captions written: {output_ass} ({len(events)} events)")
    return output_ass
