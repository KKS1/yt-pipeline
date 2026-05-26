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

    def test_cleanup_uploaded_video_files_skips_directories(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            video = tmp_path / "video.mp4"
            captions = tmp_path / "video.srt"
            voice = tmp_path / "video_voice.m4a"
            temp_dir = tmp_path / "temp"
            video.write_bytes(b"fake video")
            captions.write_text("captions", encoding="utf-8")
            voice.write_bytes(b"fake audio")
            temp_dir.mkdir()

            manual_run._cleanup_uploaded_video_files(str(video))

            self.assertFalse(video.exists())
            self.assertFalse(captions.exists())
            self.assertFalse(voice.exists())
            self.assertTrue(temp_dir.exists())

    def test_challenge_schedule_time_uses_regina_timezone(self):
        schedule_time = manual_run._challenge_schedule_time(
            start_date="2026-06-01",
            day_offset=2,
            publish_hour=9,
        )

        self.assertEqual(schedule_time, "2026-06-03T15:00:00Z")

    def test_upload_existing_challenge_uses_english_credentials(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            assets = tmp_path / "assets"
            assets.mkdir()
            (assets / "yt_credentials_english.json").write_text("{}", encoding="utf-8")
            video = tmp_path / "video.mp4"
            video.write_bytes(b"fake video")

            with patch.object(manual_run, "ASSETS_DIR", assets):
                with patch("youtube_uploader.youtube_upload") as upload:
                    upload.return_value = {"youtube_id": "abc123"}

                    with redirect_stdout(StringIO()):
                        manual_run._upload_existing_video(
                            str(video),
                            "english-challenge",
                            title="Title",
                            description="Description",
                            tags=["tag"],
                        )

                    self.assertEqual(upload.call_args.kwargs["channel"], "english")


if __name__ == "__main__":
    unittest.main()
