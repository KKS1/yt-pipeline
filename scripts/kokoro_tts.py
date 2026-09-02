"""
Shared Kokoro TTS utility.
Used by free_tts.py (trending) and family_assembler.py (family).

Model files must be in project root:
  kokoro-v0_19.onnx
  voices.bin

Voices:
  af_sarah  — warm, friendly (family)
  af_bella  — authoritative (trending)
  af_nicole — soft, calm (ambient/narration)
  af_sky    — energetic
"""

import os
import sys
import re
import subprocess
import soundfile as sf
from pathlib import Path

PROJECT_ROOT  = Path(__file__).parent.parent
KOKORO_MODEL  = str(PROJECT_ROOT / "kokoro-v1.0.onnx")
KOKORO_VOICES = str(PROJECT_ROOT / "voices.bin")

# Use ffmpeg_static if available (needed on Mac where brew ffmpeg lacks drawtext)
FFMPEG = os.environ.get("FFMPEG_CMD", "ffmpeg")

VOICE_MAP = {
    "family":   "af_sarah",
    "trending": "af_bella",
    "lofi":     "af_nicole",
    "default":  "af_sarah",
}


def get_kokoro(model: str = KOKORO_MODEL, voices: str = KOKORO_VOICES):
    """Load and return Kokoro instance."""
    try:
        from kokoro_onnx import Kokoro
    except ImportError:
        print("Kokoro not installed. Run:")
        print("  pip install kokoro-onnx soundfile --break-system-packages")
        sys.exit(1)

    if not Path(model).exists():
        print(f"Kokoro model not found: {model}")
        print("Download from:")
        print("  curl -L -o kokoro-v1.0.onnx https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/kokoro-v1.0.onnx")
        print("  curl -L -o voices.bin https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/voices-v1.0.bin")
        sys.exit(1)

    return Kokoro(model, voices)


def clean_text(text: str) -> str:
    """Strip screenplay markers before sending to TTS."""
    text = re.sub(r'\[VISUAL:[^\]]+\]', '', text)
    text = re.sub(r'\[PAUSE\]', '... ', text)
    # Replace "___" blanks with pause for audio indication
    text = re.sub(r'___', '... ', text)
    # Convert markdown bold to emphasis marker for TTS (keep for caption processing)
    text = re.sub(r'\*\*(.*?)\*\*', r'[EMPHASIS]\1[/EMPHASIS]', text)
    # Strip single-asterisk markdown emphasis (e.g. *hold the*) — TTS would vocalize as "asterisk"
    text = re.sub(r'\*(.*?)\*', r'\1', text)
    text = re.sub(r'\(.*?\)', '', text)
    text = re.sub(r'\bphrasal\b', 'phrase', text, flags=re.IGNORECASE)
    # Strip emoji so TTS doesn't vocalize them (e.g. 💬 → "Speech bubble")
    text = re.sub(r'[\U0001F300-\U0001FAFF\U00002702-\U000027B0\U000024C2-\U0001F251\U0001F900-\U0001F9FF\U0000200D\uFE0F]', '', text)
    # Replace common slash phrases and abbreviations
    text = re.sub(r'\band/or\b', 'and or', text, flags=re.IGNORECASE)
    text = re.sub(r'\beither/or\b', 'either or', text, flags=re.IGNORECASE)
    text = re.sub(r'\bw/o\b', 'without', text, flags=re.IGNORECASE)
    text = re.sub(r'\bw/(?=\s|[.,!?]|$)', 'with', text, flags=re.IGNORECASE)
    text = re.sub(r'\s*/\s*or\b', ' or', text, flags=re.IGNORECASE)
    text = re.sub(r'\s*/\s*', ' or ', text)
    text = ' '.join(text.split())
    return text.strip()


def synthesize(
    text: str,
    output_path: str,
    voice: str = "af_sarah",
    speed: float = 1.05,
    chunk_size: int = 300,
    speaker: str = None,
) -> str:
    import numpy as np

    k = get_kokoro()
    text = clean_text(text)

    print(f"  Synthesizing ({len(text)} chars, voice={voice}, speed={speed})...")

    # Apply emphasis processing for all dialogue speakers
    EMPHASIS_ENABLED_SPEAKERS = {
        "Narrator", "Emma", "Liam", "Guest",
        "StoryActor1", "StoryActor2", "Caller", "Caller_Male",
        "StoryActor1_Female", "StoryActor2_Male",
        "StoryActor1_AltMale", "StoryActor2_AltFemale",
    }
    use_emphasis = speaker in EMPHASIS_ENABLED_SPEAKERS

    if use_emphasis:
        # Split by emphasis markers and track which parts are emphasized
        emphasis_pattern = re.compile(r'\[EMPHASIS\](.*?)\[/EMPHASIS\]')
        parts = []
        pos = 0
        for match in emphasis_pattern.finditer(text):
            # Add non-emphasized part before this match
            if match.start() > pos:
                parts.append((text[pos:match.start()], False))
            # Add emphasized part
            parts.append((match.group(1), True))
            pos = match.end()
        # Add remaining text
        if pos < len(text):
            parts.append((text[pos:], False))

        # If no emphasis markers found, treat entire text as non-emphasized
        if not parts:
            parts = [(text, False)]
    else:
        # For speakers without emphasis support (family, trending, etc.), strip markers
        text = re.sub(r'\[/?EMPHASIS\]', '', text).strip()
        parts = [(text, False)]

    # Group parts into chunks by character count
    chunks = []
    current_chunk = []
    current_chars = 0
    for part_text, is_emphasis in parts:
        part_text_clean = re.sub(r'\[/?EMPHASIS\]', '', part_text).strip()
        if not part_text_clean:
            continue
        if current_chars + len(part_text_clean) < chunk_size:
            current_chunk.append((part_text_clean, is_emphasis))
            current_chars += len(part_text_clean)
        else:
            if current_chunk:
                chunks.append(current_chunk)
            current_chunk = [(part_text_clean, is_emphasis)]
            current_chars = len(part_text_clean)
    if current_chunk:
        chunks.append(current_chunk)

    all_samples = []
    sample_rate = None

    for i, chunk in enumerate(chunks):
        chunk_samples = []
        for part_text, is_emphasis in chunk:
            # Use slightly slower speed for emphasized parts (only for Narrator)
            part_speed = speed * 0.95 if is_emphasis and use_emphasis else speed
            samples, sr = k.create(part_text, voice=voice, speed=part_speed)
            chunk_samples.append(samples)
            sample_rate = sr
        if chunk_samples:
            all_samples.append(np.concatenate(chunk_samples))
        print(f"  Chunk {i+1}/{len(chunks)} done")

    if all_samples:
        combined = np.concatenate(all_samples)
    else:
        combined = np.array([])

    wav_path = str(Path(output_path).with_suffix(".wav"))
    output_path = str(Path(output_path).with_suffix(".m4a"))
    sf.write(wav_path, combined, sample_rate)

    # 🔥 Normalize to broadcast quality
    subprocess.run([
        FFMPEG, "-y", "-i", wav_path,
        "-af",
        "highpass=f=80,loudnorm=I=-16:TP=-1.5:LRA=11",
        "-ar", "48000",
        "-ac", "2",
        "-c:a", "aac",
        "-b:a", "192k",
        "-preset", "ultrafast",
        str(Path(output_path).with_suffix(".m4a")),
        "-loglevel", "error"
    ], check=True)

    Path(wav_path).unlink()
    print(f"  Saved: {output_path}")
    return output_path
    