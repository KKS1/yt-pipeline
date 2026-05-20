import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from unittest.mock import patch

from scripts import manual_run


class ManualRunUploadTests(unittest.TestCase):
    def test_upload_video_uses_shared_uploader_directly(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            assets = tmp_path / "assets"
            assets.mkdir()
            (assets / "yt_credentials_trending.json").write_text("{}", encoding="utf-8")
            video = tmp_path / "video.mp4"
            video.write_bytes(b"fake video")

            with patch.object(manual_run, "ASSETS_DIR", assets):
                with patch("youtube_uploader.youtube_upload") as upload:
                    upload.return_value = {"youtube_id": "abc123"}

                    with redirect_stdout(StringIO()):
                        manual_run._upload_video(
                            str(video),
                            "Title",
                            "Description",
                            ["tag"],
                            "trending",
                        )

                    upload.assert_called_once()
                    self.assertFalse(video.exists())


if __name__ == "__main__":
    unittest.main()
