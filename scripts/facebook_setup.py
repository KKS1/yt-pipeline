"""
facebook_setup.py
─────────────────
Validate the Facebook Page credentials before the pipeline tries to use them.

Run from the repo root:

    python scripts/facebook_setup.py

Reads FACEBOOK_PAGE_ID / FACEBOOK_PAGE_ACCESS_TOKEN from .env, so the token
never appears on a command line or in shell history.

This only performs a read (GET /{page_id}) — it does not upload anything. Use
--test-upload to additionally push a real draft Reel, which is the only way to
confirm Meta Business Suite surfaces API-created drafts.
"""

import sys
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(PROJECT_ROOT / ".env")

# Add scripts directory to path
sys.path.insert(0, str(Path(__file__).parent))

import os  # noqa: E402

from facebook_uploader import (  # noqa: E402
    DEFAULT_ENABLED_CHANNELS,
    SCOPES_NEEDED_FOR_UPLOAD,
    FacebookGraphError,
    facebook_credentials_present,
    facebook_token_scopes,
    facebook_upload_reel,
    facebook_verify_credentials,
)


def _print_config() -> None:
    page_id = (os.getenv("FACEBOOK_PAGE_ID") or "").strip()
    token = (os.getenv("FACEBOOK_PAGE_ACCESS_TOKEN") or "").strip()
    state = (os.getenv("FACEBOOK_REEL_STATE") or "DRAFT").strip().upper()
    version = (os.getenv("FACEBOOK_GRAPH_VERSION") or "").strip()
    app_id = (os.getenv("FACEBOOK_APP_ID") or "").strip()
    channels = (os.getenv("FACEBOOK_ENABLED_CHANNELS") or "").strip()

    print("Configuration")
    print("──────────────")
    print(f"  FACEBOOK_PAGE_ID            : {page_id or '(missing)'}")
    print(f"  FACEBOOK_PAGE_ACCESS_TOKEN  : {(token[:8] + '…' + str(len(token)) + ' chars') if token else '(missing)'}")
    print(f"  FACEBOOK_REEL_STATE         : {state}")
    print(f"  FACEBOOK_GRAPH_VERSION      : {version or '(default)'}")
    print(f"  FACEBOOK_ENABLED_CHANNELS   : {channels or ', '.join(DEFAULT_ENABLED_CHANNELS) + ' (default)'}")
    print(f"  FACEBOOK_APP_ID             : {app_id or '(not set — optional)'}")
    print()


def _diagnose_token_type() -> None:
    """Distinguish a Page token from a User token — the most common mix-up.

    A User token works fine for /me but cannot address a Page node, which is
    what makes this fail with subcode 33.
    """
    import requests

    from facebook_uploader import _graph_version, _page_token

    try:
        me = requests.get(
            f"https://graph.facebook.com/{_graph_version()}/me",
            params={"fields": "id,name", "access_token": _page_token()},
            timeout=30,
        ).json()
        if "error" not in me:
            print("\n  Note: this token identifies a USER ("
                  f"{me.get('name')}, id {me.get('id')}), not a Page.")
            print("  A User token cannot address a Page node. Use the token that")
            print("  /me/accounts returns for the page row instead.")
    except Exception:
        pass


def _report_scopes() -> bool:
    """Print the scopes the configured token actually carries.

    Needs an App access token, which is only derivable from the App Secret. The
    secret is never stored, so this asks for it interactively and keeps it in
    memory for a single request. Returns True if the token looks upload-ready.
    """
    app_id = (os.getenv("FACEBOOK_APP_ID") or "").strip()
    if not app_id:
        print("Token scopes")
        print("────────────")
        print("  Skipped: FACEBOOK_APP_ID is not set in .env.")
        print("  Set it to your numeric App ID to enable this check.")
        return False

    app_secret = os.getenv("FACEBOOK_APP_SECRET", "").strip()
    if not app_secret:
        import getpass

        print("Token scopes")
        print("────────────")
        print(f"  To inspect the token, supply the App Secret for app {app_id}.")
        print("  It is used for one debug_token request and never stored.")
        try:
            app_secret = getpass.getpass("  App Secret: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n  Cancelled.")
            return False
        if not app_secret:
            print("  No secret given — skipping.")
            return False

    try:
        data = facebook_token_scopes(f"{app_id}|{app_secret}")
    except FacebookGraphError as exc:
        print(f"  Could not read token scopes: {exc}")
        return False
    finally:
        app_secret = ""

    scopes = set(data.get("scopes") or [])
    issuing_app = data.get("app_id")
    is_page_token = bool(data.get("target_ids"))

    print("Token scopes")
    print("────────────")
    print(f"  issued by app  : {issuing_app}")
    if issuing_app and issuing_app != app_id:
        print("  !! This token was issued by a DIFFERENT app than")
        print(f"     FACEBOOK_APP_ID ({app_id}). It can read the Page but was")
        print("     never granted your app's write permissions. Re-mint it from a")
        print("     token generated while your app is selected.")
    print(f"  type          : {'Page' if is_page_token else 'User'}")
    print(f"  expires       : {_expiry_text(data.get('expires_at'))}")

    missing = [s for s in SCOPES_NEEDED_FOR_UPLOAD if s not in scopes]
    for scope in SCOPES_NEEDED_FOR_UPLOAD:
        print(f"  {'[x]' if scope in scopes else '[ ]'} {scope}")

    if not is_page_token:
        print("\n  !! This is a User token, not a Page token. Take the access_token")
        print("     from your page's row of GET /me/accounts?fields=id,name,access_token")
        return False

    if missing:
        print(f"\n  Missing upload scope(s): {', '.join(missing)}")
        return False

    print("\n  All upload scopes present.")
    return True


def _expiry_text(expires_at) -> str:
    if not expires_at:
        return "never (long-lived)"
    try:
        from datetime import datetime, timezone

        return datetime.fromtimestamp(int(expires_at), timezone.utc).strftime(
            "%Y-%m-%d %H:%M:%S UTC"
        )
    except (TypeError, ValueError):
        return str(expires_at)


def _explain_failure(exc: FacebookGraphError, stage: str = "verify") -> None:
    code = getattr(exc, "code", None)
    phase = getattr(exc, "phase", None)
    message = str(exc)

    heading = "Upload failed." if stage == "upload" else "Verification failed."
    print(f"\n{heading}")
    print("─" * len(heading))
    print(f"  {message}")

    lowered = message.lower()

    if code == 190 or "cannot parse access token" in lowered:
        print("\n  The token is invalid or expired. A Page token derived from a")
        print("  *long-lived* user token does not expire; one from a short-lived")
        print("  token stops working after about an hour.")
        print("  Refresh it in Graph API Explorer:")
        print("    GET /me/accounts?fields=id,name,access_token")
    elif code == 240:
        print("\n  The Page node does not accept POST — reads must use GET.")
    elif code == 200 or "permission" in lowered:
        if phase == "start" or "pages_manage_posts" in lowered:
            print("\n  The token can READ the Page but was never granted write access.")
            print("  This is the expected symptom of a Page token derived from a user")
            print("  token that lacked pages_manage_posts. A Page token cannot gain")
            print("  scopes after the fact — scopes are fixed when the user token is")
            print("  minted. Fix it in this order:")
            print("\n    1. Request a NEW user token including every scope:")
            print("       pages_manage_posts, pages_read_engagement, pages_show_list")
            print("       (plus pages_manage_engagement for comment replies)")
            print("    2. Confirm the app has pages_manage_posts approved. In")
            print("       Development mode only app-role testers get it; for a real")
            print("       Page, the app needs Advanced Access via App Review.")
            print("    3. Re-derive the Page token from that new user token:")
            print("       GET /me/accounts?fields=id,name,access_token")
            print("    4. Put the new access_token in .env as")
            print("       FACEBOOK_PAGE_ACCESS_TOKEN, then re-run this check.")
            print("\n  Do NOT reuse a long-lived user token minted before adding the")
            print("  scopes — it carries the old scope set forever.")
        else:
            print("\n  Permission error. The token needs pages_manage_posts,")
            print("  pages_read_engagement and pages_show_list.")
            print("  If the app is still in Development mode, either add yourself as a")
            print("  Page role or switch the app to Live mode.")
    elif code == 100:
        print("\n  Facebook could not read that Page ID.")
        print("  The id in a facebook.com/profile.php?id=... URL is a legacy alias")
        print("  and is NOT the Graph node id. Get the real one from:")
        print("    GET /me/accounts?fields=id,name,access_token")
        _diagnose_token_type()


def main() -> int:
    test_upload = "--test-upload" in sys.argv
    video_path = None
    if "--video" in sys.argv:
        video_path = sys.argv[sys.argv.index("--video") + 1]

    print("Facebook credential check")
    print("==========================\n")

    _print_config()

    if not facebook_credentials_present():
        print("Missing Facebook credentials in .env.")
        print("  Add these two lines:\n")
        print("    FACEBOOK_PAGE_ID=<numeric page id>")
        print("    FACEBOOK_PAGE_ACCESS_TOKEN=<page token>\n")
        print("  The page token comes from Graph API Explorer:")
        print("    GET /me/accounts?fields=id,name,access_token")
        return 1

    try:
        page = facebook_verify_credentials()
    except FacebookGraphError as exc:
        _explain_failure(exc)
        return 1

    print("Token verified")
    print("──────────────")
    print(f"  Page name : {page.get('name', '(unknown)')}")
    print(f"  Page ID   : {page.get('id', '(unknown)')}")
    print(f"  Category  : {page.get('category', '(unknown)')}")
    fans = page.get("fan_count")
    print(f"  Followers : {fans:,}" if isinstance(fans, int) else "  Followers : (unknown)")
    print()

    upload_ready = _report_scopes()
    print()

    if not test_upload:
        print("Read-only check passed. Nothing was uploaded.")
        print()
        if not upload_ready:
            print("Upload readiness is UNCONFIRMED — run the test upload to see the")
            print("real write-scope behaviour:")
        print("To confirm Meta Business Suite surfaces API-created drafts, push one:")
        print("  python scripts/facebook_setup.py --test-upload --video output/<short>.mp4")
        return 0

    if not video_path:
        print("--test-upload needs --video <path to a vertical mp4>")
        return 1

    if not Path(video_path).exists():
        print(f"Video not found: {video_path}")
        return 1

    print("Pushing a test draft Reel…")
    print("(It will NOT be public. Publish or delete it from Meta Business Suite.)")
    print()

    try:
        result = facebook_upload_reel(
            video_path=video_path,
            title="Facebook Reel publish test",
            description="Automated draft check. Safe to delete.",
        )
    except FacebookGraphError as exc:
        _explain_failure(exc, stage="upload")
        return 1

    print("\nDraft created.")
    print("─────────────")
    print(f"  video_id : {result['facebook_video_id']}")
    print(f"  state    : {result['video_state']}")
    print(f"  url      : {result['reel_url']}")
    print()
    print("Now open Meta Business Suite → Content and confirm the draft is listed.")
    print("If it is not visible there, set FACEBOOK_REEL_STATE=SCHEDULED instead —")
    print("scheduled posts are unambiguously editable from the Suite.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
