import os
import subprocess
import math
from pathlib import Path

# Fix absolute imports for modules in scripts/
import sys
sys.path.insert(0, str(Path(__file__).parent))

from ffmpeg_assembler import get_audio_duration, TEMP_DIR, OUTPUT_DIR, ASSETS_DIR, FFMPEG, VIDEO_WIDTH, VIDEO_HEIGHT, VIDEO_FPS
from kokoro_tts import synthesize

ENGLISH_VOICES = {
    "Emma": "af_heart",
    "Liam": "am_echo"
}

def generate_podcast_audio(script_data: dict) -> str:
    """
    Generate TTS for each line of dialogue using the designated voices,
    then concatenate them into a single audio file.
    """
    TEMP_DIR.mkdir(exist_ok=True)
    dialogue = script_data.get("dialogue", [])
    
    audio_files = []
    
    print("\nGenerating podcast audio...")
    for i, line in enumerate(dialogue):
        speaker = line.get("speaker", "Emma")
        text = line.get("text", "")
        voice = ENGLISH_VOICES.get(speaker, "af_sarah")
        
        out_path = str(TEMP_DIR / f"english_line_{i:03d}.m4a")
        
        try:
            print(f"  [{speaker}] -> {out_path}")
            # we use speed=1.0 for a more relaxed learning pace
            synthesize(text, out_path, voice=voice, speed=0.95)
            audio_files.append(out_path)
        except Exception as e:
            print(f"  Error generating audio for line {i}: {e}")
    
    # Concatenate all generated dialogue lines
    concat_list_path = str(TEMP_DIR / "english_audio_list.txt")
    with open(concat_list_path, "w") as f:
        for audio_file in audio_files:
            f.write(f"file '{os.path.abspath(audio_file)}'\n")
            
    final_audio_path = str(TEMP_DIR / "english_podcast_full.m4a")
    
    cmd = [
        FFMPEG, "-y",
        "-f", "concat", "-safe", "0", "-i", concat_list_path,
        "-c:a", "aac", "-b:a", "192k",
        final_audio_path
    ]
    subprocess.run(cmd, capture_output=True, check=True)
    
    print(f"  ✓ Full podcast audio generated: {final_audio_path}")
    return final_audio_path

def assemble_english_video(
    podcast_audio: str,
    loop_visual: str,
    output_path: str,
    captions_srt: str = None,
    background_music: str = None,
    title: str = ""
) -> str:
    """
    Assemble the final English learning video:
    - Loops the background visual
    - Mixes the podcast audio with subtle background music
    - Burns subtitles
    """
    duration = get_audio_duration(podcast_audio)
    print(f"\nAssembling English video: {duration:.1f}s")
    
    # 1. Normalize visual to correct size/fps first
    norm_visual = str(TEMP_DIR / "english_norm.mp4")
    subprocess.run([
        FFMPEG, "-y", "-i", loop_visual,
        "-vf", f"scale={VIDEO_WIDTH}:{VIDEO_HEIGHT}:force_original_aspect_ratio=decrease,"
               f"pad={VIDEO_WIDTH}:{VIDEO_HEIGHT}:(ow-iw)/2:(oh-ih)/2:black,"
               f"fps={VIDEO_FPS}",
        "-c:v", "libx264", "-preset", "fast", "-crf", "23",
        "-an", norm_visual, "-loglevel", "error"
    ], check=True)
    print(f"  Visual normalized")

    # 2. Mix podcast audio with background music
    if background_music and Path(background_music).exists():
        mixed_audio_path = str(TEMP_DIR / "english_mixed_audio.m4a")
        cmd = [
            FFMPEG, "-y",
            "-i", podcast_audio,
            "-stream_loop", "-1", "-i", background_music,
            "-filter_complex",
            "[0:a]volume=1.0[narr];[1:a]volume=0.08[bg];[narr][bg]amix=inputs=2:duration=first:dropout_transition=3[out]",
            "-map", "[out]",
            "-t", str(duration),
            "-c:a", "aac", "-b:a", "192k",
            mixed_audio_path
        ]
        subprocess.run(cmd, capture_output=True, check=True)
        print(f"  Audio mixed with background music")
        final_audio = mixed_audio_path
    else:
        final_audio = podcast_audio
        
    # 3. Combine visual loop + audio + subtitles
    caption_style = (
        "FontName=Arial,"
        "FontSize=22,"
        "PrimaryColour=&H0000FFFF,"
        "OutlineColour=&H00000000,"
        "BackColour=&H80000000,"
        "Bold=1,"
        "BorderStyle=3,"
        "Outline=1,"
        "Shadow=0,"
        "MarginV=40"
    )

    has_captions = captions_srt and Path(captions_srt).exists()
    vf_filter = f"subtitles={captions_srt}:force_style='{caption_style}'" if has_captions else "null"

    cmd = [
        FFMPEG, "-y",
        "-stream_loop", "-1", "-i", norm_visual,
        "-i", final_audio,
        "-vf", vf_filter,
        "-map", "0:v", "-map", "1:a",
        "-t", str(duration),
        "-c:v", "libx264", "-preset", "medium", "-crf", "20",
        "-c:a", "copy",
        "-movflags", "+faststart",
        "-metadata", f"title={title}",
        output_path, "-loglevel", "error"
    ]
    
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"  Caption burn failed, assembling without captions...")
        cmd = [
            FFMPEG, "-y",
            "-stream_loop", "-1", "-i", norm_visual,
            "-i", final_audio,
            "-map", "0:v", "-map", "1:a",
            "-t", str(duration),
            "-c:v", "libx264", "-preset", "medium", "-crf", "20",
            "-c:a", "copy", "-movflags", "+faststart",
            output_path, "-loglevel", "error"
        ]
        subprocess.run(cmd, capture_output=True, check=True)

    size_mb = Path(output_path).stat().st_size / 1024 / 1024
    print(f"  ✓ English video assembled: {output_path} ({size_mb:.1f} MB)")
    return output_path

def cleanup_english_temp():
    import shutil
    if TEMP_DIR.exists():
        shutil.rmtree(TEMP_DIR)
        TEMP_DIR.mkdir()
    print("  Temp files cleaned.")
