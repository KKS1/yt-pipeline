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
KOKORO_MODEL  = str(PROJECT_ROOT / "kokoro-v0_19.onnx")
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
        print("  curl -L -o kokoro-v0_19.onnx https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files/kokoro-v0_19.onnx")
        print("  curl -L -o voices.bin https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files/voices.bin")
        sys.exit(1)

    return Kokoro(model, voices)


def clean_text(text: str) -> str:
    """Strip screenplay markers before sending to TTS."""
    text = re.sub(r'\[VISUAL:[^\]]+\]', '', text)
    text = re.sub(r'\[PAUSE\]', '... ', text)
    text = re.sub(r'\[EMPHASIS\]', '', text)
    text = re.sub(r'\(.*?\)', '', text)
    text = ' '.join(text.split())
    return text.strip()


def synthesize(
    text: str,
    output_path: str,
    voice: str = "af_sarah",
    speed: float = 1.05,
    chunk_size: int = 300,
) -> str:
    import numpy as np

    k = get_kokoro()
    text = clean_text(text)

    print(f"  Synthesizing ({len(text)} chars, voice={voice}, speed={speed})...")

    sentences = re.split(r'(?<=[.!?])\s+', text)
    chunks, current = [], ""

    for s in sentences:
        if len(current) + len(s) < chunk_size:
            current += (" " if current else "") + s
        else:
            if current:
                chunks.append(current)
            current = s
    if current:
        chunks.append(current)

    all_samples = []
    sample_rate = None

    for i, chunk in enumerate(chunks):
        samples, sr = k.create(chunk, voice=voice, speed=speed)
        all_samples.append(samples)
        sample_rate = sr
        print(f"  Chunk {i+1}/{len(chunks)} done")

    combined = np.concatenate(all_samples)

    wav_path = str(Path(output_path).with_suffix(".wav"))
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
        output_path,
        "-loglevel", "error"
    ], check=True)

    Path(wav_path).unlink()
    print(f"  Saved: {output_path}")
    return output_path
    