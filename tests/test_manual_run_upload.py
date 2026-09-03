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
    def test_english_description_playlist_urls_replace_placeholder(self):
        cases = {
            "english": "https://www.youtube.com/playlist?list=PLQcVuzsH3e2I",
            "english-shorts": "https://www.youtube.com/playlist?list=PL1D9QTXOAjU-bNRdK4aiWxGrlb3htqBdd",
            "english-quiz": "https://www.youtube.com/playlist?list=PL1D9QTXOAjU9CjNgVhQq2xlJKwi7MrKwD",
        }

        for channel, expected_url in cases.items():
            with self.subTest(channel=channel):
                description = manual_run._description_with_playlist_url(
                    "Practice today.\n\n📺 Watch the playlist here: {playlist_url}",
                    channel,
                )

                self.assertIn(expected_url, description)
                self.assertNotIn("{playlist_url}", description)

    def test_challenge_description_playlist_placeholder_is_not_replaced_with_master_playlist(self):
        description = manual_run._description_with_playlist_url(
            "Day 1 description\n\n📺 Watch the playlist here: {playlist_url}",
            "english-challenge",
        )

        self.assertIn("{playlist_url}", description)
        self.assertNotIn("PL1D9QTXOAjU9CjNgVhQq2xlJKwi7MrKwD", description)
        self.assertNotIn("PL1D9QTXOAjU-bNRdK4aiWxGrlb3htqBdd", description)
        self.assertNotIn("PLQcVuzsH3e2I", description)

    def test_upload_video_injects_english_quiz_playlist_url(self):
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
                        manual_run._upload_video(
                            str(video),
                            "Title",
                            "Description with {playlist_url}",
                            ["tag"],
                            "english",
                            command_channel="english-quiz",
                        )

                    self.assertIn(
                        "https://www.youtube.com/playlist?list=PL1D9QTXOAjU9CjNgVhQq2xlJKwi7MrKwD",
                        upload.call_args.kwargs["description"],
                    )

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

    def test_upload_video_skips_thumbnail_for_english(self):
        """Thumbnail generation is disabled — youtube_upload receives thumbnail_path=None."""
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

                        thumb.assert_not_called()
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
