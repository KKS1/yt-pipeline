import json
import unittest

from scripts.trending_generator import (
    filter_topics,
    normalize_script_data,
    normalize_topic_data,
    parse_google_trends_rss,
    parse_groq_json,
)


class TrendingGeneratorTests(unittest.TestCase):
    def test_parse_google_trends_rss_extracts_item_titles(self):
        xml = """<?xml version="1.0"?>
        <rss><channel>
          <title>Google Trends</title>
          <item><title>Montreal Canadiens</title></item>
          <item><title>AI glasses</title></item>
          <item><title>Montreal Canadiens</title></item>
        </channel></rss>
        """

        self.assertEqual(
            parse_google_trends_rss(xml),
            ["Montreal Canadiens", "AI glasses"],
        )

    def test_parse_google_trends_rss_handles_empty_or_bad_xml(self):
        self.assertEqual(parse_google_trends_rss(""), [])
        self.assertEqual(parse_google_trends_rss("<rss><broken>"), [])

    def test_filter_topics_removes_unsafe_topics(self):
        topics = ["Stanley Cup playoffs", "Election scandal", "New tech gadget"]

        self.assertEqual(
            filter_topics(topics),
            ["Stanley Cup playoffs", "New tech gadget"],
        )

    def test_parse_groq_json_accepts_clean_and_fenced_json(self):
        payload = {"title": "Example", "tags": ["one"]}

        self.assertEqual(parse_groq_json(json.dumps(payload)), payload)
        self.assertEqual(parse_groq_json(f"```json\n{json.dumps(payload)}\n```"), payload)

    def test_normalize_topic_data_fills_defaults(self):
        data = normalize_topic_data({"chosen_topic": "AI glasses"}, fallback_topic="Fallback")

        self.assertEqual(data["chosen_topic"], "AI glasses")
        self.assertIn("AI glasses", data["keywords"])
        self.assertTrue(data["stock_keyword"])

    def test_normalize_script_data_requires_script_and_fills_shape(self):
        topic = {
            "chosen_topic": "AI glasses",
            "angle": "Why everyone is talking about them",
            "keywords": ["AI glasses"],
            "stock_keyword": "technology",
        }
        data = normalize_script_data(
            {
                "title": "Why AI Glasses Are Back",
                "description": "A quick explainer.",
                "tags": "AI, glasses, technology",
                "script": "Here is the full narrated script.",
            },
            topic,
        )

        self.assertEqual(data["title"], "Why AI Glasses Are Back")
        self.assertEqual(data["stock_keyword"], "technology")
        self.assertEqual(data["tags"], ["AI", "glasses", "technology"])

        with self.assertRaises(ValueError):
            normalize_script_data({"title": "No script"}, topic)


if __name__ == "__main__":
    unittest.main()
