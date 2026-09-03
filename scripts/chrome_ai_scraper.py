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
CHROME_AI_RATE_LIMIT_DELAY = int(os.getenv("CHROME_AI_RATE_LIMIT_DELAY", "2"))
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
        self._last_captured_image_bytes = None  # filled by network response interceptor

        # Account rotation tracking
        self.available_accounts = []
        self.current_account_index = 0
        self.account_usage = {}  # account_email -> {"generated": int, "last_used": datetime}
        
    async def __aenter__(self):
        """Initialize Playwright and browser context."""
        try:
            from playwright.async_api import async_playwright
            self.playwright = await async_playwright().start()
            
            # Launch real Chrome (not headless-shell) to avoid bot detection
            self.browser = await self.playwright.chromium.launch_persistent_context(
                user_data_dir=self.profile_path,
                headless=self.headless,
                channel="chrome",
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
    
    async def _check_daily_limit(self) -> bool:
        """Check if the page shows 'Daily limit reached' for image generation."""
        try:
            limit_indicators = [
                ':text("Daily limit reached")',
                ':text("daily limit")',
                ":text(\"You've reached your daily limit\")",
                '[aria-label*="Daily limit"]',
            ]
            for selector in limit_indicators:
                try:
                    element = await self.page.query_selector(selector)
                    if element and await element.is_visible():
                        print(f"  Daily limit detected on current account")
                        return True
                except:
                    continue
            return False
        except:
            return False
    
    async def _switch_google_account(self) -> bool:
        """Switch to a different Google account via the profile menu.
        
        Clicks the profile avatar in top-right, then selects the next
        available account from the dropdown.
        """
        try:
            # Find the profile avatar button (top-right corner)
            avatar_selectors = [
                'a[aria-label*="Google Account"]',
                'a[aria-label*="Account"]',
                'a[data-ogsr-up]',
                'div[role="button"][aria-label*="Account"]',
                'img[data-ogsr-up]',  # profile image
            ]
            
            avatar = None
            for selector in avatar_selectors:
                try:
                    avatar = await self.page.wait_for_selector(selector, timeout=5000)
                    if avatar:
                        break
                except:
                    continue
            
            if not avatar:
                raise Exception("Could not find profile avatar")
            
            await avatar.click()
            await self.page.wait_for_timeout(1500)
            
            # Now look for the account list in the dropdown
            # Each account is typically an <a> or clickable div with the email visible
            # Try to find accounts that are NOT the current one
            all_account_links = await self.page.query_selector_all(
                '[data-identifier], [data-email], [role="link"][data-navrole]'
            )
            
            # Also try finding by visible email text
            if not all_account_links:
                all_account_links = await self.page.query_selector_all('ul[role="list"] a, .gb_A .gb_D')
            
            switched = False
            for link in all_account_links:
                try:
                    # Check if this is a different account
                    email = (await link.get_attribute("data-identifier") or 
                             await link.get_attribute("data-email") or "")
                    
                    # Skip if this is the current account or empty
                    current_email = self.available_accounts[self.current_account_index] if self.available_accounts else ""
                    if email and email == current_email:
                        continue
                    if email and email == "default_account":
                        continue
                    
                    # Click this different account
                    print(f"  Switching to Google account: {email}")
                    await link.click()
                    await self.page.wait_for_timeout(3000)
                    
                    # Update current account tracking
                    if email and email not in self.available_accounts:
                        self.available_accounts.append(email)
                        self.account_usage[email] = {"generated": 0, "last_used": None}
                    if email:
                        self.current_account_index = self.available_accounts.index(email) if email in self.available_accounts else 0
                    
                    switched = True
                    break
                except:
                    continue
            
            if not switched:
                # Fallback: try clicking any non-first account link
                try:
                    all_links = await self.page.query_selector_all('a[href*="accounts.google.com"]')
                    for link in all_links:
                        text = await link.inner_text()
                        if text and text != self.available_accounts[0] if self.available_accounts else True:
                            print(f"  Switching to account via fallback: {text}")
                            await link.click()
                            await self.page.wait_for_timeout(3000)
                            switched = True
                            break
                except:
                    pass
            
            return switched
            
        except Exception as e:
            print(f"  Warning: Failed to switch account: {e}")
            return False
    
    async def _navigate_to_ai_mode(self):
        """Navigate to Chrome AI mode for image generation."""
        try:
            # Ensure browser and page are active
            await self._ensure_browser_open()
            
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
            # <textarea placeholder="Describe your image" aria-label="Search" role="combobox" name="q">
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
            
            # Enter prompt and press Enter to submit immediately
            await prompt_input.fill(prompt_text)
            await prompt_input.press("Enter")
            print(f"  Submitted prompt: {prompt_text[:50]}...")
            
            return True
            
        except Exception as e:
            raise Exception(f"Failed to submit prompt: {e}")
    
    async def _wait_for_image_generation(self, previous_count: int = 0, timeout: int = 60) -> bool:
        """Wait for a new image generation to complete.
        
        Args:
            previous_count: number of matching images before prompt submission.
                            Waits for count to exceed this value.
        """
        try:
            js_count = """
                () => {
                    for (const sel of [
                        'img[alt="AI generated image"][data-processed="true"]',
                        'img[alt="AI generated image"]',
                        'img[data-processed="true"]',
                    ]) {
                        const els = document.querySelectorAll(sel);
                        if (els.length > 0) return els.length;
                    }
                    return 0;
                }
            """
            
            start_time = time.time()
            while time.time() - start_time < timeout:
                try:
                    count = await self.page.evaluate(js_count)
                    if count > previous_count:
                        print(f"  Image generated successfully ({count} total)")
                        return True
                except:
                    pass
                await self.page.wait_for_timeout(2000)
            
            raise Exception("Timeout waiting for image generation")
            
        except Exception as e:
            raise Exception(f"Failed to wait for image generation: {e}")
    
    async def _ensure_browser_open(self):
        """Ensure browser context and page are active; re-launch if closed/crashed."""
        is_closed = True
        try:
            if self.context and self.page and not self.page.is_closed():
                is_closed = False
        except Exception:
            is_closed = True
            
        if is_closed:
            print("  Browser context closed or crashed. Re-initializing Chrome persistent context...")
            try:
                if self.page:
                    await self.page.close()
            except Exception:
                pass
            try:
                if self.context:
                    await self.context.close()
            except Exception:
                pass
                
            if not self.playwright:
                from playwright.async_api import async_playwright
                self.playwright = await async_playwright().start()
                
            self.browser = await self.playwright.chromium.launch_persistent_context(
                user_data_dir=self.profile_path,
                headless=self.headless,
                channel="chrome",
                args=[
                    "--no-sandbox",
                    "--disable-blink-features=AutomationControlled",
                ],
                viewport={"width": 1920, "height": 1080},
            )
            self.context = self.browser
            self.page = await self.context.new_page()

    def _is_page_alive(self) -> bool:
        """Check if the page is still connected and not closed."""
        try:
            return self.page is not None and not self.page.is_closed()
        except Exception:
            return False

    def _make_response_handler(self):
        """Return an async response handler that captures raw image bytes from CDN responses.
        
        Playwright intercepts responses at the network level — auth cookies are sent
        automatically, so this bypasses all CORS/JS-fetch restrictions.
        """
        async def _on_response(response):
            url = response.url
            # Match Google AI image CDN hosts
            is_image_cdn = (
                "googleusercontent.com" in url
                or "aisandbox-pa.googleapis.com" in url
                or "generativelanguage.googleapis.com" in url
            )
            if not is_image_cdn:
                return
            try:
                content_type = response.headers.get("content-type", "")
                status = response.status
                # Log ALL responses from CDN domains (not just images) for debugging
                print(f"    [net] CDN response: status={status} content-type={content_type} url={url[:100]}...")
                if "image" not in content_type and "octet" not in content_type:
                    return
                body = await response.body()
                print(f"    [net] CDN body size: {len(body) // 1024} KB")
                if body and len(body) > 50_000:  # only keep substantial images (>50 KB)
                    if self._last_captured_image_bytes is None or len(body) > len(self._last_captured_image_bytes):
                        self._last_captured_image_bytes = body
                        print(f"    [intercept] Captured CDN image: {len(body) // 1024} KB  ({url[:80]}...)")
            except Exception:
                pass
        return _on_response

    async def _extract_image_from_dom(self, output_path: Path, new_image_index: int = -1) -> bool:
        """Save the generated image to output_path.

        Args:
            output_path: Path to save the extracted image
            new_image_index: Index of the newly generated image to select

        Priority order:
          1. Network-intercepted bytes (highest quality, full CDN resolution)
          2. JS fetch with upgraded CDN URL (=s0 / =s2048)
          3. Element screenshot fallback
        """
        try:
            await self._ensure_browser_open()

            # ── Path 1: Network intercept ─────────────────────────────────────
            if self._last_captured_image_bytes and len(self._last_captured_image_bytes) > 50_000:
                output_path.parent.mkdir(parents=True, exist_ok=True)
                output_path.write_bytes(self._last_captured_image_bytes)
                size_kb = len(self._last_captured_image_bytes) / 1024
                size_mb = size_kb / 1024
                print(f"  Saved intercepted image ({size_mb:.2f} MB) to: {output_path.name}")
                self._last_captured_image_bytes = None  # consume
                return True

            # ── Path 2: JS fetch with upgraded CDN URL ────────────────────────
            # Retry once if page/context dies mid-operation
            for _attempt in range(2):
                if not self._is_page_alive():
                    print("  Page closed before DOM extraction, re-initializing...")
                    await self._ensure_browser_open()

                try:
                    return await self._extract_image_via_dom(output_path, new_image_index)
                except Exception as e:
                    err_str = str(e)
                    if "Target page" in err_str or "context or browser has been closed" in err_str:
                        print(f"  Page closed during DOM extraction, retrying... ({err_str})")
                        await self._ensure_browser_open()
                        continue
                    raise

            print("  DOM extraction failed after retry")
            return False

        except Exception as e:
            print(f"  DOM extraction failed: {e}")
            return False

    @staticmethod
    def _upgrade_cdn_url(url: str) -> list:
        """Build a list of CDN URL variants to try, from highest to lowest resolution.
        
        Google image CDN uses trailing params like =s0 (original), =s2048, =w1024, etc.
        We try the full-res variant first, then progressively smaller ones.
        """
        import re
        variants = []
        # Strip any existing size param and try =s0 (original/full resolution)
        no_size = re.sub(r'=[sw]\d+.*$', '', url)
        if no_size != url:
            variants.append(no_size + '=s0')
        # Try =s2048 (large but not necessarily original)
        variants.append(no_size + '=s2048')
        # Try =w2048 (width-based, some CDN endpoints use this)
        variants.append(no_size + '=w2048')
        # Raw URL as-is (might already be full-res)
        variants.append(url)
        return variants

    async def _extract_image_via_dom(self, output_path: Path, new_image_index: int = -1) -> bool:
        """Inner DOM extraction: find image element, JS-fetch, or screenshot.
        
        Args:
            output_path: Path to save the extracted image
            new_image_index: Index of the newly generated image in the list of images.
                           If -1 (default), selects the last image (old behavior).
                           If provided, selects the specific image at that index.
        
        Raises on page-closure so the caller can retry with a fresh page.
        """
        import base64

        img_selectors = [
            'img[alt="AI generated image"][data-processed="true"]',
            'img[alt="AI generated image"]',
            'img[data-processed="true"]',
            'img[src*="googleusercontent"]',
            'img[src*="data:image"]',
        ]
        img_element = None
        for selector in img_selectors:
            try:
                elements = await self.page.query_selector_all(selector)
                if elements:
                    # Select the specific image if index is provided, otherwise last one
                    if new_image_index >= 0 and new_image_index < len(elements):
                        img_element = elements[new_image_index]
                        print(f"  Selecting image at index {new_image_index} of {len(elements)} total images")
                    else:
                        img_element = elements[-1]
                        print(f"  Selecting last image (index {len(elements)-1}) of {len(elements)} total images")
                    break
            except Exception as e:
                if "Target page" in str(e) or "context or browser has been closed" in str(e):
                    raise
                continue

        btn_selectors = [
            'button[aria-label="Download this AI generated image"][data-processed="true"]',
            'button[aria-label="Download this AI generated image"]',
            'button[title="Download image"]',
            'a[title="Download image"]',
        ]
        btn_element = None
        for selector in btn_selectors:
            try:
                elements = await self.page.query_selector_all(selector)
                if elements:
                    btn_element = elements[-1]
                    break
            except Exception as e:
                if "Target page" in str(e) or "context or browser has been closed" in str(e):
                    raise
                continue

        if not self._is_page_alive():
            raise Exception("Page closed during element search")

        # ── Debug: comprehensive DOM scan for full-res image source ────────
        if img_element:
            try:
                dom_debug = await self.page.evaluate("""
                    (img) => {
                        const results = {};
                        // 1. All attributes on the AI generated image element
                        results.img_attrs = {};
                        for (const attr of img.attributes) {
                            const val = attr.value;
                            results.img_attrs[attr.name] = val.length > 200 ? val.slice(0, 200) + '...' : val;
                        }
                        // 2. naturalWidth/naturalHeight — tells us the intrinsic size
                        results.natural_width = img.naturalWidth;
                        results.natural_height = img.naturalHeight;
                        results.display_width = img.clientWidth;
                        results.display_height = img.clientHeight;
                        // 3. ALL img elements on page with their src
                        const allImgs = document.querySelectorAll('img');
                        results.all_imgs = [];
                        for (const i of allImgs) {
                            const src = i.currentSrc || i.src || '';
                            results.all_imgs.push({
                                srcLen: src.length,
                                srcPreview: src.slice(0, 120),
                                natural: i.naturalWidth + 'x' + i.naturalHeight,
                                display: i.clientWidth + 'x' + i.clientHeight,
                            });
                            results.all_imgs.push({
                                src: src.slice(0, 200),
                                alt: (i.alt || '').slice(0, 50),
                                w: i.naturalWidth, h: i.naturalHeight,
                                classes: (i.className || '').slice(0, 50),
                            });
                        }
                        // 4. Canvas elements (might render full-res)
                        const canvases = document.querySelectorAll('canvas');
                        results.canvases = [];
                        for (const c of canvases) {
                            if (c.width > 100 && c.height > 100) {
                                results.canvases.push({w: c.width, h: c.height, id: c.id, classes: (c.className || '').slice(0, 50)});
                            }
                        }
                        // 5. Picture/source elements
                        const sources = document.querySelectorAll('picture source, video source');
                        results.sources = [];
                        for (const s of sources) {
                            const srcset = s.srcset || '';
                            if (srcset && !srcset.startsWith('data:')) {
                                results.sources.push({srcset: srcset.slice(0, 200), type: s.type || ''});
                            }
                        }
                        // 6. Blob/object URLs anywhere in the DOM
                        const allEls = document.querySelectorAll('*');
                        results.blob_urls = [];
                        for (const el of allEls) {
                            for (const attr of el.attributes) {
                                if (attr.value && attr.value.startsWith('blob:')) {
                                    results.blob_urls.push({tag: el.tagName, attr: attr.name, url: attr.value.slice(0, 200)});
                                }
                            }
                        }
                        // 7. Download button and its full outerHTML
                        const dlBtn = document.querySelector('button[aria-label*="Download"], button[title*="ownload"], a[title*="ownload"]');
                        if (dlBtn) {
                            results.download_btn = {
                                tag: dlBtn.tagName,
                                outerHTML: dlBtn.outerHTML.slice(0, 500),
                                onclick: dlBtn.onclick ? dlBtn.onclick.toString().slice(0, 200) : null,
                            };
                        }
                        return results;
                    }
                """, img_element)
                print(f"  [dom-debug] img natural size: {dom_debug.get('natural_width')}x{dom_debug.get('natural_height')}  display: {dom_debug.get('display_width')}x{dom_debug.get('display_height')}")
                print(f"  [dom-debug] img attrs: {dom_debug.get('img_attrs', {})}")
                all_imgs = dom_debug.get('all_imgs', [])
                if all_imgs:
                    print(f"  [dom-debug] non-data img elements ({len(all_imgs)}):")
                    for ai in all_imgs:
                        print(f"    {ai}")
                canvases = dom_debug.get('canvases', [])
                if canvases:
                    print(f"  [dom-debug] canvases: {canvases}")
                sources = dom_debug.get('sources', [])
                if sources:
                    print(f"  [dom-debug] picture/source: {sources}")
                blobs = dom_debug.get('blob_urls', [])
                if blobs:
                    print(f"  [dom-debug] blob URLs: {blobs}")
                dl_btn = dom_debug.get('download_btn')
                if dl_btn:
                    print(f"  [dom-debug] download button: {dl_btn}")
            except Exception as e:
                print(f"  [dom-debug] scan failed: {e}")

        # ── Path 2a: JS fetch with CDN URL upgrade ────────────────────────
        if img_element or btn_element:
            result = await self.page.evaluate("""
                async ([img, btn, imgIndex]) => {
                    // Fallback: if img handle is stale, re-query by selector
                    if (!img || !img.src) {
                        img = document.querySelector('img[src^="data:image/"]') ||
                              document.querySelector('. catalogue-generated-image img, [class*="generated"] img, [data-generative] img') ||
                              document.querySelector('img');
                        console.log('[img-extract] fallback querySelector found:', !!img, img ? (img.src || '').slice(0, 100) : 'none');
                    }
                    let candidateUrls = [];
                    if (btn) {
                        for (const attr of ['href', 'data-url', 'data-download-url', 'data-src', 'src']) {
                            const val = btn.getAttribute ? btn.getAttribute(attr) : null;
                            if (val) candidateUrls.push({src: attr, url: val, len: val.length});
                        }
                    }
                    if (img) {
                        // Log each attribute separately to diagnose truncation
                        const imgSrc = img.src || '';
                        const imgCurrentSrc = img.currentSrc || '';
                        const imgSrcAttr = (img.getAttribute ? img.getAttribute('src') : '') || '';
                        console.log('[img-extract] img.src length:', imgSrc.length, 'starts:', imgSrc.slice(0, 120));
                        console.log('[img-extract] img.currentSrc length:', imgCurrentSrc.length, 'starts:', imgCurrentSrc.slice(0, 120));
                        console.log('[img-extract] img.getAttribute(src) length:', imgSrcAttr.length, 'starts:', imgSrcAttr.slice(0, 120));

                        for (const [label, val] of [['currentSrc', imgCurrentSrc], ['src', imgSrc], ['getAttribute-src', imgSrcAttr], ['srcset', img.srcset || ''], ['data-src', img.getAttribute ? (img.getAttribute('data-src') || '') : ''], ['data-url', img.getAttribute ? (img.getAttribute('data-url') || '') : '']]) {
                            if (val && val.length > 10) candidateUrls.push({src: label, url: val, len: val.length});
                        }
                    }

                    // CRITICAL: The full-res Google-hosted image lives in hidden
                    // 'lens.usercontent.google.com/banana' elements (classes fRm5F),
                    // separate from the thumbnail data URLs. There is one banana
                    // element per generated image, in DOM order matching the
                    // thumbnail index. Use imgIndex to select THIS scene's image
                    // (not the first one!), falling back to the latest.
                    let bananaUrls = [];
                    const bananaImgs = Array.from(document.querySelectorAll('img[src*="lens.usercontent.google.com/banana"], img.fRm5F'));
                    if (bananaImgs.length > 0) {
                        let bananaImg = null;
                        if (imgIndex !== undefined && imgIndex !== null && imgIndex >= 0 && imgIndex < bananaImgs.length) {
                            bananaImg = bananaImgs[imgIndex];
                            console.log('[img-extract] selected banana element at index', imgIndex, 'of', bananaImgs.length);
                        } else {
                            bananaImg = bananaImgs[bananaImgs.length - 1];
                            console.log('[img-extract] selected last banana element (index', bananaImgs.length - 1, ') of', bananaImgs.length);
                        }
                        const bSrc = bananaImg.getAttribute('src') || '';
                        console.log('[img-extract] found banana URL element, src length:', bSrc.length, 'preview:', bSrc.slice(0, 80));
                        bananaUrls.push({src: 'banana', url: bSrc, len: bSrc.length});
                        const bSrcset = bananaImg.getAttribute('srcset') || '';
                        if (bSrcset) {
                            console.log('[img-extract] banana srcset:', bSrcset.slice(0, 200));
                            for (const part of bSrcset.split(',')) {
                                const u = part.trim().split(/\\s+/)[0];
                                if (u) bananaUrls.push({src: 'banana-srcset', url: u, len: u.length});
                            }
                        }
                    }

                    // Build upgrade variants ONLY from non-data URLs first (banana + any CDN)
                    let upgradedUrls = [];
                    let dataUrlFallback = null;
                    for (let item of bananaUrls.concat(candidateUrls)) {
                        let u = item.url;
                        if (!u) continue;
                        // Defer data URLs: try real CDN (banana) fetch first for full resolution
                        if (u.startsWith('data:image/')) {
                            if (!dataUrlFallback) dataUrlFallback = {ok: true, data: u, src: item.src, srcLen: item.len, decodedLen: Math.round(item.len * 0.75)};
                            continue;
                        }
                        // Strip existing size param and try full-res first
                        let base = u.replace(/=[sw]\\d+.*$/, '');
                        if (base !== u) {
                            upgradedUrls.push({url: base + '=s0', label: item.src + ':s0'});
                        }
                        upgradedUrls.push({url: base + '=s2048', label: item.src + ':s2048'});
                        upgradedUrls.push({url: base + '=w2048', label: item.src + ':w2048'});
                        upgradedUrls.push({url: u, label: item.src + ':raw'});
                    }

                    let lastError = null;
                    let bestResult = null;
                    for (const target of upgradedUrls) {
                        try {
                            const response = await fetch(target.url, {credentials: 'include'});
                            if (response.ok) {
                                const blob = await response.blob();
                                console.log('[img-extract] fetch', target.label, 'size:', blob.size, 'type:', blob.type);
                                if (blob && blob.size > 20000) {
                                    if (!bestResult || blob.size > bestResult.size) {
                                        const dataUrl = await new Promise((resolve) => {
                                            const reader = new FileReader();
                                            reader.onloadend = () => resolve(reader.result);
                                            reader.readAsDataURL(blob);
                                        });
                                        bestResult = {ok: true, data: dataUrl, debug: target.label + ':' + target.url.slice(0, 80), size: blob.size};
                                    }
                                    if (blob.size > 200_000) break;
                                } else {
                                    lastError = 'blob too small: ' + (blob ? blob.size : 0) + ' label=' + target.label;
                                }
                            } else {
                                lastError = 'http ' + response.status + ' label=' + target.label + ' url=' + target.url.slice(0,60);
                            }
                        } catch (e) {
                            lastError = 'fetch error: ' + e.message + ' label=' + target.label;
                        }
                    }
                    if (bestResult) return bestResult;
                    // Fall back to the deferred data URL (thumbnail) if no CDN fetch worked
                    if (dataUrlFallback) return dataUrlFallback;
                    return {ok: false, debug: lastError, candidateCount: candidateUrls.length + bananaUrls.length, candidates: bananaUrls.concat(candidateUrls).map(c => ({src: c.src, len: c.len, preview: c.url.slice(0, 100)}))};
                }
            """, [img_element, btn_element, new_image_index])

            if result and result.get("ok") and result.get("data"):
                data_url = result["data"]
                print(f"  [img-extract] got data from: {result.get('debug', 'data-url-fallback')} | src attr: {result.get('src', '?')} | src attr len: {result.get('srcLen', '?')} | estimated decoded: {result.get('decodedLen', '?')} bytes")
                if "," in data_url:
                    _, b64 = data_url.split(",", 1)
                    print(f"  [img-extract] base64 string length: {len(b64)} chars")
                    image_bytes = base64.b64decode(b64)
                    print(f"  [img-extract] decoded image bytes: {len(image_bytes)} ({len(image_bytes) / (1024*1024):.2f} MB)")
                    if len(image_bytes) > 1000:
                        output_path.parent.mkdir(parents=True, exist_ok=True)
                        output_path.write_bytes(image_bytes)
                        print(f"  Saved image ({len(image_bytes) / (1024 * 1024):.2f} MB) via: {result.get('debug', '?')}")
                        return True
            else:
                print(f"  JS fetch failed: {result.get('debug', 'unknown')}")
                if result and result.get("candidates"):
                    for c in result["candidates"]:
                        print(f"    candidate: src={c.get('src')} len={c.get('len')} preview={c.get('preview', '')[:100]}")

        # ── Path 2b: Python requests with browser cookies (bypasses in-page JS) ──
        if img_element:
            cdn_url = await self._get_element_cdn_url(img_element)
            if cdn_url:
                success = await self._fetch_image_via_python(cdn_url, output_path)
                if success:
                    return True

        # ── Path 3: Element screenshot (lowest quality, last resort) ──────
        if img_element:
            if not self._is_page_alive():
                raise Exception("Page closed before screenshot")
            output_path.parent.mkdir(parents=True, exist_ok=True)
            await img_element.screenshot(path=str(output_path))
            size_kb = output_path.stat().st_size / 1024
            print(f"  Saved element screenshot ({size_kb:.0f} KB, low-res) to: {output_path.name}")
            return True

        print("  Could not find generated image element in DOM")
        return False

    async def _get_element_cdn_url(self, img_element) -> str:
        """Extract the CDN image URL from an img element's attributes."""
        try:
            url = await img_element.get_attribute("currentSrc")
            if url and "data:" not in url:
                return url
            url = await img_element.get_attribute("src")
            if url and "data:" not in url:
                return url
        except Exception:
            pass
        return None

    async def _fetch_image_via_python(self, cdn_url: str, output_path: Path) -> bool:
        """Fetch image via Python requests using browser cookies for auth.
        
        This bypasses in-page JS entirely — useful when page is unstable
        or JS fetch hits CORS restrictions.
        """
        import requests as py_requests

        try:
            # Get cookies from Playwright browser context
            cookies = {}
            try:
                for c in await self.context.cookies():
                    if "google" in c.get("domain", ""):
                        cookies[c["name"]] = c["value"]
            except Exception:
                pass

            for url_variant in self._upgrade_cdn_url(cdn_url):
                try:
                    resp = py_requests.get(url_variant, cookies=cookies, timeout=30)
                    if resp.status_code == 200 and len(resp.content) > 50_000:
                        output_path.parent.mkdir(parents=True, exist_ok=True)
                        output_path.write_bytes(resp.content)
                        size_mb = len(resp.content) / (1024 * 1024)
                        print(f"  Saved Python-fetched image ({size_mb:.2f} MB) via: {url_variant[:80]}")
                        return True
                except Exception:
                    continue

        except ImportError:
            print("  requests library not available for Python fallback")
        except Exception as e:
            print(f"  Python fetch failed: {e}")

        return False

    async def _download_image(self, output_path: Path, new_image_index: int = -1) -> bool:
        """Save generated image to output_path.

        Args:
            output_path: Path to save the extracted image
            new_image_index: Index of the newly generated image to select

        Priority:
          1. Network-intercepted bytes — captured by the response handler when Google AI
             loads the generated image into the page. No button click required; the CDN
             request fires automatically during generation.
          2. DOM extraction — JS fetch with CDN URL upgrade (=s0), then element screenshot.
        """
        # ── Step 1: Use bytes already captured by the network interceptor ────
        if self._last_captured_image_bytes and len(self._last_captured_image_bytes) > 50_000:
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_bytes(self._last_captured_image_bytes)
            size_mb = len(self._last_captured_image_bytes) / (1024 * 1024)
            print(f"  Saved intercepted image ({size_mb:.2f} MB) to: {output_path.name}")
            self._last_captured_image_bytes = None
            return True

        # ── Step 2: DOM extraction fallback ──────────────────────────────────
        # Highest-value fallback: the hidden `fRm5F` element's
        # `lens.usercontent.google.com/banana` URL serves the FULL-RES image.
        print("  Trying DOM extraction (banana CDN fetch for full res)...")
        success = await self._extract_image_from_dom(output_path, new_image_index)
        if success:
            return True

        # ── Step 3: Trigger the download button and capture the file ─────────
        # Google loads the thumbnail as a data URL but may save the FULL-RES file
        # via the download button (class oZWMff, title="Download image"). The
        # button is sometimes `disabled` — remove that and click it, then capture
        # the resulting browser download. Short timeout since it often does not
        # produce a real browser download event.
        try:
            await self._ensure_browser_open()
            dl_clicked = await self.page.evaluate("""
                () => {
                    const btn = document.querySelector('button[aria-label="Download this AI generated image"], button[title="Download image"], button.oZWMff');
                    if (!btn) return {clicked: false, reason: 'no button'};
                    // Remove disabled so the click is allowed
                    if (btn.disabled) { btn.disabled = false; }
                    btn.removeAttribute('disabled');
                    // Trigger the click
                    btn.click();
                    return {clicked: true, disabledWas: null};
                }
            """)
            if dl_clicked and dl_clicked.get("clicked"):
                print("  [download] dispatch click on download button, capturing download...")
                async with self.page.expect_download(timeout=3000) as dl_info:
                    # Re-dispatch in case the first JS .click() didn't trigger a download
                    await self.page.evaluate("""
                        () => {
                            const btn = document.querySelector('button[aria-label="Download this AI generated image"], button[title="Download image"], button.oZWMff');
                            if (btn) btn.click();
                        }
                    """)
                try:
                    download = await dl_info.value
                    path = await download.path()
                    if path:
                        output_path.parent.mkdir(parents=True, exist_ok=True)
                        import shutil
                        shutil.copy(path, output_path)
                        size_mb = output_path.stat().st_size / (1024 * 1024)
                        print(f"  Saved download-button image ({size_mb:.2f} MB) to: {output_path.name}")
                        return True
                except Exception as e:
                    print(f"  [download] expect_download failed: {e}")
        except Exception as e:
            print(f"  [download] path failed: {e}")

        print("  DOM extraction produced no usable image.")

        # ── Step 4: Last-resort retry — re-initialize browser and try once ──
        if not self._is_page_alive():
            print("  Page dead after DOM extraction, re-initializing and retrying...")
            await self._ensure_browser_open()
            # Re-attach response handler on fresh page
            try:
                _handler = self._make_response_handler()
                self.page.on("response", _handler)
                success = await self._extract_image_from_dom(output_path)
                try:
                    self.page.remove_listener("response", _handler)
                except Exception:
                    pass
                if success:
                    return True
            except Exception:
                pass

        raise Exception("Failed to download image: interceptor captured nothing and DOM extraction failed")

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

        # Reset intercept buffer and attach CDN response handler
        self._last_captured_image_bytes = None
        _response_handler = self._make_response_handler()
        self.page.on("response", _response_handler)

        print(f"\nGenerating {len(scenes)} scene images via Chrome AI...")

        # Navigate to AI mode once before starting
        await self._navigate_to_ai_mode()
        
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
            
            # Try generation with retries
            success = False
            needs_navigate = False  # track if we need to re-navigate
            for attempt in range(CHROME_AI_MAX_RETRIES * len(self.available_accounts)):
                try:
                    await self._ensure_browser_open()
                    print(f"  [{i}/{len(scenes)}] Generating {output_path.name} (attempt {attempt + 1}, account {self.available_accounts[self.current_account_index]})")
                    
                    # Only re-navigate if needed (first scene, after error, or after account switch)
                    if needs_navigate:
                        await self._navigate_to_ai_mode()
                        needs_navigate = False
                    
                    # Check for daily limit on current account
                    if await self._check_daily_limit():
                        print(f"    Daily limit on account {self.available_accounts[self.current_account_index]}, switching...")
                        switched = await self._switch_google_account()
                        if not switched:
                            raise Exception("Daily limit reached and no other accounts available")
                        await self._navigate_to_ai_mode()
                    
                    # Count existing images before submitting new prompt
                    previous_image_count = await self.page.evaluate("""
                        () => {
                            for (const sel of [
                                'img[alt="AI generated image"][data-processed="true"]',
                                'img[alt="AI generated image"]',
                                'img[data-processed="true"]',
                            ]) {
                                const els = document.querySelectorAll(sel);
                                if (els.length > 0) return els.length;
                            }
                            return 0;
                        }
                    """)
                    
                    # Clear any stale intercept from the previous scene, then submit prompt
                    self._last_captured_image_bytes = None
                    await self._submit_prompt(visual_prompt)
                    
                    # Check again after prompt submission (limit may show up then)
                    if await self._check_daily_limit():
                        print(f"    Daily limit after prompt submission, switching...")
                        switched = await self._switch_google_account()
                        if not switched:
                            raise Exception("Daily limit reached and no other accounts available")
                        await self._navigate_to_ai_mode()
                        previous_image_count = 0  # reset after re-navigate
                        await self._submit_prompt(visual_prompt)
                    
                    # Wait for generation — expects count to exceed previous
                    await self._wait_for_image_generation(previous_count=previous_image_count)
                    
                    # Get current image count to identify which one is new
                    current_image_count = await self.page.evaluate("""
                        () => {
                            for (const sel of [
                                'img[alt="AI generated image"][data-processed="true"]',
                                'img[alt="AI generated image"]',
                                'img[data-processed="true"]',
                            ]) {
                                const els = document.querySelectorAll(sel);
                                if (els.length > 0) return els.length;
                            }
                            return 0;
                        }
                    """)
                    
                    # The new image should be at the index of the previous count
                    new_image_index = previous_image_count if current_image_count > previous_image_count else -1
                    print(f"  Image count before: {previous_image_count}, after: {current_image_count}, new image index: {new_image_index}")
                    
                    # Extract generated image (intercept → JS fetch → Python requests → screenshot)
                    await self._download_image(output_path, new_image_index)
                    
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
                    needs_navigate = True  # re-navigate on next attempt
                    if attempt < CHROME_AI_MAX_RETRIES * len(self.available_accounts) - 1:
                        await asyncio.sleep(3)
            
            if not success:
                print(f"  [{i}/{len(scenes)}] Failed to generate {output_path.name}")
                failed += 1
                missing.append(image_filename)
        
        # Detach response listener and clear intercept buffer
        try:
            self.page.remove_listener("response", _response_handler)
        except Exception:
            pass
        self._last_captured_image_bytes = None

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
