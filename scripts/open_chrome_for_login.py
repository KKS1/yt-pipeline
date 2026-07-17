"""
open_chrome_for_login.py
────────────────────────
Open Chromium browser with Chrome profile for manual Google login.
Keep the browser open so you can complete the login process with verification codes.
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

import asyncio
from playwright.async_api import async_playwright


async def open_chrome_for_login():
    """Open Chromium with Chrome profile and keep it open for manual login."""
    
    profile_path = os.getenv("CHROME_PROFILE_PATH", "/Users/kanwal/Library/Application Support/Google/Chrome/Default")
    
    print("=" * 60)
    print("Opening Chromium for Manual Google Login")
    print("=" * 60)
    print(f"\nChrome profile: {profile_path}")
    print(f"\nBrowser will open and stay open.")
    print("Please log in to Google, then close the browser window when done.")
    print("\nAfter logging in, run: python scripts/test_chrome_ai.py")
    print("-" * 60)
    
    try:
        playwright = await async_playwright().start()
        
        # Launch Chrome with existing profile
        browser = await playwright.chromium.launch_persistent_context(
            user_data_dir=profile_path,
            headless=False,
            args=[
                "--no-sandbox",
                "--disable-blink-features=AutomationControlled",
            ],
            viewport={"width": 1920, "height": 1080},
        )
        
        # Navigate to Google accounts page
        if len(browser.pages) > 0:
            page = browser.pages[0]
        else:
            page = await browser.new_page()
        
        await page.goto("https://accounts.google.com")
        
        print("\n✓ Browser opened. Please complete Google login.")
        print("  Press Ctrl+C here when you're done to close the browser.")
        
        # Keep browser open until user interrupts
        try:
            # Just wait indefinitely for user to interrupt
            while True:
                await asyncio.sleep(1)
        except KeyboardInterrupt:
            print("\nKeyboard interrupt received, closing browser...")
        
        await browser.close()
        await playwright.stop()
        
        print("\n✓ Browser closed. Login session should now be saved.")
        print("  You can now run: python scripts/test_chrome_ai.py")
            
    except Exception as e:
        print(f"\n✗ ERROR: {e}")
        import traceback
        traceback.print_exc()
        return False
    
    return True


if __name__ == "__main__":
    # Check if Chrome profile path is set
    if not os.getenv("CHROME_PROFILE_PATH"):
        print("WARNING: CHROME_PROFILE_PATH not set in .env")
        print("Using default: /Users/kanwal/Library/Application Support/Google/Chrome/Default")
        os.environ["CHROME_PROFILE_PATH"] = "/Users/kanwal/Library/Application Support/Google/Chrome/Default"
    
    success = asyncio.run(open_chrome_for_login())
    sys.exit(0 if success else 1)
