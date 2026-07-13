import os
import subprocess
import math
import re
from pathlib import Path

# Fix absolute imports for modules in scripts/
import sys
sys.path.insert(0, str(Path(__file__).parent))

from ffmpeg_assembler import (
    append_channel_bumpers,
    get_audio_duration,
    _video_stream_info,
    TEMP_DIR,
    OUTPUT_DIR,
    ASSETS_DIR,
    FFMPEG,
    VIDEO_WIDTH,
    VIDEO_HEIGHT,
    VIDEO_FPS,
    SHORTS_WIDTH,
    SHORTS_HEIGHT,
)
from kokoro_tts import synthesize
from typing import Optional, Tuple, List
import shutil

ENGLISH_VOICES = {
    "Narrator": "af_bella",     # Keep: Best formal, structured American female narration (used by english pipeline)
    "Emma": "af_heart",         # Keep: Lively, high-energy, great for emotional dialogue
    "Liam": "am_michael",       # Upgrade: Replaces am_echo with the absolute best male voice
    "Guest": "bf_emma",         # Upgrade: Replaces af_sarah with a British female accent
    "Caller": "af_bella",       # Reuses af_bella voice for first-person storyteller in podcast format
    "StoryActor1": "am_adam",   # Default male character within stories
    "StoryActor2": "af_sarah",  # Default female character within stories
    "StoryActor1_Female": "af_bella",  # Alternative female voice for StoryActor1 (distinct from StoryActor2)
    "StoryActor2_Male": "am_echo",    # Alternative male voice for StoryActor2 (distinct from StoryActor1 and Liam)
    "StoryActor1_AltMale": "am_michael",    # Alternative male voice if StoryActor2 is also male (uses Liam's voice but acceptable as alt)
    "StoryActor2_AltFemale": "af_nicole", # Alternative female voice if StoryActor1 is also female (distinct from Emma's af_heart)
}

ENGLISH_TTS_SPEEDS = {
    "Narrator": 0.90,           # Slower for clear narration
    "Emma": 0.90,               # Normal pace for protagonist
    "Liam": 0.90,               # Normal pace for protagonist
    "Guest": 0.90,              # Slightly slower for guest characters
    "Caller": 0.90,             # Normal pace for caller storytelling
    "StoryActor1": 0.90,        # Normal pace for story characters
    "StoryActor2": 0.90,        # Normal pace for story characters
    "StoryActor1_Female": 0.90, # Alternative female voice
    "StoryActor2_Male": 0.90,   # Alternative male voice
    "StoryActor1_AltMale": 0.90,    # Alternative male voice
    "StoryActor2_AltFemale": 0.90,   # Alternative female voice
}

PAUSE_CUE_RE = re.compile(r"^\s*\[(?:PAUSE|PAUSE\s+(\d+(?:\.\d+)?)\s*SECONDS?)\]\s*$", re.IGNORECASE)

FADE_DURATION = 0.5  # crossfade duration in _xfade_video_clip_pair, used to extend pause-ending scene clips


def _pause_duration_seconds(text: str) -> float | None:
    match = PAUSE_CUE_RE.match(str(text or ""))
    if not match:
        return None
    if match.group(1):
        return max(0.25, min(float(match.group(1)), 10.0))
    return 1.0


def _gate_idiom_windows_after_pause_reveals(
    idiom_windows: list[dict] | None,
    dialogue: list[dict] | None,
) -> list[dict]:
    """Delay idiom overlays that intersect a pause-and-guess sequence until reveal."""
    if not idiom_windows or not dialogue:
        return idiom_windows or []

    reveal_windows: list[tuple[int, int, int]] = []
    for idx, turn in enumerate(dialogue):
        if _pause_duration_seconds(turn.get("text", "")) is None:
            continue
        prompt_idx = next(
            (j for j in range(idx - 1, -1, -1) if _pause_duration_seconds(dialogue[j].get("text", "")) is None),
            None,
        )
        reveal_idx = next(
            (j for j in range(idx + 1, len(dialogue)) if _pause_duration_seconds(dialogue[j].get("text", "")) is None),
            None,
        )
        if prompt_idx is not None and reveal_idx is not None:
            reveal_windows.append((prompt_idx, idx, reveal_idx))

    if not reveal_windows:
        return idiom_windows

    gated: list[dict] = []
    for window in idiom_windows:
        try:
            st = int(window.get("start_turn", 0))
            et = int(window.get("end_turn", st))
        except (TypeError, ValueError):
            gated.append(window)
            continue

        adjusted = dict(window)
        for prompt_idx, pause_idx, reveal_idx in reveal_windows:
            if st <= reveal_idx and et >= prompt_idx and st <= pause_idx:
                st = max(st, reveal_idx)
                et = max(et, st)
                adjusted["start_turn"] = st
                adjusted["end_turn"] = et
        gated.append(adjusted)
    return gated


def _generate_silence_audio(output_path: str, duration_seconds: float) -> str:
    subprocess.run([
        FFMPEG, "-y",
        "-f", "lavfi",
        "-i", "anullsrc=channel_layout=stereo:sample_rate=48000",
        "-t", str(duration_seconds),
        "-c:a", "aac",
        "-b:a", "192k",
        output_path,
        "-loglevel", "error",
    ], check=True)
    return output_path


def _pad_audio_with_silence(audio_path: str, pad_duration: float, output_path: str) -> str:
    """Append silence to an audio file. Copies input if pad_duration <= 0."""
    if pad_duration <= 0:
        import shutil
        if audio_path != output_path:
            shutil.copy2(audio_path, output_path)
        return output_path
    status = subprocess.run([
        FFMPEG, "-y",
        "-i", audio_path,
        "-f", "lavfi", "-t", str(pad_duration), "-i", "anullsrc=channel_layout=stereo:sample_rate=48000",
        "-filter_complex", "[0:a][1:a]concat=n=2:v=0:a=1[out]",
        "-map", "[out]",
        "-c:a", "aac", "-b:a", "192k",
        output_path, "-loglevel", "error",
    ], capture_output=True, text=True)
    if status.returncode != 0:
        print(f"  Warning: audio padding failed ({status.stderr.strip()}), using original")
        import shutil
        shutil.copy2(audio_path, output_path)
    return output_path


def prepare_face_badge(name: str, size: int) -> Optional[str]:
    """
    Crops the character face PNG to a circle of size x size.
    Returns path of crop in temp directory, or None if source missing.
    """
    from PIL import Image, ImageDraw
    project_root = Path(__file__).resolve().parent.parent
    src = project_root / "assets" / "characters" / name.lower() / "face.png"
    if not src.exists():
        return None

    dest_dir = project_root / "temp" / "badges"
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / f"{name.lower()}_badge_{size}.png"
    if dest.exists():
        return str(dest)

    try:
        im = Image.open(src).convert("RGBA")
        im = im.resize((size, size), Image.Resampling.LANCZOS)

        mask = Image.new("L", (size, size), 0)
        draw = ImageDraw.Draw(mask)
        draw.ellipse((0, 0, size, size), fill=255)

        output = Image.new("RGBA", (size, size), (0, 0, 0, 0))
        output.paste(im, (0, 0), mask=mask)
        output.save(dest, "PNG")
        return str(dest)
    except Exception as e:
        print(f"Error preparing face badge for {name}: {e}")
        return None

def apply_face_badge_overlays(
    video_path: str,
    dialogue: list[dict],
    per_turn_times: list[tuple[float, float]],
    output_path: str,
    is_shorts: bool = False,
) -> str:
    """
    Overlays the speaker's face PNG to the left of the captions during their speaking turns.
    """
    import shutil
    if not dialogue:
        if video_path != output_path:
            shutil.copy2(video_path, output_path)
        return output_path

    # Prepare badges for all characters
    size = 140 if is_shorts else 120
    emma_src = prepare_face_badge("Emma", size)
    liam_src = prepare_face_badge("Liam", size)
    narrator_src = prepare_face_badge("Narrator", size)
    guest_src = prepare_face_badge("Guest", size)
    caller_src = prepare_face_badge("Caller", size)
    story_actor1_src = prepare_face_badge("StoryActor1", size)
    story_actor2_src = prepare_face_badge("StoryActor2", size)
    story_actor1_female_src = prepare_face_badge("StoryActor1_Female", size)
    story_actor2_male_src = prepare_face_badge("StoryActor2_Male", size)
    story_actor1_altmale_src = prepare_face_badge("StoryActor1_AltMale", size)
    story_actor2_altfemale_src = prepare_face_badge("StoryActor2_AltFemale", size)
    
    # Check if any badges are available
    available_badges = {
        "emma": emma_src,
        "liam": liam_src,
        "narrator": narrator_src,
        "guest": guest_src,
        "caller": caller_src,
        "storyactor1": story_actor1_src,
        "storyactor2": story_actor2_src,
        "storyactor1_female": story_actor1_female_src,
        "storyactor2_male": story_actor2_male_src,
        "storyactor1_altmale": story_actor1_altmale_src,
        "storyactor2_altfemale": story_actor2_altfemale_src
    }
    if not any(available_badges.values()):
        # No face badges found — skip overlay
        print("  Face PNG badges not found, skipping face badge overlay.")
        if video_path != output_path:
            shutil.copy2(video_path, output_path)
        return output_path

    # If per_turn_times is empty, estimate based on video duration
    if not per_turn_times:
        from ffmpeg_assembler import get_media_duration
        try:
            total_dur = get_media_duration(video_path)
            turn_dur = total_dur / max(len(dialogue), 1)
            per_turn_times = [(i * turn_dur, (i + 1) * turn_dur) for i in range(len(dialogue))]
        except Exception:
            pass

    # Construct the active intervals for all characters
    intervals = {
        "emma": [],
        "liam": [],
        "narrator": [],
        "guest": [],
        "caller": [],
        "storyactor1": [],
        "storyactor2": [],
        "storyactor1_female": [],
        "storyactor2_male": [],
        "storyactor1_altmale": [],
        "storyactor2_altfemale": []
    }
    print(f"  [DEBUG] Avatar overlay: dialogue={len(dialogue)}, per_turn_times={len(per_turn_times)}")
    for i, turn in enumerate(dialogue):
        if i >= len(per_turn_times):
            print(f"  [DEBUG] Avatar overlay: skipping turn {i} (no timing)")
            break
        speaker = turn.get("speaker", "Emma").lower()
        start, end = per_turn_times[i]
        if end <= start:
            continue
        if speaker in intervals:
            intervals[speaker].append((start, end))
            print(f"  [DEBUG] Avatar overlay: {speaker} at {start:.2f}-{end:.2f}s")

    # Build enable expressions for each character that has a badge
    enable_expressions = {}
    for char, badge_src in available_badges.items():
        if badge_src and intervals[char]:
            enable_expressions[char] = "+".join(f"between(t,{s:.3f},{e:.3f})" for s, e in intervals[char])

    # Determine coordinates
    if is_shorts:
        x = 80  # Top-left with margin
        y = 80  # Top-left with margin
    else:
        x = 120  # Left with margin
        y = 720  # Left of captions

    inputs = [FFMPEG, "-y", "-i", video_path]
    filter_parts = []
    idx = 1
    prev_label = "0:v"

    # Overlay each character's badge when they speak
    for char in ["emma", "liam", "narrator", "guest", "caller", "storyactor1", "storyactor2", "storyactor1_female", "storyactor2_male", "storyactor1_altmale", "storyactor2_altfemale"]:
        if char in enable_expressions and available_badges[char]:
            inputs.extend(["-i", available_badges[char]])
            filter_parts.append(f"[{prev_label}][{idx}:v]overlay=x={x}:y={y}:enable='{enable_expressions[char]}'[v{idx}]")
            prev_label = f"v{idx}"
            idx += 1

    if idx == 1:
        # No intervals spoke — just copy
        if video_path != output_path:
            shutil.copy2(video_path, output_path)
        return output_path

    filter_complex = ";".join(filter_parts)
    # Output to video_path with audio copied
    cmd = inputs + [
        "-filter_complex", filter_complex,
        "-map", f"[v{idx-1}]",
        "-map", "0:a",
        "-c:v", "libx264", "-preset", "ultrafast", "-crf", "23",
        "-c:a", "copy",
        output_path
    ]
    subprocess.run(cmd, check=True)
    return output_path

def generate_podcast_audio(script_data: dict, return_turn_times: bool = False, speed: float = 0.98):
    """
    Generate TTS for each line of dialogue using the designated voices,
    then concatenate them into a single audio file.

    Parameters
    ----------
    return_turn_times : If True, returns (audio_path, per_turn_times) where
        per_turn_times is a list of (abs_start_sec, abs_end_sec) tuples,
        one per dialogue turn, needed for idiom overlay timestamp mapping.
    speed : Kokoro speech speed. ESL videos should stay clear; use pacing in
        the script/edits rather than speeding speech too much. This is used as
        a fallback if the speaker is not in ENGLISH_TTS_SPEEDS.
    """
    TEMP_DIR.mkdir(exist_ok=True)
    dialogue = script_data.get("dialogue", [])

    audio_files = []
    per_turn_durations: list[float] = []
    dialogue_only_durations: list[float] = []  # Track only spoken turn durations for caption timing

    print("\nGenerating podcast audio...")
    previous_speaker = None
    for i, line in enumerate(dialogue):
        speaker = line.get("speaker", "Emma")
        text = line.get("text", "")
        voice = ENGLISH_VOICES.get(speaker, "af_sarah")
        # Use character-specific speed if available, otherwise use fallback speed
        speaker_speed = ENGLISH_TTS_SPEEDS.get(speaker, speed)

        out_path = str(TEMP_DIR / f"english_line_{i:03d}.m4a")
        dur = 0.0

        try:
            pause_duration = _pause_duration_seconds(text)
            if pause_duration is not None:
                print(f"  [pause] {pause_duration:.1f}s -> {out_path}")
                _generate_silence_audio(out_path, pause_duration)
                dialogue_only_durations.append(pause_duration)
            else:
                print(f"  [{speaker}] (speed={speaker_speed}) -> {out_path}")
                synthesize(text, out_path, voice=voice, speed=speaker_speed, speaker=speaker)
                dialogue_only_durations.append(get_audio_duration(out_path))
            dur = get_audio_duration(out_path)
            audio_files.append(out_path)
            per_turn_durations.append(dur)
        except Exception as e:
            print(f"  Error generating audio for line {i}: {e}")
            per_turn_durations.append(0.0)
            dialogue_only_durations.append(0.0)
            audio_files.append(out_path)

        # Pad natural pause into the dialogue audio (avoid separate gap entries that
        # would desync per_turn_times from the actual track length).
        if pause_duration is None and i < len(dialogue) - 1:
            next_line = dialogue[i + 1]
            next_pause_duration = _pause_duration_seconds(next_line.get("text", ""))
            next_speaker = next_line.get("speaker", "Emma")
            if next_pause_duration is None:
                gap_duration = 0.3 if (speaker == "Narrator" or next_speaker == "Narrator") else 0.2
                padded_path = str(TEMP_DIR / f"english_line_{i:03d}_padded.m4a")
                _pad_audio_with_silence(out_path, gap_duration, padded_path)
                audio_files[-1] = padded_path
                dur += gap_duration
                per_turn_durations[-1] = dur
                dialogue_only_durations[-1] = dur

        previous_speaker = speaker

    # Concatenate all generated dialogue lines
    concat_list_path = str(TEMP_DIR / "english_audio_list.txt")
    with open(concat_list_path, "w") as f:
        for audio_file in audio_files:
            f.write(f"file '{os.path.abspath(audio_file)}'\n")

    final_audio_path = str(TEMP_DIR / "english_podcast_full.m4a")

    cmd = [
        FFMPEG, "-y",
        "-f", "concat", "-safe", "0", "-i", concat_list_path,
        "-c:a", "aac", "-b:a", "192k",
        final_audio_path
    ]
    subprocess.run(cmd, capture_output=True, check=True)

    print(f"  ✓ Full podcast audio generated: {final_audio_path}")

    if return_turn_times:
        cursor = 0.0
        turn_times: list[tuple[float, float]] = []
        for dur in dialogue_only_durations:
            turn_times.append((cursor, cursor + dur))
            cursor += dur
        return final_audio_path, turn_times

    return final_audio_path

def apply_idiom_overlays(
    video_path: str,
    idiom_windows: list[dict],
    card_pngs: dict[str, str],
    output_path: str,
    is_shorts: bool = False,
) -> str:
    """
    Composite idiom card PNGs into the video for their exact time windows.

    Parameters
    ----------
    video_path     : Input assembled video (with captions already burned in).
    idiom_windows  : List of dicts with abs_start_sec, abs_end_sec, idiom keys.
    card_pngs      : Dict mapping idiom string -> PNG file path.
    output_path    : Where to write the final video.
    is_shorts      : If True, places card in top-right; else bottom-right.

    Each card fades in 0.3 s and fades out 0.3 s at edges of the window.
    """
    if not idiom_windows or not card_pngs:
        # Nothing to overlay — just copy video to output
        if video_path != output_path:
            import shutil
            shutil.copy2(video_path, output_path)
        return output_path

    # Build inputs and filter_complex incrementally
    inputs = [FFMPEG, "-y", "-i", video_path]
    filter_parts: list[str] = []
    card_input_index = 1
    valid_windows: list[tuple[dict, int]] = []

    for window in idiom_windows:
        idiom = window.get("idiom", "")
        png_path = card_pngs.get(idiom)
        if not png_path or not Path(png_path).exists():
            continue
        inputs += ["-loop", "1", "-framerate", str(VIDEO_FPS), "-i", png_path]
        valid_windows.append((window, card_input_index))
        card_input_index += 1

    if not valid_windows:
        if video_path != output_path:
            import shutil
            shutil.copy2(video_path, output_path)
        return output_path

    print(f"  Compositing {len(valid_windows)} idiom card overlay(s)...")

    # Card position: bottom-right for landscape, top-right for shorts
    CARD_W = 420
    CARD_H = 180
    MARGIN = 20
    FADE   = 0.3

    if is_shorts:
        x_expr = f"W-{CARD_W + MARGIN}"
        y_expr = str(MARGIN + 80)   # below top safe area
    else:
        x_expr = f"W-{CARD_W + MARGIN}"
        y_expr = f"H-{CARD_H + MARGIN + 80}"  # above bottom captions area

    # Sort windows by start time to ensure proper layering
    valid_windows.sort(key=lambda x: x[0].get("abs_start_sec", 0.0))

    current_label = "[0:v]"
    for idx, (window, inp_idx) in enumerate(valid_windows):
        start = window.get("abs_start_sec", 0.0)
        end   = window.get("abs_end_sec",   start + 6.0)
        dur   = max(end - start, 1.0)
        fade_in_end  = start + FADE
        fade_out_start = end - FADE

        # Scale card PNG, then apply time-gated alpha fade
        scaled_label = f"[card{idx}scaled]"
        faded_label  = f"[card{idx}faded]"
        out_label    = f"[v{idx}]"

        filter_parts.append(
            f"[{inp_idx}:v]scale={CARD_W}:{CARD_H}[{scaled_label[1:-1]}]"
        )
        filter_parts.append(
            f"{scaled_label}format=rgba,"
            f"fade=t=in:st={start:.3f}:d={FADE}:alpha=1,"
            f"fade=t=out:st={fade_out_start:.3f}:d={FADE}:alpha=1"
            f"[{faded_label[1:-1]}]"
        )

        # Build enable expression: show this card only when it's active AND no later card is active
        # This prevents overlapping cards from appearing simultaneously
        enable_expr = f"between(t,{start:.3f},{end:.3f})"
        for later_idx in range(idx + 1, len(valid_windows)):
            later_start = valid_windows[later_idx][0].get("abs_start_sec", 0.0)
            enable_expr += f"*!between(t,{later_start:.3f},{later_start + 10:.3f})"

        filter_parts.append(
            f"{current_label}{faded_label}"
            f"overlay={x_expr}:{y_expr}:enable='{enable_expr}'"
            f"{out_label}"
        )
        current_label = out_label

    filter_complex = ";".join(filter_parts)
    final_label = current_label

    cmd = inputs + [
        "-filter_complex", filter_complex,
        "-map", final_label,
        "-map", "0:a",
        "-c:v", "libx264", "-preset", "ultrafast", "-crf", "23",
        "-c:a", "copy",
        "-movflags", "+faststart",
        output_path,
    ]

    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"  Idiom overlay failed (FFmpeg error), check console above for details.")
        if video_path != output_path:
            import shutil
            shutil.copy2(video_path, output_path)
    else:
        size_mb = Path(output_path).stat().st_size / 1024 / 1024
        print(f"  ✓ Idiom overlays applied: {output_path} ({size_mb:.1f} MB)")

    return output_path


def apply_cta_overlay(
    video_path: str,
    final_turn_start: float,
    final_turn_end: float,
    output_path: str,
) -> str:
    """
    Apply a visual CTA overlay (text + animated arrow) during the final turn
    to encourage clicking the playlist link.

    Parameters
    ----------
    video_path       : Input assembled video.
    final_turn_start : Start time of the final dialogue turn (seconds).
    final_turn_end   : End time of the final dialogue turn (seconds).
    output_path      : Where to write the final video.

    The overlay appears only during the final turn and cuts when audio ends
    to maintain the seamless loop.
    """
    if final_turn_start >= final_turn_end:
        # Invalid timing, just copy
        import shutil
        if video_path != output_path:
            shutil.copy2(video_path, output_path)
        return output_path

    print(f"  Applying CTA overlay during final turn ({final_turn_start:.2f}s - {final_turn_end:.2f}s)...")

    # Use FFmpeg drawtext filter for text and animated arrow
    # Text: "Tap link below for full playlist!" at y=h-650
    # Arrow: bouncing down-arrow at y=h-540 with sine wave animation
    cmd = [
        FFMPEG, "-y",
        "-i", video_path,
        "-filter_complex",
        f"[0:v]drawtext=text='Tap link below for full playlist!':fontcolor=white:fontsize=50:x=(w-text_w)/2:y=h-650:enable='between(t,{final_turn_start},{final_turn_end})',drawtext=text='↓':fontcolor=yellow:fontsize=90:x=(w-text_w)/2:y='h-540+30*sin(5*t)':enable='between(t,{final_turn_start},{final_turn_end})'[outv]",
        "-map", "[outv]",
        "-map", "0:a",
        "-c:v", "libx264", "-preset", "ultrafast", "-crf", "23",
        "-c:a", "copy",
        "-movflags", "+faststart",
        output_path,
        "-loglevel", "error",
    ]

    try:
        subprocess.run(cmd, check=True)
        size_mb = Path(output_path).stat().st_size / 1024 / 1024
        print(f"  ✓ CTA overlay applied: {output_path} ({size_mb:.1f} MB)")
    except subprocess.CalledProcessError as e:
        print(f"  CTA overlay failed: {e}")
        # Fallback: copy original
        import shutil
        if video_path != output_path:
            shutil.copy2(video_path, output_path)

    return output_path


def apply_summary_overlay(
    video_path: str,
    summary_start: float,
    summary_end: float,
    summary_png: str,
    output_path: str,
) -> str:
    """
    Composite the full-frame "What We Learned Today" summary card PNG
    on top of the video during the narrator's closing lines.

    The overlay fades in over 0.5 s and fades out over 0.5 s.
    """
    if summary_start >= summary_end or not Path(summary_png).exists():
        if video_path != output_path:
            import shutil
            shutil.copy2(video_path, output_path)
        return output_path

    overlay_dur = summary_end - summary_start

    print(f"  Applying summary card overlay ({summary_start:.2f}s – {summary_end:.2f}s)...")

    cmd = [
        FFMPEG, "-y",
        "-i", video_path,
        "-loop", "1", "-framerate", str(VIDEO_FPS), "-t", f"{overlay_dur:.3f}",
        "-i", summary_png,
        "-filter_complex",
        f"[0:v][1:v]overlay=0:0:enable='between(t,{summary_start:.3f},{summary_end:.3f})'[outv]",
        "-map", "[outv]",
        "-map", "0:a",
        "-c:v", "libx264", "-preset", "ultrafast", "-crf", "23",
        "-c:a", "copy",
        "-movflags", "+faststart",
        output_path, "-loglevel", "error",
    ]

    try:
        subprocess.run(cmd, check=True)
        size_mb = Path(output_path).stat().st_size / 1024 / 1024
        print(f"  ✓ Summary card overlay applied: {output_path} ({size_mb:.1f} MB)")
    except subprocess.CalledProcessError as e:
        print(f"  Summary card overlay failed: {e}")
        if video_path != output_path:
            import shutil
            shutil.copy2(video_path, output_path)

    return output_path


def resolve_idiom_timestamps(
    idiom_windows: list[dict],
    per_turn_times: list[tuple[float, float]],
    bumper_pad: float = 0.0,
) -> list[dict]:
    """
    Convert turn-index ranges in idiom_windows to absolute seconds,
    adding bumper_pad (intro bumper duration) as an offset.

    Returns a new list of dicts with abs_start_sec and abs_end_sec added.
    """
    resolved = []
    n = len(per_turn_times)
    for window in idiom_windows:
        st = window.get("start_turn", 0)
        et = window.get("end_turn", st)
        st = max(0, min(st, n - 1)) if n else 0
        et = max(st, min(et, n - 1)) if n else 0

        abs_start = (per_turn_times[st][0] if n else 0.0) + bumper_pad
        abs_end   = (per_turn_times[et][1] if n else 0.0) + bumper_pad
        resolved.append({**window, "abs_start_sec": abs_start, "abs_end_sec": abs_end})
    return resolved


def scene_duration_from_turns(scene: dict, per_turn_times: list, dialogue: list | None = None) -> float:
    """Compute scene duration from Kokoro audio turn timestamps."""
    if not per_turn_times:
        return 5.0
    start_turn = max(0, min(int(scene.get("start_turn", 0)), len(per_turn_times) - 1))
    end_turn = max(start_turn, min(int(scene.get("end_turn", start_turn)), len(per_turn_times) - 1))
    duration = max(0.5, per_turn_times[end_turn][1] - per_turn_times[start_turn][0])
    # Extend scene by fade duration if it ends with a [PAUSE] turn, so the
    # crossfade to the next scene happens after the silence ends.
    if dialogue and end_turn < len(dialogue):
        last_text = dialogue[end_turn].get("text", "")
        if _pause_duration_seconds(last_text) is not None:
            duration += FADE_DURATION
            print(f"  [DEBUG] Extended pause-ending scene {scene.get('scene_id', '?')} by {FADE_DURATION:.1f}s")
    print(f"  [DEBUG] Scene {scene.get('scene_id', '?')}: start_turn={start_turn}, end_turn={end_turn}, duration={duration:.2f}s")
    return duration


def _render_kb_clip(
    image_path: str,
    output_path: str,
    duration: float,
    width: int,
    height: int,
    *,
    zoom_in: bool = True,
    zoom_rate: float = 0.003,
    zoom_max: float = 1.25,
) -> None:
    """Render a single Ken Burns clip with eased zoom.

    Uses a sinusoidal acceleration curve so the zoom starts gently,
    picks up speed mid-scene, and eases into the max — creating a
    more cinematic "push in" feel than a linear ramp.
    """
    fps = VIDEO_FPS
    total_frames = max(round(duration * fps), 2)
    scale_w = width * 2
    scale_h = height * 2

    if zoom_in:
        # Ease-in: rate accelerates via sin curve, starting slow
        zoom_expr = f"min(zoom+{zoom_rate}*(1+0.5*sin(PI*on/({total_frames})))+0.0005,{zoom_max})"
    else:
        # Ease-out: decelerate as we zoom out
        zoom_expr = f"max(1.0,zoom-{zoom_rate}*(1+0.5*sin(PI*on/({total_frames})))-0.0005)"

    vf = (
        f"scale={scale_w}:{scale_h}:force_original_aspect_ratio=increase,"
        f"crop={scale_w}:{scale_h},"
        f"zoompan=z='{zoom_expr}':"
        f"x='iw/2-(iw/zoom/2)':"
        f"y='ih/2-(ih/zoom/2)':"
        f"d={total_frames}:s={width}x{height}:fps={fps}"
    )
    subprocess.run([
        FFMPEG, "-y",
        "-loop", "1", "-i", image_path,
        "-t", str(duration),
        "-vf", vf,
        "-c:v", "libx264", "-preset", "ultrafast", "-crf", "23",
        "-pix_fmt", "yuv420p",
        "-an", output_path, "-loglevel", "error",
    ], check=True)


def _kenburns_image_to_video(
    image_path: str,
    duration: float,
    output_path: str,
    width: int,
    height: int,
    *,
    zoom_in: bool = True,
    zoom_rate: float = 0.003,
    zoom_max: float = 1.25,
) -> None:
    """Convert a still image to a Ken Burns video clip with smooth zoompan.

    For clips > 10 seconds, splits into two phases with opposite zoom
    directions to reduce visual monotony and create rhythmic visual shifts.
    """
    if duration <= 10:
        _render_kb_clip(image_path, output_path, duration, width, height,
                        zoom_in=zoom_in, zoom_rate=zoom_rate, zoom_max=zoom_max)
        return

    mid = duration / 2
    phase1 = str(TEMP_DIR / f"{Path(output_path).stem}_p1.mp4")
    phase2 = str(TEMP_DIR / f"{Path(output_path).stem}_p2.mp4")
    _render_kb_clip(image_path, phase1, mid, width, height,
                    zoom_in=zoom_in, zoom_rate=zoom_rate, zoom_max=zoom_max)
    _render_kb_clip(image_path, phase2, mid, width, height,
                    zoom_in=not zoom_in, zoom_rate=zoom_rate, zoom_max=zoom_max)

    list_path = str(TEMP_DIR / f"{Path(output_path).stem}_phases.txt")
    with open(list_path, "w") as f:
        f.write(f"file '{os.path.abspath(phase1)}'\n")
        f.write(f"file '{os.path.abspath(phase2)}'\n")
    subprocess.run([
        FFMPEG, "-y",
        "-f", "concat", "-safe", "0", "-i", list_path,
        "-c:v", "libx264", "-preset", "ultrafast", "-crf", "23",
        "-pix_fmt", "yuv420p",
        "-an", output_path, "-loglevel", "error",
    ], check=True)


def _xfade_video_clip_pair(
    clip_a: str,
    clip_b: str,
    output_path: str,
    fade_duration: float = 0.5,
) -> None:
    """Crossfade two video-only clips (no audio streams)."""
    dur_a = get_audio_duration(clip_a)
    dur_b = get_audio_duration(clip_b)
    transition_dur = min(fade_duration, dur_a, dur_b)

    if transition_dur <= 0:
        list_path = str(TEMP_DIR / f"xfade_fallback_{Path(output_path).stem}.txt")
        with open(list_path, "w") as f:
            f.write(f"file '{os.path.abspath(clip_a)}'\n")
            f.write(f"file '{os.path.abspath(clip_b)}'\n")
        subprocess.run([
            FFMPEG, "-y",
            "-f", "concat", "-safe", "0", "-i", list_path,
            "-c:v", "libx264", "-preset", "ultrafast", "-crf", "23",
            "-pix_fmt", "yuv420p",
            "-an", output_path, "-loglevel", "error",
        ], check=True)
        return

    offset = max(dur_a - transition_dur, 0)
    subprocess.run([
        FFMPEG, "-y",
        "-i", clip_a, "-i", clip_b,
        "-filter_complex",
        f"[0:v]fps={VIDEO_FPS},setsar=1,settb=AVTB[v0];"
        f"[1:v]fps={VIDEO_FPS},setsar=1,settb=AVTB[v1];"
        f"[v0][v1]xfade=transition=fade:duration={transition_dur}:"
        f"offset={offset},format=yuv420p[v]",
        "-map", "[v]",
        "-c:v", "libx264", "-preset", "fast", "-crf", "20",
        "-pix_fmt", "yuv420p",
        "-an", output_path, "-loglevel", "error",
    ], check=True)


def build_scene_visual_track(
    scenes: list,
    scene_image_paths: list[str],
    per_turn_times: list,
    *,
    portrait: bool = False,
    dialogue: list | None = None,
) -> str:
    """Build crossfaded Ken Burns visual track timed to scene dialogue durations."""
    TEMP_DIR.mkdir(exist_ok=True)
    width = SHORTS_WIDTH if portrait else VIDEO_WIDTH
    height = SHORTS_HEIGHT if portrait else VIDEO_HEIGHT

    kb_scenes = []
    kb_paths = []
    for scene, img_path in zip(scenes, scene_image_paths):
        kb_scenes.append(scene)
        kb_paths.append(img_path)

    clip_paths: list[str] = []
    for idx, (scene, image_path) in enumerate(zip(kb_scenes, kb_paths)):
        duration = scene_duration_from_turns(scene, per_turn_times, dialogue)
        clip_path = str(TEMP_DIR / f"english_scene_clip_{idx:03d}.mp4")
        print(f"  Scene {scene.get('scene_id', idx + 1)}: {duration:.1f}s — {Path(image_path).name}")
        # Hook scene (index 0) gets faster zoom for visual energy; rest use standard rate
        is_hook = (idx == 0)
        kb_zoom_rate = 0.004 if is_hook else 0.003
        kb_zoom_max = 1.30 if is_hook else 1.25
        _kenburns_image_to_video(
            str(image_path),
            duration,
            clip_path,
            width,
            height,
            zoom_in=(idx % 2 == 0),
            zoom_rate=kb_zoom_rate,
            zoom_max=kb_zoom_max,
        )
        clip_paths.append(clip_path)

    visual_track = str(TEMP_DIR / "english_scene_visual_track.mp4")
    if len(clip_paths) <= 1:
        shutil.copy2(clip_paths[0], visual_track) if clip_paths else None
    else:
        current = clip_paths[0]
        for i, next_clip in enumerate(clip_paths[1:], start=1):
            pair_out = str(TEMP_DIR / f"scene_xfade_{i:02d}.mp4")
            _xfade_video_clip_pair(current, next_clip, pair_out, fade_duration=0.5)
            current = pair_out
        shutil.copy2(current, visual_track)

    print(f"  Scene visual track assembled ({len(clip_paths)} scene(s))")
    return visual_track


def assemble_english_video(
    podcast_audio: str,
    loop_visual: str,
    output_path: str,
    captions_srt: str = None,
    ass_captions: str = None,
    background_music: str = None,
    title: str = "",
    channel: str = None,
    idiom_windows: list = None,
    per_turn_times: list = None,
    dialogue: list = None,
    loop_visuals: list[str] = None,
    portrait: bool = False,
) -> str:
    """
    Assemble the final English learning video:
    - Loops one or more background visuals
    - Mixes the podcast audio with subtle background music
    - Burns subtitles (.ass preferred for karaoke; .srt fallback)
    - Composites Idiom Card overlays if idiom_windows provided
    """
    duration = get_audio_duration(podcast_audio)
    print(f"\nAssembling English video: {duration:.1f}s")

    visual_inputs = [str(v) for v in (loop_visuals or []) if v]
    if not visual_inputs and loop_visual:
        visual_inputs = [str(loop_visual)]
    if not visual_inputs:
        raise ValueError("assemble_english_video requires at least one visual loop.")

    # 1. Normalize visuals to correct size/fps first
    normalized_visuals = []
    for index, visual in enumerate(visual_inputs):
        norm_visual = str(TEMP_DIR / f"english_norm_{index:03d}.mp4")
        subprocess.run([
            FFMPEG, "-y", "-i", visual,
            "-vf", f"scale={VIDEO_WIDTH}:{VIDEO_HEIGHT}:force_original_aspect_ratio=decrease,"
                   f"pad={VIDEO_WIDTH}:{VIDEO_HEIGHT}:(ow-iw)/2:(oh-ih)/2:black,"
                   f"fps={VIDEO_FPS}",
            "-c:v", "libx264", "-preset", "ultrafast", "-crf", "23", "-pix_fmt", "yuv420p",
            "-an", norm_visual, "-loglevel", "error"
        ], check=True)
        normalized_visuals.append(norm_visual)
    print(f"  Visuals normalized: {len(normalized_visuals)}")

    # 1b. Concatenate the normalized visuals, repeating them if needed.
    total_visual_duration = sum(get_audio_duration(v) for v in normalized_visuals)
    if total_visual_duration <= 0:
        raise RuntimeError("Selected English visual loops have no readable duration.")
    visual_sequence = list(normalized_visuals)
    if total_visual_duration < duration:
        loops_needed = math.ceil(duration / total_visual_duration)
        visual_sequence = visual_sequence * loops_needed

    list_path = str(TEMP_DIR / "english_visuals.txt")
    with open(list_path, "w", encoding="utf-8") as handle:
        for visual in visual_sequence:
            handle.write(f"file '{os.path.abspath(visual)}'\n")

    visual_track = str(TEMP_DIR / "english_visual_track.mp4")
    subprocess.run([
        FFMPEG, "-y",
        "-f", "concat", "-safe", "0", "-i", list_path,
        "-t", str(duration),
        "-c:v", "libx264", "-preset", "ultrafast", "-crf", "23",
        "-an", visual_track, "-loglevel", "error"
    ], check=True)
    print("  Visual track assembled")

    # 2. Mix podcast audio with background music
    if background_music and Path(background_music).exists():
        mixed_audio_path = str(TEMP_DIR / "english_mixed_audio.m4a")
        cmd = [
            FFMPEG, "-y",
            "-i", podcast_audio,
            "-stream_loop", "-1", "-i", background_music,
            "-filter_complex",
            "[0:a]volume=1.0[narr];[1:a]volume=0.08[bg];[narr][bg]amix=inputs=2:duration=first:dropout_transition=3[out]",
            "-map", "[out]",
            "-t", str(duration),
            "-c:a", "aac", "-b:a", "192k",
            mixed_audio_path
        ]
        subprocess.run(cmd, capture_output=True, check=True)
        print("  Audio mixed with background music")
        final_audio = mixed_audio_path
    else:
        final_audio = podcast_audio

    # 3. Combine visual loop + audio + subtitles in a single pass
    base_output = output_path
    try:
        # Prefer .ass (karaoke + avatar badges); fall back to .srt with style
        has_ass = ass_captions and Path(ass_captions).exists()
        has_srt = captions_srt and Path(captions_srt).exists()

        vf_filter_parts = []
        if has_ass:
            # Escape colon in path for FFmpeg filter (Windows + macOS)
            ass_escaped = str(ass_captions).replace("\\", "/").replace(":", "\\:")
            vf_filter_parts.append(f"ass={ass_escaped}")
        elif has_srt:
            caption_style = (
                "FontName=Arial,FontSize=22,"
                "PrimaryColour=&H0000FFFF,OutlineColour=&H00000000,"
                "Bold=1,BorderStyle=1,Outline=4,Shadow=2,MarginV=40"
            )
            vf_filter_parts.append(f"subtitles={captions_srt}:force_style='{caption_style}'")

        vf_filter = ",".join(vf_filter_parts) if vf_filter_parts else "null"

        cmd = [
            FFMPEG, "-y",
            "-i", visual_track,
            "-i", final_audio,
            "-vf", vf_filter,
            "-map", "0:v", "-map", "1:a",
            "-c:v", "libx264", "-preset", "ultrafast", "-crf", "23",
            "-c:a", "copy",
            "-movflags", "+faststart",
            "-metadata", f"title={title}",
            base_output, "-loglevel", "error"
        ]
        subprocess.run(cmd, check=True, capture_output=True)
    except subprocess.CalledProcessError as e:
        print(f"  Caption burn failed, assembling without captions... Error: {e.stderr}")
        # Fallback without captions
        cmd = [
            FFMPEG, "-y",
            "-i", visual_track,
            "-i", final_audio,
            "-map", "0:v", "-map", "1:a",
            "-c:v", "libx264", "-preset", "ultrafast", "-crf", "23",
            "-c:a", "copy",
            "-movflags", "+faststart",
            "-metadata", f"title={title}",
            base_output, "-loglevel", "error"
        ]
        subprocess.run(cmd, check=True, capture_output=True)

    # Apply face overlays if .ass subtitles are used and face PNGs exist
    if has_ass and dialogue:
        temp_face = str(Path(base_output).with_suffix(".face.mp4"))
        try:
            apply_face_badge_overlays(
                video_path=base_output,
                dialogue=dialogue,
                per_turn_times=per_turn_times or [],
                output_path=temp_face,
                is_shorts=portrait
            )
            if Path(temp_face).exists():
                Path(base_output).unlink()
                import shutil
                shutil.move(temp_face, base_output)
        except Exception as e:
            print(f"  Face badge overlay skipped: {e}")

    # Apply CTA overlay for shorts/quiz formats (portrait mode)
    if portrait and dialogue and per_turn_times:
        try:
            final_turn_start = per_turn_times[-1][0]
            final_turn_end = per_turn_times[-1][1]
            temp_cta = str(Path(base_output).with_suffix(".cta.mp4"))
            apply_cta_overlay(
                video_path=base_output,
                final_turn_start=final_turn_start,
                final_turn_end=final_turn_end,
                output_path=temp_cta,
            )
            if Path(temp_cta).exists():
                Path(base_output).unlink()
                import shutil
                shutil.move(temp_cta, base_output)
        except Exception as e:
            print(f"  CTA overlay skipped: {e}")

    append_channel_bumpers(base_output, channel=channel, portrait=portrait)


    size_mb = Path(output_path).stat().st_size / 1024 / 1024
    print(f"  ✓ English video assembled: {output_path} ({size_mb:.1f} MB)")
    return output_path


def assemble_english_scene_video(
    podcast_audio: str,
    scenes: list,
    scene_image_paths: list[str],
    output_path: str,
    per_turn_times: list,
    *,
    portrait: bool = False,
    captions_srt: str = None,
    ass_captions: str = None,
    background_music: str = None,
    title: str = "",
    channel: str = None,
    idiom_windows: list = None,
    dialogue: list = None,
) -> str:
    """
    Assemble English video using scene-based Ken Burns stills timed to Kokoro audio.
    """
    duration = get_audio_duration(podcast_audio)
    print(f"\nAssembling scene-based English video: {duration:.1f}s ({len(scenes)} scenes)")

    visual_track = build_scene_visual_track(
        scenes,
        scene_image_paths,
        per_turn_times,
        portrait=portrait,
        dialogue=dialogue,
    )

    visual_duration = get_audio_duration(visual_track)
    if abs(visual_duration - duration) > 0.25:
        if visual_duration < duration:
            padded = str(TEMP_DIR / "english_scene_visual_padded.mp4")
            pad_secs = duration - visual_duration
            subprocess.run([
                FFMPEG, "-y", "-i", visual_track,
                "-vf", f"tpad=stop_mode=clone:stop_duration={pad_secs}",
                "-c:v", "libx264", "-preset", "ultrafast", "-crf", "23",
                "-an", padded, "-loglevel", "error",
            ], check=True)
            visual_track = padded
        else:
            trimmed = str(TEMP_DIR / "english_scene_visual_trimmed.mp4")
            subprocess.run([
                FFMPEG, "-y", "-i", visual_track,
                "-t", str(duration),
                "-c:v", "libx264", "-preset", "ultrafast", "-crf", "23",
                "-an", trimmed, "-loglevel", "error",
            ], check=True)
            visual_track = trimmed

    if background_music and Path(background_music).exists():
        mixed_audio_path = str(TEMP_DIR / "english_mixed_audio.m4a")
        cmd = [
            FFMPEG, "-y",
            "-i", podcast_audio,
            "-stream_loop", "-1", "-i", background_music,
            "-filter_complex",
            "[0:a]volume=1.0[narr];[1:a]volume=0.08[bg];[narr][bg]amix=inputs=2:duration=first:dropout_transition=3[out]",
            "-map", "[out]",
            "-t", str(duration),
            "-c:a", "aac", "-b:a", "192k",
            mixed_audio_path,
        ]
        subprocess.run(cmd, capture_output=True, check=True)
        final_audio = mixed_audio_path
    else:
        final_audio = podcast_audio

    base_output = output_path
    has_ass = ass_captions and Path(ass_captions).exists()
    has_srt = captions_srt and Path(captions_srt).exists()

    vf_filter_parts = []
    if has_ass:
        ass_escaped = str(ass_captions).replace("\\", "/").replace(":", "\\:")
        vf_filter_parts.append(f"ass={ass_escaped}")
    elif has_srt:
        caption_style = (
            "FontName=Arial,FontSize=22,"
            "PrimaryColour=&H0000FFFF,OutlineColour=&H00000000,"
            "Bold=1,BorderStyle=1,Outline=4,Shadow=2,MarginV=40"
        )
        vf_filter_parts.append(f"subtitles={captions_srt}:force_style='{caption_style}'")
    vf_filter_parts.append(
        f"drawbox=x=0:y=ih-4:w='iw*min(t/{duration},1)':h=4:color=white@0.5:t=fill"
    )
    vf_filter = ",".join(vf_filter_parts) if vf_filter_parts else "null"

    try:
        cmd = [
            FFMPEG, "-y",
            "-i", visual_track,
            "-i", final_audio,
            "-vf", vf_filter,
            "-map", "0:v", "-map", "1:a",
            "-c:v", "libx264", "-preset", "ultrafast", "-crf", "23",
            "-c:a", "copy",
            "-movflags", "+faststart",
            "-metadata", f"title={title}",
            base_output, "-loglevel", "error",
        ]
        subprocess.run(cmd, check=True, capture_output=True)
    except subprocess.CalledProcessError as e:
        print(f"  Caption burn failed, assembling without captions... Error: {getattr(e, 'stderr', e)}")
        cmd = [
            FFMPEG, "-y",
            "-i", visual_track,
            "-i", final_audio,
            "-map", "0:v", "-map", "1:a",
            "-c:v", "libx264", "-preset", "ultrafast", "-crf", "23",
            "-c:a", "copy",
            "-movflags", "+faststart",
            "-metadata", f"title={title}",
            base_output, "-loglevel", "error",
        ]
        subprocess.run(cmd, check=True, capture_output=True)

    if has_ass and dialogue:
        temp_face = str(Path(base_output).with_suffix(".face.mp4"))
        try:
            apply_face_badge_overlays(
                video_path=base_output,
                dialogue=dialogue,
                per_turn_times=per_turn_times or [],
                output_path=temp_face,
                is_shorts=portrait,
            )
            if Path(temp_face).exists():
                Path(base_output).unlink()
                import shutil
                shutil.move(temp_face, base_output)
        except Exception as e:
            print(f"  Face badge overlay skipped: {e}")

    gated_idiom_windows = _gate_idiom_windows_after_pause_reveals(idiom_windows, dialogue)
    if gated_idiom_windows and per_turn_times:
        try:
            from idiom_card_renderer import render_idiom_cards_batch

            resolved = resolve_idiom_timestamps(gated_idiom_windows, per_turn_times)
            card_pngs = render_idiom_cards_batch(gated_idiom_windows, output_dir=TEMP_DIR / "idiom_cards")
            apply_idiom_overlays(base_output, resolved, card_pngs, output_path=base_output, is_shorts=portrait)
        except Exception as e:
            print(f"  Idiom overlay skipped: {e}")

    # Apply CTA overlay for shorts/quiz formats (portrait mode)
    if portrait and dialogue and per_turn_times:
        try:
            final_turn_start = per_turn_times[-1][0]
            final_turn_end = per_turn_times[-1][1]
            temp_cta = str(Path(base_output).with_suffix(".cta.mp4"))
            apply_cta_overlay(
                video_path=base_output,
                final_turn_start=final_turn_start,
                final_turn_end=final_turn_end,
                output_path=temp_cta,
            )
            if Path(temp_cta).exists():
                Path(base_output).unlink()
                import shutil
                shutil.move(temp_cta, base_output)
        except Exception as e:
            print(f"  CTA overlay skipped: {e}")

    # ── Summary card text overlay ──────────────────────────────────────────
    # Find the summary card scene and composite the "What We Learned Today"
    # PNG on top of the video during the narrator's closing lines.
    if not portrait and per_turn_times:
        summary_scene = None
        summary_scene_idx = None
        for _idx, sc in enumerate(scenes):
            if str(sc.get("scene_label", "")).lower() == "summary card":
                summary_scene = sc
                summary_scene_idx = _idx
                break
        if summary_scene is not None and summary_scene_idx is not None:
            try:
                from summary_card_renderer import render_summary_card

                s_turn = max(0, min(int(summary_scene.get("start_turn", 0)), len(per_turn_times) - 1))
                e_turn = max(s_turn, min(int(summary_scene.get("end_turn", s_turn)), len(per_turn_times) - 1))
                summary_start = per_turn_times[s_turn][0]
                summary_end = per_turn_times[e_turn][1]

                bg_path = scene_image_paths[summary_scene_idx] if summary_scene_idx < len(scene_image_paths) else None
                summary_dir = TEMP_DIR / "summary_card"
                summary_png = render_summary_card(
                    idiom_windows=idiom_windows or [],
                    output_dir=summary_dir,
                    is_shorts=False,
                    bg_image_path=bg_path,
                )
                if Path(summary_png).exists():
                    temp_summary = str(Path(base_output).with_suffix(".summary.mp4"))
                    apply_summary_overlay(
                        video_path=base_output,
                        summary_start=summary_start,
                        summary_end=summary_end,
                        summary_png=summary_png,
                        output_path=temp_summary,
                    )
                    if Path(temp_summary).exists():
                        Path(base_output).unlink()
                        import shutil
                        shutil.move(temp_summary, base_output)
            except Exception as e:
                print(f"  Summary card overlay skipped: {e}")

    append_channel_bumpers(base_output, channel=channel, portrait=portrait)

    size_mb = Path(output_path).stat().st_size / 1024 / 1024
    print(f"  ✓ Scene-based English video assembled: {output_path} ({size_mb:.1f} MB)")
    return output_path


def cleanup_english_temp():
    import shutil
    if TEMP_DIR.exists():
        shutil.rmtree(TEMP_DIR)
        TEMP_DIR.mkdir()
    print("  Temp files cleaned.")


def _append_summary_card(
    video_path: str,
    idiom_windows: list,
    summary_bg_image: str = None,
    scene_visual_prompt: str = "",
    background_music: str = None,
    is_shorts: bool = False,
) -> str:
    """Append a 5-second summary card to the end of the assembled video.

    The card shows 'What We Learned Today' with the key idioms.
    If summary_bg_image is provided (pre-generated Gemini image), it is used
    directly. Otherwise falls back to the gradient background.
    """
    from summary_card_renderer import render_summary_card

    summary_dir = TEMP_DIR / "summary_card"
    summary_png = render_summary_card(
        idiom_windows=idiom_windows or [],
        scene_visual_prompt=scene_visual_prompt,
        output_dir=summary_dir,
        is_shorts=is_shorts,
        bg_image_path=summary_bg_image,
    )

    if not Path(summary_png).exists():
        print("  Summary card PNG not generated, skipping.")
        return video_path

    card_dur = 5.0
    vid_info = _video_stream_info(video_path)
    vw, vh = vid_info["width"], vid_info["height"]
    fps = VIDEO_FPS

    # Render summary card as a video clip (static image → video)
    summary_video = str(TEMP_DIR / "summary_card_clip.mp4")
    vf = (
        f"scale={vw}:{vh}:force_original_aspect_ratio=increase,"
        f"crop={vw}:{vh},"
        f"fps={fps},setsar=1"
    )
    cmd = [
        FFMPEG, "-y",
        "-loop", "1", "-i", summary_png,
        "-t", str(card_dur),
        "-vf", vf,
        "-c:v", "libx264", "-preset", "ultrafast", "-crf", "23",
        "-pix_fmt", "yuv420p",
        "-an", summary_video, "-loglevel", "error",
    ]
    subprocess.run(cmd, check=True)

    # Mix background music into the summary card clip
    if background_music and Path(background_music).exists():
        summary_audio = str(TEMP_DIR / "summary_card_audio.m4a")
        cmd = [
            FFMPEG, "-y",
            "-i", summary_video,
            "-stream_loop", "-1", "-i", background_music,
            "-filter_complex",
            "[1:a]volume=0.10[bg];[bg]atrim=0:{dur}[out]".format(dur=card_dur),
            "-map", "0:v", "-map", "[out]",
            "-t", str(card_dur),
            "-c:v", "copy", "-c:a", "aac", "-b:a", "192k",
            summary_audio, "-loglevel", "error",
        ]
        subprocess.run(cmd, check=True)
        if Path(summary_audio).exists():
            summary_video = summary_audio
    else:
        # Add silent audio so concat filter works with the audio-equipped main video
        summary_with_silence = str(TEMP_DIR / "summary_card_silent.m4a")
        cmd = [
            FFMPEG, "-y",
            "-i", summary_video,
            "-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo",
            "-map", "0:v", "-map", "1:a",
            "-t", str(card_dur),
            "-c:v", "copy", "-c:a", "aac", "-b:a", "192k",
            summary_with_silence, "-loglevel", "error",
        ]
        subprocess.run(cmd, check=True)
        if Path(summary_with_silence).exists():
            summary_video = summary_with_silence

    # Concatenate main video + summary card using filter_complex
    # (handles mixed audio/video stream counts gracefully)
    temp_out = str(Path(video_path).with_suffix(".with_summary.mp4"))
    cmd = [
        FFMPEG, "-y",
        "-i", video_path,
        "-i", summary_video,
        "-filter_complex",
        "[0:v][0:a][1:v][1:a]concat=n=2:v=1:a=1[outv][outa]",
        "-map", "[outv]", "-map", "[outa]",
        "-c:v", "libx264", "-preset", "ultrafast", "-crf", "23",
        "-c:a", "aac", "-b:a", "192k",
        "-movflags", "+faststart",
        temp_out, "-loglevel", "error",
    ]
    subprocess.run(cmd, check=True)

    if Path(temp_out).exists():
        Path(video_path).unlink()
        shutil.move(temp_out, video_path)
        print(f"  ✓ Summary card appended ({card_dur}s)")

    return video_path


def assemble_english_podcast_video(
    podcast_audio: str,
    scenes: list,
    scene_image_paths: list[str],
    output_path: str,
    per_turn_times: list,
    *,
    captions_srt: str = None,
    ass_captions: str = None,
    background_music: str = None,
    title: str = "",
    channel: str = None,
    idiom_windows: list = None,
    dialogue: list = None,
) -> str:
    """
    Assemble English Vibes Podcast video:
    - Switches between host image (podcast_host.png) and story scenes
    - Timed Ken Burns visual track
    - Generates dynamic audiogram overlay using showwaves filter
    - Burns in ASS/SRT subtitles
    - Applies summary card/idiom overlays and appends bumpers
    """
    duration = get_audio_duration(podcast_audio)
    print(f"\nAssembling English podcast video: {duration:.1f}s ({len(scenes)} scenes)")

    visual_track = build_scene_visual_track(
        scenes,
        scene_image_paths,
        per_turn_times,
        portrait=False,
        dialogue=dialogue,
    )

    visual_duration = get_audio_duration(visual_track)
    if abs(visual_duration - duration) > 0.25:
        if visual_duration < duration:
            padded = str(TEMP_DIR / "english_scene_visual_padded.mp4")
            pad_secs = duration - visual_duration
            subprocess.run([
                FFMPEG, "-y", "-i", visual_track,
                "-vf", f"tpad=stop_mode=clone:stop_duration={pad_secs}",
                "-c:v", "libx264", "-preset", "ultrafast", "-crf", "23",
                "-an", padded, "-loglevel", "error",
            ], check=True)
            visual_track = padded
        else:
            trimmed = str(TEMP_DIR / "english_scene_visual_trimmed.mp4")
            subprocess.run([
                FFMPEG, "-y", "-i", visual_track,
                "-t", str(duration),
                "-c:v", "libx264", "-preset", "ultrafast", "-crf", "23",
                "-an", trimmed, "-loglevel", "error",
            ], check=True)
            visual_track = trimmed

    if background_music and Path(background_music).exists():
        mixed_audio_path = str(TEMP_DIR / "english_mixed_audio.m4a")
        cmd = [
            FFMPEG, "-y",
            "-i", podcast_audio,
            "-stream_loop", "-1", "-i", background_music,
            "-filter_complex",
            "[0:a]volume=1.0[narr];[1:a]volume=0.08[bg];[narr][bg]amix=inputs=2:duration=first:dropout_transition=3[out]",
            "-map", "[out]",
            "-t", str(duration),
            "-c:a", "aac", "-b:a", "192k",
            mixed_audio_path,
        ]
        subprocess.run(cmd, capture_output=True, check=True)
        final_audio = mixed_audio_path
    else:
        final_audio = podcast_audio

    base_output = output_path
    has_ass = ass_captions and Path(ass_captions).exists()
    has_srt = captions_srt and Path(captions_srt).exists()

    # Build the filter complex for audiogram (showwaves) + subtitles + progress bar
    filter_parts = [
        f"[1:a]showwaves=s=800x150:mode=line:colors=0x66B2FF:scale=sqrt:r={VIDEO_FPS}[wave]",
        f"[0:v][wave]overlay=x=(W-800)/2:y=200[bgwave]"
    ]
    current_v = "[bgwave]"
    if has_ass:
        ass_escaped = str(ass_captions).replace("\\", "/").replace(":", "\\:")
        filter_parts.append(f"{current_v}ass={ass_escaped}[captionedv]")
        current_v = "[captionedv]"
    elif has_srt:
        caption_style = (
            "FontName=Arial,FontSize=22,"
            "PrimaryColour=&H0000FFFF,OutlineColour=&H00000000,"
            "Bold=1,BorderStyle=1,Outline=4,Shadow=2,MarginV=40"
        )
        filter_parts.append(f"{current_v}subtitles={captions_srt}:force_style='{caption_style}'[captionedv]")
        current_v = "[captionedv]"
    
    filter_parts.append(f"{current_v}drawbox=x=0:y=ih-4:w='iw*min(t/{duration},1)':h=4:color=white@0.5:t=fill[outv]")
    filter_complex = ";".join(filter_parts)

    try:
        cmd = [
            FFMPEG, "-y",
            "-i", visual_track,
            "-i", final_audio,
            "-filter_complex", filter_complex,
            "-map", "[outv]", "-map", "1:a",
            "-c:v", "libx264", "-preset", "ultrafast", "-crf", "23",
            "-c:a", "copy",
            "-movflags", "+faststart",
            "-metadata", f"title={title}",
            base_output, "-loglevel", "error",
        ]
        subprocess.run(cmd, check=True, capture_output=True)
    except subprocess.CalledProcessError as e:
        print(f"  Caption/Audiogram burn failed, assembling fallback... Error: {getattr(e, 'stderr', e)}")
        cmd = [
            FFMPEG, "-y",
            "-i", visual_track,
            "-i", final_audio,
            "-map", "0:v", "-map", "1:a",
            "-c:v", "libx264", "-preset", "ultrafast", "-crf", "23",
            "-c:a", "copy",
            "-movflags", "+faststart",
            "-metadata", f"title={title}",
            base_output, "-loglevel", "error",
        ]
        subprocess.run(cmd, check=True, capture_output=True)

    if has_ass and dialogue:
        temp_face = str(Path(base_output).with_suffix(".face.mp4"))
        try:
            apply_face_badge_overlays(
                video_path=base_output,
                dialogue=dialogue,
                per_turn_times=per_turn_times or [],
                output_path=temp_face,
                is_shorts=False,
            )
            if Path(temp_face).exists():
                Path(base_output).unlink()
                import shutil
                shutil.move(temp_face, base_output)
        except Exception as e:
            print(f"  Face badge overlay skipped: {e}")

    gated_idiom_windows = _gate_idiom_windows_after_pause_reveals(idiom_windows, dialogue)
    if gated_idiom_windows and per_turn_times:
        try:
            from idiom_card_renderer import render_idiom_cards_batch
            resolved = resolve_idiom_timestamps(gated_idiom_windows, per_turn_times)
            card_pngs = render_idiom_cards_batch(gated_idiom_windows, output_dir=TEMP_DIR / "idiom_cards")
            apply_idiom_overlays(base_output, resolved, card_pngs, output_path=base_output, is_shorts=False)
        except Exception as e:
            print(f"  Idiom overlay skipped: {e}")

    # Apply summary card text overlay
    if per_turn_times:
        summary_scene = None
        summary_scene_idx = None
        for _idx, sc in enumerate(scenes):
            if str(sc.get("scene_label", "")).lower() == "summary card":
                summary_scene = sc
                summary_scene_idx = _idx
                break
        if summary_scene is not None and summary_scene_idx is not None:
            try:
                from summary_card_renderer import render_summary_card
                s_turn = max(0, min(int(summary_scene.get("start_turn", 0)), len(per_turn_times) - 1))
                e_turn = max(s_turn, min(int(summary_scene.get("end_turn", s_turn)), len(per_turn_times) - 1))
                summary_start = per_turn_times[s_turn][0]
                summary_end = per_turn_times[e_turn][1]

                bg_path = scene_image_paths[summary_scene_idx] if summary_scene_idx < len(scene_image_paths) else None
                summary_dir = TEMP_DIR / "summary_card"
                summary_png = render_summary_card(
                    idiom_windows=idiom_windows or [],
                    output_dir=summary_dir,
                    is_shorts=False,
                    bg_image_path=bg_path,
                )
                if Path(summary_png).exists():
                    temp_summary = str(Path(base_output).with_suffix(".summary.mp4"))
                    apply_summary_overlay(
                        video_path=base_output,
                        summary_start=summary_start,
                        summary_end=summary_end,
                        summary_png=summary_png,
                        output_path=temp_summary,
                    )
                    if Path(temp_summary).exists():
                        Path(base_output).unlink()
                        import shutil
                        shutil.move(temp_summary, base_output)
            except Exception as e:
                print(f"  Summary card overlay skipped: {e}")

    append_channel_bumpers(base_output, channel=channel, portrait=False)

    size_mb = Path(output_path).stat().st_size / 1024 / 1024
    print(f"  ✓ Podcast video assembly complete: {output_path} ({size_mb:.1f} MB)")
    return output_path
