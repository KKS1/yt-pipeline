#!/usr/bin/env python3
"""Test script to verify the description formatting fixes for podcast videos."""

import sys
import json
import re
from pathlib import Path

# Add scripts directory to path
sys.path.insert(0, str(Path(__file__).resolve().parent))

from english_generator import (
    finalize_english_description,
    remove_duplicate_phrases,
    ensure_english_vibes_hashtags,
    ensure_english_seo_opener,
    ensure_english_description_cta,
)

# Load the existing podcast description
podcast_file = Path(__file__).resolve().parent / "output" / "english_podcast.json"
with open(podcast_file, "r") as f:
    podcast_data = json.load(f)

original_description = podcast_data["description"]
theme = podcast_data.get("theme", "Lost Booking Disaster")

print("=" * 80)
print("ORIGINAL DESCRIPTION:")
print("=" * 80)
print(original_description)
print("\n")

# Test the complete post-processing pipeline
print("=" * 80)
print("PROCESSED DESCRIPTION:")
print("=" * 80)

processed = finalize_english_description(
    original_description,
    include_timeline=True,  # Podcast videos have timeline
    is_quiz=False,
    theme=theme,
)
print(processed)
print("\n")

# Verify key requirements
print("=" * 80)
print("VERIFICATION:")
print("=" * 80)

# Check for bell icon in subscribe line
if "🔔 Subscribe" in processed:
    print("✅ Bell icon (🔔) present in subscribe line")
else:
    print("❌ Bell icon (🔔) missing from subscribe line")

# Check for proper spacing (blank lines between sections)
lines = processed.splitlines()
blank_line_count = sum(1 for line in lines if line.strip() == "")
if blank_line_count >= 3:
    print(f"✅ Proper spacing ({blank_line_count} blank lines found)")
else:
    print(f"❌ Insufficient spacing (only {blank_line_count} blank lines)")

# Check hashtags are comprehensive
hashtag_lines = [line.strip() for line in lines if line.strip().startswith("#")]
if hashtag_lines:
    hashtag_text = " ".join(hashtag_lines)
    required_tags = ["#LearnEnglish", "#EnglishListeningPractice", "#SpeakEnglish"]
    missing_tags = [tag for tag in required_tags if tag not in hashtag_text]
    if not missing_tags:
        print("✅ Comprehensive hashtags present")
    else:
        print(f"❌ Missing required hashtags: {missing_tags}")
else:
    print("❌ No hashtags found")

# Check for duplicate lines
lines_lower = [line.strip().lower() for line in lines if line.strip()]
if len(lines_lower) == len(set(lines_lower)):
    print("✅ No duplicate lines")
else:
    print("❌ Duplicate lines found")

# Check for Timeline section
if "📑 Timeline:" in processed:
    print("✅ Timeline section present")
else:
    print("❌ Timeline section missing")

# Check for proper paragraph structure (no mashed text)
# Look for sections that should be separated by blank lines
sections = ["🎯", "📺", "💬", "🔔", "📑"]
section_positions = {}
for i, line in enumerate(lines):
    for section in sections:
        if line.strip().startswith(section):
            section_positions[section] = i

if len(section_positions) >= 3:
    # Check if sections are properly separated
    positions = sorted(section_positions.values())
    properly_separated = all(positions[i+1] - positions[i] > 1 for i in range(len(positions)-1))
    if properly_separated:
        print("✅ Sections properly separated with blank lines")
    else:
        print("❌ Sections not properly separated (mashed together)")
else:
    print(f"⚠️  Only {len(section_positions)} sections found, cannot verify separation")

print("\n" + "=" * 80)
