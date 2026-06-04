# YouTube Autonomous Pipeline 🎬

A fully autonomous YouTube content pipeline for multiple channels, running on ~$20/month with under 20 minutes of human effort per week.

## Channels

| Channel                | Content                                                        | CPM   | Effort/week |
| ---------------------- | -------------------------------------------------------------- | ----- | ----------- |
| **Daily Insights Hub** | Finance, health, AI, lifestyle, true crime, useful facts       | $8–40 | ~10 min     |
| **Family-Friendly**    | This or that, fun facts, riddles, trivia                       | $4–12 | ~5 min      |
| **EnglishVibesHub**    | English learning podcasts and 7-day weekly challenge playlists | $4–15 | ~10 min     |
| **Lofi Study Music**   | 3-hour focus/study sessions                                    | $1–4  | ~5 min      |

## How it works

```
6AM daily → Fetch trends (Google + Reddit + YouTube)
          → Claude scores & picks best topics
          → Claude writes full scripts
          → ElevenLabs generates voiceover
          → Pexels fetches stock video
          → Whisper generates captions
          → FFmpeg assembles final MP4
          → YouTube Data API uploads & schedules
          → You get a digest email Monday morning
```

## Stack

- **n8n** — workflow orchestration (self-hosted, free)
- **Claude API** — topic scoring + scriptwriting
- **ElevenLabs** — text-to-speech voiceover
- **Pexels API** — stock video (free)
- **FFmpeg** — video assembly (free)
- **Whisper** — captions (free)
- **YouTube Data API v3** — upload & schedule (free)
- **Flask** — local API bridge between n8n and Python

## Monthly cost

| Service            | Cost           |
| ------------------ | -------------- |
| Hetzner CX22 VPS   | $4.50          |
| Claude API         | $10–15         |
| ElevenLabs Starter | $5.00          |
| Everything else    | Free           |
| **Total**          | **~$20–25/mo** |

## Quick start

**Want to publish for free first?** → See **[docs/FREE_START.md](docs/FREE_START.md)**
This walks you through all 20 steps to publish your first video at $0.

**Ready for the full automated setup?** → See **[docs/SETUP.md](docs/SETUP.md)**

```bash
git clone https://github.com/YOUR_USERNAME/yt-pipeline.git
cd yt-pipeline
pip install -r requirements.txt
cp .env.example .env   # fill in your API keys
python scripts/server.py
```

Then import `n8n/workflow.json` into your n8n instance and activate.

Optional: add `NANO_BANANA_PRO_API_KEY` to `.env` to enable Nano Banana Pro thumbnail generation for the English channel. When available, the pipeline generates a fresh, custom thumbnail background from the script concept and overlays mobile-friendly title text instead of relying on a video frame.

### English weekly challenge playlist

Generate a 7-video weekly challenge for the English channel:

```bash
python scripts/manual_run.py --channel english-challenge --topic "Small Talk Without Freezing" --start-date 2026-06-01
```

This creates Day 1-6 daily learning videos plus a Day 7 recap/question challenge. Uploads use the existing `english` YouTube credentials and are scheduled one video per day at 9AM local time by default. Add `--no-upload` to only assemble the videos.

## Project structure

```
yt-pipeline/
├── prompts/
│   └── claude_prompts.py      # AI scripting system
├── scripts/
│   ├── ffmpeg_assembler.py    # Video assembly pipeline
│   ├── server.py              # Flask API bridge for n8n
│   ├── manual_run.py          # Run free-mode channel publishing commands
│   ├── trending_generator.py  # Google Trends + Groq script generation
│   ├── english_generator.py   # English podcast + weekly challenge scripts
│   └── free_tts.py            # Free local voiceover (Kokoro TTS)
├── n8n/
│   └── workflow.json          # Import into n8n
├── assets/                    # Your media files go here (gitignored)
│   ├── background_music.mp3
│   ├── lofi_loop.mp4
│   ├── bumpers/               # Optional channel intro/outro MP4s
│   │   ├── english/
│   │   ├── family/
│   │   ├── lofi/
│   │   └── trending/
│   ├── lofi/                  # MP3 tracks from Suno/Udio
│   └── client_secrets.json    # Google OAuth (gitignored)
├── output/                    # Assembled videos (gitignored)
├── docs/
│   ├── FREE_START.md          # Start here: 20 steps, zero dollars
│   └── SETUP.md               # Full automated setup walkthrough
├── .env.example
├── .gitignore
├── requirements.txt
└── README.md
```

Optional channel bumpers can be added as `assets/bumpers/<channel>/intro.mp4` and
`assets/bumpers/<channel>/outro.mp4`. Missing bumper files are skipped. English
podcasts and weekly challenge videos use `assets/bumpers/english/`; English
Shorts intentionally skip bumpers because they are short-form clips.

## Monetization timeline

| Month      | Milestone                                       |
| ---------- | ----------------------------------------------- |
| Day 1      | Affiliate links live in every description       |
| Month 2–3  | First brand sponsor outreach at 500 subs        |
| Month 3–5  | YouTube AdSense on Channel 1 (1k subs + 4k hrs) |
| Month 4–6  | AdSense on Channels 2 & 3                       |
| Month 6–12 | $500–2,000/month combined                       |

## License

MIT
