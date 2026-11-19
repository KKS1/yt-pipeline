"""
test_chrome_ai_scraper.py
─────────────────────────
Unit tests for Chrome AI scraper fallback image extraction logic.
"""

import unittest
import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from scripts.chrome_ai_scraper import ChromeAIGenerator


class ChromeAIScraperTests(unittest.IsolatedAsyncioTestCase):

    async def test_extract_image_from_dom_base64_fallback(self):
        """Test _extract_image_from_dom with base64 data URL from browser JS-fetch path."""
        generator = ChromeAIGenerator()

        mock_page = AsyncMock()
        mock_page.is_closed = MagicMock(return_value=False)
        mock_element = AsyncMock()

        generator.page = mock_page
        generator.context = MagicMock()

        mock_page.query_selector_all.return_value = [mock_element]

        # Simulate JS evaluate returning {ok: True, data: "data:image/png;base64,..."}
        fake_data_url = "data:image/png;base64," + ("A" * 1500)
        mock_page.evaluate.return_value = {"ok": True, "data": fake_data_url, "debug": "test"}

        output_file = Path("/tmp/test_chrome_ai_dom.png")
        try:
            success = await generator._extract_image_from_dom(output_file)
            self.assertTrue(success)
            self.assertTrue(output_file.exists())
            self.assertGreater(len(output_file.read_bytes()), 1000)
        finally:
            if output_file.exists():
                output_file.unlink()

    async def test_extract_image_from_dom_screenshot_fallback(self):
        """Test _extract_image_from_dom falling back to element screenshot when JS fetch fails."""
        generator = ChromeAIGenerator()

        mock_page = AsyncMock()
        mock_page.is_closed = MagicMock(return_value=False)
        mock_element = AsyncMock()

        generator.page = mock_page
        generator.context = MagicMock()

        mock_page.query_selector_all.return_value = [mock_element]
        # Simulate JS evaluate returning {ok: False} so we fall through to screenshot
        mock_page.evaluate.return_value = {"ok": False, "debug": "http 403"}

        output_file = Path("/tmp/test_chrome_ai_screenshot.png")

        async def fake_screenshot(path):
            Path(path).write_bytes(b"PNG_FAKE_SCREENSHOT_DATA")

        mock_element.screenshot.side_effect = fake_screenshot

        try:
            success = await generator._extract_image_from_dom(output_file)
            self.assertTrue(success)
            self.assertTrue(output_file.exists())
            self.assertEqual(output_file.read_bytes(), b"PNG_FAKE_SCREENSHOT_DATA")
        finally:
            if output_file.exists():
                output_file.unlink()

    async def test_download_image_uses_dom_extraction_first(self):
        """Test _download_image uses DOM extraction first without clicking download button."""
        generator = ChromeAIGenerator()
        output_file = Path("/tmp/test_chrome_ai_dom_first.png")
        
        with patch.object(generator, "_extract_image_from_dom", return_value=True) as mock_extract:
            success = await generator._download_image(output_file, new_image_index=2)
            self.assertTrue(success)
            mock_extract.assert_called_once_with(output_file, 2)

    async def test_ensure_browser_open_reinitializes_on_closed_context(self):
        """Test _ensure_browser_open re-initializes Playwright persistent context if page/context was closed."""
        generator = ChromeAIGenerator()
        
        mock_page = AsyncMock()
        mock_page.is_closed = MagicMock(return_value=True)  # closed page!
        
        generator.page = mock_page
        generator.context = AsyncMock()
        generator.playwright = AsyncMock()
        
        new_mock_context = AsyncMock()
        new_mock_page = AsyncMock()
        new_mock_context.new_page.return_value = new_mock_page
        generator.playwright.chromium.launch_persistent_context.return_value = new_mock_context
        
        await generator._ensure_browser_open()
        
        self.assertEqual(generator.context, new_mock_context)
        self.assertEqual(generator.page, new_mock_page)

    async def test_navigate_to_ai_mode_uses_direct_url(self):
        """Direct AI Mode URL is preferred over the homepage button hunt."""
        from scripts.chrome_ai_scraper import AI_MODE_URLS

        generator = ChromeAIGenerator()
        generator.page = AsyncMock()

        tools_button = AsyncMock()
        image_button = AsyncMock()

        with patch.object(generator, "_ensure_browser_open", new_callable=AsyncMock) as ensure, \
             patch.object(generator, "_wait_for_ai_mode_prompt", new_callable=AsyncMock, return_value=True), \
             patch.object(generator, "_find_first", new_callable=AsyncMock,
                          side_effect=[None, tools_button, image_button]):
            await generator._navigate_to_ai_mode()

        ensure.assert_awaited_once()
        generator.page.goto.assert_awaited_once_with(
            AI_MODE_URLS[0], timeout=30000, wait_until="domcontentloaded"
        )
        tools_button.click.assert_awaited_once()
        image_button.click.assert_awaited_once()

    async def test_navigate_to_ai_mode_falls_back_to_homepage(self):
        """Falls back to the homepage entry point when direct URLs fail."""
        generator = ChromeAIGenerator()
        generator.page = AsyncMock()

        entry_button = AsyncMock()
        image_button = AsyncMock()

        with patch.object(generator, "_ensure_browser_open", new_callable=AsyncMock), \
             patch.object(generator, "_wait_for_ai_mode_prompt", new_callable=AsyncMock,
                          side_effect=[False, False, False, True]), \
             patch.object(generator, "_find_first", new_callable=AsyncMock,
                          side_effect=[entry_button, image_button]):
            await generator._navigate_to_ai_mode()

        self.assertEqual(generator.page.goto.await_count, 4)
        self.assertEqual(
            generator.page.goto.await_args_list[-1].args[0], "https://www.google.com"
        )
        entry_button.click.assert_awaited_once()
        image_button.click.assert_awaited_once()

    async def test_navigate_to_ai_mode_raises_clear_error_on_failure(self):
        """A missing entry point surfaces the original actionable message."""
        generator = ChromeAIGenerator()
        generator.page = AsyncMock()

        with patch.object(generator, "_ensure_browser_open", new_callable=AsyncMock), \
             patch.object(generator, "_wait_for_ai_mode_prompt", new_callable=AsyncMock,
                          return_value=False), \
             patch.object(generator, "_find_first", new_callable=AsyncMock, return_value=None), \
             patch.object(generator, "_dump_page_debug", new_callable=AsyncMock) as dump:
            with self.assertRaisesRegex(Exception, "Could not find AI mode button in Chrome"):
                await generator._navigate_to_ai_mode()

        dump.assert_awaited_once()
