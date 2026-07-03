#!/usr/bin/env python3
"""Test script to verify the description formatting fixes."""

import sys
import json
import re
from pathlib import Path

# Add scripts directory to path
sys.path.insert(0, str(Path(__file__).resolve().parent))

from english_generator import (
    finalize_english_description,
    remove_duplicate_phrases,
    ensure_english_quiz_shorts_hashtags,
    ensure_english_quiz_about_section,
    ensure_english_seo_opener,
    remove_timeline_from_shorts,
    ensure_english_description_cta,
)

# Load the existing quiz description
quiz_file = Path(__file__).resolve().parent / "output" / "english_quiz.json"
with open(quiz_file, "r") as f:
    quiz_data = json.load(f)

original_description = quiz_data["description"]
theme = quiz_data.get("theme", "Idiom Quiz - Under the Table")

print("=" * 80)
print("ORIGINAL DESCRIPTION:")
print("=" * 80)
print(original_description)
print("\n")

# Test the complete post-processing pipeline
print("=" * 80)
print("PROCESSED DESCRIPTION:")
print("=" * 80)

# Debug: Check each step
print("\n--- After duplicate removal ---")
step1 = remove_duplicate_phrases(original_description)
print(step1[:200] + "...")

print("\n--- After SEO opener ---")
step2 = ensure_english_seo_opener(step1, theme=theme)
print(step2[:200] + "...")

print("\n--- After timeline removal ---")
step3 = remove_timeline_from_shorts(step2)
print(step3[:200] + "...")

print("\n--- After CTA ---")
step4 = ensure_english_description_cta(step3, include_timeline=False)
print(step4[:300] + "...")

processed = finalize_english_description(
    original_description,
    include_timeline=False,  # Quiz shorts don't have timeline
    is_quiz=True,
    theme=theme,
)
print("\n--- FINAL ---")
print(processed)
print("\n")

# Verify key requirements
print("=" * 80)
print("VERIFICATION:")
print("=" * 80)

# Check hashtags are at the end
lines = processed.splitlines()
hashtag_lines = [i for i, line in enumerate(lines) if line.strip().startswith("#")]
if hashtag_lines:
    last_hashtag_idx = hashtag_lines[-1]
    if last_hashtag_idx == len(lines) - 1:
        print("✅ Hashtags are at the END")
    else:
        print(f"❌ Hashtags are NOT at the end (last hashtag at line {last_hashtag_idx}, total lines {len(lines)})")
else:
    print("❌ No hashtags found")

# Check for duplicate lines
lines_lower = [line.strip().lower() for line in lines if line.strip()]
if len(lines_lower) == len(set(lines_lower)):
    print("✅ No duplicate lines")
else:
    print("❌ Duplicate lines found")

# Check for About This Lesson section
if "📑 About This Lesson:" in processed:
    print("✅ About This Lesson section present")
else:
    print("❌ About This Lesson section missing")

# Check for timeline (should NOT be present in quiz shorts)
if "📑 Timeline:" in processed or re.search(r"\d+:\d{2}\s*-\s*", processed):
    print("❌ Timeline found (should be removed for quiz shorts)")
else:
    print("✅ Timeline removed (correct for quiz shorts)")

# Check for proper spacing
if "\n\n\n" not in processed:
    print("✅ Proper spacing (no triple blank lines)")
else:
    print("❌ Excessive blank lines found")

print("\n" + "=" * 80)
