# yt-pipeline — AGENTS.md

## Entrypoints

- `python scripts/manual_run.py --channel trending|family|lofi` — single-video run
- `python scripts/manual_run.py --channel english` — two-phase: `--manifest-only` then `--resume-from-manifest manifests/<slug>.manifest.json`
- `python scripts/manual_run.py --channel english-traditional` — two-phase: `--manifest-only` then `--resume-from-manifest manifests/<slug>.manifest.json` (traditional educational format)
- `python scripts/manual_run.py --channel english-challenge --topic "..." --start-date YYYY-MM-DD`
- `python scripts/manual_run.py --channel english-shorts|english-quiz|english-challenge-shorts`
- `python scripts/server.py` — Flask API bridge for n8n (port 5001)
- `python scripts/facebook_setup.py` — validate Facebook Page credentials (read-only; add `--test-upload --video <path>` to push one real draft Reel)
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
- **Facebook uploads**: `english-shorts` and `english-quiz` also publish a Reel to the Facebook Page as a **DRAFT** — release manually in Meta Business Suite. **Facebook has no "unlisted" audience for Pages**, so a draft is the closest equivalent to YouTube's unlisted.
- **Facebook Page ID**: The id in a `facebook.com/profile.php?id=…` URL is a legacy alias and does **not** resolve as a Graph node. Get the real id from `GET /me/accounts?fields=id,name,access_token`.
- **Facebook token**: Must be the **Page** token (the page row's own `access_token`), not the user token. A user token works for `/me` but fails on a Page node with error 100 / subcode 33.
- **Facebook token lifetime**: a Page token inherits the lifetime of the user token it was derived from. Deriving from a **short-lived** user token produces a Page token that dies in roughly an hour, surfacing as error 190 or "permission(s) must be granted before impersonating a user's page" — which reads like a scope problem but is not. Always: short-lived user token → `fb_exchange_token` → long-lived user token → *then* `GET /me/accounts` to derive the Page token. Skipping the long-lived step is the recurring failure here.
- **Facebook App Secret**: deliberately never stored in `.env` or read by code — needed once, in a browser, for the long-lived token exchange.
- **Facebook `video_reels` endpoint**: no read, update, or delete support. A bad draft can only be fixed or removed in Meta Business Suite. Reads of a Page node must use **GET** — `POST` returns error 240.
- **Facebook ordering**: the Reel upload must run *before* `_cleanup_uploaded_video_files()`, which deletes the local MP4. Facebook failures are swallowed so they can never cost a successful YouTube upload its ledger entry.
- **Failed Facebook cross-post preserves the MP4**: on failure the video is *moved* (not deleted) to `output/facebook_retry/` with a `.txt` sidecar naming the title, YouTube ID and the exact re-post command. A cross-post failure is nearly always a transient credential/network problem, and destroying the only local copy would force a re-download from YouTube Studio. Re-post with `facebook_setup.py --test-upload --video output/facebook_retry/<file>.mp4`, then delete the pair. Successful cross-posts leave nothing behind.
- **Playlist URL**: Use `{playlist_url}` placeholder in descriptions (replaced at upload time).
- **Timezone**: `America/Regina` (no DST). Set `LOCAL_TIMEZONE` in `.env`.
- **`.env` keys**: `.env` is gitignored and untracked — live credentials live there and are never committed. Do not hardcode credentials.
- **Chrome AI full-res images**: Chrome AI accumulates generated images in one conversation. Each image has a thumbnail (data URL, ~0.1MB) plus a hidden full-res `img.fRm5F` element (`lens.usercontent.google.com/banana` URL) — the banana URL fetched raw yields the full-res (~2MB) image. MUST select the banana element at the scene's `new_image_index` (not the first via `querySelector`), or every scene silently saves the same first image.
- **Chrome AI download button**: `button[aria-label="Download this AI generated image"]` is `disabled` and never emits a real browser `download` event; don't rely on it. DOM banana fetch is the winning path.

## Structure

| Path | Role |
|---|---|
| `scripts/` | All pipeline code (no package, uses sys.path imports) |
| `scripts/facebook_uploader.py` | Meta Reels Publishing API (3-phase upload, retries, spec warnings) |
| `scripts/facebook_setup.py` | Facebook credential validator / draft-visibility test |
| `prompts/` | Claude prompt templates (`claude_prompts.py`) |
| `n8n/workflow.json` | Import into n8n instance |
| `tests/` | Pytest suite |
| `assets/bumpers/<channel>/` | Optional intro/outro MP4s |
| `assets/generated_scenes/` | Scene images for English pipeline |
| `manifests/` | Two-phase pipeline manifests (gitignored) |
| `output/` | Assembled videos (gitignored) |

## Channels & credential files

YouTube credentials: `assets/yt_credentials_<channel>.json` (e.g. `yt_credentials_english.json`). English sub-channels (shorts, quiz, challenge) all use `yt_credentials_english.json`.

Facebook credentials: `FACEBOOK_PAGE_ID` + `FACEBOOK_PAGE_ACCESS_TOKEN` in `.env` (no per-channel files — one Page).

## Pipeline notes

- English podcasts use Kokoro TTS with multi-voice dialogue (Emma/Liam/Narrator/Guest).
- English traditional format uses Emma/Liam hosts with direct teaching approach (warm, conversational, practical).
- Scene durations driven by actual TTS audio, not estimates.
- Family channel uses photo-first card format with Pexels images.
- Captions use `.ass` format (Advanced Sub Station Alpha) with karaoke highlighting.
- `--no-upload` flag skips YouTube publish; `--skip-facebook` skips the Facebook Reel cross-post; `--skip-gemini` skips scene image generation.
- Facebook Reels require 9:16, 3–90s. English shorts/quiz are 25–45s vertical, so they qualify. `facebook_uploader` ffprobe-warns if a video drifts out of spec but still uploads.
- **Facebook caption**: defaults to `FACEBOOK_CAPTION_STYLE=title`, reusing the YouTube title verbatim — shorts titles are already written as scroll-stopping hooks, and this matches what was previously posted by hand. `description` opts back into the first-description-paragraph behaviour. Facebook does not linkify URLs in captions, so the "Watch on YouTube" line is opt-in via `FACEBOOK_APPEND_YOUTUBE_LINK=1`.
- **Facebook tags**: the YouTube `tags` list is **not** sent to Facebook. Reels have no separate tags field, so hashtags are lifted out of the YouTube *description* into the caption automatically (`_extract_hashtags`, capped at 5). Suppress with `FACEBOOK_INCLUDE_HASHTAGS=0`.
- **`#Shorts` is dropped on Facebook**: it is a YouTube format signal. Facebook has no Shorts format (Meta renamed the Videos tab to Reels; every video there is a Reel), so the tag carries no meaning. Adjust with `FACEBOOK_DROP_HASHTAGS=` (empty restores it) and `FACEBOOK_REPLACE_HASHTAGS=#fbreels`.
- **All-caps hooks vs Meta's Reel guidance**: Meta's published best practice asks for captions with "no links, minimal use of capital letters, and no more than five hashtags". The Shorts titles are deliberately ALL CAPS for YouTube CTR and are reused verbatim on Facebook — a real tension, resolved in favour of the hand-tuned hook. Revisit if Reel reach underperforms.
- **Facebook caption limit**: Meta's documented Reel cap is five hashtags; `_truncate_keeping_ends` also enforces the 500-char caption limit.
- **Facebook caption CTA**: an engagement ask is appended last by default (`DEFAULT_ENGAGEMENT_CTA`), asking for save/share/comment — the three signals Reel ranking rewards. Likes are deliberately not requested. Override the wording, or set `FACEBOOK_ENGAGEMENT_CTA=` to drop it.
- **Facebook caption truncation**: at the 500-char limit `_truncate_keeping_ends` sheds hashtags first, then shortens the hook with an ellipsis, and never cuts the CTA.

## English Pipeline Comparison

- **english** (main): High-CTR dramatic storytelling with Narrator/Emma/Liam, crisis hooks, emotional triggers
- **english-traditional**: Educational format with Emma/Liam direct teaching, warm conversational style, traditional titles
- **english-challenge**: 7-day structured learning series with Emma/Liam, daily practice tasks
- **english-podcast**: Similar to main but shorter clips, multi-voice caller format
- **english-shorts**: Short-form with high-CTR mistake/crisis hooks
- **english-quiz**: Quiz format shorts with interactive questions
