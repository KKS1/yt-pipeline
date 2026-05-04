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
import os
import wave
import tempfile
import argparse
from pathlib import Path


def clean_script(text: str) -> str:
    """Strip screenplay markers before sending to TTS."""
    text = re.sub(r'\[VISUAL:[^\]]+\]', '', text)
    text = re.sub(r'\[PAUSE\]', '... ', text)
    text = re.sub(r'\[EMPHASIS\]', '', text)
    text = ' '.join(text.split())
    return text.strip()


def _generate_chunked(tts, text: str, output_path: str, kwargs: dict, chunk_size: int = 500):
    """Split long text into sentence-boundary chunks and concat the audio."""
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

    print(f"  Splitting into {len(chunks)} chunks...")

    tmp_files = []
    for i, chunk in enumerate(chunks):
        tmp = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
        tmp.close()
        tts.tts_to_file(text=chunk, file_path=tmp.name, **kwargs)
        tmp_files.append(tmp.name)
        print(f"  Chunk {i+1}/{len(chunks)} done")

    # Concatenate all wav chunks into final output
    wav_out = output_path.replace(".mp3", ".wav")
    with wave.open(wav_out, "wb") as out_wav:
        for i, f in enumerate(tmp_files):
            with wave.open(f, "rb") as in_wav:
                if i == 0:
                    out_wav.setparams(in_wav.getparams())
                out_wav.writeframes(in_wav.readframes(in_wav.getnframes()))

    for f in tmp_files:
        os.unlink(f)

    # Convert wav to mp3 via ffmpeg (already a dependency in your pipeline)
    os.system(f'ffmpeg -y -i "{wav_out}" -q:a 2 "{output_path}" -loglevel quiet')
    os.unlink(wav_out)


def generate_tts(text: str, output_path: str, model: str = "tts_models/en/ljspeech/tacotron2-DDC"):
    """
    Generate speech from text using Coqui TTS.

    Free models (quality order, best first):
      tts_models/en/vctk/vits              — multi-speaker, most natural
      tts_models/en/ljspeech/tacotron2-DDC — single speaker, clear
      tts_models/en/ljspeech/glow-tts      — fast, decent quality

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

    # Raise decoder cap — default 10000 cuts off long scripts
    if hasattr(tts, "synthesizer") and hasattr(tts.synthesizer, "tts_config"):
        tts.synthesizer.tts_config.max_decoder_steps = 50000

    kwargs = {}
    if "vctk" in model:
        kwargs["speaker"] = "p273"  # Clear, neutral voice

    clean_text = clean_script(text)
    print(f"  Generating speech ({len(clean_text)} chars)...")

    # Chunk long scripts so the decoder never strains on one huge input
    if len(clean_text) > 500:
        _generate_chunked(tts, clean_text, output_path, kwargs)
    else:
        tts.tts_to_file(text=clean_text, file_path=output_path, **kwargs)

    print(f"  Saved: {output_path}")
    return output_path


def list_models():
    """Print available free English TTS models."""
    models = [
        ("tts_models/en/vctk/vits",               "Best quality, multi-speaker, ~120MB"),
        ("tts_models/en/ljspeech/tacotron2-DDC",  "Good quality, single speaker, ~80MB"),
        ("tts_models/en/ljspeech/glow-tts",       "Fast, decent quality, ~50MB"),
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
    