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
                if "image" not in content_type and "octet" not in content_type:
                    return
                body = await response.body()
                if body and len(body) > 50_000:  # only keep substantial images (>50 KB)
                    if self._last_captured_image_bytes is None or len(body) > len(self._last_captured_image_bytes):
                        self._last_captured_image_bytes = body
                        print(f"    [intercept] Captured CDN image: {len(body) // 1024} KB  ({url[:80]}...)")
            except Exception:
                pass
        return _on_response

    async def _extract_image_from_dom(self, output_path: Path) -> bool:
        """Save the generated image to output_path.

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
                    return await self._extract_image_via_dom(output_path)
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

    async def _extract_image_via_dom(self, output_path: Path) -> bool:
        """Inner DOM extraction: find image element, JS-fetch, or screenshot.
        
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
                    img_element = elements[-1]
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

        # ── Path 2a: JS fetch with CDN URL upgrade ────────────────────────
        if img_element or btn_element:
            result = await self.page.evaluate("""
                async ([img, btn]) => {
                    let candidateUrls = [];
                    if (btn) {
                        for (const attr of ['href', 'data-url', 'data-download-url', 'data-src', 'src']) {
                            const val = btn.getAttribute ? btn.getAttribute(attr) : null;
                            if (val) candidateUrls.push(val);
                        }
                    }
                    if (img) {
                        for (const attr of ['currentSrc', 'src', 'srcset', 'data-src', 'data-url']) {
                            const val = img[attr] || (img.getAttribute ? img.getAttribute(attr) : null);
                            if (val) candidateUrls.push(val);
                        }
                    }

                    let upgradedUrls = [];
                    for (let u of candidateUrls) {
                        if (!u) continue;
                        if (u.startsWith('data:image/')) return {ok: true, data: u, debug: 'data-url'};
                        // Strip existing size param and try full-res first
                        let base = u.replace(/=[sw]\\d+.*$/, '');
                        if (base !== u) {
                            upgradedUrls.push(base + '=s0');      // original resolution
                        }
                        upgradedUrls.push(base + '=s2048');       // large fallback
                        upgradedUrls.push(base + '=w2048');       // width-based fallback
                        upgradedUrls.push(u);                     // raw URL as-is
                    }

                    let lastError = null;
                    let bestResult = null;
                    for (const targetUrl of upgradedUrls) {
                        try {
                            const response = await fetch(targetUrl, {credentials: 'include'});
                            if (response.ok) {
                                const blob = await response.blob();
                                if (blob && blob.size > 20000) {
                                    // Keep the largest successful fetch
                                    if (!bestResult || blob.size > bestResult.size) {
                                        const dataUrl = await new Promise((resolve) => {
                                            const reader = new FileReader();
                                            reader.onloadend = () => resolve(reader.result);
                                            reader.readAsDataURL(blob);
                                        });
                                        bestResult = {ok: true, data: dataUrl, debug: targetUrl.slice(0, 80), size: blob.size};
                                    }
                                    // If we got something > 200KB, it's likely full-res — stop early
                                    if (blob.size > 200_000) break;
                                } else {
                                    lastError = 'blob too small: ' + (blob ? blob.size : 0) + ' url=' + targetUrl.slice(0,60);
                                }
                            } else {
                                lastError = 'http ' + response.status + ' url=' + targetUrl.slice(0,60);
                            }
                        } catch (e) {
                            lastError = 'fetch error: ' + e.message + ' url=' + targetUrl.slice(0,60);
                        }
                    }
                    if (bestResult) return bestResult;
                    return {ok: false, debug: lastError, urls: upgradedUrls.slice(0, 3)};
                }
            """, [img_element, btn_element])

            if result and result.get("ok") and result.get("data"):
                data_url = result["data"]
                if "," in data_url:
                    _, b64 = data_url.split(",", 1)
                    image_bytes = base64.b64decode(b64)
                    if len(image_bytes) > 1000:
                        output_path.parent.mkdir(parents=True, exist_ok=True)
                        output_path.write_bytes(image_bytes)
                        size_mb = len(image_bytes) / (1024 * 1024)
                        print(f"  Saved JS-fetched image ({size_mb:.2f} MB) via: {result.get('debug', '?')}")
                        return True
            else:
                print(f"  JS fetch failed: {result.get('debug', 'unknown')} | tried urls: {result.get('urls', [])}")

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

    async def _download_image(self, output_path: Path) -> bool:
        """Save generated image to output_path.

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
        print("  No intercepted bytes yet, attempting DOM extraction...")
        success = await self._extract_image_from_dom(output_path)
        if success:
            return True

        # ── Step 3: Last-resort retry — re-initialize browser and try once ──
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
                    
                    # Extract generated image (intercept → JS fetch → Python requests → screenshot)
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
