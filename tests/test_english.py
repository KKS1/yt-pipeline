import os
import json
from pathlib import Path
from scripts.english_assembler import generate_podcast_audio, assemble_english_video, cleanup_english_temp

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
        title=script["title"]
    )
    
    print("Done. Output at:", out_path)

if __name__ == "__main__":
    test_pipeline()
