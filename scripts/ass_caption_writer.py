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
STYLE_COUNTDOWN = "Countdown"

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

PAUSE_CUE_RE = re.compile(r"^\s*\[(?:PAUSE|PAUSE\s+(\d+(?:\.\d+)?)\s*SECONDS?)\]\s*$", re.IGNORECASE)

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


def _is_pause_turn(text: str) -> bool:
    return PAUSE_CUE_RE.match(str(text or "")) is not None


def _plain_caption_line(text: str, speaker: str) -> str:
    return _badge_override(speaker) + str(text or "").replace("\n", r"\N").strip()


def _pause_guess_windows(
    dialogue: list[dict],
    per_turn_times: list[tuple[float, float]],
) -> list[dict]:
    """Return prompt/pause/reveal windows for [PAUSE] based challenges."""
    if not dialogue or not per_turn_times or len(per_turn_times) != len(dialogue):
        print(f"  [DEBUG] _pause_guess_windows: dialogue={len(dialogue)}, per_turn_times={len(per_turn_times)}, match={len(per_turn_times) == len(dialogue)}")
        return []

    windows: list[dict] = []
    for i, turn in enumerate(dialogue):
        text = turn.get("text", "")
        is_pause = _is_pause_turn(text)
        if not is_pause:
            continue

        print(f"  [DEBUG] Found pause turn at index {i}: '{text}'")

        prompt_idx = next(
            (j for j in range(i - 1, -1, -1) if not _is_pause_turn(dialogue[j].get("text", ""))),
            None,
        )
        reveal_idx = next(
            (j for j in range(i + 1, len(dialogue)) if not _is_pause_turn(dialogue[j].get("text", ""))),
            None,
        )
        if prompt_idx is None or reveal_idx is None:
            print(f"  [DEBUG] Skipping pause at {i}: prompt_idx={prompt_idx}, reveal_idx={reveal_idx}")
            continue

        print(f"  [DEBUG] Adding pause window: prompt={prompt_idx}, pause={i}, reveal={reveal_idx}")
        windows.append({
            "prompt_index": prompt_idx,
            "pause_index": i,
            "reveal_index": reveal_idx,
            "pause_start": per_turn_times[i][0],
            "pause_end": per_turn_times[i][1],
            "reveal_start": per_turn_times[reveal_idx][0],
        })
    print(f"  [DEBUG] Total pause windows found: {len(windows)}")
    return windows


def _gate_idiom_windows_for_reveals(idiom_windows: list[dict], reveal_windows: list[dict]) -> list[dict]:
    """Delay idiom cards that overlap a pause-and-guess sequence until reveal."""
    gated: list[dict] = []
    for window in idiom_windows or []:
        try:
            st = int(window.get("start_turn", 0))
            et = int(window.get("end_turn", st))
        except (TypeError, ValueError):
            gated.append(window)
            continue

        adjusted = dict(window)
        for reveal in reveal_windows:
            prompt_idx = reveal["prompt_index"]
            pause_idx = reveal["pause_index"]
            reveal_idx = reveal["reveal_index"]
            if st <= reveal_idx and et >= prompt_idx and st <= pause_idx:
                st = max(st, reveal_idx)
                et = max(et, st)
                adjusted["start_turn"] = st
                adjusted["end_turn"] = et
        gated.append(adjusted)
    return gated


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
        countdown_font_size = 120
    else:
        margin_v_bottom = 140
        margin_v_top = 100
        margin_l = 300
        margin_r = 300
        card_font_size = 60
        countdown_font_size = 84

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
Style: {STYLE_COUNTDOWN},{_eff_fontname()},{countdown_font_size},{COLOUR_WHITE},{COLOUR_WHITE},{COLOUR_BLACK},&H88000000,1,0,0,0,100,100,0,0,1,5,1,5,40,40,0,1

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


def _add_idiom_card_events(
    events: list[str],
    script_data: dict,
    turn_times: list[tuple[float, float]],
    video_width: int,
    margin_v: int,
    reveal_windows: Optional[list[dict]] = None,
):
    """Add top-of-screen Idiom Box events based on script_data['idiom_windows']."""
    # Avoid showing idiom card captions in English quizzes, as it reveals the answer
    if script_data and script_data.get("video_format") == "shorts_quiz":
        return

    if not script_data:
        return
    windows = _gate_idiom_windows_for_reveals(
        script_data.get("idiom_windows", []),
        reveal_windows or [],
    )
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


def _add_pause_guess_events(
    events: list[str],
    dialogue: list[dict],
    per_turn_times: list[tuple[float, float]],
    reveal_windows: list[dict],
):
    """Freeze the prompt during silence and burn a 3-2-1 countdown in ASS."""
    print(f"  [DEBUG] _add_pause_guess_events called with {len(reveal_windows)} windows")
    for window in reveal_windows:
        prompt_idx = window["prompt_index"]
        pause_start = float(window["pause_start"])
        pause_end = float(window["pause_end"])
        print(f"  [DEBUG] Processing window: prompt_idx={prompt_idx}, pause_start={pause_start:.2f}, pause_end={pause_end:.2f}")
        if pause_end <= pause_start:
            print(f"  [DEBUG] Skipping window: pause_end <= pause_start")
            continue

        prompt = dialogue[prompt_idx]
        style = STYLE_EMMA if prompt.get("speaker", "Emma").lower() == "emma" else STYLE_LIAM
        text = _plain_caption_line(prompt.get("text", ""), prompt.get("speaker", "Emma"))
        events.append(
            f"Dialogue: 0,{_ass_timestamp(pause_start)},{_ass_timestamp(pause_end)},"
            f"{style},,0,0,0,,{text}"
        )

        duration = pause_end - pause_start
        count = min(3, max(1, int(math.ceil(duration))))
        slot = duration / count
        labels = [str(n) for n in range(count, 0, -1)]
        print(f"  [DEBUG] Adding countdown: duration={duration:.2f}s, count={count}, labels={labels}")
        for idx, label in enumerate(labels):
            start_t = pause_start + idx * slot
            end_t = pause_end if idx == count - 1 else min(pause_end, pause_start + (idx + 1) * slot)
            if end_t <= start_t:
                continue
            countdown_text = rf"{{\fad(80,120)\t(0,180,\fscx118\fscy118)}}{label}"
            events.append(
                f"Dialogue: 2,{_ass_timestamp(start_t)},{_ass_timestamp(end_t)},"
                f"{STYLE_COUNTDOWN},,0,0,0,,{countdown_text}"
            )
    print(f"  [DEBUG] _add_pause_guess_events added {len(events)} total events")


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


def _words_grouped_by_turn(
    words: list[dict],
    dialogue: list[dict],
    per_turn_times: list[tuple[float, float]],
) -> list[list[dict]]:
    """Assign transcribed words to dialogue turns and clamp to turn bounds."""
    grouped: list[list[dict]] = [[] for _ in dialogue]
    if not dialogue or not per_turn_times or len(per_turn_times) != len(dialogue):
        return grouped

    for word in words:
        start = float(word.get("start", 0.0))
        end = float(word.get("end", start))
        mid = (start + end) / 2.0
        assigned_idx = None

        for idx, (turn_start, turn_end) in enumerate(per_turn_times):
            if _is_pause_turn(dialogue[idx].get("text", "")):
                continue
            if turn_start <= mid < turn_end:
                assigned_idx = idx
                break

        # Whisper can occasionally place an edge word a few centiseconds outside
        # the known TTS span. Keep it with the nearest spoken turn, never a pause.
        if assigned_idx is None:
            nearest: tuple[float, int] | None = None
            for idx, (turn_start, turn_end) in enumerate(per_turn_times):
                if _is_pause_turn(dialogue[idx].get("text", "")):
                    continue
                distance = min(abs(mid - turn_start), abs(mid - turn_end))
                if distance <= 0.25 and (nearest is None or distance < nearest[0]):
                    nearest = (distance, idx)
            assigned_idx = nearest[1] if nearest else None

        if assigned_idx is None:
            continue

        turn_start, turn_end = per_turn_times[assigned_idx]
        clamped = dict(word)
        clamped["start"] = max(start, turn_start)
        clamped["end"] = min(max(end, clamped["start"] + 0.01), turn_end)
        if clamped["end"] > clamped["start"]:
            grouped[assigned_idx].append(clamped)

    return grouped


def _add_caption_events_from_turn_words(
    events: list[str],
    grouped_words: list[list[dict]],
    dialogue: list[dict],
    max_chars: int,
    extra_idioms: list[str],
):
    for idx, turn_words in enumerate(grouped_words):
        if not turn_words or idx >= len(dialogue):
            continue
        speaker = dialogue[idx].get("speaker", "Emma")
        for chunk in _group_words_into_chunks(turn_words, max_chars):
            if not chunk:
                continue
            start_t = chunk[0]["start"]
            end_t = chunk[-1]["end"]
            style = STYLE_IDIOM if _is_idiom_chunk(
                " ".join(w["word"] for w in chunk), extra_idioms
            ) else (STYLE_EMMA if speaker.lower() == "emma" else STYLE_LIAM)

            text = _karaoke_line(chunk, speaker, extra_idioms)
            events.append(
                f"Dialogue: 0,{_ass_timestamp(start_t)},{_ass_timestamp(end_t)},"
                f"{style},,0,0,0,,{text}"
            )


# ─── Public API ───────────────────────────────────────────────────────────────

def generate_ass_captions(
    audio_path: str,
    output_ass: str,
    script_data: Optional[dict] = None,
    idiom_phrases: Optional[list[str]] = None,
    is_shorts: bool = False,
    video_width: int = 1920,
    video_height: int = 1080,
    per_turn_times: Optional[list[tuple[float, float]]] = None,
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
    per_turn_times : Optional list of (start, end) tuples for each dialogue turn.
                     If provided, this is used for speaker mapping instead of estimation.

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
        font_size_normal = 95
        font_size_idiom  = 105

    print("  Transcribing audio with faster-whisper (word timestamps)...")
    model = WhisperModel("base", device="cpu", compute_type="int8")
    segments, _info = model.transcribe(audio_path, language="en", word_timestamps=True)

    # Build a flat list of word dicts from all segments
    all_words: list[dict] = []
    for seg in segments:
        for w in (seg.words or []):
            word_text = w.word
            # Fix common Whisper transcription errors
            word_text = re.sub(r'\bfrost\b', 'phrasal', word_text, flags=re.IGNORECASE)
            word_text = re.sub(r'\balver\b', 'verb', word_text, flags=re.IGNORECASE)
            word_text = re.sub(r'\bfrazal\b', 'phrasal', word_text, flags=re.IGNORECASE)
            word_text = re.sub(r'\bfrazel\b', 'phrasal', word_text, flags=re.IGNORECASE)
            # Convert "phrase" back to "phrasal" (TTS uses "phrase" for pronunciation)
            word_text = re.sub(r'\bphrase verb\b', 'phrasal verb', word_text, flags=re.IGNORECASE)
            all_words.append({
                "word":  word_text,
                "start": w.start,
                "end":   w.end,
            })

    # Build per-turn speaker lookup from script_data
    # Maps (approx_start, approx_end) → speaker
    turn_speaker_map: list[tuple[float, float, str]] = []
    events: list[str] = []

    dialogue = script_data.get("dialogue", []) if script_data else []
    reveal_windows = _pause_guess_windows(dialogue, per_turn_times or [])

    if script_data and per_turn_times and len(per_turn_times) == len(dialogue):
        for i, (s, e) in enumerate(per_turn_times):
            spk = dialogue[i].get("speaker", "Emma")
            turn_speaker_map.append((s, e, spk))
    elif script_data:
        # Fallback to estimation if precise times aren't available
        total_dur = all_words[-1]["end"] if all_words else 0.0
        turn_dur = total_dur / max(len(dialogue), 1)
        for i, line in enumerate(dialogue):
            turn_speaker_map.append((i * turn_dur, (i + 1) * turn_dur, line.get("speaker", "Emma")))

    # Add Idiom Box events (Top of screen)
    margin_v_top = 160 if is_shorts else 100
    _add_idiom_card_events(
        events,
        script_data,
        [(s, e) for s, e, _ in turn_speaker_map],
        video_width,
        margin_v_top,
        reveal_windows,
    )
    _add_pause_guess_events(events, dialogue, per_turn_times or [], reveal_windows)

    def _speaker_at(t: float) -> str:
        for s, e, spk in turn_speaker_map:
            if s <= t < e:
                return spk
        return "Emma"

    if dialogue and per_turn_times and len(per_turn_times) == len(dialogue):
        grouped_words = _words_grouped_by_turn(all_words, dialogue, per_turn_times)
        _add_caption_events_from_turn_words(events, grouped_words, dialogue, max_chars, extra_idioms)
    else:
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
        font_size_normal = 95
        font_size_idiom  = 105

    # Fix common Whisper transcription errors in word list
    for w in words:
        w["word"] = re.sub(r'\bfrost\b', 'phrasal', w["word"], flags=re.IGNORECASE)
        w["word"] = re.sub(r'\balver\b', 'verb', w["word"], flags=re.IGNORECASE)
        w["word"] = re.sub(r'\bfrazal\b', 'phrasal', w["word"], flags=re.IGNORECASE)
        w["word"] = re.sub(r'\bfrazel\b', 'phrasal', w["word"], flags=re.IGNORECASE)
        # Convert "phrase" back to "phrasal" (TTS uses "phrase" for pronunciation)
        w["word"] = re.sub(r'\bphrase verb\b', 'phrasal verb', w["word"], flags=re.IGNORECASE)

    # Build per-turn speaker lookup
    turn_speaker_map: list[tuple[float, float, str]] = []
    events: list[str] = []

    reveal_windows = _pause_guess_windows(dialogue, per_turn_times or [])

    for i, (s, e) in enumerate(per_turn_times):
        if i < len(dialogue):
            turn_speaker_map.append((s, e, dialogue[i].get("speaker", "Emma")))

    # Add Idiom Box events (Top of screen)
    margin_v_top = 160 if is_shorts else 100
    _add_idiom_card_events(
        events,
        {"idiom_windows": dialogue[0].get("idiom_windows", []) if isinstance(dialogue, list) and dialogue and "idiom_windows" in dialogue[0] else []},
        per_turn_times,
        video_width,
        margin_v_top,
        reveal_windows,
    )
    _add_pause_guess_events(events, dialogue, per_turn_times or [], reveal_windows)

    def _speaker_at(t: float) -> str:
        for s, e, spk in turn_speaker_map:
            if s <= t < e:
                return spk
        return "Emma"

    if dialogue and per_turn_times and len(per_turn_times) == len(dialogue):
        grouped_words = _words_grouped_by_turn(words, dialogue, per_turn_times)
        _add_caption_events_from_turn_words(events, grouped_words, dialogue, max_chars, extra_idioms)
    else:
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
