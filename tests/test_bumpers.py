import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts import ffmpeg_assembler
from scripts import manual_run


class BumperSupportTests(unittest.TestCase):
    def test_resolve_bumper_paths_finds_intro_and_outro(self):
        with tempfile.TemporaryDirectory() as tmp:
            assets = Path(tmp) / "assets"
            bumper_dir = assets / "bumpers" / "trending"
            bumper_dir.mkdir(parents=True)
            (bumper_dir / "intro.mp4").write_bytes(b"intro")
            (bumper_dir / "outro.mp4").write_bytes(b"outro")

            with patch.object(ffmpeg_assembler, "ASSETS_DIR", assets):
                paths = ffmpeg_assembler.resolve_channel_bumper_paths("trending")

        self.assertEqual([label for label, _ in paths], ["intro", "outro"])

    def test_resolve_bumper_paths_skips_missing_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            assets = Path(tmp) / "assets"
            bumper_dir = assets / "bumpers" / "lofi"
            bumper_dir.mkdir(parents=True)
            (bumper_dir / "intro.mp4").write_bytes(b"intro")

            with patch.object(ffmpeg_assembler, "ASSETS_DIR", assets):
                paths = ffmpeg_assembler.resolve_channel_bumper_paths("lofi")

        self.assertEqual([label for label, _ in paths], ["intro"])

    def test_resolve_bumper_paths_missing_folder_is_noop(self):
        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(ffmpeg_assembler, "ASSETS_DIR", Path(tmp) / "assets"):
                paths = ffmpeg_assembler.resolve_channel_bumper_paths("family")

        self.assertEqual(paths, [])

    def test_english_challenge_uses_english_bumpers(self):
        with tempfile.TemporaryDirectory() as tmp:
            assets = Path(tmp) / "assets"
            bumper_dir = assets / "bumpers" / "english"
            bumper_dir.mkdir(parents=True)
            (bumper_dir / "outro.mp4").write_bytes(b"outro")

            with patch.object(ffmpeg_assembler, "ASSETS_DIR", assets):
                paths = ffmpeg_assembler.resolve_channel_bumper_paths("english-challenge")

        self.assertEqual([label for label, _ in paths], ["outro"])

    def test_normalize_bumper_video_adds_silent_audio_when_missing(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "intro.mp4"
            output = Path(tmp) / "intro_norm.mp4"
            source.write_bytes(b"video")
            commands = []

            with patch.object(ffmpeg_assembler, "_has_audio_stream", return_value=False):
                with patch.object(ffmpeg_assembler, "get_audio_duration", return_value=1.5):
                    with patch.object(ffmpeg_assembler, "run_ffmpeg", side_effect=lambda cmd: commands.append(cmd)):
                        ffmpeg_assembler._normalize_bumper_video(source, output, 1080, 1920)

        flat = [part for cmd in commands for part in cmd]
        self.assertIn("anullsrc=r=48000:cl=stereo", flat)
        self.assertTrue(any("scale=1080:1920" in part for part in flat))
        self.assertIn("-ar", flat)
        self.assertIn("48000", flat)
        self.assertIn("-ac", flat)
        self.assertIn("2", flat)

    def test_get_media_duration_uses_ffprobe_format(self):
        with patch.object(ffmpeg_assembler, "_run_ffprobe", return_value={"format": {"duration": "12.34"}}):
            self.assertEqual(ffmpeg_assembler.get_media_duration("sample.mp4"), 12.34)

    def test_create_thumbnail_from_video_uses_frame_and_drawtext(self):
        with tempfile.TemporaryDirectory() as tmp:
            thumbnail = Path(tmp) / "thumb.jpg"
            commands = []

            with patch.object(ffmpeg_assembler, "get_media_duration", return_value=24.0):
                with patch.object(ffmpeg_assembler, "run_ffmpeg", side_effect=lambda cmd: commands.append(cmd)):
                    result = ffmpeg_assembler.create_thumbnail_from_video(
                        video_path="video.mp4",
                        title_text="Unique Topic",
                        output_path=str(thumbnail),
                        style="lofi",
                    )

        self.assertEqual(result, str(thumbnail))
        flat = [part for cmd in commands for part in cmd]
        self.assertIn("video.mp4", flat)
        self.assertTrue(any("-ss" in part for part in flat))
        self.assertTrue(any("drawtext=text='Unique Topic'" in part for part in flat))

    def test_append_channel_bumpers_replaces_output_after_successful_crossfade(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            assets = root / "assets"
            temp = root / "temp"
            output = root / "video.mp4"
            bumper_dir = assets / "bumpers" / "trending"
            bumper_dir.mkdir(parents=True)
            temp.mkdir()
            output.write_bytes(b"original")
            (bumper_dir / "intro.mp4").write_bytes(b"intro")
            (bumper_dir / "outro.mp4").write_bytes(b"outro")

            def normalize(_source, normalized, _width, _height):
                normalized.write_bytes(b"normalized")

            commands = []

            def run(cmd):
                commands.append(cmd)
                Path(cmd[-1]).write_bytes(b"with bumpers")

            with patch.object(ffmpeg_assembler, "ASSETS_DIR", assets):
                with patch.object(ffmpeg_assembler, "TEMP_DIR", temp):
                    with patch.object(ffmpeg_assembler, "_video_stream_info", return_value={"width": 1920, "height": 1080}):
                        with patch.object(ffmpeg_assembler, "_normalize_bumper_video", side_effect=normalize):
                            with patch.object(ffmpeg_assembler, "get_audio_duration", return_value=2.0):
                                with patch.object(ffmpeg_assembler, "run_ffmpeg", side_effect=run):
                                    result = ffmpeg_assembler.append_channel_bumpers(str(output), "trending")
                                    output_bytes = output.read_bytes()

        self.assertEqual(result, str(output))
        self.assertEqual(output_bytes, b"with bumpers")
        flat = [part for cmd in commands for part in cmd]
        filter_args = [part for part in flat if isinstance(part, str) and "xfade=" in part]
        self.assertTrue(any("xfade=transition=fade:duration=0.5" in part for part in filter_args))
        self.assertTrue(any("acrossfade=d=0.5" in part for part in filter_args))
        self.assertIn(str(temp / "video_bumper_intro.mp4"), flat)
        self.assertIn(str(output), flat)

    def test_english_shorts_does_not_request_bumpers(self):
        script = {
            "title": "Quick English Tip",
            "description": "A short lesson",
            "tags": ["english"],
            "dialogue": [{"speaker": "Emma", "text": "Hello!"}],
        }

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            assets = tmp_path / "assets"
            output = tmp_path / "output"
            visuals = assets / "english_shorts_visuals"
            visuals.mkdir(parents=True)
            output.mkdir()
            visual = visuals / "clip.mp4"
            visual.write_bytes(b"visual")

            with patch.object(manual_run, "ASSETS_DIR", assets):
                with patch.object(manual_run, "OUTPUT_DIR", output):
                    with patch("english_generator.generate_english_shorts_script", return_value=script):
                        with patch("english_assembler.cleanup_english_temp"):
                            with patch("english_assembler.generate_podcast_audio", return_value=str(tmp_path / "voice.m4a")):
                                with patch("ffmpeg_assembler.generate_captions", return_value=str(output / "captions.srt")):
                                    with patch("ffmpeg_assembler.assemble_shorts_video") as assemble:
                                        with patch("random.choice", return_value=visual):
                                            manual_run.run_english_shorts(upload=False)

        self.assertIsNone(assemble.call_args.kwargs.get("channel"))

    def test_english_long_form_requests_english_bumpers(self):
        script = {
            "title": "English Podcast",
            "dialogue": [{"speaker": "Emma", "text": "Hello!"}],
        }

        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "output"
            output.mkdir()
            visual = Path(tmp) / "visual.mp4"
            visual.write_bytes(b"visual")

            with patch.object(manual_run, "OUTPUT_DIR", output):
                with patch("english_assembler.cleanup_english_temp"):
                    with patch("english_assembler.generate_podcast_audio", return_value=str(Path(tmp) / "voice.m4a")):
                        with patch("ffmpeg_assembler.generate_captions", return_value=str(output / "captions.srt")):
                            with patch("english_assembler.assemble_english_video") as assemble:
                                manual_run._assemble_english_script(script, "english_podcast", visual, None)

        self.assertEqual(assemble.call_args.kwargs["channel"], "english")

    def test_trending_build_requests_trending_bumpers(self):
        package = {
            "title": "Trending Topic",
            "script": "This is a quick script.",
            "stock_keyword": "news",
            "description": "Description",
            "tags": ["news"],
            "video_format": "shorts",
        }
        fake_free_tts = types.SimpleNamespace(
            generate_tts=lambda *_args, **_kwargs: None,
            clean_script=lambda text: text,
        )

        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "output"
            output.mkdir()

            with patch.dict("sys.modules", {"free_tts": fake_free_tts}):
                with patch.object(manual_run, "OUTPUT_DIR", output):
                    with patch.object(manual_run, "_ensure_background_music", return_value=str(Path(tmp) / "bg.mp3")):
                        with patch("ffmpeg_assembler.get_audio_duration", return_value=10):
                            with patch("ffmpeg_assembler.fetch_stock_videos", return_value=[str(Path(tmp) / "clip.mp4")]):
                                with patch("ffmpeg_assembler.generate_captions", return_value=str(output / "captions.srt")):
                                    with patch("ffmpeg_assembler.cleanup_temp"):
                                        with patch("ffmpeg_assembler.assemble_shorts_video") as assemble:
                                            manual_run._build_trending_video(package)

        self.assertEqual(assemble.call_args.kwargs["channel"], "trending")


if __name__ == "__main__":
    unittest.main()
