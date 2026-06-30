import os
import json
from pathlib import Path
from scripts import manual_run
from scripts.english_assembler import (
    _pause_duration_seconds,
    generate_podcast_audio,
    assemble_english_video,
    cleanup_english_temp,
)
from scripts.english_generator import align_scenes_to_turns


def test_pause_duration_seconds_parses_prompt_pause_cues():
    assert _pause_duration_seconds("[PAUSE 3 SECONDS]") == 3.0
    assert _pause_duration_seconds("[pause]") == 1.0
    assert _pause_duration_seconds("Say this out loud.") is None


def test_select_english_visuals_prefers_script_keywords():
    visuals = [
        Path("assets/english_visuals/flow_mountains1.mp4"),
        Path("assets/english_visuals/glimmer_drink_coffee1.mp4"),
        Path("assets/english_visuals/library_reading.mp4"),
    ]
    script = {
        "title": "English Listening Practice at the Coffee Shop",
        "visual_keywords": ["cafe", "coffee", "conversation"],
    }

    selected = manual_run._select_english_visuals(script, visuals, max_count=2)

    assert selected[0].name == "glimmer_drink_coffee1.mp4"


def test_align_scenes_to_turns_redistributes_incorrect_ranges():
    """Test that scene turns are redistributed correctly when AI generates invalid ranges."""
    dialogue = [{"speaker": "Emma", "text": f"Line {i}"} for i in range(10)]
    
    # Simulate AI generating incorrect ranges (scene 2 has end < start)
    scenes = [
        {"scene_id": 1, "start_turn": 0, "end_turn": 5, "image_filename": "scene_1.png"},
        {"scene_id": 2, "start_turn": 6, "end_turn": 5, "image_filename": "scene_2.png"},  # Invalid: end < start
    ]
    
    aligned = align_scenes_to_turns(scenes, dialogue)
    
    # Should redistribute turns evenly: 10 turns / 2 scenes = 5 turns each
    assert len(aligned) == 2
    assert aligned[0]["start_turn"] == 0
    assert aligned[0]["end_turn"] == 4
    assert aligned[1]["start_turn"] == 5
    assert aligned[1]["end_turn"] == 9  # Last scene covers to the end


def test_align_scenes_to_turns_handles_remainder():
    """Test that scene turns handle remainder distribution correctly."""
    dialogue = [{"speaker": "Emma", "text": f"Line {i}"} for i in range(11)]
    
    scenes = [
        {"scene_id": 1, "start_turn": 0, "end_turn": 3, "image_filename": "scene_1.png"},
        {"scene_id": 2, "start_turn": 4, "end_turn": 7, "image_filename": "scene_2.png"},
        {"scene_id": 3, "start_turn": 8, "end_turn": 10, "image_filename": "scene_3.png"},
    ]
    
    aligned = align_scenes_to_turns(scenes, dialogue)
    
    # 11 turns / 3 scenes = 3 turns each with 2 remainder distributed to first 2 scenes
    assert len(aligned) == 3
    assert aligned[0]["start_turn"] == 0
    assert aligned[0]["end_turn"] == 3  # 4 turns (3 + 1 remainder)
    assert aligned[1]["start_turn"] == 4
    assert aligned[1]["end_turn"] == 7  # 4 turns (3 + 1 remainder)
    assert aligned[2]["start_turn"] == 8
    assert aligned[2]["end_turn"] == 10  # 3 turns

def test_pipeline():
    cleanup_english_temp()
    
    script = {
        "title": "Test Podcast",
        "description": "Just a test",
        "tags": ["test"],
        "dialogue": [
            {"speaker": "Emma", "text": "Hello Liam, how are you today?"},
            {"speaker": "Liam", "text": "I am doing great Emma, thanks for asking!"}
        ]
    }
    
    print("Generating audio...")
    audio_path = generate_podcast_audio(script)
    
    visual_path = "assets/english_visuals/test_loop.mp4"
    out_path = "output/test_english_video.mp4"
    
    # We will skip subtitles for this quick test unless they exist, we pass None
    print("Assembling video...")
    assemble_english_video(
        podcast_audio=audio_path,
        loop_visual=visual_path,
        output_path=out_path,
        captions_srt=None,
        background_music="assets/background_music.mp3" if os.path.exists("assets/background_music.mp3") else None,
        title=script["title"],
        portrait=False
    )
    
    print("Done. Output at:", out_path)

if __name__ == "__main__":
    test_pipeline()
