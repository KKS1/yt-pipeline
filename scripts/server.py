"""
Assembly Server — Flask API
Bridges n8n workflow ↔ Python pipeline scripts.
Runs on port 5001 on your VPS.

Start: python server.py
Install: pip install flask google-auth google-auth-oauthlib google-api-python-client requests --break-system-packages
"""

import os
import json
import threading
import re
from pathlib import Path
from flask import Flask, request, jsonify

# Import pipeline modules
import sys
sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent / "prompts"))
from youtube_uploader import youtube_upload

app = Flask(__name__)

# Always resolve relative to project root (yt-pipeline/), not cwd
PROJECT_ROOT = Path(__file__).parent.parent
OUTPUT_DIR   = PROJECT_ROOT / "output"
TEMP_DIR     = PROJECT_ROOT / "temp"
ASSETS_DIR   = PROJECT_ROOT / "assets"

for d in [OUTPUT_DIR, TEMP_DIR, ASSETS_DIR]:
    d.mkdir(exist_ok=True)

# Background job tracker
jobs = {}


# ─────────────────────────────────────────────
# FLASK ROUTES
# ─────────────────────────────────────────────

@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "ok", "jobs": len(jobs)})


@app.route("/assemble", methods=["POST"])
def assemble():
    """Trigger video assembly in background, return job ID immediately."""
    data = request.json
    job_id = f"job_{len(jobs)+1:04d}"
    jobs[job_id] = {"status": "running", "data": data}

    def run():
        try:
            from ffmpeg_assembler import run_full_pipeline

            # Default background music (put a royalty-free MP3 in assets/)
            bg_music = str(ASSETS_DIR / "background_music.mp3")
            if not Path(bg_music).exists():
                # Fallback: generate silent audio
                import subprocess
                subprocess.run([
                    "ffmpeg", "-y", "-f", "lavfi", "-i", "anullsrc=r=44100:cl=stereo",
                    "-t", "300", bg_music
                ], capture_output=True)

            result = run_full_pipeline(data, data.get("channel_type", "trending"), bg_music)
            jobs[job_id] = {"status": "done", **result}

        except Exception as e:
            jobs[job_id] = {"status": "error", "error": str(e)}

    threading.Thread(target=run, daemon=True).start()
    return jsonify({"job_id": job_id, "status": "running"})


@app.route("/assemble-lofi", methods=["POST"])
def assemble_lofi():
    """Assemble a lofi video. Expects pre-downloaded music files in assets/lofi/."""
     # Handle both parsed JSON and raw string body
    data = request.get_json(force=True, silent=True)
    if data is None:
        try:
            data = json.loads(request.data.decode("utf-8"))
        except Exception:
            return jsonify({"error": "Could not parse request body as JSON"}), 400

    job_id = f"lofi_{len(jobs)+1:04d}"
    jobs[job_id] = {"status": "running"}

    # metadata may arrive as a dict or a JSON string — handle both
    raw_metadata = data.get("metadata", {})
    if isinstance(raw_metadata, str):
        raw_metadata = re.sub(r"```json|```", "", raw_metadata).strip()
        try:
            raw_metadata = json.loads(raw_metadata)
        except Exception:
            raw_metadata = {}
    metadata = raw_metadata

    def run():
        try:
            from ffmpeg_assembler import assemble_lofi_video

            # Find music files in assets/lofi/
            lofi_dir = ASSETS_DIR / "lofi"
            lofi_dir.mkdir(exist_ok=True)
            music_files = sorted(lofi_dir.glob("*.mp3"))

            if not music_files:
                raise FileNotFoundError(
                    "No MP3 files in assets/lofi/. "
                    "Download from Suno/Udio and place there first."
                )

            # Find or use default loop visual
            # Pick a random visual loop from assets/lofi_visuals/
            import random
            visuals_dir = ASSETS_DIR / "lofi_visuals"
            visuals_dir.mkdir(exist_ok=True)
            visual_files = sorted(visuals_dir.glob("*.mp4"))

            if not visual_files:
                # Fallback to legacy single file
                fallback = ASSETS_DIR / "lofi_loop.mp4"
                if fallback.exists():
                    visual_files = [fallback]
                else:
                    raise FileNotFoundError(
                        "No video files in assets/lofi_visuals/ and no lofi_loop.mp4 fallback. "
                        "Add at least one .mp4 loop to assets/lofi_visuals/"
                    )

            visual_path = str(random.choice(visual_files))
            print(f"  Using visual: {Path(visual_path).name}")

            title    = metadata.get("title", "Lofi Study Music")
            duration = data.get("duration_hours", 3)
            slug     = title[:40].replace(" ", "_").lower()
            slug     = "".join(c for c in slug if c.isalnum() or c == "_")
            out_path = str(OUTPUT_DIR / f"{slug}.mp4")

            assemble_lofi_video(
                music_tracks=[str(f) for f in music_files],
                loop_visual=str(visual_path),
                output_path=out_path,
                duration_hours=duration,
                title=title,
                tracklist=metadata.get("tracklist", []),
                channel="lofi",
            )

            jobs[job_id] = {
                "status": "done",
                "video_path": out_path,
                "title": title,
                "description": metadata.get("description", ""),
                "tags": metadata.get("tags", []),
            }

        except Exception as e:
            jobs[job_id] = {"status": "error", "error": str(e)}

    threading.Thread(target=run, daemon=True).start()
    return jsonify({"job_id": job_id, "status": "running"})


@app.route("/job/<job_id>", methods=["GET"])
def get_job(job_id):
    """Poll job status."""
    return jsonify(jobs.get(job_id, {"status": "not_found"}))


@app.route("/upload", methods=["POST"])
def upload():
    """Upload finished video to YouTube."""
    data = request.json

    # If assembly is still running, wait and poll
    video_path = data.get("video_path", "")
    if not video_path or not Path(video_path).exists():
        return jsonify({"error": f"Video not found: {video_path}"}), 400

    try:
        result = youtube_upload(
            video_path    = video_path,
            title         = data.get("title", ""),
            description   = data.get("description", ""),
            tags          = data.get("tags", []),
            thumbnail_path= data.get("thumbnail_path"),
            channel       = data.get("channel", "trending"),
            schedule_time = data.get("schedule_time"),
        )
        return jsonify(result)

    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/jobs", methods=["GET"])
def list_jobs():
    """List all jobs and their statuses."""
    summary = {
        jid: {"status": j.get("status"), "title": j.get("title", j.get("data", {}).get("title", ""))}
        for jid, j in jobs.items()
    }
    return jsonify(summary)


@app.route("/queue-status", methods=["GET"])
def queue_status():
    """Quick summary for the weekly digest."""
    counts = {"running": 0, "done": 0, "error": 0}
    for j in jobs.values():
        s = j.get("status", "unknown")
        counts[s] = counts.get(s, 0) + 1
    return jsonify(counts)


# ─────────────────────────────────────────────
# YOUTUBE OAUTH SETUP (run once manually)
# ─────────────────────────────────────────────

@app.route("/setup-auth/<channel>", methods=["GET"])
def setup_auth(channel):
    """
    One-time OAuth setup. Visit this URL in your browser.
    Saves credentials to assets/yt_credentials_{channel}.json
    """
    from google_auth_oauthlib.flow import InstalledAppFlow

    client_secrets = str(ASSETS_DIR / "client_secrets.json")
    if not Path(client_secrets).exists():
        return (
            "Download client_secrets.json from Google Cloud Console "
            "(APIs & Services → Credentials → OAuth 2.0 Client → Download JSON) "
            f"and place it at {client_secrets}", 400
        )

    scopes = [
        "https://www.googleapis.com/auth/youtube.upload",
        "https://www.googleapis.com/auth/youtube",
        "https://www.googleapis.com/auth/yt-analytics.readonly",
    ]

    flow = InstalledAppFlow.from_client_secrets_file(client_secrets, scopes)
    creds = flow.run_local_server(port=8080)

    creds_out = {
        "token":         creds.token,
        "refresh_token": creds.refresh_token,
        "client_id":     creds.client_id,
        "client_secret": creds.client_secret,
    }

    out_path = ASSETS_DIR / f"yt_credentials_{channel}.json"
    with open(out_path, "w") as f:
        json.dump(creds_out, f, indent=2)

    return f"✓ Credentials saved for channel: {channel}"


if __name__ == "__main__":
    print("Assembly server starting on http://localhost:5001")
    print("Endpoints:")
    print("  POST /assemble        — trigger video assembly")
    print("  POST /assemble-lofi   — trigger lofi video assembly")
    print("  POST /upload          — upload to YouTube")
    print("  GET  /job/<id>        — check job status")
    print("  GET  /jobs            — list all jobs")
    print("  GET  /setup-auth/<ch> — one-time YouTube OAuth")
    app.run(host="0.0.0.0", port=5001, debug=False)
