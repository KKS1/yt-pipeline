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

def test_conversation_pauses_added_between_turns():
    """Test that natural pauses are added between conversation turns."""
    cleanup_english_temp()
    
    script = {
        "title": "Test Pauses",
        "dialogue": [
            {"speaker": "Emma", "text": "Hello there."},
            {"speaker": "Liam", "text": "Hi Emma."},
            {"speaker": "Narrator", "text": "They greeted each other."},
            {"speaker": "Emma", "text": "Thanks for explaining."},
        ]
    }
    
    audio_path, turn_times = generate_podcast_audio(script, return_turn_times=True)
    
    # Should have 4 dialogue turns + 3 gap pauses = 7 total segments
    assert len(turn_times) == 7
    
    # Check that gaps exist between turns
    # Emma -> Liam: 300ms gap (turn 1)
    gap_1_duration = turn_times[1][1] - turn_times[1][0]
    assert 0.29 < gap_1_duration < 0.31, f"Expected ~300ms gap, got {gap_1_duration}"
    
    # Liam -> Narrator: 400ms gap (turn 3) - entering Narrator
    gap_2_duration = turn_times[3][1] - turn_times[3][0]
    assert 0.39 < gap_2_duration < 0.41, f"Expected ~400ms gap, got {gap_2_duration}"
    
    # Narrator -> Emma: 400ms gap (turn 5) - exiting Narrator
    gap_3_duration = turn_times[5][1] - turn_times[5][0]
    assert 0.39 < gap_3_duration < 0.41, f"Expected ~400ms gap, got {gap_3_duration}"
    
    print("✓ Conversation pauses test passed")


def test_no_additional_pause_before_explicit_pause_token():
    """Test that no gap is added before an explicit [PAUSE X SECONDS] token."""
    cleanup_english_temp()
    
    script = {
        "title": "Test No Double Pause",
        "dialogue": [
            {"speaker": "Emma", "text": "What is the answer?"},
            {"speaker": "Narrator", "text": "[PAUSE 3 SECONDS]"},
            {"speaker": "Liam", "text": "The answer is forty-two."},
        ]
    }
    
    audio_path, turn_times = generate_podcast_audio(script, return_turn_times=True)
    
    # Should have 3 dialogue turns (no gap before pause token, no gap after pause token)
    # Emma -> Pause -> Liam (no gaps added because pause token already provides silence)
    assert len(turn_times) == 3
    
    # Emma turn should be first
    assert turn_times[0][0] == 0.0
    
    # Pause should be 3 seconds
    pause_duration = turn_times[1][1] - turn_times[1][0]
    assert 2.9 < pause_duration < 3.1, f"Expected ~3s pause, got {pause_duration}"
    
    # Liam should come after pause with no additional gap
    liam_start = turn_times[2][0]
    pause_end = turn_times[1][1]
    assert liam_start == pause_end, f"Liam should start immediately after pause, but gap is {liam_start - pause_end}s"
    
    print("✓ No double pause test passed")


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
