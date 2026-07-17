"""
chrome_ai_scraper.py
────────────────────
Automate Google Chrome AI image generation for English pipeline scenes.
Uses existing Chrome profile with logged-in Google accounts to generate
images via Chrome's built-in AI mode, avoiding API costs.
"""

from __future__ import annotations

import json
import os
import time
import asyncio
from pathlib import Path
from typing import Optional, Dict, List, Tuple
from datetime import datetime
from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent.parent

# Load environment variables from .env
load_dotenv(PROJECT_ROOT / ".env")

# Configuration from environment
CHROME_PROFILE_PATH = os.getenv("CHROME_PROFILE_PATH", "/Users/kanwal/Library/Application Support/Google/Chrome/Default")
CHROME_AI_HEADLESS = os.getenv("CHROME_AI_HEADLESS", "false").lower() == "true"
CHROME_AI_RATE_LIMIT_DELAY = int(os.getenv("CHROME_AI_RATE_LIMIT_DELAY", "30"))
CHROME_AI_MAX_RETRIES = int(os.getenv("CHROME_AI_MAX_RETRIES", "3"))


class ChromeAIGenerator:
    """Automate Chrome AI image generation using existing Google sessions."""
    
    def __init__(
        self,
        profile_path: str = CHROME_PROFILE_PATH,
        headless: bool = CHROME_AI_HEADLESS,
    ):
        self.profile_path = profile_path
        self.headless = headless
        self.playwright = None
        self.browser = None
        self.context = None
        self.page = None
        
        # Account rotation tracking
        self.available_accounts = []
        self.current_account_index = 0
        self.account_usage = {}  # account_email -> {"generated": int, "last_used": datetime}
        
    async def __aenter__(self):
        """Initialize Playwright and browser context."""
        try:
            from playwright.async_api import async_playwright
            self.playwright = await async_playwright().start()
            
            # Launch Chrome with existing profile
            self.browser = await self.playwright.chromium.launch_persistent_context(
                user_data_dir=self.profile_path,
                headless=self.headless,
                args=[
                    "--no-sandbox",
                    "--disable-blink-features=AutomationControlled",
                ],
                viewport={"width": 1920, "height": 1080},
            )
            
            self.context = self.browser
            self.page = await self.context.new_page()
            
            # Detect available Google accounts
            await self._detect_available_accounts()
            
            print(f"  Chrome AI scraper initialized (headless={self.headless})")
            print(f"  Detected {len(self.available_accounts)} Google account(s)")
            return self
            
        except ImportError:
            raise ImportError(
                "Playwright not installed. Run: pip install playwright && playwright install chromium"
            )
        except Exception as e:
            raise Exception(f"Failed to initialize Chrome AI scraper: {e}")
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Clean up Playwright resources."""
        if self.page:
            await self.page.close()
        if self.context:
            await self.context.close()
        if self.browser:
            await self.browser.close()
        if self.playwright:
            await self.playwright.stop()
    
    async def _detect_available_accounts(self):
        """Detect available Google accounts in Chrome profile."""
        try:
            # Navigate to Google accounts page
            await self.page.goto("https://accounts.google.com", timeout=30000)
            await self.page.wait_for_load_state("networkidle")
            
            # Look for account indicators
            # This is a simplified detection - in production, we'd parse the page more carefully
            account_selectors = [
                'div[data-email]',
                '[aria-label*="Google Account"]',
                '.wLBKD',  # Google account container
            ]
            
            accounts = []
            for selector in account_selectors:
                try:
                    elements = await self.page.query_selector_all(selector)
                    for element in elements:
                        email = await element.get_attribute("data-email")
                        if email:
                            accounts.append(email)
                except:
                    continue
            
            # Fallback: assume at least one account is logged in
            if not accounts:
                accounts = ["default_account"]
            
            self.available_accounts = accounts
            for account in accounts:
                self.account_usage[account] = {"generated": 0, "last_used": None}
            
        except Exception as e:
            print(f"  Warning: Could not detect accounts ({e}), using default")
            self.available_accounts = ["default_account"]
            self.account_usage["default_account"] = {"generated": 0, "last_used": None}
    
    async def _rotate_account(self):
        """Rotate to next available account to avoid rate limits."""
        if not self.available_accounts:
            return
        
        # Find account with least usage
        min_usage = min(
            self.account_usage[acc]["generated"] 
            for acc in self.available_accounts
        )
        
        # Get all accounts with minimum usage
        candidates = [
            acc for acc in self.available_accounts 
            if self.account_usage[acc]["generated"] == min_usage
        ]
        
        # Pick first candidate
        next_account = candidates[0]
        self.current_account_index = self.available_accounts.index(next_account)
        
        print(f"  Rotated to account: {next_account}")
    
    async def _navigate_to_ai_mode(self):
        """Navigate to Chrome AI mode for image generation."""
        try:
            # Navigate to Google homepage
            await self.page.goto("https://www.google.com", timeout=30000)
            await self.page.wait_for_load_state("networkidle")
            
            # Debug: Print page title and URL
            print(f"  Current page: {self.page.url}")
            print(f"  Page title: {await self.page.title()}")
            
            # Debug: Look for any buttons on the page
            all_buttons = await self.page.query_selector_all('button, [role="button"], cr-icon-button')
            print(f"  Found {len(all_buttons)} button-like elements on page")
            for i, btn in enumerate(all_buttons[:10]):  # Show first 10
                try:
                    text = await btn.inner_text()
                    aria_label = await btn.get_attribute('aria-label')
                    classes = await btn.get_attribute('class')
                    print(f"    Button {i}: text='{text}', aria-label='{aria_label}', class='{classes}'")
                except:
                    print(f"    Button {i}: (could not get attributes)")
            
            # Look for AI mode button in search bar
            # Based on actual Chrome HTML: <cr-icon-button id="entrypoint" class="ai-mode-button" ...>
            # Also looking for '+' button as user mentioned
            # User provided actual button: <button jsname="ko0Zye" class="UbbAWe" aria-label="Add files, tools, and select a model">
            # Note: jsname and class can be dynamic, so rely on aria-label
            ai_selectors = [
                'button[aria-label="Add files, tools, and select a model"]',
                'button[aria-label*="Add files"]',
                'button[aria-label*="files, tools"]',
                'button[aria-label*="tools, and select a model"]',
                'button[aria-label*="Enhance your search with tabs, files, or an AI tool"]',
                'button[aria-label*="AI"]',
                'button[aria-label*="Google AI"]',
                'button:has-text("+")',
                '[role="button"]:has-text("+")',
            ]
            
            ai_button = None
            for selector in ai_selectors:
                try:
                    ai_button = await self.page.wait_for_selector(selector, timeout=5000)
                    if ai_button:
                        print(f"  Found AI mode button with selector: {selector}")
                        break
                except:
                    continue
            
            if not ai_button:
                raise Exception("Could not find AI mode button in Chrome")
            
            # Click AI mode button
            await ai_button.click()
            await self.page.wait_for_timeout(2000)
            
            # Look for "create images" option
            # Based on actual Chrome HTML: <button class="izN7If" data-tool="4" role="menuitemradio" ...><span>Create images</span>
            # Note: jsname and class can be dynamic, so rely on data-tool, role, and text
            image_selectors = [
                'button[data-tool="4"]',
                'button[role="menuitemradio"]:has-text("Create images")',
                'button:has-text("Create images")',
                '[role="menuitemradio"][data-tool="4"]',
                'button:has-text("🍌")',
            ]
            
            image_button = None
            for selector in image_selectors:
                try:
                    image_button = await self.page.wait_for_selector(selector, timeout=5000)
                    if image_button:
                        print(f"  Found create images button with selector: {selector}")
                        break
                except:
                    continue
            
            if not image_button:
                raise Exception("Could not find 'create images' option")
            
            # Click create images
            await image_button.click()
            await self.page.wait_for_timeout(2000)
            
            print(f"  Successfully navigated to Chrome AI image generation")
            
        except Exception as e:
            raise Exception(f"Failed to navigate to AI mode: {e}")
    
    async def _submit_prompt(self, prompt_text: str) -> bool:
        """Submit visual prompt to Chrome AI and wait for generation."""
        try:
            # Look for prompt input field
            # Based on actual Chrome HTML: <textarea placeholder="Describe your image" aria-label="Search" role="combobox" name="q">
            # Note: jsname, class, id can be dynamic, so rely on placeholder, aria-label, role, name
            input_selectors = [
                'textarea[placeholder="Describe your image"]',
                'textarea[placeholder*="Describe your"]',
                'textarea[aria-label="Search"]',
                'textarea[role="combobox"]',
                'textarea[name="q"]',
                'textarea[placeholder*="image"]',
                'textarea[placeholder*="describe"]',
                'div[contenteditable="true"]',
            ]
            
            prompt_input = None
            for selector in input_selectors:
                try:
                    prompt_input = await self.page.wait_for_selector(selector, timeout=5000)
                    if prompt_input:
                        break
                except:
                    continue
            
            if not prompt_input:
                raise Exception("Could not find prompt input field")
            
            # Enter prompt
            await prompt_input.fill(prompt_text)
            await self.page.wait_for_timeout(1000)
            
            # Look for generate button
            generate_selectors = [
                'button:has-text("generate")',
                'button:has-text("Generate")',
                '[data-test-id="generate-button"]',
                'button[type="submit"]',
            ]
            
            generate_button = None
            for selector in generate_selectors:
                try:
                    generate_button = await self.page.wait_for_selector(selector, timeout=5000)
                    if generate_button:
                        break
                except:
                    continue
            
            if not generate_button:
                raise Exception("Could not find generate button")
            
            # Click generate
            await generate_button.click()
            print(f"  Submitted prompt: {prompt_text[:50]}...")
            
            return True
            
        except Exception as e:
            raise Exception(f"Failed to submit prompt: {e}")
    
    async def _wait_for_image_generation(self, timeout: int = 60) -> bool:
        """Wait for image generation to complete by checking for the generated image element."""
        try:
            # Look for the actual generated image tag in Chrome AI mode
            # <img alt="AI generated image" data-processed="true" ... />
            image_selectors = [
                'img[alt="AI generated image"][data-processed="true"]',
                'img[alt="AI generated image"]',
                'img[data-processed="true"]',
            ]
            
            start_time = time.time()
            while time.time() - start_time < timeout:
                for selector in image_selectors:
                    try:
                        image_element = await self.page.query_selector(selector)
                        if image_element:
                            print(f"  Image generated successfully")
                            return True
                    except:
                        continue
                
                await self.page.wait_for_timeout(2000)
            
            raise Exception("Timeout waiting for image generation")
            
        except Exception as e:
            raise Exception(f"Failed to wait for image generation: {e}")
    
    async def _download_image(self, output_path: Path) -> bool:
        """Click the download button to save the generated image."""
        try:
            # Find the download button in Chrome AI mode
            # <button aria-label="Download this AI generated image" title="Download image" data-processed="true" ... />
            download_selectors = [
                'button[aria-label="Download this AI generated image"][data-processed="true"]',
                'button[aria-label="Download this AI generated image"]',
                'button[title="Download image"][data-processed="true"]',
                'button[title="Download image"]',
            ]
            
            download_button = None
            for selector in download_selectors:
                try:
                    download_button = await self.page.wait_for_selector(selector, timeout=10000)
                    if download_button:
                        print(f"  Found download button with selector: {selector}")
                        break
                except:
                    continue
            
            if not download_button:
                raise Exception("Could not find download button")
            
            # Set up download handler before clicking
            async with self.page.expect_download(timeout=30000) as download_info:
                await download_button.click()
            
            download = await download_info.value
            
            # Save to output path
            output_path.parent.mkdir(parents=True, exist_ok=True)
            await download.save_as(str(output_path))
            
            print(f"  Downloaded image to: {output_path.name}")
            return True
                
        except Exception as e:
            raise Exception(f"Failed to download image: {e}")
    
    async def generate_scene_images(
        self,
        scenes: List[dict],
        output_dir: Path,
        skip_existing: bool = True,
    ) -> dict:
        """Generate images for all scenes using Chrome AI.
        
        Returns summary dict: {generated, skipped, failed, missing}
        """
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        
        generated = 0
        skipped = 0
        failed = 0
        missing = []
        
        print(f"\nGenerating {len(scenes)} scene images via Chrome AI...")
        
        for i, scene in enumerate(scenes, start=1):
            scene_id = scene.get("scene_id", i)
            visual_prompt = scene.get("visual_prompt", "").strip()
            image_filename = scene.get("image_filename", f"scene_{scene_id}.png")
            output_path = output_dir / image_filename
            
            # Skip if file exists and skip_existing is True
            if skip_existing and output_path.exists():
                print(f"  [{i}/{len(scenes)}] Skipping existing {output_path.name}")
                skipped += 1
                continue
            
            if not visual_prompt:
                print(f"  [{i}/{len(scenes)}] No visual_prompt for scene {scene_id}")
                failed += 1
                missing.append(image_filename)
                continue
            
            # Rotate account if needed
            await self._rotate_account()
            
            # Try generation with retries
            success = False
            for attempt in range(CHROME_AI_MAX_RETRIES):
                try:
                    print(f"  [{i}/{len(scenes)}] Generating {output_path.name} (attempt {attempt + 1})")
                    
                    # Navigate to AI mode
                    await self._navigate_to_ai_mode()
                    
                    # Submit prompt
                    await self._submit_prompt(visual_prompt)
                    
                    # Wait for generation
                    await self._wait_for_image_generation()
                    
                    # Download image via click
                    await self._download_image(output_path)
                    
                    # Update account usage
                    current_account = self.available_accounts[self.current_account_index]
                    self.account_usage[current_account]["generated"] += 1
                    self.account_usage[current_account]["last_used"] = datetime.now()
                    
                    generated += 1
                    success = True
                    
                    # Rate limit delay between generations
                    if i < len(scenes):
                        print(f"  Waiting {CHROME_AI_RATE_LIMIT_DELAY}s before next generation...")
                        await asyncio.sleep(CHROME_AI_RATE_LIMIT_DELAY)
                    
                    break
                    
                except Exception as e:
                    print(f"    Attempt {attempt + 1} failed: {e}")
                    if attempt < CHROME_AI_MAX_RETRIES - 1:
                        await asyncio.sleep(5)  # Brief delay before retry
            
            if not success:
                print(f"  [{i}/{len(scenes)}] Failed to generate {output_path.name}")
                failed += 1
                missing.append(image_filename)
        
        # Check for missing images
        for scene in scenes:
            image_filename = scene.get("image_filename", "")
            if image_filename:
                output_path = output_dir / image_filename
                if not output_path.exists() and image_filename not in missing:
                    missing.append(image_filename)
        
        return {
            "generated": generated,
            "skipped": skipped,
            "failed": failed,
            "missing": missing,
        }


def generate_scene_images_sync(
    scenes_dir: Path,
    scenes: List[dict],
    *,
    skip_existing: bool = True,
) -> dict:
    """Synchronous wrapper for Chrome AI image generation."""
    async def _generate():
        async with ChromeAIGenerator() as generator:
            return await generator.generate_scene_images(
                scenes, scenes_dir, skip_existing=skip_existing
            )
    
    return asyncio.run(_generate())


def fetch_scenes_for_manifest_entry(
    project_root: Path,
    entry,
    *,
    skip_existing: bool = True,
) -> dict:
    """Generate scene images for a manifest entry using Chrome AI."""
    from manifest_runner import scenes_assets_dir
    
    scenes_dir = scenes_assets_dir(project_root, entry.scenes_folder)
    return generate_scene_images_sync(
        scenes_dir,
        entry.scenes,
        skip_existing=skip_existing,
    )
