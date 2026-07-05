#!/usr/bin/env python3
"""Test script to verify English description fixes."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from english_generator import (
    finalize_english_description,
    ensure_english_seo_opener,
    ensure_english_description_cta,
    ensure_english_quiz_about_section,
)

def test_subscribe_icon():
    """Test that subscribe line has proper bell icon."""
    print("Testing subscribe icon fix...")
    description = "🎯 English listening practice via Story: Airport Security.\n\n📺 Watch the playlist here: {playlist_url}"
    
    result = ensure_english_description_cta(description, include_timeline=False)
    
    # Check for proper bell icon
    if "🔔 Subscribe" in result:
        print("✅ Subscribe icon fixed correctly")
        return True
    else:
        print("❌ Subscribe icon not fixed")
        print(f"Result: {result}")
        return False

def test_about_section_placement():
    """Test that About section appears immediately after SEO opener."""
    print("\nTesting About section placement...")
    description = "🎯 English listening practice via Story: Airport Security Nightmare.\n\n📺 Watch the playlist here: {playlist_url}"
    
    result = ensure_english_quiz_about_section(description, theme="in a bind")
    
    lines = result.splitlines()
    
    # Check that About section appears early in the description (within first 3 lines)
    # Allow for blank line between SEO opener and About section
    about_found = False
    for i in range(min(3, len(lines))):
        if lines[i].strip().startswith("📑 About This Lesson:"):
            about_found = True
            break
    
    if about_found:
        print("✅ About section placed correctly after SEO opener")
        return True
    else:
        print("❌ About section not placed correctly")
        print(f"Result:\n{result}")
        return False

def test_seo_opener():
    """Test that SEO opener generates proper format."""
    print("\nTesting SEO opener generation...")
    description = "Some random description text"
    theme = "Airport Security Nightmare"
    
    result = ensure_english_seo_opener(description, theme=theme)
    
    # Check for required keywords
    required_keywords = ["English listening practice", "Master natural English", "speak like a native"]
    has_all_keywords = all(keyword in result for keyword in required_keywords)
    
    if has_all_keywords and result.startswith("🎯"):
        print("✅ SEO opener generated correctly")
        print(f"Result: {result}")
        return True
    else:
        print("❌ SEO opener not generated correctly")
        print(f"Result: {result}")
        return False

def test_full_finalization():
    """Test the full finalize_english_description function with quiz mode."""
    print("\nTesting full description finalization (quiz mode)...")
    description = "🎯 English listening practice via Story: Airport Security.\n\nSome content here"
    
    result = finalize_english_description(description, is_quiz=True, theme="in a bind", include_timeline=False)
    
    lines = result.splitlines()
    
    # Check structure: SEO opener → About section → CTAs → hashtags
    # Allow for blank lines between sections
    about_found = any(line.strip().startswith("📑 About This Lesson:") for line in lines)
    
    checks = {
        "SEO opener first": lines[0].startswith("🎯") if lines else False,
        "About section present": about_found,
        "Subscribe has bell": "🔔 Subscribe" in result,
        "Has hashtags at end": any(line.strip().startswith("#") for line in lines),
    }
    
    all_passed = all(checks.values())
    
    if all_passed:
        print("✅ Full description finalization passed all checks")
        for check, passed in checks.items():
            print(f"  - {check}: {'✅' if passed else '❌'}")
        return True
    else:
        print("❌ Full description finalization failed some checks")
        for check, passed in checks.items():
            print(f"  - {check}: {'✅' if passed else '❌'}")
        print(f"\nFull result:\n{result}")
        return False

if __name__ == "__main__":
    print("=" * 60)
    print("Testing English Description Fixes")
    print("=" * 60)
    
    results = []
    results.append(test_subscribe_icon())
    results.append(test_about_section_placement())
    results.append(test_seo_opener())
    results.append(test_full_finalization())
    
    print("\n" + "=" * 60)
    print(f"Results: {sum(results)}/{len(results)} tests passed")
    print("=" * 60)
    
    sys.exit(0 if all(results) else 1)
