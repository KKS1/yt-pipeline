import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts import dynamic_english_renderer
from scripts import manual_run


class DynamicEnglishRendererTests(unittest.TestCase):
    def test_rhubarb_cues_map_optional_shapes_to_supported_assets(self):
        cues = dynamic_english_renderer.parse_rhubarb_mouth_cues(
            {
                "mouthCues": [
                    {"start": 0, "end": 0.1, "value": "A"},
                    {"start": 0.1, "end": 0.2, "value": "G"},
                    {"start": 0.2, "end": 0.3, "value": "H"},
                    {"start": 0.3, "end": 0.4, "value": "unknown"},
                    {"start": "bad", "end": 0.5, "value": "B"},
                ]
            }
        )

        self.assertEqual(
            cues,
            [
                {"start": 0.0, "end": 0.1, "value": "A"},
                {"start": 0.1, "end": 0.2, "value": "F"},
                {"start": 0.2, "end": 0.3, "value": "F"},
                {"start": 0.3, "end": 0.4, "value": "X"},
            ],
        )

    def test_preflight_reports_missing_character_assets(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config_path = root / "character_config.json"
            config_path.write_text(
                json.dumps(
                    {
                        "background": str(root / "missing_background.png"),
                        "characters": {
                            "Emma": {
                                "body": str(root / "emma.png"),
                                "position": {"x": 0, "y": 0, "width": 1, "height": 1},
                                "mouth": {"x": 0, "y": 0, "width": 1, "height": 1},
                            },
                            "Liam": {
                                "body": str(root / "liam.png"),
                                "position": {"x": 0, "y": 0, "width": 1, "height": 1},
                                "mouth": {"x": 0, "y": 0, "width": 1, "height": 1},
                            },
                        },
                    }
                ),
                encoding="utf-8",
            )

            with self.assertRaises(dynamic_english_renderer.DynamicRendererPreflightError) as ctx:
                dynamic_english_renderer.preflight_dynamic_english_assets(config_path)

        message = str(ctx.exception)
        self.assertIn("missing_background.png", message)
        self.assertIn("emma.png", message)
        self.assertIn("liam.png", message)

    def test_dynamic_visuals_require_no_upload(self):
        with patch.object(
            sys,
            "argv",
            ["manual_run.py", "--channel", "english-shorts", "--dynamic-visuals"],
        ):
            with self.assertRaises(SystemExit):
                manual_run.main()

    def test_dynamic_visuals_route_to_english_shorts_only_when_opted_in(self):
        with patch.object(
            sys,
            "argv",
            ["manual_run.py", "--channel", "english-shorts", "--dynamic-visuals", "--no-upload"],
        ):
            with patch.object(manual_run, "run_english_shorts") as run:
                manual_run.main()

        run.assert_called_once()
        self.assertFalse(run.call_args.kwargs["upload"])
        self.assertTrue(run.call_args.kwargs["dynamic_visuals"])

    def test_run_english_shorts_dynamic_upload_guard(self):
        with self.assertRaisesRegex(RuntimeError, "must be run with --no-upload"):
            manual_run.run_english_shorts(upload=True, dynamic_visuals=True)


if __name__ == "__main__":
    unittest.main()
