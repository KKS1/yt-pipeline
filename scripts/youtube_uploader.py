"""
Shared YouTube Data API upload helper.

Used by both the Flask server and direct manual publishing commands.
"""

import json
from pathlib import Path


PROJECT_ROOT = Path(__file__).parent.parent
ASSETS_DIR = PROJECT_ROOT / "assets"


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

    media = MediaFileUpload(
        video_path,
        mimetype="video/mp4",
        resumable=True,
        chunksize=10 * 1024 * 1024,
    )

    request_obj = youtube.videos().insert(
        part="snippet,status",
        body=body,
        media_body=media,
    )

    response = None
    while response is None:
        status, response = request_obj.next_chunk()
        if status:
            pct = int(status.progress() * 100)
            print(f"    Upload progress: {pct}%")

    video_id = response["id"]
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
