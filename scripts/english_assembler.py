import os
import subprocess
import math
from pathlib import Path

# Fix absolute imports for modules in scripts/
import sys
sys.path.insert(0, str(Path(__file__).parent))

from ffmpeg_assembler import (
    append_channel_bumpers,
    get_audio_duration,
    TEMP_DIR,
    OUTPUT_DIR,
    ASSETS_DIR,
    FFMPEG,
    VIDEO_WIDTH,
    VIDEO_HEIGHT,
    VIDEO_FPS,
)
from kokoro_tts import synthesize
from typing import Optional, Tuple, List

ENGLISH_VOICES = {
    "Emma": "af_heart",
    "Liam": "am_echo"
}

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

    # Prepare badges
    size = 80 if is_shorts else 64
    emma_src = prepare_face_badge("Emma", size)
    liam_src = prepare_face_badge("Liam", size)
    if not emma_src or not liam_src:
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

    # Construct the active intervals for Emma and Liam
    emma_intervals = []
    liam_intervals = []
    for i, turn in enumerate(dialogue):
        if i >= len(per_turn_times):
            break
        speaker = turn.get("speaker", "Emma").lower()
        start, end = per_turn_times[i]
        if end <= start:
            continue
        if speaker == "emma":
            emma_intervals.append((start, end))
        elif speaker == "liam":
            liam_intervals.append((start, end))

    emma_enable = "+".join(f"between(t,{s:.3f},{e:.3f})" for s, e in emma_intervals)
    liam_enable = "+".join(f"between(t,{s:.3f},{e:.3f})" for s, e in liam_intervals)

    # Determine coordinates
    if is_shorts:
        x = 80
        y = 990
    else:
        x = 150
        y = 936

    inputs = [FFMPEG, "-y", "-i", video_path]
    filter_parts = []
    idx = 1
    prev_label = "0:v"

    if emma_enable:
        inputs.extend(["-i", emma_src])
        filter_parts.append(f"[{prev_label}][{idx}:v]overlay=x={x}:y={y}:enable='{emma_enable}'[v{idx}]")
        prev_label = f"v{idx}"
        idx += 1

    if liam_enable:
        inputs.extend(["-i", liam_src])
        filter_parts.append(f"[{prev_label}][{idx}:v]overlay=x={x}:y={y}:enable='{liam_enable}'[v{idx}]")
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
    subprocess.run(cmd, check=True, capture_output=True)
    return output_path

def generate_podcast_audio(script_data: dict, return_turn_times: bool = False):
    """
    Generate TTS for each line of dialogue using the designated voices,
    then concatenate them into a single audio file.

    Parameters
    ----------
    return_turn_times : If True, returns (audio_path, per_turn_times) where
        per_turn_times is a list of (abs_start_sec, abs_end_sec) tuples,
        one per dialogue turn, needed for idiom overlay timestamp mapping.
    """
    TEMP_DIR.mkdir(exist_ok=True)
    dialogue = script_data.get("dialogue", [])

    audio_files = []
    per_turn_durations: list[float] = []

    print("\nGenerating podcast audio...")
    for i, line in enumerate(dialogue):
        speaker = line.get("speaker", "Emma")
        text = line.get("text", "")
        voice = ENGLISH_VOICES.get(speaker, "af_sarah")

        out_path = str(TEMP_DIR / f"english_line_{i:03d}.m4a")

        try:
            print(f"  [{speaker}] -> {out_path}")
            # we use speed=1.0 for a more relaxed learning pace
            synthesize(text, out_path, voice=voice, speed=1.05)  # Increased speed for shorts
            dur = get_audio_duration(out_path)
            audio_files.append(out_path)
            per_turn_durations.append(dur)
        except Exception as e:
            print(f"  Error generating audio for line {i}: {e}")
            per_turn_durations.append(0.0)

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
        for dur in per_turn_durations:
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
        inputs += ["-i", png_path]
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
        filter_parts.append(
            f"{current_label}{faded_label}"
            f"overlay={x_expr}:{y_expr}:enable='between(t,{start:.3f},{end:.3f})'"
            f"{out_label}"
        )
        current_label = out_label

    filter_complex = ";".join(filter_parts)
    final_label = current_label

    cmd = inputs + [
        "-filter_complex", filter_complex,
        "-map", final_label,
        "-map", "0:a",
        "-c:v", "libx264", "-preset", "fast", "-crf", "20",
        "-c:a", "copy",
        "-movflags", "+faststart",
        output_path,
    ]

    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"  Idiom overlay failed (FFmpeg error), keeping plain video: {result.stderr[:300]}")
        if video_path != output_path:
            import shutil
            shutil.copy2(video_path, output_path)
    else:
        size_mb = Path(output_path).stat().st_size / 1024 / 1024
        print(f"  ✓ Idiom overlays applied: {output_path} ({size_mb:.1f} MB)")

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
) -> str:
    """
    Assemble the final English learning video:
    - Loops the background visual
    - Mixes the podcast audio with subtle background music
    - Burns subtitles (.ass preferred for karaoke; .srt fallback)
    - Composites Idiom Card overlays if idiom_windows provided
    """
    duration = get_audio_duration(podcast_audio)
    print(f"\nAssembling English video: {duration:.1f}s")

    # 1. Normalize visual to correct size/fps first
    norm_visual = str(TEMP_DIR / "english_norm.mp4")
    subprocess.run([
        FFMPEG, "-y", "-i", loop_visual,
        "-vf", f"scale={VIDEO_WIDTH}:{VIDEO_HEIGHT}:force_original_aspect_ratio=decrease,"
               f"pad={VIDEO_WIDTH}:{VIDEO_HEIGHT}:(ow-iw)/2:(oh-ih)/2:black,"
               f"fps={VIDEO_FPS}",
        "-c:v", "libx264", "-preset", "ultrafast", "-crf", "23", "-pix_fmt", "yuv420p",
        "-an", norm_visual, "-loglevel", "error"
    ], check=True)
    print("  Visual normalized")

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

    # 3. Combine visual loop + audio + subtitles
    # Prefer .ass (karaoke + avatar badges); fall back to .srt with style
    has_ass = ass_captions and Path(ass_captions).exists()
    has_srt = captions_srt and Path(captions_srt).exists()

    if has_ass:
        # Escape colon in path for FFmpeg filter (Windows + macOS)
        ass_escaped = str(ass_captions).replace("\\", "/").replace(":", "\\:")
        vf_filter = f"ass={ass_escaped}"
    elif has_srt:
        caption_style = (
            "FontName=Arial,FontSize=22,"
            "PrimaryColour=&H0000FFFF,OutlineColour=&H00000000,"
            "Bold=1,BorderStyle=1,Outline=4,Shadow=2,MarginV=40"
        )
        vf_filter = f"subtitles={captions_srt}:force_style='{caption_style}'"
    else:
        vf_filter = "null"

    base_output = output_path if not (idiom_windows and per_turn_times) else str(
        Path(output_path).with_stem(Path(output_path).stem + "_precards")
    )

    cmd = [
        FFMPEG, "-y",
        "-stream_loop", "-1", "-i", norm_visual,
        "-i", final_audio,
        "-vf", vf_filter,
        "-map", "0:v", "-map", "1:a",
        "-t", str(duration),
        "-c:v", "libx264", "-preset", "ultrafast", "-crf", "23",
        "-c:a", "copy",
        "-movflags", "+faststart",
        "-metadata", f"title={title}",
        base_output, "-loglevel", "error"
    ]

    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print("  Caption burn failed, assembling without captions...")
        cmd = [
            FFMPEG, "-y",
            "-stream_loop", "-1", "-i", norm_visual,
            "-i", final_audio,
            "-map", "0:v", "-map", "1:a",
            "-t", str(duration),
            "-c:v", "libx264", "-preset", "ultrafast", "-crf", "23",
            "-c:a", "copy", "-movflags", "+faststart",
            base_output, "-loglevel", "error"
        ]
        subprocess.run(cmd, capture_output=True, check=True)

    # Apply face overlays if .ass subtitles are used and face PNGs exist
    if has_ass and dialogue:
        temp_face = str(Path(base_output).with_suffix(".face.mp4"))
        try:
            apply_face_badge_overlays(
                video_path=base_output,
                dialogue=dialogue,
                per_turn_times=per_turn_times or [],
                output_path=temp_face,
                is_shorts=False
            )
            if Path(temp_face).exists():
                Path(base_output).unlink()
                import shutil
                shutil.move(temp_face, base_output)
        except Exception as e:
            print(f"  Face badge overlay skipped: {e}")

    append_channel_bumpers(base_output, channel=channel)

    # 4. Idiom card overlays (post-bumper composition)
    if idiom_windows and per_turn_times:
        try:
            from ffmpeg_assembler import get_media_duration
            from idiom_card_renderer import render_idiom_cards_batch

            # Measure intro bumper duration for timestamp padding
            bumper_intro = Path(__file__).resolve().parent.parent / "assets" / "bumpers" / "english" / "intro.mp4"
            bumper_pad = get_media_duration(str(bumper_intro)) if bumper_intro.exists() else 0.0

            resolved = resolve_idiom_timestamps(idiom_windows, per_turn_times, bumper_pad)
            card_pngs = render_idiom_cards_batch(idiom_windows, output_dir=TEMP_DIR / "idiom_cards")
            apply_idiom_overlays(base_output, resolved, card_pngs, output_path, is_shorts=False)
            # Remove precards temp file
            if base_output != output_path and Path(base_output).exists():
                Path(base_output).unlink()
        except Exception as exc:
            print(f"  Idiom overlays skipped: {exc}")
            if base_output != output_path:
                import shutil
                shutil.copy2(base_output, output_path)
    else:
        if base_output != output_path:
            import shutil
            shutil.copy2(base_output, output_path)

    size_mb = Path(output_path).stat().st_size / 1024 / 1024
    print(f"  ✓ English video assembled: {output_path} ({size_mb:.1f} MB)")
    return output_path

def cleanup_english_temp():
    import shutil
    if TEMP_DIR.exists():
        shutil.rmtree(TEMP_DIR)
        TEMP_DIR.mkdir()
    print("  Temp files cleaned.")


# ─────────────────────────────────────────────
# SLOW ENGLISH MODE — 0.80x speed, bold captions
# ─────────────────────────────────────────────

def generate_slow_podcast_audio(script_data: dict, return_turn_times: bool = False):
    """
    Same as generate_podcast_audio but synthesises at 0.80x speed
    and writes to differently-named temp files to avoid collision with the
    normal render when both are generated in the same pipeline run.

    Parameters
    ----------
    return_turn_times : If True, returns (audio_path, per_turn_times) where
        per_turn_times is a list of (abs_start_sec, abs_end_sec) tuples.
    """
    TEMP_DIR.mkdir(exist_ok=True)
    dialogue = script_data.get("dialogue", [])

    audio_files = []
    per_turn_durations: list[float] = []

    print("\nGenerating SLOW podcast audio (0.80x speed)...")
    for i, line in enumerate(dialogue):
        speaker = line.get("speaker", "Emma")
        text = line.get("text", "")
        voice = ENGLISH_VOICES.get(speaker, "af_sarah")

        out_path = str(TEMP_DIR / f"english_slow_line_{i:03d}.m4a")

        try:
            print(f"  [{speaker}] -> {out_path}")
            synthesize(text, out_path, voice=voice, speed=0.80)
            dur = get_audio_duration(out_path)
            audio_files.append(out_path)
            per_turn_durations.append(dur)
        except Exception as e:
            print(f"  Error generating slow audio for line {i}: {e}")
            per_turn_durations.append(0.0)

    concat_list_path = str(TEMP_DIR / "english_slow_audio_list.txt")
    with open(concat_list_path, "w") as f:
        for audio_file in audio_files:
            f.write(f"file '{os.path.abspath(audio_file)}'\n")

    final_audio_path = str(TEMP_DIR / "english_slow_podcast_full.m4a")

    cmd = [
        FFMPEG, "-y",
        "-f", "concat", "-safe", "0", "-i", concat_list_path,
        "-c:a", "aac", "-b:a", "192k",
        final_audio_path
    ]
    subprocess.run(cmd, capture_output=True, check=True)

    print(f"  ✓ Full slow podcast audio generated: {final_audio_path}")

    if return_turn_times:
        cursor = 0.0
        turn_times: list[tuple[float, float]] = []
        for dur in per_turn_durations:
            turn_times.append((cursor, cursor + dur))
            cursor += dur
        return final_audio_path, turn_times

    return final_audio_path


def assemble_slow_english_video(
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
) -> str:
    """
    Assemble the slow-mode English learning video:
    - Same pipeline as assemble_english_video
    - Larger, bolder, high-contrast captions (.ass karaoke preferred; .srt fallback)
    - 🐢 SLOW MODE badge burned into the top-left corner via drawtext
    - Idiom card overlays applied as final pass
    """
    duration = get_audio_duration(podcast_audio)
    print(f"\nAssembling SLOW English video: {duration:.1f}s")

    # 1. Normalize visual
    norm_visual = str(TEMP_DIR / "english_slow_norm.mp4")
    subprocess.run([
        FFMPEG, "-y", "-i", loop_visual,
        "-vf", f"scale={VIDEO_WIDTH}:{VIDEO_HEIGHT}:force_original_aspect_ratio=decrease,"
               f"pad={VIDEO_WIDTH}:{VIDEO_HEIGHT}:(ow-iw)/2:(oh-ih)/2:black,"
               f"fps={VIDEO_FPS}",
        "-c:v", "libx264", "-preset", "ultrafast", "-crf", "23", "-pix_fmt", "yuv420p",
        "-an", norm_visual, "-loglevel", "error"
    ], check=True)
    print("  Visual normalized")

    # 2. Mix podcast audio with optional background music
    if background_music and Path(background_music).exists():
        mixed_audio_path = str(TEMP_DIR / "english_slow_mixed_audio.m4a")
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

    # 3. Build video filter chain:
    #    - Bold, large SRT captions (FontSize 32, centred, high contrast)
    #    - 🐢 SLOW MODE text badge in top-left corner
    slow_caption_style = (
        "FontName=Arial,"
        "FontSize=32,"
        "PrimaryColour=&H00FFFFFF,"
        "OutlineColour=&H00000000,"
        "BackColour=&H99000000,"
        "Bold=1,"
        "BorderStyle=3,"
        "Outline=2,"
        "Shadow=0,"
        "MarginV=50,"
        "Alignment=2"
    )

    has_ass = ass_captions and Path(ass_captions).exists()
    has_srt = captions_srt and Path(captions_srt).exists()

    if has_ass:
        ass_escaped = str(ass_captions).replace("\\", "/").replace(":", "\\:")
        vf_filter = (
            f"ass={ass_escaped},"
            f"drawtext=text='🐢 SLOW MODE':fontcolor=white:fontsize=20:"
            f"box=1:boxcolor=black@0.55:boxborderw=6:x=16:y=16"
        )
    elif has_srt:
        srt_escaped = captions_srt.replace("\\", "/").replace(":", "\\:")
        vf_filter = (
            f"subtitles={srt_escaped}:force_style='{slow_caption_style}',"
            f"drawtext=text='🐢 SLOW MODE':fontcolor=white:fontsize=20:"
            f"box=1:boxcolor=black@0.55:boxborderw=6:x=16:y=16"
        )
    else:
        vf_filter = (
            f"drawtext=text='🐢 SLOW MODE':fontcolor=white:fontsize=20:"
            f"box=1:boxcolor=black@0.55:boxborderw=6:x=16:y=16"
        )

    base_output = output_path if not (idiom_windows and per_turn_times) else str(
        Path(output_path).with_stem(Path(output_path).stem + "_precards")
    )

    cmd = [
        FFMPEG, "-y",
        "-stream_loop", "-1", "-i", norm_visual,
        "-i", final_audio,
        "-vf", vf_filter,
        "-map", "0:v", "-map", "1:a",
        "-t", str(duration),
        "-c:v", "libx264", "-preset", "ultrafast", "-crf", "23",
        "-c:a", "copy",
        "-movflags", "+faststart",
        "-metadata", f"title={title} [Slow Mode]",
        base_output, "-loglevel", "error"
    ]

    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print("  Slow caption/badge burn failed — falling back to plain video...")
        cmd = [
            FFMPEG, "-y",
            "-stream_loop", "-1", "-i", norm_visual,
            "-i", final_audio,
            "-map", "0:v", "-map", "1:a",
            "-t", str(duration),
            "-c:v", "libx264", "-preset", "ultrafast", "-crf", "23",
            "-c:a", "copy", "-movflags", "+faststart",
            base_output, "-loglevel", "error"
        ]
        subprocess.run(cmd, capture_output=True, check=True)

    # Apply face overlays if .ass subtitles are used and face PNGs exist
    if has_ass and dialogue:
        temp_face = str(Path(base_output).with_suffix(".face.mp4"))
        try:
            apply_face_badge_overlays(
                video_path=base_output,
                dialogue=dialogue,
                per_turn_times=per_turn_times or [],
                output_path=temp_face,
                is_shorts=False
            )
            if Path(temp_face).exists():
                Path(base_output).unlink()
                import shutil
                shutil.move(temp_face, base_output)
        except Exception as e:
            print(f"  Face badge overlay skipped: {e}")

    append_channel_bumpers(base_output, channel=channel)

    # Idiom card overlays (post-bumper composition)
    if idiom_windows and per_turn_times:
        try:
            from ffmpeg_assembler import get_media_duration
            from idiom_card_renderer import render_idiom_cards_batch

            bumper_intro = Path(__file__).resolve().parent.parent / "assets" / "bumpers" / "english" / "intro.mp4"
            bumper_pad = get_media_duration(str(bumper_intro)) if bumper_intro.exists() else 0.0

            resolved = resolve_idiom_timestamps(idiom_windows, per_turn_times, bumper_pad)
            card_pngs = render_idiom_cards_batch(idiom_windows, output_dir=TEMP_DIR / "idiom_cards")
            apply_idiom_overlays(base_output, resolved, card_pngs, output_path, is_shorts=False)
            if base_output != output_path and Path(base_output).exists():
                Path(base_output).unlink()
        except Exception as exc:
            print(f"  Idiom overlays skipped: {exc}")
            if base_output != output_path:
                import shutil
                shutil.copy2(base_output, output_path)
    else:
        if base_output != output_path:
            import shutil
            shutil.copy2(base_output, output_path)

    size_mb = Path(output_path).stat().st_size / 1024 / 1024
    print(f"  ✓ Slow English video assembled: {output_path} ({size_mb:.1f} MB)")
    return output_path
