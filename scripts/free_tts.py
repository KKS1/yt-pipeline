"""
Free local text-to-speech using Kokoro.
Runs entirely on your machine — no API key, no cost, unlimited use.

Install:
  pip install kokoro-onnx soundfile --break-system-packages
  brew install espeak-ng

Model files in project root (one-time download ~80MB):
  curl -L -o kokoro-v0_19.onnx https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files/kokoro-v0_19.onnx
  curl -L -o voices.bin https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files/voices.bin

Usage:
  python free_tts.py "Your script text here" output.mp3
  python free_tts.py --file script.txt output.mp3
"""

import sys
import argparse
from pathlib import Path

# Import shared Kokoro utility
sys.path.insert(0, str(Path(__file__).parent))
from kokoro_tts import synthesize, clean_text, VOICE_MAP


def clean_script(text: str) -> str:
    """Public alias used by manual_run.py."""
    return clean_text(text)


def generate_tts(
    text: str,
    output_path: str,
    voice: str = "af_sarah",
    speed: float = 1.05,
) -> str:
    """
    Generate speech from text using Kokoro.
    Drop-in replacement for old Coqui-based generate_tts().

    Voices:
      af_sarah  — warm, friendly
      af_bella  — authoritative, clear (default for trending)
      af_nicole — soft, calm
      af_sky    — energetic
    """
    return synthesize(text, output_path, voice=voice, speed=speed)


def list_voices():
    voices = [
        ("af_sarah",  "Warm, friendly — great for family content"),
        ("af_bella",  "Authoritative, clear — great for trending/narration"),
        ("af_nicole", "Soft, calm — great for ambient narration"),
        ("af_sky",    "Energetic, upbeat"),
    ]
    print("\nAvailable voices:\n")
    for name, desc in voices:
        print(f"  {name}")
        print(f"    {desc}\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Free local TTS using Kokoro")
    parser.add_argument("text", nargs="?", help="Text to speak (or use --file)")
    parser.add_argument("output", nargs="?", default="output.mp3", help="Output path")
    parser.add_argument("--file", help="Read script from a text file")
    parser.add_argument("--voice", default="af_bella", help="Kokoro voice to use")
    parser.add_argument("--speed", type=float, default=1.1, help="Speech speed (default 1.1)")
    parser.add_argument("--list-voices", action="store_true", help="Show available voices")

    args = parser.parse_args()

    if args.list_voices:
        list_voices()
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

    generate_tts(text, args.output, voice=args.voice, speed=args.speed)
    