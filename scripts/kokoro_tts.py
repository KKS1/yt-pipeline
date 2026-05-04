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

import sys
import re
import soundfile as sf
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
KOKORO_MODEL = str(PROJECT_ROOT / "kokoro-v0_19.onnx")
KOKORO_VOICES = str(PROJECT_ROOT / "voices.bin")

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
    text = re.sub(r'\(.*?\)', '', text)  # Remove parenthetical directions
    text = ' '.join(text.split())
    return text.strip()


def synthesize(
    text: str,
    output_path: str,
    voice: str = "af_sarah",
    speed: float = 1.1,
    chunk_size: int = 300,
) -> str:
    """
    Synthesize text to audio file using Kokoro.
    Automatically chunks long text at sentence boundaries.
    Returns output_path.
    """
    import numpy as np

    k = get_kokoro()
    text = clean_text(text)

    print(f"  Synthesizing ({len(text)} chars, voice={voice}, speed={speed})...")

    # Chunk at sentence boundaries
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

    # Always save as wav first, convert to mp3 via ffmpeg if needed
    output_path = str(output_path)
    if output_path.endswith(".mp3"):
        wav_path = output_path.replace(".mp3", ".wav")
        sf.write(wav_path, combined, sample_rate)
        import subprocess
        subprocess.run(
            ["ffmpeg", "-y", "-i", wav_path, "-q:a", "2", output_path, "-loglevel", "quiet"],
            check=True
        )
        Path(wav_path).unlink()
    else:
        sf.write(output_path, combined, sample_rate)

    print(f"  Saved: {output_path}")
    return output_path
    