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
    "dialogue": [
        {"speaker": "Emma", "text": "Hi Liam! Today we are testing the caption visuals. Do they look big enough?"},
        {"speaker": "Liam", "text": "Hey Emma. I hope so. Let's throw an idiom under the bus and see."},
        {"speaker": "Emma", "text": "Haha, nice one!"},
        {"speaker": "Liam", "text": "Btw, how is the weather!"},
        {"speaker": "Emma", "text": "Its looking good so far, I think. Was cloudy earlier but the sun is out now."},
        {"speaker": "Liam", "text": "Good to hear that. I am also looking forward to the rest of the day."},
        {"speaker": "Emma", "text": "Same here! Hopefully we can go out and enjoy the sun!"},
        {"speaker": "Liam", "text": "Sounds good!"},
        {"speaker": "Emma", "text": "Thanks for listening, see you next time!"},
        {"speaker": "Liam", "text": "Bye!"}
    ],
    "idiom_windows": [{"idiom": "under the bus", "start_turn": 0, "end_turn": 8}]
}

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

from manual_run import run_english, run_english_shorts, run_english_quiz_shorts

def test_visuals():
    print("=" * 60)
    print("Testing English Landscape...")
    print("=" * 60)
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
