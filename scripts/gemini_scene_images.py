"""
gemini_scene_images.py
──────────────────────
Generate Pixar-style scene stills via Gemini 2.5 Flash Image API.
Supports skip-existing, daily quota tracking, and manual fallback.
"""

from __future__ import annotations

import json
import os
import time
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
COUNTER_FILE = PROJECT_ROOT / "gemini_usage_tracker.json"
DEFAULT_DAILY_LIMIT = int(os.getenv("GEMINI_DAILY_IMAGE_LIMIT", "490"))
DEFAULT_MODEL = os.getenv("GEMINI_IMAGE_MODEL", "gemini-2.5-flash-image")
SLEEP_BETWEEN_CALLS = float(os.getenv("GEMINI_IMAGE_SLEEP_SECONDS", "2"))


def _load_quota() -> dict:
    today = datetime.now().strftime("%Y-%m-%d")
    data = {"date": today, "count": 0}
    if COUNTER_FILE.exists():
        try:
            loaded = json.loads(COUNTER_FILE.read_text(encoding="utf-8"))
            if loaded.get("date") == today:
                data = loaded
        except (json.JSONDecodeError, KeyError, OSError):
            pass
    return data


def _save_quota(data: dict) -> None:
    COUNTER_FILE.write_text(json.dumps(data, indent=2), encoding="utf-8")


def get_daily_usage() -> int:
    return int(_load_quota().get("count", 0))


def increment_daily_usage() -> int:
    data = _load_quota()
    data["count"] = int(data.get("count", 0)) + 1
    _save_quota(data)
    return data["count"]


def _scene_output_path(scenes_dir: Path, scene: dict) -> Path:
    filename = scene.get("image_filename") or f"scene_{scene.get('scene_id', 0)}.jpg"
    return scenes_dir / filename


def generate_scene_images(
    scenes_dir: Path,
    scenes: list,
    *,
    skip_existing: bool = True,
    daily_limit: int = DEFAULT_DAILY_LIMIT,
) -> dict:
    """
    Generate scene images via Gemini. Returns summary dict:
    {generated, skipped, failed, missing}.
    """
    scenes_dir = Path(scenes_dir)
    scenes_dir.mkdir(parents=True, exist_ok=True)

    api_key = os.getenv("GEMINI_API_KEY", "").strip()
    if not api_key:
        print("  GEMINI_API_KEY not set — skipping Gemini image generation.")
        missing = [
            _scene_output_path(scenes_dir, s).name
            for s in scenes
            if not _scene_output_path(scenes_dir, s).exists()
        ]
        return {"generated": 0, "skipped": 0, "failed": 0, "missing": missing}

    try:
        from google import genai
        from google.genai import types
    except ImportError as exc:
        print(f"  google-genai not installed — skipping Gemini: {exc}")
        missing = [
            _scene_output_path(scenes_dir, s).name
            for s in scenes
            if not _scene_output_path(scenes_dir, s).exists()
        ]
        return {"generated": 0, "skipped": 0, "failed": 0, "missing": missing}

    client = genai.Client(api_key=api_key)
    generated = skipped = failed = 0
    missing = []

    for i, scene in enumerate(scenes, start=1):
        out_path = _scene_output_path(scenes_dir, scene)
        if skip_existing and out_path.exists():
            print(f"  [{i}/{len(scenes)}] Skipping existing {out_path.name}")
            skipped += 1
            continue

        usage = get_daily_usage()
        if usage >= daily_limit:
            print(f"  Daily Gemini cap reached ({usage}/{daily_limit}). Stopping.")
            missing.append(out_path.name)
            continue

        prompt = str(scene.get("visual_prompt", "")).strip()
        if not prompt:
            print(f"  [{i}/{len(scenes)}] No visual_prompt for scene {scene.get('scene_id')}")
            failed += 1
            missing.append(out_path.name)
            continue

        print(f"  [{i}/{len(scenes)}] Generating {out_path.name} via Gemini...")
        try:
            response = client.models.generate_content(
                model=DEFAULT_MODEL,
                contents=prompt,
                config=types.GenerateContentConfig(response_modalities=["IMAGE"]),
            )
            image_written = False
            if response.candidates:
                for part in response.candidates[0].content.parts:
                    if part.inline_data is not None:
                        out_path.write_bytes(part.inline_data.data)
                        count = increment_daily_usage()
                        print(f"    ✓ Saved {out_path.name} (daily usage: {count}/{daily_limit})")
                        image_written = True
                        generated += 1
                        time.sleep(SLEEP_BETWEEN_CALLS)
                        break
            if not image_written:
                print(f"    ✗ No image payload for {out_path.name}")
                failed += 1
                missing.append(out_path.name)
        except Exception as exc:
            print(f"    ✗ Gemini failed for {out_path.name}: {exc}")
            failed += 1
            missing.append(out_path.name)

    for scene in scenes:
        out_path = _scene_output_path(scenes_dir, scene)
        if not out_path.exists() and out_path.name not in missing:
            missing.append(out_path.name)

    return {
        "generated": generated,
        "skipped": skipped,
        "failed": failed,
        "missing": missing,
    }


def fetch_scenes_for_manifest_entry(
    project_root: Path,
    entry,
    *,
    skip_existing: bool = True,
) -> dict:
    """Generate scene images for a manifest entry."""
    from manifest_runner import scenes_assets_dir

    scenes_dir = scenes_assets_dir(project_root, entry.scenes_folder)
    return generate_scene_images(
        scenes_dir,
        entry.scenes,
        skip_existing=skip_existing,
    )
