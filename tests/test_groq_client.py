import unittest
from unittest.mock import Mock, patch

from scripts.groq_client import (
    groq_chat_json,
    is_json_validation_error,
    parse_rate_limit_wait_seconds,
)


class GroqClientTests(unittest.TestCase):
    def test_parse_rate_limit_wait_from_error_message(self):
        response = Mock()
        response.headers = {}
        response.text = (
            '{"error":{"message":"Rate limit reached... Please try again in 19.495s."}}'
        )
        response.json.return_value = {
            "error": {"message": "Rate limit reached... Please try again in 19.495s."}
        }

        self.assertAlmostEqual(parse_rate_limit_wait_seconds(response), 19.495, places=3)

    def test_parse_rate_limit_wait_from_retry_after_header(self):
        response = Mock()
        response.headers = {"Retry-After": "12"}
        response.text = "{}"
        response.json.side_effect = ValueError()

        self.assertEqual(parse_rate_limit_wait_seconds(response), 12.0)

    def test_detect_json_validation_error(self):
        response = Mock()
        response.text = '{"error":{"message":"Failed to generate JSON.","code":"json_validate_failed"}}'
        response.json.return_value = {
            "error": {
                "message": "Failed to generate JSON.",
                "code": "json_validate_failed",
            }
        }

        self.assertTrue(is_json_validation_error(response))

    @patch("scripts.groq_client.time.sleep")
    @patch("scripts.groq_client.requests.post")
    @patch.dict("scripts.groq_client.os.environ", {"GROQ_API_KEY": "test-key"})
    def test_groq_chat_json_retries_json_validation_error(self, post, sleep):
        failed = Mock()
        failed.status_code = 400
        failed.text = '{"error":{"message":"Failed to generate JSON.","code":"json_validate_failed"}}'
        failed.json.return_value = {
            "error": {
                "message": "Failed to generate JSON.",
                "code": "json_validate_failed",
            }
        }

        succeeded = Mock()
        succeeded.status_code = 200
        succeeded.json.return_value = {
            "choices": [{"message": {"content": '{"ok": true}'}}],
        }
        post.side_effect = [failed, succeeded]

        result = groq_chat_json(
            messages=[{"role": "user", "content": "Return JSON"}],
            max_retries=2,
        )

        self.assertEqual(result, {"ok": True})
        self.assertEqual(post.call_count, 2)
        self.assertLess(post.call_args_list[1].kwargs["json"]["temperature"], 0.7)
        self.assertIn(
            "strict JSON",
            post.call_args_list[1].kwargs["json"]["messages"][-1]["content"],
        )
        sleep.assert_called_once()


if __name__ == "__main__":
    unittest.main()
