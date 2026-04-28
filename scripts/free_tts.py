"""
Free local text-to-speech using Coqui TTS.
Runs entirely on your machine — no API key, no cost, unlimited use.

Install: pip install TTS --break-system-packages
First run downloads the model (~150MB, one-time only).

Usage:
  python free_tts.py "Your script text here" output.mp3
  python free_tts.py --file script.txt output.mp3
"""

import sys
import re
import argparse
from pathlib import Path


def clean_script(text: str) -> str:
    """Strip screenplay markers before sending to TTS."""
    text = re.sub(r'\[VISUAL:[^\]]+\]', '', text)
    text = re.sub(r'\[PAUSE\]', '... ', text)
    text = re.sub(r'\[EMPHASIS\]', '', text)
    text = ' '.join(text.split())
    return text.strip()


def generate_tts(text: str, output_path: str, model: str = "tts_models/en/ljspeech/tacotron2-DDC"):
    """
    Generate speech from text using Coqui TTS.

    Free models (quality order, best first):
      tts_models/en/vctk/vits           — multi-speaker, most natural
      tts_models/en/ljspeech/tacotron2-DDC — single speaker, clear
      tts_models/en/ljspeech/glow-tts    — fast, decent quality

    First run: model downloads automatically (~150MB).
    Subsequent runs: instant, uses cached model.
    """
    try:
        from TTS.api import TTS
    except ImportError:
        print("Coqui TTS not installed. Run:")
        print("  pip install TTS --break-system-packages")
        sys.exit(1)

    print(f"  Loading TTS model: {model}")
    print(f"  (First run downloads ~150MB — subsequent runs are instant)")

    tts = TTS(model_name=model, progress_bar=True)

    # VITS multi-speaker needs a speaker name
    kwargs = {}
    if "vctk" in model:
        kwargs["speaker"] = "p273"  # Clear, neutral voice

    clean_text = clean_script(text)
    print(f"  Generating speech ({len(clean_text)} chars)...")

    tts.tts_to_file(text=clean_text, file_path=output_path, **kwargs)
    print(f"  Saved: {output_path}")
    return output_path


def list_models():
    """Print available free English TTS models."""
    models = [
        ("tts_models/en/vctk/vits",              "Best quality, multi-speaker, ~120MB"),
        ("tts_models/en/ljspeech/tacotron2-DDC", "Good quality, single speaker, ~80MB"),
        ("tts_models/en/ljspeech/glow-tts",      "Fast, decent quality, ~50MB"),
        ("tts_models/en/ljspeech/speedy-speech",  "Very fast, lower quality, ~20MB"),
    ]
    print("\nAvailable free English models:\n")
    for name, desc in models:
        print(f"  {name}")
        print(f"    {desc}\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Free local TTS — no API key needed")
    parser.add_argument("text", nargs="?", help="Text to speak (or use --file)")
    parser.add_argument("output", nargs="?", default="output.mp3", help="Output MP3 path")
    parser.add_argument("--file", help="Read script from a text file")
    parser.add_argument("--model", default="tts_models/en/ljspeech/tacotron2-DDC",
                        help="Coqui TTS model to use")
    parser.add_argument("--list-models", action="store_true", help="Show available models")

    args = parser.parse_args()

    if args.list_models:
        list_models()
        sys.exit(0)

    if args.file:
        text = Path(args.file).read_text()
    elif args.text:
        text = args.text
    else:
        print("Provide text or --file. Example:")
        print('  python free_tts.py "Hello world" output.mp3')
        print('  python free_tts.py --file script.txt output.mp3')
        sys.exit(1)

    generate_tts(text, args.output, args.model)
