import os
import json
import pytest
from pathlib import Path
from scripts import manual_run
from scripts.english_assembler import (
    _pause_duration_seconds,
    generate_podcast_audio,
    assemble_english_video,
    cleanup_english_temp,
    get_audio_duration,
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


def test_align_scenes_to_turns_clamps_invalid_ranges():
    """Test that invalid scene ranges (end < start) are clamped and last scene is extended."""
    dialogue = [{"speaker": "Emma", "text": f"Line {i}"} for i in range(10)]
    
    # Simulate AI generating incorrect ranges (scene 2 has end < start)
    scenes = [
        {"scene_id": 1, "start_turn": 0, "end_turn": 5, "image_filename": "scene_1.png"},
        {"scene_id": 2, "start_turn": 6, "end_turn": 5, "image_filename": "scene_2.png"},  # Invalid: end < start
    ]
    
    aligned = align_scenes_to_turns(scenes, dialogue)
    
    # Scene 1 keeps its range, Scene 2 is clamped (end >= start), last scene extended to end
    assert len(aligned) == 2
    assert aligned[0]["start_turn"] == 0
    assert aligned[0]["end_turn"] == 5
    assert aligned[1]["start_turn"] == 6
    assert aligned[1]["end_turn"] == 9  # Last scene forced to final turn


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
    """Test that natural pauses are padded into dialogue turn durations."""
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
    
    # Should have exactly 4 entries — one per dialogue turn (gaps absorbed into each turn)
    assert len(turn_times) == 4
    
    # Turns must be contiguous (no silent gaps between entries that would desync visual timing)
    for i in range(len(turn_times) - 1):
        assert turn_times[i][1] == turn_times[i+1][0], \
            f"Turn {i} end ({turn_times[i][1]:.3f}s) != Turn {i+1} start ({turn_times[i+1][0]:.3f}s)"
    
    # Total duration must match the actual audio file (no trailing silence or truncation)
    total_dur = turn_times[-1][1]
    audio_dur = get_audio_duration(audio_path)
    assert abs(total_dur - audio_dur) < 0.05, \
        f"Turn times sum ({total_dur:.3f}s) != audio duration ({audio_dur:.3f}s)"
    
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


@pytest.mark.skipif(
    not Path("kokoro-v0_19.onnx").exists() and not Path("kokoro-v1.0.onnx").exists()
    or not Path("assets/english_visuals/test_loop.mp4").exists(),
    reason="Requires Kokoro TTS model files and test_loop.mp4 asset"
)
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
