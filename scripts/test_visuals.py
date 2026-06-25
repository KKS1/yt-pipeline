"""
test_visuals.py — tests for visual selection and manifest-based two-phase pipeline.

Run:
    python scripts/test_visuals.py

Tests:
    1. English landscape   — old --review-visuals path
    2. English Shorts      — old --review-visuals path
    3. English Quiz Shorts — old --review-visuals path
    4. Manifest-only English       — Phase 1 manifest generation
    5. Manifest-only English Shorts — Phase 1 manifest generation
    6. Manifest-only English Quiz  — Phase 1 manifest generation
    7. Manifest-only Challenge     — Phase 1 manifest generation (14 entries)
    8. Manifest read-back          — verify manifest round-trips correctly
"""

import os
import sys
from pathlib import Path
import json
import tempfile
import shutil

# Add scripts directory to path
sys.path.insert(0, str(Path(__file__).resolve().parent))

# Monkeypatch the generators
import english_generator

dummy_script_base = {
    "title": "Visual Test",
    "visual_keywords": ["coffee", "cafe", "conversation", "library"],
    "theme": "Coffee Shop English",
    "dialogue": [
        {"speaker": "Emma", "text": "Quick test. Which phrase sounds natural at a coffee shop?"},
        {"speaker": "Liam", "text": "Pause and guess before Emma answers."},
        {"speaker": "Emma", "text": "[PAUSE 3 SECONDS]"},
        {"speaker": "Liam", "text": "Say, can I get this to go? That sounds natural."},
        {"speaker": "Emma", "text": "Good. Now let's throw an idiom under the bus and see the card."},
        {"speaker": "Liam", "text": "Btw, how is the weather!"},
        {"speaker": "Emma", "text": "Its looking good so far, I think. Was cloudy earlier but the sun is out now."},
        {"speaker": "Liam", "text": "Good to hear that. I am also looking forward to the rest of the day."},
        {"speaker": "Emma", "text": "Same here! Hopefully we can go out and enjoy the sun!"},
        {"speaker": "Liam", "text": "Sounds good!"},
        {"speaker": "Emma", "text": "Thanks for listening, see you next time!"},
        {"speaker": "Liam", "text": "Bye!"}
    ],
}

dummy_challenge_package = {
    "series_title": "Test Weekly Challenge",
    "description": "A test challenge",
    "tags": ["test", "english"],
    "days": [
        {"day": 1, "title": "Day 1: Basics", "focus": "basic greetings", "practice_task": "Say hello to 3 people", "keywords": ["greetings", "hello"]},
        {"day": 2, "title": "Day 2: Conversations", "focus": "small talk", "practice_task": "Have a 2-min chat", "keywords": ["talk", "conversation"]},
    ],
    "scripts": [],
}


def _with_scenes(script: dict) -> dict:
    data = dict(script)
    data["scenes"] = [
        {
            "scene_id": 1,
            "scene_label": "Coffee Shop Scene",
            "image_filename": "scene_1_coffee.jpg",
            "visual_prompt": "Pixar 3D animation, Emma and Liam at a cozy coffee shop.",
            "start_turn": 0,
            "end_turn": max(0, len(data.get("dialogue", [])) - 1),
        }
    ]
    return data


# Build 2 days of scripts with quiz_script
for d in dummy_challenge_package["days"]:
    day_num = d["day"]
    day_script = _with_scenes({
        **dummy_script_base,
        "title": f"Day {day_num}: {d['title']}",
        "day": day_num,
        "series_title": "Test Weekly Challenge",
        "focus": d["focus"],
        "practice_task": d["practice_task"],
        "visual_keywords": d["keywords"],
        "quiz_script": _with_scenes({
            "title": f"Quiz Day {day_num}",
            "visual_keywords": ["quiz", "test"],
            "dialogue": [
                {"speaker": "Emma", "text": "Quick question!"},
                {"speaker": "Liam", "text": "The answer is B."},
            ],
        }),
    })
    dummy_challenge_package["scripts"].append(day_script)


def mock_annotate(script):
    if "idiom_windows" not in script or not script["idiom_windows"]:
        script["idiom_windows"] = [
            {
                "idiom": "under the bus",
                "type": "idiom",
                "definition": "to sacrifice someone for personal gain",
                "start_turn": 1,
                "end_turn": 4,
            }
        ]


def mock_gen_english(topic=None):
    return _with_scenes({**dummy_script_base, "title": "Mock English Podcast"})


def mock_gen_shorts(topic=None):
    return _with_scenes({**dummy_script_base, "title": "Mock English Short"})


def mock_gen_quiz(topic=None):
    return _with_scenes({**dummy_script_base, "title": "Mock English Quiz"})


def mock_gen_challenge(topic=None):
    return dummy_challenge_package


# Apply mocks
english_generator.generate_english_script = mock_gen_english
english_generator.generate_english_shorts_script = mock_gen_shorts
english_generator.generate_english_quiz_shorts_script = mock_gen_quiz
english_generator.generate_weekly_challenge_scripts = mock_gen_challenge
english_generator.annotate_script_with_idiom_windows = mock_annotate
english_generator.attach_storyboard_to_script = lambda script, **kwargs: script

from manual_run import (
    run_english,
    run_english_shorts,
    run_english_quiz_shorts,
)


# ── Legacy visual review tests ─────────────────────────────────

def test_legacy_landscape():
    """Test the old --review-visuals path (no interactive review)."""
    print("=" * 60)
    print("[1/8] Legacy: English Landscape (--review-visuals path)")
    print("=" * 60)
    out = run_english(topic="test", upload=False)
    print(f"Landscape Output: {out}")
    return out


def test_legacy_shorts():
    """Test the old --review-visuals path for shorts."""
    print("\n" + "=" * 60)
    print("[2/8] Legacy: English Shorts")
    print("=" * 60)
    out = run_english_shorts(topic="test", upload=False)
    print(f"Shorts Output: {out}")
    return out


def test_legacy_quiz():
    """Test the old --review-visuals path for quiz shorts."""
    print("\n" + "=" * 60)
    print("[3/8] Legacy: English Quiz Shorts")
    print("=" * 60)
    out = run_english_quiz_shorts(topic="test", upload=False)
    print(f"Quiz Shorts Output: {out}")
    return out


# ── Manifest mode tests ────────────────────────────────────────

from manual_run import (
    MANIFEST_ONLY_ROUTER,
    run_manifest_only_english,
    run_manifest_only_shorts,
    run_manifest_only_quiz_shorts,
    run_manifest_only_challenge,
    MANIFEST_DIR,
)
from manifest_runner import VisualManifest, read_manifest, ManifestEntry


def test_manifest_english():
    """Phase 1 manifest generation for English podcast."""
    print("\n" + "=" * 60)
    print("[4/8] Manifest-Only: English Podcast")
    print("=" * 60)

    # Count existing manifests
    before = list(MANIFEST_DIR.glob("*.manifest.json"))
    print(f"  Manifests before: {len(before)}")

    run_manifest_only_english(topic="test", skip_gemini=True)

    after = list(MANIFEST_DIR.glob("*.manifest.json"))
    print(f"  Manifests after:  {len(after)}")

    new = [m for m in after if m not in before]
    if not new:
        print("  ❌ No new manifest found!")
        return False

    manifest_path = new[0]
    print(f"  Manifest: {manifest_path}")

    manifest = read_manifest(manifest_path)
    print(f"  Pipeline: {manifest.pipeline}")
    print(f"  Entries:  {len(manifest.entries)}")
    assert manifest.pipeline == "english"
    assert len(manifest.entries) == 1
    entry = manifest.entries[0]
    assert entry.visual_mode == "scenes"
    assert entry.scenes_folder.startswith("generated_scenes/")
    assert len(entry.scenes) >= 1
    print(f"  ✓ Entry: '{entry.label}' | scenes={len(entry.scenes)} | folder=assets/{entry.scenes_folder}/")

    # Cleanup
    manifest_path.unlink()
    print(f"  ✓ Cleaned up test manifest")
    return True


def test_manifest_shorts():
    """Phase 1 manifest generation for English Shorts."""
    print("\n" + "=" * 60)
    print("[5/8] Manifest-Only: English Shorts")
    print("=" * 60)

    run_manifest_only_shorts(topic="test", skip_gemini=True)

    new = sorted(MANIFEST_DIR.glob("*.manifest.json"), key=lambda p: p.stat().st_mtime, reverse=True)[:1]
    if not new:
        print("  ❌ No new manifest found!")
        return False

    manifest_path = new[0]
    manifest = read_manifest(manifest_path)
    assert manifest.pipeline == "english-shorts"
    assert len(manifest.entries) == 1
    entry = manifest.entries[0]
    assert entry.visual_mode == "scenes"
    print(f"  ✓ Entry: '{entry.label}' | scenes={len(entry.scenes)} | folder=assets/{entry.scenes_folder}/")

    manifest_path.unlink()
    return True


def test_manifest_quiz():
    """Phase 1 manifest generation for English Quiz Shorts."""
    print("\n" + "=" * 60)
    print("[6/8] Manifest-Only: English Quiz Shorts")
    print("=" * 60)

    run_manifest_only_quiz_shorts(topic="test", skip_gemini=True)

    new = sorted(MANIFEST_DIR.glob("*.manifest.json"), key=lambda p: p.stat().st_mtime, reverse=True)[:1]
    if not new:
        print("  ❌ No new manifest found!")
        return False

    manifest_path = new[0]
    manifest = read_manifest(manifest_path)
    assert manifest.pipeline == "english-quiz"
    assert len(manifest.entries) == 1
    entry = manifest.entries[0]
    assert entry.visual_mode == "scenes"
    print(f"  ✓ Entry: '{entry.label}' | scenes={len(entry.scenes)} | folder=assets/{entry.scenes_folder}/")

    manifest_path.unlink()
    return True


def test_manifest_challenge():
    """Phase 1 manifest generation for Weekly Challenge (multi-entry)."""
    print("\n" + "=" * 60)
    print("[7/8] Manifest-Only: English Weekly Challenge")
    print("=" * 60)

    run_manifest_only_challenge(topic="test", skip_gemini=True)

    new = sorted(MANIFEST_DIR.glob("*.manifest.json"), key=lambda p: p.stat().st_mtime, reverse=True)[:1]
    if not new:
        print("  ❌ No new manifest found!")
        return False

    manifest_path = new[0]
    manifest = read_manifest(manifest_path)
    assert manifest.pipeline == "english-challenge"
    # 2 days × (1 long-form + 1 quiz) = 4 entries
    expected_entries = 2 * 2
    assert len(manifest.entries) == expected_entries, f"Expected {expected_entries} entries, got {len(manifest.entries)}"
    print(f"  ✓ Series: '{manifest.series_title}'")
    print(f"  ✓ {len(manifest.entries)} entries:")
    for entry in manifest.entries:
        print(f"    - {entry.label:40s} folder={entry.assets_folder}")

    # Verify individual script files were written
    script_path = Path("scripts/output/challenge_day_1.json")
    assert script_path.exists(), "Day 1 script not written"
    print(f"  ✓ Individual script files present")

    # Cleanup
    manifest_path.unlink()
    for entry in manifest.entries:
        sp = Path(entry.script_path)
        if sp.exists():
            sp.unlink()
    print(f"  ✓ Cleaned up test files")
    return True


def test_manifest_roundtrip():
    """Verify manifest can be serialized and read back with all fields intact."""
    print("\n" + "=" * 60)
    print("[8/8] Manifest round-trip")
    print("=" * 60)

    original = VisualManifest(
        version=2,
        pipeline="test-roundtrip",
        generated_at="2026-06-22T12:00:00+00:00",
        series_title="Round Trip Test",
        entries=[
            ManifestEntry(
                label="Entry A",
                script_path="scripts/a.json",
                assets_folder="english_visuals",
                visual_keywords=["coffee", "cafe", "morning"],
                topic="Morning Coffee",
                orientation="landscape",
                estimated_duration_seconds=120.0,
                resolved_visuals=["assets/english_visuals/coffee.mp4"],
                scenes=[{"scene_id": 1, "image_filename": "scene_1.jpg"}],
                scenes_folder="generated_scenes/morning_coffee",
                scene_images_ready=False,
                visual_mode="scenes",
            ),
            ManifestEntry(
                label="Entry B",
                script_path="scripts/b.json",
                assets_folder="english_shorts_visuals",
                visual_keywords=["quiz", "test"],
                topic="Quick Quiz",
                orientation="portrait",
            ),
        ],
    )

    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir) / "test.manifest.json"
        from manifest_runner import write_manifest, save_resolved_manifest
        write_manifest(original, tmp)
        assert tmp.exists()
        print(f"  ✓ Manifest written: {tmp}")

        restored = read_manifest(tmp)
        assert restored.pipeline == original.pipeline
        assert restored.series_title == original.series_title
        assert len(restored.entries) == len(original.entries)
        for i, (oe, re) in enumerate(zip(original.entries, restored.entries)):
            assert oe.label == re.label
            assert oe.visual_keywords == re.visual_keywords
            assert oe.orientation == re.orientation
            assert oe.estimated_duration_seconds == re.estimated_duration_seconds
            assert oe.resolved_visuals == re.resolved_visuals
            assert oe.scenes == re.scenes
            assert oe.scenes_folder == re.scenes_folder
            assert oe.visual_mode == re.visual_mode
            print(f"  ✓ Entry {i+1}: '{re.label}' round-trips OK")

    print(f"  ✓ All fields survive serialization")
    return True


# ── Run all tests ──────────────────────────────────────────────

def main():
    print("Visual Pipeline Test Runner\n")
    print(f"Using manifest dir: {MANIFEST_DIR}")
    print()

    results = [
        ("Legacy Landscape",        test_legacy_landscape()),
        ("Legacy Shorts",           test_legacy_shorts()),
        ("Legacy Quiz",             test_legacy_quiz()),
        ("Manifest English",        test_manifest_english()),
        ("Manifest Shorts",         test_manifest_shorts()),
        ("Manifest Quiz",           test_manifest_quiz()),
        ("Manifest Challenge",      test_manifest_challenge()),
        ("Manifest Round-trip",     test_manifest_roundtrip()),
    ]

    print("\n" + "=" * 60)
    print("RESULTS SUMMARY")
    print("=" * 60)
    all_pass = True
    for name, result in results:
        status = "✓ PASS" if result else "✗ FAIL"
        print(f"  {status:>8}  {name}")
        if not result:
            all_pass = False

    print()
    if all_pass:
        print("All tests PASSED!")
    else:
        print("Some tests FAILED!")
        sys.exit(1)


if __name__ == "__main__":
    main()
