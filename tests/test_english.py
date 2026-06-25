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
