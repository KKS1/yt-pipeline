"""
facebook_uploader.py
────────────────────
Publish vertical videos to a Facebook Page as Reels via the Meta Reels
Publishing API.

The API is a three-phase flow:

  1. POST graph.facebook.com/{ver}/{page_id}/video_reels?upload_phase=start
     -> returns {video_id, upload_url}
  2. POST {upload_url}            (rupload.facebook.com, NOT the graph host)
     headers: Authorization: OAuth <page_access_token>, offset, file_size
     body: raw MP4 bytes
  3. POST graph.facebook.com/{ver}/{page_id}/video_reels?upload_phase=finish
     with video_id, video_state, title, description

Reels are published as DRAFT by default so the public publish time stays under
manual control in Meta Business Suite. Facebook has no "unlisted" visibility for
Page content, so a draft is the closest available equivalent.

Note: the video_reels endpoint supports no read, update, or delete operations.
A draft that uploads incorrectly can only be fixed or removed through Meta
Business Suite.

The App Secret is deliberately never read here. It is needed once, in a browser,
to exchange a short-lived user token for a long-lived one. Only the resulting
Page access token is used.
"""

from __future__ import annotations

import os
import re
import time
from pathlib import Path

import requests
from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent.parent

# Load environment variables from .env
load_dotenv(PROJECT_ROOT / ".env")

DEFAULT_GRAPH_VERSION = "v26.0"
DEFAULT_REEL_STATE = "DRAFT"
DEFAULT_TIMEOUT = 180
DEFAULT_ENABLED_CHANNELS = ("english-shorts", "english-quiz")

# Reel captions reuse the YouTube title by default — shorts titles are already
# written as hooks. Set FACEBOOK_CAPTION_STYLE=description for the first-paragraph
# behaviour instead.
DEFAULT_CAPTION_STYLE = "title"
VALID_CAPTION_STYLES = ("title", "description")

# Reels have no separate tags field, so hashtags ride along in the caption.
# Meta's own Reel guidance caps these at five; more starts reading as spam.
DEFAULT_MAX_HASHTAGS = 5

# #Shorts is a YouTube format signal with no meaning on Facebook, so it is
# dropped rather than carried into the Reel caption.
DEFAULT_DROP_HASHTAGS = ("shorts",)

# Set to an empty value to stop dropping anything (keeps #Shorts).
# FACEBOOK_REPLACE_HASHTAGS can add platform tags back, e.g. "#fbreels".

# Asks for the three signals Facebook's Reel ranking actually rewards. Likes are
# deliberately not requested — comments, saves and shares carry more weight.
DEFAULT_ENGAGEMENT_CTA = (
    "Save this for your next conversation, share it with someone who needs it, "
    "and drop in the comments which one you'll use."
)

# Meta hard limits for Reels. See:
# https://developers.facebook.com/docs/video-api/guides/reels-publishing
REELS_MAX_SECONDS = 90.0
REELS_MIN_SECONDS = 3.0
REELS_MAX_CAPTION_CHARS = 500
REELS_TARGET_ASPECT = 9 / 16

VALID_REEL_STATES = ("DRAFT", "SCHEDULED", "PUBLISHED")

# Graph API error codes worth a second attempt. Everything else (190 invalid
# token, 200 permissions, 100 invalid parameter) will not fix itself.
RETRIABLE_ERROR_CODES = frozenset({2, 17, 341, 368, 613})


class FacebookGraphError(RuntimeError):
    """A Facebook Graph API call failed."""

    def __init__(
        self,
        message: str,
        status_code=None,
        code=None,
        error_subcode=None,
        phase: str = None,
    ):
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.error_subcode = error_subcode
        self.phase = phase


def _page_id() -> str:
    return (os.getenv("FACEBOOK_PAGE_ID") or "").strip()


def _page_token() -> str:
    return (os.getenv("FACEBOOK_PAGE_ACCESS_TOKEN") or "").strip()


def _graph_version() -> str:
    version = (os.getenv("FACEBOOK_GRAPH_VERSION") or "").strip() or DEFAULT_GRAPH_VERSION
    return version if version.startswith("v") else f"v{version}"


def _reel_state() -> str:
    state = (os.getenv("FACEBOOK_REEL_STATE") or "").strip().upper() or DEFAULT_REEL_STATE
    if state not in VALID_REEL_STATES:
        raise ValueError(
            f"FACEBOOK_REEL_STATE must be one of {VALID_REEL_STATES}, got {state!r}"
        )
    return state


def _timeout() -> float:
    raw = (os.getenv("FACEBOOK_TIMEOUT") or "").strip()
    if not raw:
        return float(DEFAULT_TIMEOUT)
    try:
        return float(raw)
    except ValueError:
        return float(DEFAULT_TIMEOUT)


def _enabled_channels() -> frozenset:
    raw = (os.getenv("FACEBOOK_ENABLED_CHANNELS") or "").strip()
    if not raw:
        return frozenset(DEFAULT_ENABLED_CHANNELS)
    return frozenset(part.strip() for part in raw.split(",") if part.strip())


def facebook_channel_enabled(command_channel: str) -> bool:
    """True when this pipeline's videos should also cross-post to Facebook."""
    if not command_channel:
        return False
    return command_channel in _enabled_channels()


def facebook_credentials_present() -> bool:
    return bool(_page_id() and _page_token())


def _graph_url(edge: str = "") -> str:
    base = f"https://graph.facebook.com/{_graph_version()}/{_page_id()}"
    return f"{base}/{edge}" if edge else base


def _require_credentials() -> None:
    missing = []
    if not _page_id():
        missing.append("FACEBOOK_PAGE_ID")
    if not _page_token():
        missing.append("FACEBOOK_PAGE_ACCESS_TOKEN")
    if missing:
        raise FacebookGraphError(
            f"Missing Facebook credentials in .env: {', '.join(missing)}. "
            "Get a Page token from Graph API Explorer via "
            "GET /me/accounts?fields=id,name,access_token"
        )


def _safe_json(response) -> dict:
    try:
        payload = response.json()
    except ValueError:
        return {}
    return payload if isinstance(payload, dict) else {}


def _graph_error(payload: dict) -> dict:
    error = payload.get("error")
    return error if isinstance(error, dict) else {}


def _describe(payload: dict) -> str:
    error = _graph_error(payload)
    if not error:
        return str(payload)[:300]
    code = error.get("code")
    subcode = error.get("error_subcode")
    message = error.get("message", "Unknown Facebook Graph error")
    parts = [f"[{code}] {message}"]
    if subcode:
        parts.append(f"(subcode {subcode})")
    type_name = (error.get("type") or "").strip()
    if type_name:
        parts.append(f"type={type_name}")
    return " ".join(parts)


def _is_retriable(status_code, code) -> bool:
    """True when a transient failure is worth one more attempt."""
    if isinstance(status_code, int) and status_code >= 500:
        return True
    if isinstance(status_code, int) and status_code == 429:
        return True
    return code in RETRIABLE_ERROR_CODES


def _request(url: str, method: str, *, phase: str, params=None, headers=None, body=None, attempts: int = 2):
    """Call the Graph API with a single retry on transient failures.

    `method` is POST for the Reels upload phases and GET for reads — the Page
    node rejects POST, which surfaces as Graph error 240.
    """
    timeout = _timeout()
    last_status = None
    last_code = None
    last_subcode = None
    last_detail = None
    caller = requests.post if method.upper() == "POST" else requests.get

    for attempt in range(1, attempts + 1):
        try:
            response = caller(
                url, params=params, headers=headers, data=body, timeout=timeout
            )
        except requests.RequestException as exc:
            last_status = None
            last_code = None
            last_subcode = None
            last_detail = f"network error: {exc}"
            if attempt < attempts:
                print(f"    Facebook {phase}: {last_detail} — retrying ({attempt}/{attempts - 1})")
                time.sleep(2 * attempt)
                continue
            raise FacebookGraphError(
                f"Facebook {phase} failed: {last_detail}", phase=phase
            ) from exc

        if response.ok:
            return _safe_json(response)

        payload = _safe_json(response)
        error = _graph_error(payload)
        last_status = response.status_code
        last_code = error.get("code")
        last_subcode = error.get("error_subcode")
        last_detail = _describe(payload) or f"HTTP {response.status_code}"

        if _is_retriable(last_status, last_code) and attempt < attempts:
            print(f"    Facebook {phase}: {last_detail} — retrying ({attempt}/{attempts - 1})")
            time.sleep(2 * attempt)
            continue
        break

    raise FacebookGraphError(
        f"Facebook {phase} failed: {last_detail}",
        status_code=last_status,
        code=last_code,
        error_subcode=last_subcode,
        phase=phase,
    )


def _post(url: str, **kwargs):
    return _request(url, "POST", **kwargs)


def _get(url: str, **kwargs):
    return _request(url, "GET", **kwargs)


def _probe_media(video_path: str) -> dict:
    """ffprobe the file for the Reel duration/aspect pre-flight checks.

    Failures here are warnings, never fatal — a marginal video still gets
    uploaded so Meta can make the final call.
    """
    info = {"duration": None, "width": None, "height": None}
    try:
        from ffmpeg_assembler import get_media_duration, _video_stream_info
    except Exception as exc:  # ffprobe or ffmpeg module unavailable
        print(f"  Facebook: media probe skipped ({exc})")
        return info

    try:
        info["duration"] = get_media_duration(video_path)
    except Exception as exc:
        print(f"  Facebook: could not read duration ({exc})")
    try:
        stream = _video_stream_info(video_path)
        info["width"] = stream.get("width")
        info["height"] = stream.get("height")
    except Exception as exc:
        print(f"  Facebook: could not read video dimensions ({exc})")

    duration = info["duration"]
    if duration:
        if duration > REELS_MAX_SECONDS:
            print(
                f"  ⚠️ Facebook: video is {duration:.1f}s but Reels cap at "
                f"{REELS_MAX_SECONDS:.0f}s — publishing anyway, it may be rejected."
            )
        elif duration < REELS_MIN_SECONDS:
            print(
                f"  ⚠️ Facebook: video is only {duration:.1f}s but Reels require at "
                f"least {REELS_MIN_SECONDS:.0f}s — publishing anyway, it may be rejected."
            )

    width, height = info["width"], info["height"]
    if width and height:
        ratio = width / height
        if abs(ratio - REELS_TARGET_ASPECT) > 0.02:
            print(
                f"  ⚠️ Facebook: video is {width}x{height} (ratio {ratio:.2f}), "
                f"Reels expect 9:16 — publishing anyway."
            )
    return info


def _caption_style() -> str:
    raw = (os.getenv("FACEBOOK_CAPTION_STYLE") or "").strip().lower() or DEFAULT_CAPTION_STYLE
    if raw not in VALID_CAPTION_STYLES:
        raise ValueError(
            f"FACEBOOK_CAPTION_STYLE must be one of {VALID_CAPTION_STYLES}, got {raw!r}"
        )
    return raw


def _append_youtube_link() -> bool:
    raw = (os.getenv("FACEBOOK_APPEND_YOUTUBE_LINK") or "").strip().lower()
    if not raw:
        return False
    return raw not in ("0", "false", "no", "off")


def _engagement_cta() -> str:
    """Call to action asking for the three signals Facebook rewards.

    Comments, saves and shares all feed the ranking signal on Reels, unlike
    likes. Overridable for A/B testing via FACEBOOK_ENGAGEMENT_CTA.
    """
    raw = os.getenv("FACEBOOK_ENGAGEMENT_CTA")
    if raw is not None:
        return raw.strip()
    return DEFAULT_ENGAGEMENT_CTA


def _hashtags_to_drop() -> frozenset:
    """Hashtags that mean nothing on Facebook and cost caption space.

    #Shorts is a YouTube format signal. Facebook has no Shorts format — Meta
    renamed the Videos tab to Reels and every video on Facebook is a Reel — so
    the tag carries no meaning there.
    """
    raw = os.getenv("FACEBOOK_DROP_HASHTAGS")
    if raw is None:
        return frozenset(DEFAULT_DROP_HASHTAGS)
    return frozenset(
        part.strip().lstrip("#").lower() for part in raw.split(",") if part.strip()
    )


def _hashtag_replacements() -> list:
    """Platform tags added in place of any dropped ones, if configured."""
    raw = os.getenv("FACEBOOK_REPLACE_HASHTAGS") or ""
    return [part.strip() for part in raw.split(",") if part.strip()]


def _extract_hashtags(description: str) -> list:
    """Pull the hashtag block out of a YouTube description, in order.

    The description carries the hashtag line at the very end (see
    english_generator.ensure_english_quiz_shorts_hashtags), so a title-style
    caption would otherwise drop every tag. Platform-specific tags are filtered
    out — see _hashtags_to_drop.
    """
    drop = _hashtags_to_drop()
    found = []
    seen = set()
    for match in re.finditer(r"#\w+", description or ""):
        tag = match.group(0)
        key = tag.lstrip("#").lower()
        if key in drop or key in seen:
            continue
        seen.add(key)
        found.append(tag)

    for tag in _hashtag_replacements():
        key = tag.lstrip("#").lower()
        if key not in seen:
            seen.add(key)
            found.append(tag)
    return found


def _reel_caption(description: str, title: str = "", youtube_id: str = None) -> str:
    """Build the Reel caption from the YouTube title and description.

    Style "title" (default) reuses the YouTube title verbatim. Shorts titles are
    already written as scroll-stopping hooks ("STOP Saying 'No Problem' — Say
    This Instead"), which is exactly what a Reel caption needs, and it matches
    what was previously posted by hand.

    Style "description" keeps the old behaviour: the first non-empty paragraph
    of the description, which drops the YouTube-specific boilerplate
    (playlists, timelines, tag blocks).

    Hashtags are lifted out of the description and re-attached in both styles —
    Reels have no separate tags field, so the caption is the only place they
    can live. The engagement CTA is appended last.

    A "Watch on YouTube" link is only appended when FACEBOOK_APPEND_YOUTUBE_LINK
    is set, because Facebook does not linkify URLs in captions — an unclickable
    link just burns caption characters.
    """
    if _caption_style() == "title":
        text = (title or "").strip()
        if not text:
            # No title is unusual; fall back to the description hook.
            text = _description_hook(description)
    else:
        text = _description_hook(description) or (title or "").strip()

    tags = _extract_hashtags(description)
    cta = _engagement_cta()
    parts = [text] if text else []

    if tags and _include_hashtags():
        tag_line = " ".join(tags[:DEFAULT_MAX_HASHTAGS])
        if tag_line:
            parts.append(tag_line)

    if cta:
        parts.append(cta)

    caption = "\n\n".join(parts)

    if youtube_id and _append_youtube_link():
        link = f"Watch on YouTube: https://youtu.be/{youtube_id}"
        caption = f"{caption}\n{link}" if caption else link

    if len(caption) > REELS_MAX_CAPTION_CHARS:
        # Truncate from the middle: keep the hook and the CTA, shed hashtags.
        caption = _truncate_keeping_ends(caption, text, cta, tags)
    return caption


def _truncate_keeping_ends(caption: str, hook: str, cta: str, tags: list) -> str:
    """Shed content from the middle outwards, never the hook or the CTA.

    Priority order, highest protected last: hook, then hashtags, then CTA. The
    CTA is protected because an engagement ask is the whole point of including
    it; hashtags are the first thing sacrificed since they aid discovery but
    are not needed for the post to read.
    """
    hook = (hook or "").strip()
    tag_line = " ".join(tags[:DEFAULT_MAX_HASHTAGS]) if _include_hashtags() else ""
    cta = (cta or "").strip()

    def build(hook_text: str, tag_text: str, cta_text: str) -> str:
        return "\n\n".join(p for p in (hook_text, tag_text, cta_text) if p)

    # Give the hook as much room as possible, then decide what else fits.
    for tags_in in (tag_line, ""):
        base = build(hook, tags_in, cta)
        if len(base) <= REELS_MAX_CAPTION_CHARS:
            return base

    room = REELS_MAX_CAPTION_CHARS - (len(cta) + 2 if cta else 0)
    if room <= 0:
        # Not even the CTA fits: keep the tail of the hook.
        return (hook or caption)[-REELS_MAX_CAPTION_CHARS:].strip()

    shortened_hook = hook[:room].rstrip()
    if len(shortened_hook) < len(hook):
        # The ellipsis is itself a character, so reserve room for it.
        shortened_hook = shortened_hook[: max(0, room - 1)].rstrip(" ,;:-—") + "…"
    return build(shortened_hook, "", cta)


def _include_hashtags() -> bool:
    raw = (os.getenv("FACEBOOK_INCLUDE_HASHTAGS") or "").strip().lower()
    if not raw:
        return True
    return raw not in ("0", "false", "no", "off")


def _description_hook(description: str) -> str:
    """First non-empty paragraph of a YouTube description."""
    text = (description or "").strip().replace("{playlist_url}", "").strip()
    for block in text.split("\n\n"):
        candidate = block.strip()
        if candidate:
            return candidate
    return ""


SCOPES_NEEDED_FOR_UPLOAD = (
    "pages_manage_posts",
    "pages_read_engagement",
    "pages_show_list",
)


def facebook_token_scopes(app_access_token: str) -> dict:
    """Introspect the configured Page token via GET /debug_token.

    This is the only call that reveals which scopes the token actually carries
    and — critically — which app issued it. Tokens minted by Graph API Explorer's
    default app belong to that app, not to yours, so they read fine (public_page)
    yet fail every write with error 200.

    The App access token is passed in by the caller and never persisted here.
    """
    _require_credentials()
    payload = _get(
        f"https://graph.facebook.com/{_graph_version()}/debug_token",
        phase="debug_token",
        params={
            "input_token": _page_token(),
            "access_token": app_access_token,
        },
        attempts=1,
    )
    data = payload.get("data")
    if not isinstance(data, dict):
        raise FacebookGraphError(
            f"debug_token returned no data: {_describe(payload)}",
            phase="debug_token",
        )
    return data


def facebook_verify_credentials() -> dict:
    """Confirm the Page ID and token work together. Returns the Page fields.

    Uses GET: the Page node does not accept POST, which Graph reports as
    error 240 ("Requires a valid user to be specified").
    """
    _require_credentials()
    payload = _get(
        _graph_url(),
        phase="verify",
        params={
            "fields": "id,name,fan_count,category",
            "access_token": _page_token(),
        },
        attempts=2,
    )
    return payload


def facebook_upload_reel(
    video_path: str,
    title: str = "",
    description: str = "",
    video_state: str = None,
    schedule_time: str = None,
    youtube_id: str = None,
) -> dict:
    """Upload a vertical video to the Facebook Page as a Reel.

    Defaults to a DRAFT so the public publish time stays under manual control
    in Meta Business Suite. Pass video_state="SCHEDULED" with schedule_time to
    hand the timing to Meta, or "PUBLISHED" to go live immediately.
    """
    _require_credentials()

    state = (video_state or _reel_state()).upper()
    if state not in VALID_REEL_STATES:
        raise ValueError(f"video_state must be one of {VALID_REEL_STATES}, got {state!r}")

    if state == "SCHEDULED" and not schedule_time:
        raise ValueError("video_state='SCHEDULED' requires schedule_time")

    path = Path(video_path)
    if not path.exists():
        raise FileNotFoundError(f"Facebook upload source not found: {path}")

    media = _probe_media(str(path))
    caption = _reel_caption(description, title=title, youtube_id=youtube_id)
    token = _page_token()

    print(f"\nUploading to Facebook as {state}...")
    print(f"  Reel: {title}")

    # Phase 1 — open the upload session.
    start = _post(
        _graph_url("video_reels"),
        phase="phase 1 (start)",
        params={"upload_phase": "start", "access_token": token},
        attempts=2,
    )
    video_id = start.get("video_id")
    upload_url = start.get("upload_url")
    if not video_id or not upload_url:
        raise FacebookGraphError(
            f"Facebook phase 1 (start) returned no video_id/upload_url: {start}",
            phase="phase 1 (start)",
        )
    print(f"  video_id: {video_id}")

    # Phase 2 — push the bytes to the rupload host.
    size = path.stat().st_size
    with open(path, "rb") as handle:
        upload = _post(
            upload_url,
            phase="phase 2 (upload)",
            headers={
                "Authorization": f"OAuth {token}",
                "offset": "0",
                "file_size": str(size),
                "Content-Type": "application/octet-stream",
            },
            body=handle,
            attempts=2,
        )
    if upload.get("success") is False:
        raise FacebookGraphError(
            f"Facebook phase 2 (upload) rejected the file: {upload}",
            phase="phase 2 (upload)",
        )

    # Phase 3 — close the session and set the final state.
    finish_params = {
        "upload_phase": "finish",
        "video_id": video_id,
        "video_state": state,
        "title": (title or "").strip(),
        "description": caption,
        "access_token": token,
    }
    if state == "SCHEDULED":
        finish_params["scheduled_publish_time"] = schedule_time

    finish = _post(
        _graph_url("video_reels"),
        phase="phase 3 (finish)",
        params=finish_params,
        attempts=2,
    )
    if finish.get("success") is False:
        raise FacebookGraphError(
            f"Facebook phase 3 (finish) failed: {_describe(finish)}",
            phase="phase 3 (finish)",
        )

    post_id = finish.get("post_id")
    result = {
        "facebook_video_id": video_id,
        "post_id": post_id,
        "video_state": state,
        "reel_url": f"https://www.facebook.com/reel/{video_id}",
        "caption": caption,
        "duration": media.get("duration"),
        "width": media.get("width"),
        "height": media.get("height"),
    }

    print(f"\nFacebook {state}: {result['reel_url']}")
    if state == "DRAFT":
        print("  Draft only — publish it from Meta Business Suite when you're ready.")
    return result
