"""
Shared YouTube Data API upload helper.

Used by both the Flask server and direct manual publishing commands.
"""

import errno
import hashlib
import json
import os
import random
import socket
import ssl
import time
from pathlib import Path


PROJECT_ROOT = Path(__file__).parent.parent
ASSETS_DIR = PROJECT_ROOT / "assets"
UPLOAD_SESSION_DIR = PROJECT_ROOT / "output" / ".youtube_upload_sessions"


def _upload_session_path(video_path: str, channel: str) -> Path:
    video = Path(video_path)
    stat = video.stat()
    session_key = json.dumps(
        {
            "path": str(video.resolve()),
            "size": stat.st_size,
            "mtime": int(stat.st_mtime),
            "channel": channel,
        },
        sort_keys=True,
    )
    digest = hashlib.sha256(session_key.encode("utf-8")).hexdigest()[:24]
    return UPLOAD_SESSION_DIR / f"{digest}.json"


def _is_retriable_upload_error(exc: Exception) -> bool:
    status = getattr(getattr(exc, "resp", None), "status", None)
    if status in (500, 502, 503, 504):
        return True

    if isinstance(exc, (BrokenPipeError, ConnectionResetError, TimeoutError, socket.timeout, ssl.SSLError)):
        return True

    if isinstance(exc, OSError):
        return exc.errno in (
            errno.EPIPE,
            errno.ECONNRESET,
            errno.ETIMEDOUT,
            errno.ECONNABORTED,
        )

    return False


def _save_resumable_session(path: Path, request_obj, video_path: str, channel: str) -> None:
    resumable_uri = getattr(request_obj, "resumable_uri", None)
    if not resumable_uri:
        return

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "resumable_uri": resumable_uri,
                "video_path": str(Path(video_path).resolve()),
                "channel": channel,
                "saved_at": time.time(),
            },
            indent=2,
        ),
        encoding="utf-8",
    )


def youtube_upload(
    video_path: str,
    title: str,
    description: str,
    tags: list,
    thumbnail_path: str = None,
    channel: str = "trending",
    schedule_time: str = None,
) -> dict:
    """Upload a video to YouTube using channel-specific OAuth credentials."""

    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build
    from googleapiclient.http import MediaFileUpload

    creds_file = ASSETS_DIR / f"yt_credentials_{channel}.json"
    if not creds_file.exists():
        raise FileNotFoundError(
            f"No credentials found: {creds_file}\n"
            f"Run python scripts/server.py and visit http://localhost:5001/setup-auth/{channel}"
        )

    with open(creds_file) as f:
        creds_data = json.load(f)

    creds = Credentials(
        token=creds_data["token"],
        refresh_token=creds_data["refresh_token"],
        token_uri="https://oauth2.googleapis.com/token",
        client_id=creds_data["client_id"],
        client_secret=creds_data["client_secret"],
    )

    youtube = build("youtube", "v3", credentials=creds)

    category_map = {
        "trending": "22",
        "family": "24",
        "lofi": "10",
        "kids": "24",
    }

    body = {
        "snippet": {
            "title": title[:100],
            "description": description[:5000],
            "tags": tags[:500],
            "categoryId": category_map.get(channel, "22"),
            "defaultLanguage": "en",
        },
        "status": {
            "privacyStatus": "private" if schedule_time else "public",
            "selfDeclaredMadeForKids": channel == "kids",
        },
    }

    if schedule_time:
        body["status"]["publishAt"] = schedule_time

    print(f"  Uploading to YouTube [{channel}]: {title[:60]}...")

    chunk_mb = int(os.getenv("YT_UPLOAD_CHUNK_MB", "32"))
    media = MediaFileUpload(
        video_path,
        mimetype="video/mp4",
        resumable=True,
        chunksize=chunk_mb * 1024 * 1024,
    )

    request_obj = youtube.videos().insert(
        part="snippet,status",
        body=body,
        media_body=media,
    )

    session_path = _upload_session_path(video_path, channel)
    if session_path.exists():
        try:
            session_data = json.loads(session_path.read_text(encoding="utf-8"))
            request_obj.resumable_uri = session_data["resumable_uri"]
            print("  Resuming previous YouTube upload session...")
        except (KeyError, json.JSONDecodeError, OSError):
            session_path.unlink(missing_ok=True)

    max_retries = int(os.getenv("YT_UPLOAD_MAX_RETRIES", "10"))
    base_sleep = float(os.getenv("YT_UPLOAD_RETRY_BASE_SECONDS", "5"))
    max_sleep = float(os.getenv("YT_UPLOAD_RETRY_MAX_SECONDS", "120"))
    retries = 0
    last_pct = None

    response = None
    while response is None:
        try:
            status, response = request_obj.next_chunk()
            _save_resumable_session(session_path, request_obj, video_path, channel)
            retries = 0
        except Exception as exc:
            _save_resumable_session(session_path, request_obj, video_path, channel)
            if not _is_retriable_upload_error(exc) or retries >= max_retries:
                raise

            retries += 1
            sleep_for = min(max_sleep, base_sleep * (2 ** (retries - 1)))
            sleep_for += random.uniform(0, min(3, sleep_for / 4))
            print(
                f"    Upload interrupted ({exc}); retrying "
                f"{retries}/{max_retries} in {sleep_for:.1f}s..."
            )
            time.sleep(sleep_for)
            continue

        if status:
            pct = int(status.progress() * 100)
            if pct != last_pct:
                print(f"    Upload progress: {pct}%")
                last_pct = pct

    video_id = response["id"]
    session_path.unlink(missing_ok=True)
    print(f"  Uploaded: https://youtu.be/{video_id}")

    if thumbnail_path and Path(thumbnail_path).exists():
        youtube.thumbnails().set(
            videoId=video_id,
            media_body=MediaFileUpload(thumbnail_path, mimetype="image/jpeg"),
        ).execute()
        print("  Thumbnail set")

    return {
        "youtube_id": video_id,
        "url": f"https://youtu.be/{video_id}",
        "status": "scheduled" if schedule_time else "public",
    }
