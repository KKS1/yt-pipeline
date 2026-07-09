# yt-pipeline — AGENTS.md

## Entrypoints

- `python scripts/manual_run.py --channel trending|family|lofi` — single-video run
- `python scripts/manual_run.py --channel english` — two-phase: `--manifest-only` then `--resume-from-manifest manifests/<slug>.manifest.json`
- `python scripts/manual_run.py --channel english-challenge --topic "..." --start-date YYYY-MM-DD`
- `python scripts/manual_run.py --channel english-shorts|english-quiz|english-challenge-shorts`
- `python scripts/server.py` — Flask API bridge for n8n (port 5001)
- `n8n_start.sh` — sources `.env` then `n8n start`

## Tests

```sh
python -m pytest tests/ -v
```

Mix of plain pytest functions and `unittest.TestCase`. Some tests (English audio) require Kokoro model files in project root. Bumper tests mock paths.

## Key gotchas

- **sys.path**: All scripts use `sys.path.insert(0, ...)` — never call them from outside the repo root.
- **FFMPEG_CMD**: Set to `ffmpeg_static` on macOS (brew's ffmpeg lacks `drawtext`). Default `ffmpeg`.
- **Kokoro model files**: `kokoro-v0_19.onnx` / `kokoro-v1.0.onnx` + `voices.bin` in project root (~300MB, gitignored). Required for local TTS.
- **Groq free tier**: Set `GROQ_PART_COOLDOWN_SEC=25` between English 3-part calls; `GROQ_ENGLISH_MAX_TOKENS=4096`.
- **Gemini image gen**: Uses `gemini-2.5-flash-image` model, daily limit 490, 2s sleep between calls. Set `GEMINI_API_KEY`.
- **YouTube uploads**: Always **unlisted** — publish manually in YouTube Studio.
- **Playlist URL**: Use `{playlist_url}` placeholder in descriptions (replaced at upload time).
- **Timezone**: `America/Regina` (no DST). Set `LOCAL_TIMEZONE` in `.env`.
- **`.env` keys**: Live credentials are committed to `.env` — do not hardcode or regenerate unless intended.

## Structure

| Path | Role |
|---|---|
| `scripts/` | All pipeline code (no package, uses sys.path imports) |
| `prompts/` | Claude prompt templates (`claude_prompts.py`) |
| `n8n/workflow.json` | Import into n8n instance |
| `tests/` | Pytest suite |
| `assets/bumpers/<channel>/` | Optional intro/outro MP4s |
| `assets/generated_scenes/` | Scene images for English pipeline |
| `manifests/` | Two-phase pipeline manifests (gitignored) |
| `output/` | Assembled videos (gitignored) |

## Channels & credential files

YouTube credentials: `assets/yt_credentials_<channel>.json` (e.g. `yt_credentials_english.json`). English sub-channels (shorts, quiz, challenge) all use `yt_credentials_english.json`.

## Pipeline notes

- English podcasts use Kokoro TTS with multi-voice dialogue (Emma/Liam/Narrator/Guest).
- Scene durations driven by actual TTS audio, not estimates.
- Family channel uses photo-first card format with Pexels images.
- Captions use `.ass` format (Advanced Sub Station Alpha) with karaoke highlighting.
- `--no-upload` flag skips YouTube publish; `--skip-gemini` skips scene image generation.
