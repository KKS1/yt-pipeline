# Free start guide — publish your first video at $0

Follow these steps in order. Everything here is free.
The only paid step (marked clearly) is optional until you're ready to automate.

---

## Before you begin

You need:

- A computer with internet access (Mac, Windows, or Linux)
- A Google account (for YouTube)
- Git installed (git-scm.com)
- Python 3.11+ installed (python.org)
- Node.js 18+ installed (nodejs.org) — for n8n later
- This project cloned from GitHub

```bash
git clone https://github.com/YOUR_USERNAME/yt-pipeline.git
cd yt-pipeline
```

---

## Phase 1 — Install tools on your machine (~30 min)

### Step 1 — Install FFmpeg

Mac:

```bash
brew install ffmpeg
```

Windows (run as Administrator):

```bash
choco install ffmpeg
```

Linux:

```bash
sudo apt install ffmpeg
```

Verify:

```bash
ffmpeg -version
```

---

### Step 2 — Install Python dependencies

```bash
pip install -r requirements.txt
```

This installs everything including Kokoro TTS (free local voiceover) and Whisper (free captions).

You will also need `espeak-ng` installed on your system for Kokoro to work:

- Mac: `brew install espeak-ng`
- Linux: `sudo apt install espeak-ng`
- Windows: Download from the official espeak-ng repository.

**Download Kokoro Model Files:**
Run these commands in your `yt-pipeline` root directory to download the required voice models (~80MB):

```bash
curl -L -o kokoro-v0_19.onnx https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files/kokoro-v0_19.onnx
curl -L -o voices.bin https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files/voices.bin
```

---

### Step 3 — Install Whisper

Already included in requirements.txt above. Verify it works:

```bash
whisper --help
```

---

## Phase 2 — Create your free accounts (~45 min)

### Step 4 — Create 3 YouTube channels

1. Go to youtube.com → sign in with your Google account
2. Click your profile icon → "Create a channel"
3. Create three channels with these names (or your own branding):
   - **Lofi Study Hub** (or similar)
   - **Family Fun Zone** (or similar)
   - **Daily Insights Hub** (for trending insight content)
4. For each channel: add a basic description, pick a category
5. Do NOT set audience to "made for kids" on the family channel — set it to "Yes, set this channel as made for kids" ONLY on the lofi kids nursery channel if you create one later

---

### Step 5 — Get a Pexels API key (free stock video)

1. Go to pexels.com/api
2. Click "Get Started" — sign up free
3. Copy your API key
4. Add to your `.env` file:

```
PEXELS_API_KEY=your_key_here
```

No credit card. No limits for our usage level.

---

### Step 6 — Set up Google Cloud for YouTube upload

This lets the pipeline upload videos automatically to your channels.

1. Go to console.cloud.google.com
2. Click "New Project" → name it "yt-pipeline" → Create
3. In the search bar type "YouTube Data API v3" → Enable it
4. Go to "Credentials" (left sidebar)
5. Click "+ Create Credentials" → "API Key"
   - Copy this key → add to `.env` as `YOUTUBE_API_KEY=...`
6. Click "+ Create Credentials" again → "OAuth 2.0 Client ID"
   - Application type: Desktop app
   - Name: yt-pipeline
   - Click Create → Download JSON
   - Rename the file to `client_secrets.json`
   - Place it in your project's `assets/` folder
7. Go to "OAuth consent screen" → set to External → fill in app name → Save

---

### Step 7 — Sign up for Suno AI (free lofi music)

1. Go to suno.ai → sign up free
2. Free tier gives 50 credits per day (each song = 5 credits = 10 songs/day)
3. Generate lofi tracks using this prompt:
   ```
   lofi hip hop, jazzy piano, mellow beats, study music, no lyrics,
   peaceful atmosphere, soft drums, chill vibes
   ```
4. Download each track as MP3
5. Save them to `assets/lofi/track_01.mp3`, `track_02.mp3`, etc.
6. Aim for at least 10 tracks before assembling your first lofi video
7. You can generate more over several days — Suno resets credits daily

---

### Step 8 — Download a free lofi visual loop

1. Go to pixabay.com/videos
2. Search "lofi anime" or "cozy room animation" or "rainy window"
3. Download any free MP4 loop (short 5-30 second loops work best)
4. Save it as `assets/lofi_loop.mp4`

Also grab background music for narrated videos:

1. Go to pixabay.com/music
2. Search "ambient background" or "cinematic background"
3. Download an MP3 → save as `assets/background_music.mp3`

---

### Optional Step 9 — Set up Nano Banana Pro for better thumbnails

Nano Banana Pro can generate a stunning custom thumbnail background for English videos and English weekly challenge videos. This is optional, but it gives a cleaner, more clickable mobile thumbnail than a frame-based overlay.

1. Sign up for Nano Banana Pro and get a free API key.
2. Add it to your `.env` file:

```bash
NANO_BANANA_PRO_API_KEY=your_key_here
```

3. Optionally override the default Nano Banana Pro endpoint if needed:

```bash
NANO_BANANA_PRO_API_URL=https://api.nanobanana.pro/v1/generate
```

4. The English flow will now:
   - generate a custom thumbnail background using Nano Banana Pro
   - overlay short mobile-friendly thumbnail text
   - fall back automatically to a frame-based thumbnail if the API call fails

If you do not set `NANO_BANANA_PRO_API_KEY`, the pipeline still works and uses the current frame-based English thumbnail logic instead.

---

## Phase 3 — Set up YouTube OAuth (~15 min)

This is the one-time step that lets the pipeline upload to each channel.

### Step 9 — Run OAuth for each channel

Start the pipeline server locally:

```bash
cd scripts
python server.py
```

In a separate terminal, forward the auth port (needed for Google's OAuth redirect):

```bash
# Leave the server running, open a new terminal
# The server is already running on localhost:5001
```

Open your browser and visit each of these URLs one at a time.
Sign in with the Google account that owns that channel:

```
http://localhost:5001/setup-auth/lofi
http://localhost:5001/setup-auth/family
http://localhost:5001/setup-auth/trending
```

Each one opens a Google sign-in page → approve → credentials saved automatically to `assets/yt_credentials_lofi.json` etc.

After completing all three, stop the server (Ctrl+C).

---

## Phase 4 — Test everything locally (~20 min)

### Step 10 — Generate a test audio file

```bash
ffmpeg -f lavfi -i "sine=frequency=440:duration=60" assets/test_audio.mp3
```

### Step 11 — Test Whisper captions

```bash
whisper assets/test_audio.mp3 --model base --output_format srt --output_dir output/
```

Should create `output/test_audio.srt`. If it works, captions are good.

### Step 12 — Test Kokoro TTS (free voiceover)

```bash
python scripts/free_tts.py "Hello, welcome to the channel. Today we're going to explore something amazing." output/test_voice.wav
```

Listen to `output/test_voice.wav` to hear the voice quality. Since you downloaded the model files in Step 2, this will run instantly entirely on your local machine.

### Step 13 — Test the server health check

```bash
python scripts/server.py &
curl http://localhost:5001/health
# Should return: {"status": "ok", "jobs": 0}
kill %1
```

---

## Phase 5 — Publish your first video (lofi channel) 🎉

### Step 14 — Write your first lofi video metadata

Go to claude.ai (this chat) and ask:

```
Write YouTube metadata for a 3-hour lofi study music video set in a
rainy Tokyo café. Include: title (under 70 chars), 200-word description
with study music keywords, and 10 tags.
```

Copy the title, description, and tags it gives you.

### Step 15 — Run the manual pipeline

```bash
python scripts/manual_run.py --channel lofi
```

The script will ask you for:

- Title (paste from Claude)
- Description (paste from Claude)
- Tags (paste from Claude)
- Duration (enter 3 for 3 hours)

It will then:

1. Check your `assets/lofi/` folder for MP3 tracks
2. Check for `assets/lofi_loop.mp4`
3. Assemble the full 3-hour video with FFmpeg
4. Ask if you want to upload to YouTube

Say yes to upload. Your first video goes live. 🚀

Assembly takes about 20-40 minutes for a 3-hour video on a typical laptop.
You can leave it running in the background.

---

## Phase 6 — Publish your first family video

### Step 16 — Generate a script in Claude.ai

Go to claude.ai and ask:

```
Write a family-friendly YouTube script for a "This or That?" video
about animals. Include 15 questions, build from easy to hard, add a
fun fact after every 3rd question. Tone: excited game show host,
fun for kids AND adults. Also write a YouTube title and description.
```

### Step 17 — Run the family pipeline

```bash
python scripts/manual_run.py --channel family
```

Paste your script, title, description, and tags when prompted.
Choose option 1 (free local TTS) for voiceover.
Upload when done.

---

## Phase 7 — Set up n8n for automation (~30 min, still free)

Once you've manually published 3-5 videos and confirmed everything works,
set up n8n to automate the daily pipeline on your local machine.

### Step 18 — Install and start n8n

```bash
npm install -g n8n
n8n start
```

Open: http://localhost:5678

### Step 19 — Import the workflow

1. In n8n: Workflows → Import
2. Upload `n8n/workflow.json`
3. Open the workflow
4. Add your API keys in Settings → Environment Variables:
   ```
   PEXELS_API_KEY=...
   YOUTUBE_API_KEY=...
   YT_CHANNEL_ID=...
   ALERT_EMAIL=...
   DIGEST_EMAIL=...
   ```
5. The Claude API and ElevenLabs nodes will show errors — that's fine for now.
   The lofi and family pipelines don't need them.

### Step 20 — Activate the lofi trigger

In the workflow, find "Lofi Weekly Trigger" (runs Tuesday and Friday at 7AM).
Right-click → Enable node.
This will auto-generate and upload lofi videos twice a week while you sleep.

---

## Phase 8 — Publish your first Daily Insights Hub video (trending channel)

Daily Insights Hub explains the topics people are actively searching right now —
finance, health, AI, true crime, lifestyle, science, culture, and useful facts. The goal is
a clear, calm 45-90 second vertical Short that shows up while a topic is peaking.
For bigger search-friendly topics, you can also run the original 5-7 minute
landscape explainer format.

**Good topic example:** If "Montreal Canadiens" is trending on Google (playoff run,
big trade, coaching news), a video like _"Why Everyone is Talking About the Canadiens
Right Now"_ will catch search traffic without needing deep sports knowledge. Keep it
broad enough for casual viewers, not just fans.

### Step 21 — Find a trending topic

1. Go to [trends.google.com](https://trends.google.com) → click "Trending Now"
2. Filter by your country (Canada works well for hockey, local news, etc.)
3. Pick a topic with broad appeal — something with a clear "why is this happening?" angle
4. Alternatively check YouTube's Trending tab (Explore → Trending)

Avoid: niche sports stats, political controversy, or anything that could age badly
within 24 hours (breaking news with lots of unknowns).

### Step 22 — Run the trending pipeline

```bash
python scripts/manual_run.py --channel trending
```

The command fetches Canada trends, uses Groq free tier to pick an angle and
write the script, generates local Kokoro voiceover, pulls relevant stock video
from Pexels using your `PEXELS_API_KEY`, adds captions via Whisper, assembles the
final video, and uploads it to the trending YouTube channel.

To force a specific topic instead of auto-picking from Google Trends:

```bash
python scripts/manual_run.py --channel trending --topic "Montreal Canadiens"
```

To assemble without uploading:

```bash
python scripts/manual_run.py --channel trending --no-upload
```

**Timing matters:** Trending videos have a short window. Check Google Trends
in the morning and aim to publish by early afternoon the same day.

---

## What's fully automated now (still $0)

- Lofi channel: posts automatically twice a week
- Whisper captions on all videos
- YouTube upload and scheduling

## What still needs 5 minutes of your time per video (family + trending)

- Copy a topic → ask Claude.ai for a script → paste into manual_run.py
- That's it. The rest assembles and uploads automatically.

---

## When to add paid services (optional, when ready)

| Service            | Cost      | What it unlocks                                       |
| ------------------ | --------- | ----------------------------------------------------- |
| Anthropic API      | $5 credit | Auto-scripts for all channels, no more manual pasting |
| ElevenLabs Starter | $5/mo     | Much better voice quality on narrated videos          |
| Hetzner VPS        | $4.50/mo  | 24/7 automation, no laptop needed                     |

None of these are needed to start. Add them when your first affiliate
commission or AdSense payment covers the cost.

---

## Add affiliate links right now (earn from day 1)

In every video description, add links like these (sign up for each free):

**Amazon Associates** (amazon.ca for Canada):

```
🎧 Headphones I recommend for studying: [your affiliate link]
```

**Skillshare** (pays $7-10 per trial signup):

```
📚 Learn anything with 1 month free on Skillshare: [your affiliate link]
```

**NordVPN** (pays $30-40 per signup):

```
🔒 Stay safe online with NordVPN: [your affiliate link]
```

Sign up at:

- affiliate-program.amazon.com
- skillshare.com/affiliates
- nordvpn.com/affiliate

All free to join. No minimum traffic required.

---

## You're live. Here's what happens next.

Week 1-2: First 3-5 videos published. Affiliate links in every description.
Month 1: 15-20 videos across channels. First affiliate clicks.
Month 2-3: Lofi channel likely hits AdSense watch hours threshold (4k hrs).
Month 3-5: Family/trending channels hit 1k subscribers + 4k hours.
Month 6+: Multiple revenue streams running simultaneously.

The lofi channel is your fastest path — a single 3-hour video earns
watch time every day for years. Post your first one today.
