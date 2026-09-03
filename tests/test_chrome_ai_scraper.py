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
        """Test _extract_image_from_dom with base64 data URL from browser DOM."""
        generator = ChromeAIGenerator()
        
        mock_page = AsyncMock()
        mock_page.is_closed = MagicMock(return_value=False)
        mock_element = AsyncMock()
        
        generator.page = mock_page
        generator.context = MagicMock()
        
        mock_page.query_selector_all.return_value = [mock_element]
        
        # Fake base64 payload (> 1000 chars of base64 data)
        fake_base64 = "data:image/png;base64," + ("A" * 1500)
        mock_page.evaluate.return_value = fake_base64
        
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
        """Test _extract_image_from_dom falling back to element screenshot when canvas yields no data."""
        generator = ChromeAIGenerator()
        
        mock_page = AsyncMock()
        mock_page.is_closed = MagicMock(return_value=False)
        mock_element = AsyncMock()
        
        generator.page = mock_page
        generator.context = MagicMock()
        
        mock_page.query_selector_all.return_value = [mock_element]
        mock_page.evaluate.return_value = None
        
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

    async def test_download_image_triggers_dom_fallback_on_closed_target(self):
        """Test _download_image automatically falling back to DOM extraction when download.save_as throws closed target error."""
        generator = ChromeAIGenerator()
        
        mock_page = AsyncMock()
        mock_page.is_closed = MagicMock(return_value=False)
        mock_button = AsyncMock()
        
        generator.page = mock_page
        generator.context = MagicMock()
        
        mock_page.query_selector_all.return_value = [mock_button]
        
        class DummyDownloadInfo:
            async def __aenter__(self):
                return self
            async def __aexit__(self, exc_type, exc_val, exc_tb):
                pass
            @property
            def value(self):
                mock_dl = AsyncMock()
                mock_dl.save_as.side_effect = Exception("Download.save_as: Target page, context or browser has been closed")
                mock_dl.path.side_effect = Exception("Target page closed")
                fut = asyncio.Future()
                fut.set_result(mock_dl)
                return fut

        mock_page.expect_download = MagicMock(return_value=DummyDownloadInfo())
        
        output_file = Path("/tmp/test_chrome_ai_dl_fallback.png")
        
        with patch.object(generator, "_extract_image_from_dom", return_value=True) as mock_extract:
            success = await generator._download_image(output_file)
            self.assertTrue(success)
            mock_extract.assert_called_once_with(output_file)
