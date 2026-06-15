import os
import types
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
            publish_hour=6,
        )

        self.assertEqual(schedule_time, "2026-06-03T12:00:00Z")

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
                            schedule_time="2026-06-03T15:00:00Z",
                        )

                    self.assertEqual(upload.call_args.kwargs["channel"], "english")
                    self.assertEqual(upload.call_args.kwargs["schedule_time"], "2026-06-03T15:00:00Z")

    def test_upload_video_generates_frame_thumbnail_for_english(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            assets = tmp_path / "assets"
            assets.mkdir()
            (assets / "yt_credentials_english.json").write_text("{}", encoding="utf-8")
            video = tmp_path / "video.mp4"
            video.write_bytes(b"fake video")

            with patch.object(manual_run, "ASSETS_DIR", assets):
                with patch("youtube_uploader.youtube_upload") as upload:
                    with patch("ffmpeg_assembler.create_thumbnail_from_video") as thumb:
                        upload.return_value = {"youtube_id": "abc123"}
                        thumb.return_value = str(video.with_suffix('.jpg'))

                        with redirect_stdout(StringIO()):
                            manual_run._upload_video(
                                str(video),
                                "Title",
                                "Description",
                                ["tag"],
                                "english",
                                thumbnail_text="Speak Confidently",
                                thumbnail_concept="Bright cafe study scene with bold text",
                            )

                        thumb.assert_called_once()
                        upload.assert_called_once()

    def test_english_challenge_creates_playlist_and_adds_uploaded_videos(self):
        package = {
            "series_title": "Small Talk Without Freezing",
            "tags": ["English conversation", "small talk"],
            "scripts": [
                {
                    "day": 1,
                    "title": "Day 1: Start Small Talk",
                    "description": "Day 1 description",
                    "tags": ["day 1"],
                },
                {
                    "day": 2,
                    "title": "Day 2: Keep It Going",
                    "description": "Day 2 description",
                    "tags": ["day 2"],
                },
            ],
        }
        fake_generator = types.SimpleNamespace(
            generate_weekly_challenge_scripts=lambda topic=None: package,
            save_published_topic=lambda title, topic_type="quiz": None
        )

        with tempfile.TemporaryDirectory() as tmp:
            old_cwd = os.getcwd()
            os.chdir(tmp)
            Path("scripts/output").mkdir(parents=True)
            try:
                with patch.dict("sys.modules", {"english_generator": fake_generator}):
                    with patch.object(manual_run, "_english_video_assets", return_value=([Path("visual.mp4")], "")):
                        with patch.object(manual_run, "_assemble_english_script", return_value="video.mp4"):
                            with patch("youtube_uploader.create_playlist") as create_playlist:
                                with patch("youtube_uploader.add_video_to_playlist") as add_to_playlist:
                                    with patch.object(manual_run, "_upload_video") as upload_video:
                                        create_playlist.return_value = {"playlist_id": "playlist123"}
                                        upload_video.side_effect = [
                                            {"youtube_id": "video1"},
                                            {"youtube_id": "video2"},
                                        ]

                                        with redirect_stdout(StringIO()):
                                            manual_run.run_english_challenge(
                                                topic="small talk",
                                                upload=True,
                                                start_date="2026-05-28",
                                                publish_hour=6,
                                            )
            finally:
                os.chdir(old_cwd)

        self.assertEqual(create_playlist.call_count, 2)
        self.assertEqual(
            create_playlist.call_args_list[0].kwargs["title"],
            "Small Talk Without Freezing | 7-Day English Challenge",
        )
        self.assertEqual(
            create_playlist.call_args_list[1].kwargs["title"],
            "Small Talk Without Freezing | Daily Quizzes",
        )
        self.assertTrue(
            all(call.kwargs["channel"] == "english" for call in create_playlist.call_args_list)
        )
        self.assertEqual(
            [call.kwargs["video_id"] for call in add_to_playlist.call_args_list],
            ["video1", "video2"],
        )
        self.assertTrue(
            all(call.kwargs["playlist_id"] == "playlist123" for call in add_to_playlist.call_args_list)
        )


if __name__ == "__main__":
    unittest.main()
