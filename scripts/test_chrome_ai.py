"""
test_chrome_ai.py
─────────────────
Test script for Chrome AI image generation scraper.
Run this to verify the scraper works before using it in production.
"""

import sys
import os
from pathlib import Path
from dotenv import load_dotenv

# Load environment variables from .env
PROJECT_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(PROJECT_ROOT / ".env")

# Add scripts directory to path
sys.path.insert(0, str(Path(__file__).parent))

from chrome_ai_scraper import ChromeAIGenerator


async def test_chrome_ai():
    """Test Chrome AI scraper with a simple prompt."""
    
    # Test configuration
    test_scenes = [
        {
            "scene_id": 1,
            "visual_prompt": "A cute cat sitting on a windowsill, looking outside at a sunny garden with flowers",
            "image_filename": "test_scene_1_cat.png"
        }
    ]
    
    output_dir = Path(__file__).parent.parent / "assets" / "test_chrome_ai"
    
    print("=" * 60)
    print("Chrome AI Scraper Test")
    print("=" * 60)
    print(f"\nTest prompt: {test_scenes[0]['visual_prompt']}")
    print(f"Output directory: {output_dir}")
    print(f"Headless mode: {os.getenv('CHROME_AI_HEADLESS', 'false')}")
    print(f"Chrome profile: {os.getenv('CHROME_PROFILE_PATH', 'default')}")
    print("\nStarting test...")
    print("-" * 60)
    
    try:
        async with ChromeAIGenerator() as generator:
            result = await generator.generate_scene_images(
                test_scenes,
                output_dir,
                skip_existing=False
            )
            
            print("\n" + "=" * 60)
            print("Test Results:")
            print("=" * 60)
            print(f"Generated: {result['generated']}")
            print(f"Skipped: {result['skipped']}")
            print(f"Failed: {result['failed']}")
            print(f"Missing: {result['missing']}")
            
            if result['generated'] > 0:
                print(f"\n✓ SUCCESS: Image generated successfully!")
                print(f"  Check: {output_dir / test_scenes[0]['image_filename']}")
            else:
                print(f"\n✗ FAILED: No images generated")
                if result['missing']:
                    print(f"  Missing files: {result['missing']}")
            
            return result['generated'] > 0
            
    except Exception as e:
        print(f"\n✗ ERROR: {e}")
        import traceback
        traceback.print_exc()
        return False


if __name__ == "__main__":
    import asyncio
    
    # Check if Chrome profile path is set
    if not os.getenv("CHROME_PROFILE_PATH"):
        print("WARNING: CHROME_PROFILE_PATH not set in .env")
        print("Using default: /Users/kanwal/Library/Application Support/Google/Chrome/Default")
        os.environ["CHROME_PROFILE_PATH"] = "/Users/kanwal/Library/Application Support/Google/Chrome/Default"
    
    success = asyncio.run(test_chrome_ai())
    sys.exit(0 if success else 1)
