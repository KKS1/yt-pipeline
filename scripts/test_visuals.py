import os
import sys
from pathlib import Path
import json

# Add scripts directory to path
sys.path.insert(0, str(Path(__file__).resolve().parent))

# Monkeypatch the generators
import english_generator

dummy_script_base = {
    "title": "Visual Test",
    "visual_keywords": ["coffee", "cafe", "conversation", "library"],
    "dialogue": [
        {"speaker": "Emma", "text": "Quick test. Which phrase sounds natural at a coffee shop?"},
        {"speaker": "Liam", "text": "Pause and guess before Emma answers."},
        {"speaker": "Emma", "text": "[PAUSE 3 SECONDS]"},
        {"speaker": "Liam", "text": "Say, can I get this to go? That sounds natural."},
        {"speaker": "Emma", "text": "Good. Now let's throw an idiom under the bus and see the card."},
        {"speaker": "Liam", "text": "Btw, how is the weather!"},
        {"speaker": "Emma", "text": "Its looking good so far, I think. Was cloudy earlier but the sun is out now."},
        {"speaker": "Liam", "text": "Good to hear that. I am also looking forward to the rest of the day."},
        {"speaker": "Emma", "text": "Same here! Hopefully we can go out and enjoy the sun!"},
        {"speaker": "Liam", "text": "Sounds good!"},
        {"speaker": "Emma", "text": "Thanks for listening, see you next time!"},
        {"speaker": "Liam", "text": "Bye!"}
    ],
}

def mock_annotate(script):
    # Ensure the card is populated even in dummy tests
    if "idiom_windows" not in script or not script["idiom_windows"]:
        script["idiom_windows"] = [
            {
                "idiom": "under the bus", 
                "type": "idiom", 
                "definition": "to sacrifice someone for personal gain", 
                "start_turn": 1, 
                "end_turn": 4
            }
        ]

def mock_gen_english(topic=None):
    return {**dummy_script_base, "title": "Test English Landscape"}

def mock_gen_shorts(topic=None):
    return {**dummy_script_base, "title": "Test English Shorts"}

def mock_gen_quiz(topic=None):
    return {**dummy_script_base, "title": "Test English Quiz"}

def mock_gen_challenge(topic=None):
    return {**dummy_script_base, "title": "Test English Challenge"}

english_generator.generate_english_script = mock_gen_english
english_generator.generate_english_shorts_script = mock_gen_shorts
english_generator.generate_english_quiz_shorts_script = mock_gen_quiz
english_generator.annotate_script_with_idiom_windows = mock_annotate

from manual_run import run_english, run_english_shorts, run_english_quiz_shorts

def test_visuals():
    print("=" * 60)
    print("Testing English Landscape...")
    print("=" * 60)
    # Note: run_english now returns the output path from _upload_video, which can be None.
    out1 = run_english(topic="test", upload=False)
    
    print("\n" + "=" * 60)
    print("Testing English Shorts...")
    print("=" * 60)
    out2 = run_english_shorts(topic="test", upload=False)
    
    print("\n" + "=" * 60)
    print("Testing English Quiz Shorts...")
    print("=" * 60)
    out3 = run_english_quiz_shorts(topic="test", upload=False)
    
    print("\n" + "=" * 60)
    print("ALL TESTS COMPLETED!")
    print("Outputs:")
    print("1. Landscape: ", out1)
    print("2. Shorts (static):    ", out2)
    print("3. Quiz:      ", out3)
    # Challenge logic currently relies on week numbers/json files, so we skip mocking it here for speed, 
    # as English Shorts already test the shorts format visuals perfectly.

if __name__ == "__main__":
    test_visuals()
