import json
import random
import sys
from pathlib import Path

# Add the scripts directory to sys.path so we can import local modules
current_dir = Path(__file__).parent
sys.path.insert(0, str(current_dir))

from manual_run import slug
from english_assembler import generate_podcast_audio, assemble_english_video, cleanup_english_temp
from ffmpeg_assembler import generate_captions
from youtube_uploader import youtube_upload

PROJECT_ROOT = current_dir.parent
ASSETS_DIR = PROJECT_ROOT / "assets"
OUTPUT_DIR = PROJECT_ROOT / "output"

def main():
    json_file = current_dir / "output" / "english_podcast.json"
    if not json_file.exists():
        print("Could not find english_podcast.json!")
        sys.exit(1)
        
    script = json.loads(json_file.read_text(encoding="utf-8"))
    
    title = script["title"]
    out_slug = slug(title)
    
    print(f"\n==========================================")
    print(f"Re-generating video for: {title}")
    print(f"==========================================\n")
    
    # 1. Generate audio
    audio_path = generate_podcast_audio(script)
    
    # 2. Generate captions
    srt_path = str(OUTPUT_DIR / f"{out_slug}.srt")
    try:
        generate_captions(audio_path, srt_path)
    except Exception as e:
        print(f"  Captions skipped: {e}")
        srt_path = None
        
    # 3. Pick random background visual
    visuals_dir = ASSETS_DIR / "english_visuals"
    visual_files = sorted(visuals_dir.glob("*.mp4"))
    if not visual_files:
        print("No video files found in assets/english_visuals/")
        sys.exit(1)
        
    visual_path = random.choice(visual_files)
    
    # Background music
    bg_music = ASSETS_DIR / "background_music.mp3"
    bg_music_str = str(bg_music) if bg_music.exists() else None
    
    # 4. Assemble Video
    out_path = str(OUTPUT_DIR / f"{out_slug}.mp4")
    assemble_english_video(
        podcast_audio=audio_path,
        loop_visual=str(visual_path),
        output_path=out_path,
        captions_srt=srt_path,
        background_music=bg_music_str,
        title=title
    )
    
    cleanup_english_temp()
    
    print("\nStarting upload to YouTube...")
    try:
        youtube_upload(
            video_path=out_path,
            title=title,
            description=script.get("description", ""),
            tags=script.get("tags", []),
            channel="english"
        )
        print("\nUpload completed successfully!")
    except Exception as e:
        print(f"\nUpload failed: {e}")

if __name__ == "__main__":
    main()
