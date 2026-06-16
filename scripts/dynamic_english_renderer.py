import json
import math
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter

sys.path.insert(0, str(Path(__file__).resolve().parent))

from english_assembler import ENGLISH_VOICES
from ffmpeg_assembler import (
    ASSETS_DIR,
    BG_MUSIC_VOLUME,
    FFMPEG,
    NARRATION_VOLUME,
    OUTPUT_DIR,
    SHORTS_HEIGHT,
    SHORTS_WIDTH,
    TEMP_DIR,
    VIDEO_FPS,
    generate_captions,
    get_audio_duration,
    run_ffmpeg,
)
from kokoro_tts import synthesize


PROJECT_ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = ASSETS_DIR / "characters" / "character_config.json"
MOUTH_DIR = ASSETS_DIR / "characters" / "generated_mouths"
DEFAULT_RHUBARB_PATH = PROJECT_ROOT / "tools" / "rhubarb" / "rhubarb"
SUPPORTED_MOUTHS = {"A", "B", "C", "D", "E", "F", "X"}
RHUBARB_TO_ASSET = {
    "A": "A",
    "B": "B",
    "C": "C",
    "D": "D",
    "E": "E",
    "F": "F",
    "G": "F",
    "H": "F",
    "X": "X",
}


class DynamicRendererPreflightError(RuntimeError):
    """Raised when dynamic rendering cannot start because local assets are missing."""


@dataclass
class DialogueSegment:
    speaker: str
    text: str
    audio_path: str
    start: float
    end: float
    mouth_cues: list[dict]


def _project_path(value: str) -> Path:
    path = Path(value)
    return path if path.is_absolute() else PROJECT_ROOT / path


def _default_config() -> dict:
    return {
        "canvas": {"width": SHORTS_WIDTH, "height": SHORTS_HEIGHT, "fps": VIDEO_FPS},
        "background": "assets/dynamic_backgrounds/test_scene.png",
        "characters": {
            "Emma": {
                "body": "assets/characters/emma/body.png",
                "position": {"x": 60, "y": 560, "width": 470, "height": 820},
                "mouth": {"x": 250, "y": 895, "width": 86, "height": 46},
            },
            "Liam": {
                "body": "assets/characters/liam/body.png",
                "position": {"x": 550, "y": 560, "width": 470, "height": 820},
                "mouth": {"x": 740, "y": 895, "width": 86, "height": 46},
            },
        },
    }


def load_character_config(config_path: Path = CONFIG_PATH) -> dict:
    config = _default_config()
    if config_path.exists():
        loaded = json.loads(config_path.read_text(encoding="utf-8"))
        config.update({k: v for k, v in loaded.items() if k != "characters"})
        if "characters" in loaded:
            config["characters"].update(loaded["characters"])

    characters = config.get("characters") or {}
    for name in ("Emma", "Liam"):
        if name not in characters:
            raise DynamicRendererPreflightError(f"Missing character config for {name}")
        for key in ("body", "position", "mouth"):
            if key not in characters[name]:
                raise DynamicRendererPreflightError(f"Missing {key} config for {name}")

    return config


def find_rhubarb_binary() -> Path:
    configured = os.getenv("RHUBARB_BIN", "").strip()
    candidates = [Path(configured)] if configured else []
    candidates.append(DEFAULT_RHUBARB_PATH)

    for candidate in candidates:
        if candidate and candidate.exists() and os.access(candidate, os.X_OK):
            return candidate

    found = shutil.which("rhubarb")
    if found:
        return Path(found)

    raise DynamicRendererPreflightError(
        "Rhubarb Lip Sync not found. Install it and set RHUBARB_BIN=/absolute/path/to/rhubarb "
        f"or place the binary at {DEFAULT_RHUBARB_PATH}."
    )


def parse_rhubarb_mouth_cues(data: dict) -> list[dict]:
    cues = []
    for cue in data.get("mouthCues", []):
        try:
            start = float(cue["start"])
            end = float(cue["end"])
        except (KeyError, TypeError, ValueError):
            continue
        value = RHUBARB_TO_ASSET.get(str(cue.get("value", "X")).upper(), "X")
        cues.append({"start": start, "end": end, "value": value})
    return cues


def _mouth_at(cues: list[dict], local_time: float) -> str:
    for cue in cues:
        if cue["start"] <= local_time < cue["end"]:
            return cue["value"]
    return "X"


def ensure_generated_mouth_assets(mouth_dir: Path = MOUTH_DIR) -> dict[str, Path]:
    mouth_dir.mkdir(parents=True, exist_ok=True)
    specs = {
        "A": {"box": (18, 34, 142, 66), "fill": (45, 18, 22, 255), "teeth": False},
        "B": {"box": (24, 30, 136, 74), "fill": (52, 20, 26, 255), "teeth": True},
        "C": {"box": (20, 24, 140, 82), "fill": (58, 19, 28, 255), "teeth": False},
        "D": {"box": (16, 18, 144, 92), "fill": (64, 18, 30, 255), "teeth": False},
        "E": {"box": (28, 26, 132, 84), "fill": (58, 19, 28, 255), "teeth": False},
        "F": {"box": (38, 24, 122, 82), "fill": (50, 18, 24, 255), "teeth": False},
        "X": {"box": (26, 46, 134, 58), "fill": (40, 16, 20, 255), "teeth": False},
    }

    paths = {}
    for value, spec in specs.items():
        path = mouth_dir / f"mouth_{value}.png"
        if not path.exists():
            image = Image.new("RGBA", (160, 110), (0, 0, 0, 0))
            draw = ImageDraw.Draw(image)
            draw.ellipse(spec["box"], fill=spec["fill"], outline=(120, 45, 55, 255), width=4)
            if spec["teeth"]:
                draw.rounded_rectangle((38, 34, 122, 46), radius=4, fill=(245, 235, 220, 255))
            image.save(path)
        paths[value] = path
    return paths


def preflight_dynamic_english_assets(config_path: Path = CONFIG_PATH) -> dict:
    config = load_character_config(config_path)
    missing = []

    background = _project_path(config["background"])
    if not background.exists():
        missing.append(str(background))

    for name in ("Emma", "Liam"):
        body = _project_path(config["characters"][name]["body"])
        if not body.exists():
            missing.append(str(body))

    if missing:
        lines = "\n".join(f"  - {path}" for path in missing)
        raise DynamicRendererPreflightError(
            "Dynamic English renderer is missing required local art assets:\n"
            f"{lines}\n"
            "Create transparent waist-up Emma/Liam PNGs and a test background before rerunning."
        )

    find_rhubarb_binary()
    return config


def _run_rhubarb(audio_path: str, rhubarb_bin: Path, out_json: Path) -> list[dict]:
    wav_path = out_json.with_suffix(".wav")
    run_ffmpeg([
        FFMPEG, "-y",
        "-i", audio_path,
        "-ac", "1",
        "-ar", "16000",
        str(wav_path),
    ])
    result = subprocess.run(
        [str(rhubarb_bin), "-f", "json", "-o", str(out_json), str(wav_path)],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(f"Rhubarb failed for {audio_path}: {result.stderr or result.stdout}")
    return parse_rhubarb_mouth_cues(json.loads(out_json.read_text(encoding="utf-8")))


def _generate_dialogue_segments(script_data: dict, rhubarb_bin: Path) -> tuple[list[DialogueSegment], str]:
    dialogue = script_data.get("dialogue", [])
    segments = []
    audio_files = []
    cursor = 0.0

    for index, line in enumerate(dialogue):
        speaker = line.get("speaker", "Emma")
        if speaker not in ("Emma", "Liam"):
            speaker = "Emma"
        text = line.get("text", "").strip()
        if not text:
            continue

        voice = ENGLISH_VOICES.get(speaker, "af_sarah")
        out_path = str(TEMP_DIR / f"dynamic_english_line_{index:03d}.m4a")
        print(f"  [{speaker}] dynamic TTS -> {out_path}")
        audio_path = synthesize(text, out_path, voice=voice, speed=0.95)
        duration = get_audio_duration(audio_path)
        cues = _run_rhubarb(audio_path, rhubarb_bin, TEMP_DIR / f"dynamic_english_line_{index:03d}.json")
        segments.append(DialogueSegment(speaker, text, audio_path, cursor, cursor + duration, cues))
        audio_files.append(audio_path)
        cursor += duration

    if not audio_files:
        raise RuntimeError("Dynamic English renderer received no usable dialogue lines.")

    concat_list_path = TEMP_DIR / "dynamic_english_audio_list.txt"
    with open(concat_list_path, "w", encoding="utf-8") as handle:
        for audio_file in audio_files:
            handle.write(f"file '{Path(audio_file).resolve()}'\n")

    full_audio_path = str(TEMP_DIR / "dynamic_english_full.m4a")
    run_ffmpeg([
        FFMPEG, "-y",
        "-f", "concat", "-safe", "0",
        "-i", str(concat_list_path),
        "-c:a", "aac",
        "-b:a", "192k",
        full_audio_path,
    ])

    return segments, full_audio_path


def _load_rgba(path: Path, size: tuple[int, int]) -> Image.Image:
    return Image.open(path).convert("RGBA").resize(size, Image.Resampling.LANCZOS)


def _active_segment(segments: list[DialogueSegment], timestamp: float) -> DialogueSegment | None:
    for segment in segments:
        if segment.start <= timestamp < segment.end:
            return segment
    return segments[-1] if segments else None


def _render_silent_video(
    segments: list[DialogueSegment],
    config: dict,
    mouth_paths: dict[str, Path],
    duration: float,
    output_path: str,
) -> None:
    canvas = config.get("canvas", {})
    width = int(canvas.get("width", SHORTS_WIDTH))
    height = int(canvas.get("height", SHORTS_HEIGHT))
    fps = int(canvas.get("fps", VIDEO_FPS))
    total_frames = max(1, math.ceil(duration * fps))

    background = Image.open(_project_path(config["background"])).convert("RGB")
    background = background.resize((width, height), Image.Resampling.LANCZOS).filter(ImageFilter.GaussianBlur(0.4))

    character_images = {}
    mouth_images = {}
    for name in ("Emma", "Liam"):
        char = config["characters"][name]
        box = char["position"]
        character_images[name] = _load_rgba(
            _project_path(char["body"]),
            (int(box["width"]), int(box["height"])),
        )
    for key, path in mouth_paths.items():
        mouth_images[key] = Image.open(path).convert("RGBA")

    cmd = [
        FFMPEG, "-y",
        "-f", "rawvideo",
        "-pix_fmt", "rgb24",
        "-s", f"{width}x{height}",
        "-r", str(fps),
        "-i", "-",
        "-an",
        "-c:v", "libx264",
        "-preset", "fast",
        "-crf", "20",
        "-pix_fmt", "yuv420p",
        output_path,
    ]
    process = subprocess.Popen(cmd, stdin=subprocess.PIPE)
    try:
        for frame_index in range(total_frames):
            timestamp = frame_index / fps
            active = _active_segment(segments, timestamp)
            frame = background.copy().convert("RGBA")

            for name in ("Emma", "Liam"):
                char = config["characters"][name]
                box = char["position"]
                is_speaking = active is not None and active.speaker == name
                bounce = 0
                x = int(box["x"])
                y = int(box["y"]) - bounce
                frame.alpha_composite(character_images[name], (x, y))

                mouth_key = "X"
                if is_speaking and active is not None:
                    mouth_key = _mouth_at(active.mouth_cues, timestamp - active.start)
                mouth_cfg = char["mouth"]
                mouth = mouth_images.get(mouth_key, mouth_images["X"]).resize(
                    (int(mouth_cfg["width"]), int(mouth_cfg["height"])),
                    Image.Resampling.LANCZOS,
                )
                
                # Calculate mouth position relative to character body
                abs_mouth_x = x + int(mouth_cfg["x"])
                abs_mouth_y = y + int(mouth_cfg["y"])
                frame.alpha_composite(mouth, (abs_mouth_x, abs_mouth_y))

            process.stdin.write(frame.convert("RGB").tobytes())
    finally:
        if process.stdin:
            process.stdin.close()
        return_code = process.wait()
    if return_code != 0:
        raise RuntimeError(f"FFmpeg failed while rendering dynamic frames: exit {return_code}")


def _mux_dynamic_video(
    silent_video: str,
    narration_audio: str,
    output_path: str,
    captions_srt: str | None,
    background_music: str | None,
    duration: float,
    title: str,
) -> None:
    if background_music and Path(background_music).exists():
        mixed_audio_path = str(TEMP_DIR / "dynamic_english_mixed_audio.m4a")
        run_ffmpeg([
            FFMPEG, "-y",
            "-i", narration_audio,
            "-stream_loop", "-1",
            "-i", background_music,
            "-filter_complex",
            f"[0:a]volume={NARRATION_VOLUME}[narr];"
            f"[1:a]volume={BG_MUSIC_VOLUME}[bg];"
            "[narr][bg]amix=inputs=2:duration=first:dropout_transition=3[out]",
            "-map", "[out]",
            "-t", str(duration),
            "-c:a", "aac",
            "-b:a", "192k",
            mixed_audio_path,
        ])
        final_audio = mixed_audio_path
    else:
        final_audio = narration_audio

    caption_style = (
        "FontName=Arial,"
        "FontSize=18,"
        "PrimaryColour=&H00FFFFFF,"
        "OutlineColour=&H00000000,"
        "BackColour=&H80000000,"
        "Bold=1,"
        "Outline=2,"
        "Shadow=1,"
        "Alignment=2,"
        "MarginV=60"
    )
    fade_start = max(duration - 1, 0)
    vf_filter = f"fade=t=in:st=0:d=0.3,fade=t=out:st={fade_start}:d=1"
    if captions_srt and Path(captions_srt).exists():
        vf_filter += f",subtitles={captions_srt}:force_style='{caption_style}'"

    run_ffmpeg([
        FFMPEG, "-y",
        "-i", silent_video,
        "-i", final_audio,
        "-map", "0:v",
        "-map", "1:a",
        "-vf", vf_filter,
        "-c:v", "libx264",
        "-preset", "medium",
        "-crf", "20",
        "-c:a", "copy",
        "-movflags", "+faststart",
        "-metadata", f"title={title}",
        output_path,
    ])


def render_dynamic_english_short(
    script_data: dict,
    output_path: str,
    captions_srt: str | None = None,
    background_music: str | None = None,
    title: str = "",
) -> str:
    print("\nAssembling dynamic English Short with Emma and Liam...")
    config = preflight_dynamic_english_assets()
    rhubarb_bin = find_rhubarb_binary()
    mouth_paths = ensure_generated_mouth_assets()

    segments, narration_audio = _generate_dialogue_segments(script_data, rhubarb_bin)
    duration = get_audio_duration(narration_audio)

    if captions_srt:
        try:
            generate_captions(narration_audio, captions_srt, max_line_width=25, max_line_count=2)
        except Exception as exc:
            print(f"  Captions skipped: {exc}")
            captions_srt = None

    silent_video = str(TEMP_DIR / "dynamic_english_silent.mp4")
    _render_silent_video(segments, config, mouth_paths, duration, silent_video)
    _mux_dynamic_video(
        silent_video=silent_video,
        narration_audio=narration_audio,
        output_path=output_path,
        captions_srt=captions_srt,
        background_music=background_music,
        duration=duration,
        title=title,
    )

    size_mb = Path(output_path).stat().st_size / 1024 / 1024
    print(f"  Dynamic English Short assembled: {output_path} ({size_mb:.1f} MB)")
    return output_path
