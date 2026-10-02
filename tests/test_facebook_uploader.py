"""
test_facebook_uploader.py
─────────────────────────
Unit tests for the Meta Reels Publishing API helper.

Every `requests.post` is mocked, so these tests never touch the network and
never read the real Facebook token from .env — see `fb_env` below, which
strips every FACEBOOK_* variable for the duration of each test.
"""

import contextlib
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).resolve().parent.parent

# facebook_uploader lazily imports ffmpeg_assembler, and both live in scripts/.
# Mirror manual_run.py, which puts scripts/ on sys.path before importing them.
# Import top-level (not scripts.facebook_uploader) so there is exactly one module
# instance — otherwise patch() would target a different copy than the one under test.
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

import facebook_uploader


FACEBOOK_ENV_KEYS = (
    "FACEBOOK_PAGE_ID",
    "FACEBOOK_PAGE_ACCESS_TOKEN",
    "FACEBOOK_REEL_STATE",
    "FACEBOOK_GRAPH_VERSION",
    "FACEBOOK_TIMEOUT",
    "FACEBOOK_ENABLED_CHANNELS",
    "FACEBOOK_CAPTION_STYLE",
    "FACEBOOK_APPEND_YOUTUBE_LINK",
    "FACEBOOK_ENGAGEMENT_CTA",
    "FACEBOOK_INCLUDE_HASHTAGS",
    "FACEBOOK_DROP_HASHTAGS",
    "FACEBOOK_REPLACE_HASHTAGS",
)


@contextlib.contextmanager
def fb_env(**overrides):
    """Run with exactly the given FACEBOOK_* vars and nothing else."""
    saved = {key: os.environ.pop(key, None) for key in FACEBOOK_ENV_KEYS}
    try:
        os.environ.update({k: v for k, v in overrides.items() if v is not None})
        yield
    finally:
        for key in FACEBOOK_ENV_KEYS:
            os.environ.pop(key, None)
        os.environ.update({k: v for k, v in saved.items() if v is not None})


class FakeResponse:
    def __init__(self, status_code=200, payload=None):
        self.status_code = status_code
        self.ok = status_code < 400
        self._payload = payload

    def json(self):
        if self._payload is None:
            raise ValueError("response body is not JSON")
        return self._payload


def graph_error(code, message="boom"):
    return {"error": {"message": message, "type": "OAuthException", "code": code}}


def reel_responses(state="DRAFT"):
    """The three responses Meta returns for a successful upload."""
    return [
        FakeResponse(200, {
            "video_id": "999888777",
            "upload_url": "https://rupload.facebook.com/video-upload/v26.0/999888777",
        }),
        FakeResponse(200, {"success": True, "h": "handle-abc"}),
        FakeResponse(200, {"success": True, "post_id": None, "message": "Draft created"}),
    ]


class FakeProbe(dict):
    """Stand-in for _probe_media with predictable values."""


def make_probe(**kwargs):
    values = {"duration": 42.0, "width": 1080, "height": 1920}
    values.update(kwargs)
    return values


class ConfigTests(unittest.TestCase):
    def test_credentials_present_requires_both_vars(self):
        with fb_env():
            self.assertFalse(facebook_uploader.facebook_credentials_present())

        with fb_env(FACEBOOK_PAGE_ID="123"):
            self.assertFalse(facebook_uploader.facebook_credentials_present())

        with fb_env(FACEBOOK_PAGE_ACCESS_TOKEN="EAAabc"):
            self.assertFalse(facebook_uploader.facebook_credentials_present())

        with fb_env(FACEBOOK_PAGE_ID="123", FACEBOOK_PAGE_ACCESS_TOKEN="EAAabc"):
            self.assertTrue(facebook_uploader.facebook_credentials_present())

    def test_channel_enabled_defaults_to_shorts_and_quiz(self):
        with fb_env():
            self.assertTrue(facebook_uploader.facebook_channel_enabled("english-shorts"))
            self.assertTrue(facebook_uploader.facebook_channel_enabled("english-quiz"))
            self.assertFalse(facebook_uploader.facebook_channel_enabled("english"))
            self.assertFalse(facebook_uploader.facebook_channel_enabled("family"))
            self.assertFalse(facebook_uploader.facebook_channel_enabled(""))
            self.assertFalse(facebook_uploader.facebook_channel_enabled(None))

    def test_channel_enabled_honours_env_override(self):
        with fb_env(FACEBOOK_ENABLED_CHANNELS="english-shorts, english-challenge-shorts"):
            self.assertTrue(facebook_uploader.facebook_channel_enabled("english-shorts"))
            self.assertTrue(
                facebook_uploader.facebook_channel_enabled("english-challenge-shorts")
            )
            self.assertFalse(facebook_uploader.facebook_channel_enabled("english-quiz"))

    def test_graph_version_defaults_and_normalises(self):
        with fb_env():
            self.assertEqual(facebook_uploader._graph_version(), "v26.0")
        with fb_env(FACEBOOK_GRAPH_VERSION="v23.0"):
            self.assertEqual(facebook_uploader._graph_version(), "v23.0")
        with fb_env(FACEBOOK_GRAPH_VERSION="24.0"):
            self.assertEqual(facebook_uploader._graph_version(), "v24.0")

    def test_reel_state_defaults_to_draft_and_validates(self):
        with fb_env():
            self.assertEqual(facebook_uploader._reel_state(), "DRAFT")
        with fb_env(FACEBOOK_REEL_STATE="scheduled"):
            self.assertEqual(facebook_uploader._reel_state(), "SCHEDULED")
        with fb_env(FACEBOOK_REEL_STATE="nonsense"):
            with self.assertRaises(ValueError):
                facebook_uploader._reel_state()


class CaptionTests(unittest.TestCase):
    def _caption(self, description="", title="", youtube_id=None, **env):
        with fb_env(**env):
            return facebook_uploader._reel_caption(description, title=title, youtube_id=youtube_id)

    def test_defaults_to_the_youtube_title_plus_hashtags_and_cta(self):
        """Shorts titles are already hooks; hashtags and CTA ride along."""
        caption = self._caption(
            "Stop saying no problem.\n\n📺 Playlist\n\n#Shorts #LearnEnglish #Vocabulary",
            title="STOP Saying 'No Problem' — Say This Instead",
        )
        lines = caption.split("\n\n")
        self.assertEqual(lines[0], "STOP Saying 'No Problem' — Say This Instead")
        self.assertIn("#LearnEnglish", caption)
        self.assertIn("#Vocabulary", caption)
        self.assertNotIn("#Shorts", caption)
        self.assertTrue(caption.rstrip().endswith("which one you'll use."))

    def test_cta_asks_for_save_share_and_comment(self):
        caption = self._caption("desc", title="Title")
        cta = caption.rsplit("\n\n", 1)[-1].lower()
        for word in ("save", "share", "comments"):
            self.assertIn(word, cta)

    def test_cta_can_be_overridden_or_removed(self):
        custom = self._caption("d", title="T", FACEBOOK_ENGAGEMENT_CTA="Say it in the comments!")
        self.assertTrue(custom.rstrip().endswith("Say it in the comments!"))

        blank = self._caption("d", title="T", FACEBOOK_ENGAGEMENT_CTA="")
        self.assertNotIn("Save this", blank)

    def test_hashtags_can_be_disabled(self):
        caption = self._caption("#Shorts #LearnEnglish", title="T", FACEBOOK_INCLUDE_HASHTAGS="0")
        self.assertNotIn("#Shorts", caption)

    def test_hashtags_are_capped_and_deduped(self):
        caption = self._caption(
            "#a #b #c #d #e #f #g #a", title="T", FACEBOOK_ENGAGEMENT_CTA=""
        )
        self.assertEqual(caption, "T\n\n#a #b #c #d #e")

    def test_drops_shorts_hashtag_which_is_youtube_only(self):
        caption = self._caption(
            "#Shorts #EnglishQuiz #LearnEnglish #Vocabulary #EnglishPractice",
            title="T",
        )
        self.assertNotIn("#Shorts", caption)
        self.assertIn("#EnglishQuiz", caption)

    def test_dropped_hashtag_can_be_restored(self):
        caption = self._caption(
            "#Shorts #LearnEnglish", title="T",
            FACEBOOK_DROP_HASHTAGS="", FACEBOOK_ENGAGEMENT_CTA="",
        )
        self.assertIn("#Shorts", caption)

    def test_platform_hashtag_can_be_substituted(self):
        caption = self._caption(
            "#Shorts #LearnEnglish", title="T",
            FACEBOOK_REPLACE_HASHTAGS="#fbreels", FACEBOOK_ENGAGEMENT_CTA="",
        )
        self.assertNotIn("#Shorts", caption)
        self.assertIn("#fbreels", caption)

    def test_custom_drop_list_is_respected(self):
        caption = self._caption(
            "#Shorts #LearnEnglish #Boring", title="T",
            FACEBOOK_DROP_HASHTAGS="boring", FACEBOOK_ENGAGEMENT_CTA="",
        )
        self.assertIn("#Shorts", caption)
        self.assertNotIn("#Boring", caption)

    def test_description_style_uses_first_paragraph_only(self):
        caption = self._caption(
            "Hook line that sells the video.\n\n00:00 Intro\n\n📺 Playlist\n\n#Reels",
            title="Some Title",
            FACEBOOK_CAPTION_STYLE="description",
            FACEBOOK_ENGAGEMENT_CTA="",
        )
        self.assertEqual(caption, "Hook line that sells the video.\n\n#Reels")

    def test_strips_unreplaced_playlist_placeholder(self):
        caption = self._caption(
            "Watch here: {playlist_url}", FACEBOOK_ENGAGEMENT_CTA=""
        )
        self.assertNotIn("{playlist_url}", caption)

    def test_no_link_by_default_because_facebook_does_not_linkify(self):
        caption = self._caption("Practice this phrase.", youtube_id="abc123")
        self.assertNotIn("youtu.be", caption)

    def test_link_appends_when_explicitly_enabled(self):
        caption = self._caption(
            "Practice this phrase.",
            youtube_id="abc123",
            FACEBOOK_APPEND_YOUTUBE_LINK="1",
        )
        self.assertIn("Practice this phrase.", caption)
        self.assertIn("https://youtu.be/abc123", caption)

    def test_falls_back_to_description_when_title_missing(self):
        caption = self._caption(
            "A hook from the description.", FACEBOOK_CAPTION_STYLE="title",
            FACEBOOK_ENGAGEMENT_CTA="",
        )
        self.assertEqual(caption, "A hook from the description.")

    def test_caps_long_captions_keeping_hook_and_cta(self):
        caption = self._caption("x" * 2000, title="T" * 900)
        self.assertLessEqual(len(caption), facebook_uploader.REELS_MAX_CAPTION_CHARS)
        self.assertTrue(caption.endswith("comments which one you'll use."))

    def test_sheds_hashtags_before_cutting_the_hook(self):
        caption = self._caption(
            " ".join(f"#Tag{i}" for i in range(12)),
            title="HOOKMARKER " * 40,
        )
        self.assertLessEqual(len(caption), facebook_uploader.REELS_MAX_CAPTION_CHARS)
        self.assertIn("HOOKMARKER", caption)
        self.assertTrue(caption.endswith("which one you'll use."))

    def test_rejects_unknown_caption_style(self):
        with fb_env(FACEBOOK_CAPTION_STYLE="nonsense"):
            with self.assertRaises(ValueError):
                facebook_uploader._reel_caption("x", title="y")


class UploadFlowTests(unittest.TestCase):
    def _video(self, tmp, name="reel.mp4", size=2048):
        path = Path(tmp) / name
        path.write_bytes(b"0" * size)
        return str(path)

    def _run(self, video, responses, env=None, **kwargs):
        base = {
            "FACEBOOK_PAGE_ID": "61594893993727",
            "FACEBOOK_PAGE_ACCESS_TOKEN": "EAA-token",
        }
        base.update(env or {})
        with fb_env(**base):
            with patch.object(facebook_uploader, "_probe_media", return_value=make_probe()):
                with patch(
                    "facebook_uploader.requests.post", side_effect=responses
                ) as post:
                    with patch("facebook_uploader.time.sleep"):
                        result = facebook_uploader.facebook_upload_reel(
                            video_path=video, **kwargs
                        )
        return result, post

    def test_three_phases_run_in_order_against_correct_hosts(self):
        with tempfile.TemporaryDirectory() as tmp:
            video = self._video(tmp)
            result, post = self._run(
                video,
                reel_responses(),
                title="Stop saying the wrong here",
                description="Practise this phrase today.",
            )

        self.assertEqual(post.call_count, 3)
        start, upload, finish = (call.args[0] for call in post.call_args_list)

        self.assertEqual(
            start,
            "https://graph.facebook.com/v26.0/61594893993727/video_reels",
        )
        self.assertEqual(post.call_args_list[0].kwargs["params"]["upload_phase"], "start")

        # Phase 2 must hit the rupload host Meta handed back, not the graph host.
        self.assertEqual(upload, "https://rupload.facebook.com/video-upload/v26.0/999888777")

        self.assertEqual(
            finish, "https://graph.facebook.com/v26.0/61594893993727/video_reels"
        )
        self.assertEqual(post.call_args_list[2].kwargs["params"]["upload_phase"], "finish")

        self.assertEqual(result["facebook_video_id"], "999888777")
        self.assertEqual(result["video_state"], "DRAFT")
        self.assertEqual(result["reel_url"], "https://www.facebook.com/reel/999888777")
        self.assertIsNone(result["post_id"])

    def test_phase_two_sends_auth_offset_size_and_binary_body(self):
        with tempfile.TemporaryDirectory() as tmp:
            video = self._video(tmp, size=4096)
            _, post = self._run(video, reel_responses(), title="T", description="D")

        headers = post.call_args_list[1].kwargs["headers"]
        self.assertEqual(headers["Authorization"], "OAuth EAA-token")
        self.assertEqual(headers["offset"], "0")
        self.assertEqual(headers["file_size"], "4096")
        self.assertEqual(headers["Content-Type"], "application/octet-stream")

        # The body must be an open binary handle, not a bytes blob in memory.
        body = post.call_args_list[1].kwargs["data"]
        self.assertTrue(hasattr(body, "read"))
        body.close()

    def test_phase_three_defaults_to_draft_with_title_and_caption(self):
        with tempfile.TemporaryDirectory() as tmp:
            video = self._video(tmp)
            _, post = self._run(
                video,
                reel_responses(),
                title="Stop saying the wrong here",
                description="Hook line.\n\n00:00 Intro",
                youtube_id="yt123",
            )

        params = post.call_args_list[2].kwargs["params"]
        self.assertEqual(params["video_state"], "DRAFT")
        self.assertEqual(params["title"], "Stop saying the wrong here")
        # Default caption style reuses the YouTube title, omits the unclickable
        # YouTube link, and appends the engagement CTA.
        self.assertTrue(params["description"].startswith("Stop saying the wrong here"))
        self.assertNotIn("00:00", params["description"])
        self.assertNotIn("youtu.be", params["description"])
        self.assertNotIn("scheduled_publish_time", params)

    def test_phase_three_can_send_description_hook_and_link(self):
        """Opt-in style: description hook plus an explicit YouTube link."""
        with tempfile.TemporaryDirectory() as tmp:
            video = self._video(tmp)
            _, post = self._run(
                video,
                reel_responses(),
                title="Stop saying the wrong here",
                description="Hook line.\n\n00:00 Intro",
                youtube_id="yt123",
                env={
                    "FACEBOOK_CAPTION_STYLE": "description",
                    "FACEBOOK_APPEND_YOUTUBE_LINK": "1",
                },
            )

        params = post.call_args_list[2].kwargs["params"]
        self.assertEqual(params["title"], "Stop saying the wrong here")
        self.assertIn("Hook line.", params["description"])
        self.assertIn("https://youtu.be/yt123", params["description"])
        self.assertNotIn("00:00", params["description"])

    def test_scheduled_state_requires_and_sends_publish_time(self):
        with fb_env(FACEBOOK_PAGE_ID="61594893993727", FACEBOOK_PAGE_ACCESS_TOKEN="EAA-token"):
            with patch.object(facebook_uploader, "_probe_media", return_value=make_probe()):
                with patch("facebook_uploader.requests.post", side_effect=reel_responses()):
                    with patch("facebook_uploader.time.sleep"):
                        with self.assertRaises(ValueError):
                            facebook_uploader.facebook_upload_reel(
                                video_path="/tmp/does-not-matter.mp4",
                                video_state="SCHEDULED",
                            )

        with tempfile.TemporaryDirectory() as tmp:
            video = self._video(tmp)
            _, post = self._run(
                video,
                reel_responses(),
                title="T",
                video_state="SCHEDULED",
                schedule_time="2026-06-03T15:00:00Z",
            )

        params = post.call_args_list[2].kwargs["params"]
        self.assertEqual(params["video_state"], "SCHEDULED")
        self.assertEqual(params["scheduled_publish_time"], "2026-06-03T15:00:00Z")

    def test_transient_failure_retries_once_then_succeeds(self):
        with tempfile.TemporaryDirectory() as tmp:
            video = self._video(tmp)
            responses = [
                FakeResponse(500, graph_error(2, "temporarily unavailable")),
                FakeResponse(200, {"video_id": "555", "upload_url": "https://rupload.facebook.com/x"}),
                FakeResponse(200, {"success": True}),
                FakeResponse(200, {"success": True, "post_id": "p1"}),
            ]
            result, post = self._run(video, responses, title="T")

        self.assertEqual(post.call_count, 4)
        self.assertEqual(result["facebook_video_id"], "555")

    def test_non_retriable_failure_does_not_retry(self):
        with tempfile.TemporaryDirectory() as tmp:
            video = self._video(tmp)
            responses = [FakeResponse(400, graph_error(190, "Invalid OAuth token"))]
            with self.assertRaises(facebook_uploader.FacebookGraphError) as ctx:
                self._run(video, responses, title="T")

        self.assertEqual(ctx.exception.code, 190)
        self.assertEqual(ctx.exception.phase, "phase 1 (start)")

    def test_missing_upload_url_is_a_clear_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            video = self._video(tmp)
            responses = [FakeResponse(200, {"video_id": "555"})]
            with self.assertRaises(facebook_uploader.FacebookGraphError):
                self._run(video, responses, title="T")

    def test_missing_credentials_raise_before_any_network_call(self):
        with fb_env():
            with patch("facebook_uploader.requests.post") as post:
                with self.assertRaises(facebook_uploader.FacebookGraphError):
                    facebook_uploader.facebook_upload_reel(video_path="/tmp/x.mp4")
        post.assert_not_called()

    def test_missing_video_file_raises(self):
        with fb_env(FACEBOOK_PAGE_ID="1", FACEBOOK_PAGE_ACCESS_TOKEN="t"):
            with patch("facebook_uploader.requests.post") as post:
                with self.assertRaises(FileNotFoundError):
                    facebook_uploader.facebook_upload_reel(
                        video_path="/tmp/definitely-not-here.mp4"
                    )
        post.assert_not_called()


class VerifyTests(unittest.TestCase):
    def test_verify_returns_page_fields(self):
        page = {"id": "1343593842170731", "name": "English Vibes Hub", "fan_count": 1234}
        with fb_env(FACEBOOK_PAGE_ID="1343593842170731", FACEBOOK_PAGE_ACCESS_TOKEN="EAA"):
            with patch(
                "facebook_uploader.requests.get", return_value=FakeResponse(200, page)
            ) as get:
                result = facebook_uploader.facebook_verify_credentials()

        self.assertEqual(result["name"], "English Vibes Hub")
        params = get.call_args.kwargs["params"]
        self.assertEqual(params["access_token"], "EAA")
        self.assertIn("name", params["fields"])

    def test_verify_uses_get_not_post(self):
        """The Page node rejects POST with error 240 — reads must use GET."""
        with fb_env(FACEBOOK_PAGE_ID="1343593842170731", FACEBOOK_PAGE_ACCESS_TOKEN="EAA"):
            with patch(
                "facebook_uploader.requests.get",
                return_value=FakeResponse(200, {"id": "1343593842170731"}),
            ):
                with patch("facebook_uploader.requests.post") as post:
                    facebook_uploader.facebook_verify_credentials()

        post.assert_not_called()

    def test_verify_failure_raises_with_code(self):
        with fb_env(FACEBOOK_PAGE_ID="1", FACEBOOK_PAGE_ACCESS_TOKEN="bad"):
            with patch(
                "facebook_uploader.requests.get",
                return_value=FakeResponse(400, graph_error(100, "Unsupported get request",)),
            ):
                with self.assertRaises(facebook_uploader.FacebookGraphError) as ctx:
                    facebook_uploader.facebook_verify_credentials()

        self.assertEqual(ctx.exception.code, 100)
        self.assertEqual(ctx.exception.phase, "verify")

    def test_token_scopes_reports_granted_and_issuing_app(self):
        """debug_token is the only way to see the real scope set and issuer."""
        payload = {"data": {"scopes": ["pages_show_list", "pages_read_engagement"],
                            "app_id": "999", "target_ids": ["1343593842170731"]}}
        with fb_env(FACEBOOK_PAGE_ID="1", FACEBOOK_PAGE_ACCESS_TOKEN="page-token"):
            with patch(
                "facebook_uploader.requests.get",
                return_value=FakeResponse(200, payload),
            ):
                data = facebook_uploader.facebook_token_scopes("app|secret")

        self.assertEqual(data["app_id"], "999")
        self.assertIn("pages_show_list", data["scopes"])

    def test_token_scopes_raises_when_data_missing(self):
        with fb_env(FACEBOOK_PAGE_ID="1", FACEBOOK_PAGE_ACCESS_TOKEN="page-token"):
            with patch(
                "facebook_uploader.requests.get",
                return_value=FakeResponse(200, {"error": {"message": "bad", "code": 100}}),
            ):
                with self.assertRaises(facebook_uploader.FacebookGraphError):
                    facebook_uploader.facebook_token_scopes("app|secret")

    def test_subcode_is_captured_for_diagnostics(self):
        """Subcode 33 is what distinguishes a user token from a page token."""
        payload = {"error": {"message": "Unsupported get request", "code": 100,
                             "error_subcode": 33, "type": "GraphMethodException"}}
        with fb_env(FACEBOOK_PAGE_ID="1", FACEBOOK_PAGE_ACCESS_TOKEN="user-token"):
            with patch(
                "facebook_uploader.requests.get",
                return_value=FakeResponse(400, payload),
            ):
                with self.assertRaises(facebook_uploader.FacebookGraphError) as ctx:
                    facebook_uploader.facebook_verify_credentials()

        self.assertEqual(ctx.exception.error_subcode, 33)
        self.assertIn("33", str(ctx.exception))


class ProbeTests(unittest.TestCase):
    def test_duration_over_cap_warns_but_returns(self):
        with patch("ffmpeg_assembler.get_media_duration", return_value=120.0):
            with patch(
                "ffmpeg_assembler._video_stream_info",
                return_value={"width": 1080, "height": 1920},
            ):
                with patch("builtins.print") as printed:
                    info = facebook_uploader._probe_media("x.mp4")

        self.assertEqual(info["duration"], 120.0)
        warning = " ".join(str(c) for c in printed.call_args_list)
        self.assertIn("120.0s", warning)
        self.assertIn("90s", warning)

    def test_non_vertical_video_warns(self):
        with patch("ffmpeg_assembler.get_media_duration", return_value=30.0):
            with patch(
                "ffmpeg_assembler._video_stream_info",
                return_value={"width": 1920, "height": 1080},
            ):
                with patch("builtins.print") as printed:
                    info = facebook_uploader._probe_media("x.mp4")

        self.assertEqual((info["width"], info["height"]), (1920, 1080))
        warning = " ".join(str(c) for c in printed.call_args_list)
        self.assertIn("9:16", warning)

    def test_vertical_video_within_cap_is_quiet(self):
        with patch("ffmpeg_assembler.get_media_duration", return_value=42.0):
            with patch(
                "ffmpeg_assembler._video_stream_info",
                return_value={"width": 1080, "height": 1920},
            ):
                with patch("builtins.print") as printed:
                    facebook_uploader._probe_media("x.mp4")

        printed.assert_not_called()


if __name__ == "__main__":
    unittest.main()
