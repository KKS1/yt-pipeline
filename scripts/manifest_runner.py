"""
manifest_runner.py
──────────────────
Two-phase pipeline: generate scripts + manifest first, then
resume to review visuals and assemble.

Phase 1 (--manifest-only):
  Generate Groq scripts, write manifest JSON with per-entry
  metadata.  Exit — user places/renames visuals in assets folders.

Phase 2 (--resume-from-manifest <path>):
  Read manifest, load scripts from disk, interactively resolve
  visuals per entry, then proceed to TTS + assembly.
"""

from __future__ import annotations

import json
import os
import random
import re
import sys
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional


# ── Dataclasses ──────────────────────────────────────────────────────────────

@dataclass
class ManifestEntry:
    """One video to assemble."""
    label: str                     # e.g. "English Podcast" or "Day 3: ..."
    script_path: str               # relative to project root
    assets_folder: str             # subfolder under assets/, e.g. "english_visuals"
    visual_keywords: list[str]     # from the generated script
    topic: str                     # title / topic for display
    orientation: str               # "landscape" or "portrait"
    estimated_duration_seconds: float = 0.0
    resolved_visuals: list[str] = field(default_factory=list)
    scenes: list = field(default_factory=list)
    scenes_folder: str = ""
    scene_images_ready: bool = False
    visual_mode: str = "scenes"    # "scenes" | "legacy_loops"

    def to_dict(self) -> dict:
        # Strip dialogues from scenes to avoid staleness - only keep turn indices
        scenes_without_dialogues = []
        for scene in self.scenes:
            scene_copy = dict(scene)
            scene_copy.pop("dialogues", None)
            scenes_without_dialogues.append(scene_copy)
        
        return {
            "label": self.label,
            "script_path": self.script_path,
            "assets_folder": self.assets_folder,
            "visual_keywords": self.visual_keywords,
            "topic": self.topic,
            "orientation": self.orientation,
            "estimated_duration_seconds": self.estimated_duration_seconds,
            "resolved_visuals": self.resolved_visuals,
            "scenes": scenes_without_dialogues,
            "scenes_folder": self.scenes_folder,
            "scene_images_ready": self.scene_images_ready,
            "visual_mode": self.visual_mode,
        }

    @classmethod
    def from_dict(cls, d: dict) -> ManifestEntry:
        known = {f.name for f in cls.__dataclass_fields__.values()}
        filtered = {k: v for k, v in d.items() if k in known}
        if "visual_mode" not in filtered and not filtered.get("scenes"):
            filtered["visual_mode"] = "legacy_loops"
        return cls(**filtered)


@dataclass
class VisualManifest:
    """Full manifest for one pipeline run."""
    version: int = 2
    pipeline: str = ""             # "english", "english-shorts", etc.
    generated_at: str = ""
    series_title: str = ""         # for challenges
    entries: list[ManifestEntry] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "version": self.version,
            "pipeline": self.pipeline,
            "generated_at": self.generated_at,
            "series_title": self.series_title,
            "entries": [e.to_dict() for e in self.entries],
        }

    @classmethod
    def from_dict(cls, d: dict) -> VisualManifest:
        entries = [ManifestEntry.from_dict(e) for e in d.pop("entries", [])]
        return cls(**d, entries=entries)


# ── I/O ───────────────────────────────────────────────────────────────────────

def write_manifest(manifest: VisualManifest, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(manifest.to_dict(), indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    print(f"\n  Manifest written: {path}")


def read_manifest(path: Path) -> VisualManifest:
    data = json.loads(path.read_text(encoding="utf-8"))
    return VisualManifest.from_dict(data)


# ── Visual helpers (mirrors manual_run.py logic) ─────────────────────────────

VISUAL_KEYWORD_ALIASES = {
    "airport": {"travel", "mountains", "city", "talk"},
    "bakery": {"bakery", "cafe", "coffee"},
    "book": {"library", "reading", "write"},
    "cafe": {"cafe", "coffee", "drink", "bakery", "glimmer"},
    "coffee": {"cafe", "coffee", "drink", "bakery", "glimmer"},
    "conversation": {"talk", "life", "rooftop", "tea"},
    "daily": {"life", "talk", "rooftop"},
    "food": {"bakery", "icecream", "cafe", "coffee"},
    "hotel": {"travel", "city", "rooftop"},
    "interview": {"talk", "write", "library"},
    "meeting": {"talk", "write", "library"},
    "office": {"write", "talk", "library"},
    "phone": {"talk", "life"},
    "reading": {"library", "reading", "write"},
    "restaurant": {"cafe", "coffee", "bakery", "icecream"},
    "school": {"library", "reading", "kids"},
    "shopping": {"city", "life", "icecream"},
    "small": {"talk", "life"},
    "study": {"library", "reading", "write"},
    "travel": {"beach", "mountains", "city", "rooftop"},
    "work": {"write", "talk", "library"},
}


def _tokenize(text) -> set[str]:
    return {t for t in re.split(r"[^a-z0-9]+", str(text).lower()) if len(t) >= 3}


def _scored_visuals(
    visual_files: list[Path], terms: set[str]
) -> list[tuple[int, float, Path]]:
    scored = []
    for v in visual_files:
        file_terms = _tokenize(v.stem)
        score = len(terms & file_terms)
        scored.append((score, random.random(), v))
    scored.sort(key=lambda x: (x[0], x[1]), reverse=True)
    return scored


def scan_visuals(assets_dir: Path) -> list[Path]:
    """Return all video loops in a directory, sorted."""
    if not assets_dir.exists():
        return []
    return sorted(
        list(assets_dir.glob("*.mp4"))
        + list(assets_dir.glob("*.mov"))
        + list(assets_dir.glob("*.m4v"))
    )


def select_top_visuals(
    visual_files: list[Path], terms: set[str], max_count: int = 5
) -> list[Path]:
    """Pick the best-matching visuals by keyword score, fill with random if needed."""
    if not visual_files:
        return []
    scored = _scored_visuals(visual_files, terms)
    matched = [v for s, _, v in scored if s > 0]
    unmatched = [v for s, _, v in scored if s == 0]
    return (matched + unmatched)[:max_count]


SCENE_IMAGE_EXTENSIONS = (".jpg", ".jpeg", ".png", ".webp")


def scenes_assets_dir(project_root: Path, scenes_folder: str) -> Path:
    return project_root / "assets" / scenes_folder


def scene_image_path(scenes_dir: Path, scene: dict) -> Path:
    filename = scene.get("image_filename") or f"scene_{scene.get('scene_id', 0)}.png"
    return scenes_dir / filename


def check_scene_images_ready(scenes_dir: Path, scenes: list) -> tuple[bool, list[str]]:
    """Return (all_ready, missing_relative_paths)."""
    if not scenes:
        return False, []
    missing = []
    for scene in scenes:
        path = scene_image_path(scenes_dir, scene)
        if not path.exists():
            missing.append(path.name)
    return len(missing) == 0, missing


def resolve_scene_image_paths(scenes_dir: Path, scenes: list) -> list[Path]:
    """Return ordered scene image paths (must all exist)."""
    paths = []
    for scene in scenes:
        path = scene_image_path(scenes_dir, scene)
        if not path.exists():
            raise FileNotFoundError(f"Missing scene image: {path}")
        paths.append(path)
    return paths


def interactive_resolve_scenes(
    entry: ManifestEntry,
    project_root: Path,
) -> bool:
    """
    Phase 2 scene-image resolution for one manifest entry.
    Returns True when all scene images are present.
    """
    if entry.visual_mode != "scenes" or not entry.scenes:
        return False

    scenes_dir = scenes_assets_dir(project_root, entry.scenes_folder)
    scenes_dir.mkdir(parents=True, exist_ok=True)

    while True:
        ready, missing = check_scene_images_ready(scenes_dir, entry.scenes)
        entry.scene_images_ready = ready

        print("\n" + "=" * 58)
        print(f"  SCENE REVIEW: {entry.label}")
        print("=" * 58)
        print(f"  Topic / Title : {entry.topic}")
        print(f"  Scenes folder : assets/{entry.scenes_folder}/")
        print(f"  Scene count   : {len(entry.scenes)}")
        print()

        for scene in entry.scenes:
            path = scene_image_path(scenes_dir, scene)
            status = "✓" if path.exists() else "✗ MISSING"
            label = scene.get("scene_label") or scene.get("image_filename", "")
            print(f"  [{status}] {path.name} — {label}")

        if ready:
            print("\n  ✓ All scene images ready.")
            return True

        print(f"\n  ⚠ Missing {len(missing)} image(s). Place files in assets/{entry.scenes_folder}/")
        for m in missing:
            print(f"    - {m}")
        print()

        action = input(
            "  [Y] Continue (all images placed)  [R] Re-scan  [S] Skip  [Q] Quit: "
        ).strip().lower()

        if action in ("", "y", "yes"):
            ready, _ = check_scene_images_ready(scenes_dir, entry.scenes)
            entry.scene_images_ready = ready
            if ready:
                return True
            print("  Still missing images. Re-scan or skip.")
            continue
        if action in ("r", "refresh"):
            input("  Press Enter after placing images...")
            continue
        if action in ("s", "skip"):
            print(f"  ⏭ Skipping '{entry.label}'")
            return False
        if action in ("q", "quit"):
            print("  Aborting pipeline.")
            sys.exit(0)


def interactive_resolve_entry(
    entry: ManifestEntry,
    project_root: Path,
    max_loops: int = 5,
    auto_confirm: bool = False,
) -> list[Path]:
    """
    Phase 2 interactive visual resolution for one manifest entry.

    Shows matched keywords, candidate visuals ranked by score, and
    asks user to confirm / refresh / skip / quit.

    Returns selected Paths (may be empty if skipped).
    """
    assets_dir = project_root / "assets" / entry.assets_folder
    assets_dir.mkdir(parents=True, exist_ok=True)

    # Build search terms from keywords + topic
    terms = set()
    for kw in entry.visual_keywords:
        terms.update(_tokenize(kw))
        terms.update(VISUAL_KEYWORD_ALIASES.get(kw.lower(), set()))
    terms.update(_tokenize(entry.topic))
    # Also add the label for extra context
    terms.update(_tokenize(entry.label))

    visual_files = scan_visuals(assets_dir)

    while True:
        selected = select_top_visuals(visual_files, terms, max_count=max_loops)

        print("\n" + "=" * 58)
        print(f"  VISUAL REVIEW: {entry.label}")
        print("=" * 58)
        print(f"  Topic / Title : {entry.topic}")
        print(f"  Keywords      : {', '.join(entry.visual_keywords)}")
        print(f"  Orientation   : {entry.orientation}")
        print(f"  Assets folder : {assets_dir}")
        print(f"  Files found   : {len(visual_files)}")
        print()

        if visual_files:
            scored = _scored_visuals(visual_files, terms)
            header = f"  {'Score':<6} {'Matched Terms':<30} {'Filename'}"
            print(header)
            print(f"  {'─'*6} {'─'*30} {'─'*35}")
            for score, _, vpath in scored:
                v_terms = _tokenize(vpath.stem)
                matched_terms = (terms & v_terms)
                matched_str = ", ".join(sorted(matched_terms))[:28] if matched_terms else "(none)"
                marker = " ⬅" if vpath in selected else ""
                print(f"  {score:<6} {matched_str:<30} {vpath.name}{marker}")
        else:
            print("  ⚠ No visual files found in this folder!")
            print(f"  Place .mp4 loops in {assets_dir}")

        print()
        action = input(
            "  [Y] Use these visuals  [R] Refresh after adding files  "
            "[S] Skip  [Q] Quit: "
        ).strip().lower()

        if action in ("", "y", "yes"):
            entry.resolved_visuals = [str(p) for p in selected]
            print(f"  ✓ {len(selected)} visual(s) selected for '{entry.label}'")
            return selected

        elif action in ("r", "refresh"):
            print("  Add or rename files now, then press Enter to re-scan...")
            input()
            visual_files = scan_visuals(assets_dir)
            continue

        elif action in ("s", "skip"):
            print(f"  ⏭ Skipping '{entry.label}'")
            return []

        elif action in ("q", "quit"):
            print("  Aborting pipeline.")
            sys.exit(0)


def resolve_manifest(
    manifest: VisualManifest,
    project_root: Path,
    max_loops: int = 5,
    auto_confirm: bool = False,
) -> VisualManifest:
    """
    Run interactive visual resolution for every entry in the manifest.
    Mutates and returns the manifest with resolved_visuals filled in.
    """
    print(f"\n  Manifest has {len(manifest.entries)} video(s) to process")
    for i, entry in enumerate(manifest.entries, 1):
        if entry.visual_mode == "scenes" and entry.scenes:
            if entry.scene_images_ready:
                print(f"\n  [{i}/{len(manifest.entries)}] Scene images already ready: {entry.label}")
                act = input("    Re-check scene images? [y/N]: ").strip().lower()
                if act not in ("y", "yes"):
                    continue
            interactive_resolve_scenes(entry, project_root)
            continue

        if entry.resolved_visuals:
            print(f"\n  [{i}/{len(manifest.entries)}] Already resolved: {entry.label}")
            print(f"    Previous selection: {', '.join(Path(p).name for p in entry.resolved_visuals)}")
            act = input("    Use previous? [Y]es / [R]e-resolve: ").strip().lower()
            if act in ("", "y", "yes"):
                continue
        interactive_resolve_entry(
            entry, project_root, max_loops=max_loops, auto_confirm=auto_confirm
        )
    return manifest


def save_resolved_manifest(manifest: VisualManifest, path: Path) -> None:
    """Write manifest back after resolution so user can re-run without re-resolving."""
    write_manifest(manifest, path)
    print(f"  Resolution saved to: {path}")
