# YouTube Autonomous Pipeline — Setup Guide

## What this does

Fully autonomous YouTube content pipeline for 3 channels:

- **Channel 1** — Trending narrated (any topic, highest CPM)
- **Channel 2** — Family-friendly (this or that, fun facts, full ad monetization)
- **Channel 3A** — Lofi study music (multi-hour, passive watch time)

Daily runs at 6AM: pulls trends → scores topics → generates scripts →
creates voiceover → fetches stock video → assembles → uploads to YouTube.  
Your time: **~20 minutes/week** reviewing the digest email.

---

## Project Structure

```
yt-pipeline/
├── prompts/
│   └── claude_prompts.py      ← AI scripting system (Claude API)
├── scripts/
│   ├── ffmpeg_assembler.py    ← Video assembly (FFmpeg + ElevenLabs + Pexels)
│   └── server.py              ← Flask API bridge for n8n
├── n8n/
│   └── workflow.json          ← Import this into n8n
└── assets/                    ← Put your files here (created at runtime)
    ├── background_music.mp3   ← Royalty-free BG music for narrated videos
    ├── lofi_loop.mp4          ← Looping animation for lofi channel
    ├── lofi/                  ← MP3 tracks from Suno/Udio
    │   ├── track_01.mp3
    │   └── ...
    ├── client_secrets.json    ← From Google Cloud Console
    └── yt_credentials_*.json  ← Auto-generated after OAuth
```

---

## Step 1 — Get a VPS (5 min)

1. Sign up at [Hetzner](https://hetzner.com) — cheapest option (~$4.50/mo)
2. Create a **CX22** server: Ubuntu 24.04, 2 vCPU, 4GB RAM
3. SSH in: `ssh root@YOUR_VPS_IP`

---

## Step 2 — Install dependencies (10 min)

```bash
# System packages
apt update && apt install -y ffmpeg python3-pip python3-venv git curl nodejs npm

# Python packages
pip install anthropic flask requests google-auth google-auth-oauthlib \
            google-api-python-client faster-whisper --break-system-packages

# n8n (workflow automation)
npm install -g n8n

# Verify ffmpeg works
ffmpeg -version
```

---

## Step 3 — Set environment variables (5 min)

Add to `~/.bashrc` or `/etc/environment`:

```bash
export ANTHROPIC_API_KEY="sk-ant-..."           # From console.anthropic.com
export ELEVENLABS_API_KEY="..."                  # From elevenlabs.io
export ELEVENLABS_VOICE_ID="21m00Tcm4TlvDq8ikWAM"  # Rachel (or your custom voice)
export PEXELS_API_KEY="..."                      # From pexels.com/api (free)
export YOUTUBE_API_KEY="..."                     # From Google Cloud Console
export YT_CHANNEL_ID="UCxxxxxx"                 # Your channel ID
export NANO_BANANA_PRO_API_KEY="..."              # Optional: free Nano Banana Pro thumbnail generation for English
export AIRTABLE_API_KEY="..."                    # Optional: for logging
export AIRTABLE_BASE_ID="appXXXXXX"             # Optional: for logging
export ALERT_EMAIL="you@email.com"
export DIGEST_EMAIL="you@email.com"

source ~/.bashrc
```

**Getting API keys:**

- **Anthropic**: console.anthropic.com → API Keys
- **ElevenLabs**: elevenlabs.io → Profile → API Key (free tier: 10k chars/mo)
- **Pexels**: pexels.com/api → completely free, generous limits
- **YouTube**: console.cloud.google.com → Enable YouTube Data API v3 → Credentials

---

## Step 4 — Google OAuth for YouTube Upload (15 min)

This is the most involved step but only done once per channel.

```bash
# 1. Go to console.cloud.google.com
# 2. Create project → Enable "YouTube Data API v3"
# 3. Credentials → Create OAuth 2.0 Client ID → Desktop app
# 4. Download JSON → rename to client_secrets.json
# 5. Upload to your VPS:

scp client_secrets.json root@YOUR_VPS_IP:/root/yt-pipeline/assets/

# 6. On your VPS, start the server:
cd /root/yt-pipeline/scripts
python server.py &

# NOTE: Ensure server.py uses the following SCOPES to allow pinned comments:
# ['https://www.googleapis.com/auth/youtube.upload', 'https://www.googleapis.com/auth/youtube.force-ssl']

# 7. On your LOCAL machine, forward ports:
ssh -L 8080:localhost:8080 -L 5001:localhost:5001 root@YOUR_VPS_IP

# 8. In your browser, visit:
http://localhost:5001/setup-auth/trending
# → Sign in with your YouTube channel account
# → Credentials saved automatically

# Repeat for each channel:
http://localhost:5001/setup-auth/family
http://localhost:5001/setup-auth/lofi
```

---

## Step 5 — Add your media assets (10 min)

### Background music (narrated channels)

Download 1-2 royalty-free tracks:

- [Pixabay Music](https://pixabay.com/music/) → search "ambient background"
- Save as `assets/background_music.mp3`

### Lofi loop visual

Download a free lofi animation MP4:

- [Pixabay Videos](https://pixabay.com/videos/) → search "lofi anime"
- Save as `assets/lofi_loop.mp4`

### Lofi music tracks (for Channel 3A)

Generate 10-15 tracks at [Suno.ai](https://suno.ai) (free tier):

- Prompt: _"lofi hip hop, jazzy, mellow, study music, no lyrics, chill beats"_
- Download as MP3 → save to `assets/lofi/track_01.mp3`, etc.

---

## Step 6 — Start the assembly server (2 min)

```bash
# Run as a persistent background service
nohup python /root/yt-pipeline/scripts/server.py > /var/log/yt-server.log 2>&1 &

# Or use systemd for auto-restart:
cat > /etc/systemd/system/yt-pipeline.service << EOF
[Unit]
Description=YouTube Pipeline Assembly Server
After=network.target

[Service]
User=root
WorkingDirectory=/root/yt-pipeline/scripts
ExecStart=/usr/bin/python3 server.py
Restart=always
RestartSec=10
Environment=PYTHONUNBUFFERED=1

[Install]
WantedBy=multi-user.target
EOF

systemctl enable yt-pipeline
systemctl start yt-pipeline
systemctl status yt-pipeline
```

---

## Step 7 — Set up n8n (5 min)

```bash
# Start n8n
nohup n8n start > /var/log/n8n.log 2>&1 &

# Access dashboard (forward port locally first):
ssh -L 5678:localhost:5678 root@YOUR_VPS_IP
# Then open: http://localhost:5678

# In n8n dashboard:
# 1. Settings → Environment Variables → Add all your API keys
# 2. Workflows → Import → Upload n8n/workflow.json
# 3. Open the workflow → click each HTTP node → verify URLs
# 4. Activate the workflow (toggle top-right)
```

**n8n auto-start on reboot:**

```bash
cat > /etc/systemd/system/n8n.service << EOF
[Unit]
Description=n8n Workflow Automation
After=network.target

[Service]
User=root
ExecStart=/usr/bin/n8n start
Restart=always
Environment=N8N_PORT=5678

[Install]
WantedBy=multi-user.target
EOF

systemctl enable n8n
systemctl start n8n
```

---

## Step 8 — Test the pipeline (5 min)

```bash
# Test Claude prompts
cd /root/yt-pipeline/prompts
python claude_prompts.py

# Test assembly server health
curl http://localhost:5001/health

# Trigger a manual test run
curl -X POST http://localhost:5001/assemble \
  -H "Content-Type: application/json" \
  -d '{
    "channel_type": "trending",
    "title": "Test Video",
    "script": "This is a test script for the pipeline. It should generate a short video.",
    "description": "Test description",
    "tags": ["test"],
    "thumbnail_text": "TEST VIDEO",
    "keywords": ["technology"]
  }'

# Check job status (replace job_0001 with returned ID)
curl http://localhost:5001/job/job_0001
```

---

## Weekly routine (your ~20 min/week)

Every Monday morning you'll receive a digest email. It contains:

- Top 3 videos from the past week (views, watch time, revenue)
- What's queued for this week (5-7 trending Shorts + 2 lofi)
- Any errors that need attention

Your only job: skim the email, check the YouTube Studio queue if anything looks off, done.

The pipeline handles everything else: 6AM daily trend fetch, scoring, scripting,
voice generation, video assembly, and upload scheduling.
Daily trending defaults to vertical Shorts. Use the manual runner's
`--video-format explainer` option when a topic deserves the original 5-7 minute
search-focused landscape treatment.

---

## Monetization timeline

| Milestone              | When      | Action                                                   |
| ---------------------- | --------- | -------------------------------------------------------- |
| Affiliate links live   | Day 1     | Add Amazon/NordVPN/Skillshare links to every description |
| First brand outreach   | 200 subs  | Email 5 relevant brands using your niche data            |
| YouTube Partner (Ch1)  | Month 3-4 | 1k subs + 4k watch hours                                 |
| YouTube Partner (Lofi) | Month 2-3 | Watch time accrues fast with 3hr videos                  |
| $100/month             | Month 3-5 | Combined affiliates + early AdSense                      |
| $500/month             | Month 6-9 | AdSense on 2-3 channels + sponsors                       |

---

## Monthly costs

| Service                   | Cost           |
| ------------------------- | -------------- |
| Hetzner CX22 VPS          | $4.50          |
| Claude API (~150 scripts) | $10-15         |
| ElevenLabs Starter        | $5.00          |
| Pexels stock video        | Free           |
| Suno AI music             | Free tier      |
| FFmpeg, Whisper, n8n      | Free           |
| YouTube/TikTok APIs       | Free           |
| **Total**                 | **~$20-25/mo** |

---

## Troubleshooting

**Pipeline not triggering:**  
Check n8n workflow is activated (toggle in top-right). Check logs: `journalctl -u n8n -f`

**Upload failing:**  
OAuth tokens expire every hour but auto-refresh. If persistent: re-run `/setup-auth/trending`

**Video assembly slow:**  
Trending Shorts should assemble quickly because they are under 2 minutes. Long lofi videos can still take 20-40 minutes on a typical machine.

**Whisper captions failing:**  
Run `pip install faster-whisper --break-system-packages` and ensure ffmpeg is installed.

**ElevenLabs quota hit:**  
Free tier is 10k chars/month. Starter ($5) gives 30k chars — enough for ~20 videos/month.  
Alternative free TTS: Kokoro TTS is included in this repository and runs entirely locally. See FREE_START.md for setup instructions.
