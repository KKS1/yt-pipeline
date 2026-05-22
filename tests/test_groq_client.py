import unittest
from unittest.mock import Mock

from scripts.groq_client import parse_rate_limit_wait_seconds


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


if __name__ == "__main__":
    unittest.main()
