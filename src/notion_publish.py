"""Publish a video because someone pressed a button in Notion.

The button is the trigger, never the source of truth. Notion's automation
webhooks carry page *properties* only — not page content — and nothing stops
a payload being replayed or forged, so the only thing taken from the request
body is which page was clicked. Everything that decides what gets published is
re-read from the Notion API afterwards.

Publishing to YouTube cannot be undone, so the guards are deliberately strict:
the card must be a video, it must name a source, and it must not already be
published. Anything else is refused with a reason written back onto the card.
"""

import hmac
import os
import threading
import traceback

import requests
from flask import Blueprint, jsonify, request

API = "https://api.notion.com/v1"
NOTION_VERSION = "2025-09-03"
TIMEOUT = 30


class Refused(Exception):
    """The publish was refused; the message is safe to write back to Notion."""


def _headers() -> dict:
    token = os.environ.get("NOTION_API_KEY")
    if not token:
        raise Refused("NOTION_API_KEY is not set on the publisher.")
    return {"Authorization": f"Bearer {token}",
            "Notion-Version": NOTION_VERSION,
            "Content-Type": "application/json"}


# --- reading the card ---

def page_id_from(payload: dict) -> str:
    """Find the clicked page's id, wherever this flavour of webhook put it.

    Notion has shipped several payload shapes across buttons, database
    automations and API subscriptions. Rather than pin to one, look in the
    places all of them use.
    """
    if not isinstance(payload, dict):
        raise Refused("Webhook body was not an object.")
    for candidate in (payload.get("page_id"),
                      payload.get("id"),
                      (payload.get("data") or {}).get("id"),
                      (payload.get("entity") or {}).get("id"),
                      (payload.get("page") or {}).get("id")):
        if isinstance(candidate, str) and candidate.strip():
            return candidate.strip()
    raise Refused("Could not find a page id in the webhook body.")


def _plain(prop) -> str:
    if not prop:
        return ""
    kind = prop.get("type")
    if kind in ("title", "rich_text"):
        return "".join(p.get("plain_text", "") for p in prop.get(kind, []))
    if kind == "select":
        return (prop.get("select") or {}).get("name", "")
    if kind == "status":
        return (prop.get("status") or {}).get("name", "")
    if kind == "url":
        return prop.get("url") or ""
    return ""


def fetch_card(page_id: str) -> dict:
    """Re-read the card from the API. This, not the webhook body, is the truth."""
    response = requests.get(f"{API}/pages/{page_id}", headers=_headers(),
                            timeout=TIMEOUT)
    if response.status_code == 404:
        raise Refused("That page is not shared with the publisher's Notion "
                      "integration.")
    if response.status_code != 200:
        raise Refused(f"Notion returned {response.status_code} for the page.")
    props = response.json().get("properties", {})
    return {
        "title": _plain(props.get("Name")),
        "type": _plain(props.get("Type")),
        "status": _plain(props.get("Status")),
        "source": _plain(props.get("Source video")),
        "headline": _plain(props.get("Thumbnail headline")),
        "subline": _plain(props.get("Thumbnail subline")),
        "style": _plain(props.get("Thumbnail style")),
        "live_url": _plain(props.get("Channel + live URL")),
    }


def check(card: dict) -> None:
    """Refuse anything that should not become a YouTube video."""
    if card["type"] != "video":
        raise Refused(f"Type is '{card['type'] or 'unset'}', not 'video'. "
                      "Only video cards publish.")
    if not card["source"]:
        raise Refused("No Source video on the card.")
    if card["status"] == "Published":
        raise Refused("Already Published. Clear the status to republish "
                      "deliberately.")


# --- writing back ---

def update_card(page_id: str, **props) -> None:
    """Best-effort write-back. Never raises: a publish that succeeded must not
    be reported as a failure because Notion was briefly unreachable."""
    body = {}
    if "status" in props:
        body["Status"] = {"select": {"name": props["status"]}}
    if "live_url" in props:
        body["Channel + live URL"] = {
            "rich_text": [{"text": {"content": props["live_url"][:1900]}}]}
    if "log" in props:
        body["Publish log"] = {
            "rich_text": [{"text": {"content": props["log"][:1900]}}]}
    if not body:
        return
    try:
        requests.patch(f"{API}/pages/{page_id}", headers=_headers(),
                       json={"properties": body}, timeout=TIMEOUT)
    except Exception as exc:  # noqa: BLE001
        print(f"notion write-back failed for {page_id}: {exc}")


# --- the run ---

def _publish(page_id: str, card: dict) -> None:
    from src.pipeline import run_pipeline

    lines = []

    def log(message):
        print(message)
        lines.append(str(message))

    try:
        update_card(page_id, status="In progress",
                    log="Publishing — started from the Notion button.")
        result = run_pipeline(card["source"], log=log)
        youtube = (result or {}).get("youtube_url") or ""
        update_card(
            page_id,
            status="Published" if youtube else "Waiting approval",
            live_url=youtube or card["live_url"],
            log=("Published: " + youtube) if youtube else
                ("Pipeline finished without a YouTube URL.\n"
                 + "\n".join(lines[-6:])))
    except Exception as exc:  # noqa: BLE001
        traceback.print_exc()
        # Back to Waiting approval, not Published — a half-finished publish
        # must never look done on the board.
        update_card(page_id, status="Waiting approval",
                    log=f"Failed: {exc}\n" + "\n".join(lines[-6:]))


def handle(payload: dict) -> dict:
    """Validate, then publish in the background.

    Returns immediately: the pipeline takes minutes — dubbing, transcoding,
    three uploads — and Notion's webhook will have long since timed out.
    """
    page_id = page_id_from(payload)
    card = fetch_card(page_id)
    check(card)

    threading.Thread(target=_publish, args=(page_id, card), daemon=True,
                     name=f"notion-publish-{page_id[:8]}").start()
    return {"ok": True, "page_id": page_id, "title": card["title"],
            "started": True}


# --- the route ---
#
# A blueprint rather than a route on the app, so wiring it up is one line in
# slack_app.py and nothing else there has to move:
#
#     from src.notion_publish import notion_bp
#     app.register_blueprint(notion_bp)
#
# Then in Notion: add a Button property to Content Pipeline, action "Send
# webhook", URL https://video-upload.agents.wxrks.app/notion/publish, with the
# header Authorization: Bearer <NOTION_HOOK_SECRET>.

notion_bp = Blueprint("notion_publish", __name__)


def _authorised() -> bool:
    """Notion does not sign automation or button webhooks, so this rests
    entirely on a shared secret sent as a custom header. With no secret
    configured the endpoint stays shut — an open publish trigger is worse
    than a broken one."""
    secret = os.environ.get("NOTION_HOOK_SECRET", "")
    if not secret:
        return False
    presented = (request.headers.get("Authorization", "")
                 or request.headers.get("X-Hook-Secret", "")).strip()
    if presented.lower().startswith("bearer "):
        presented = presented[7:].strip()
    return hmac.compare_digest(secret, presented)


@notion_bp.route("/notion/publish", methods=["POST"])
def notion_publish():
    if not _authorised():
        return jsonify({"ok": False, "error": "unauthorised"}), 401
    try:
        return jsonify(handle(request.get_json(silent=True) or {}))
    except Refused as exc:
        # 200, not 4xx: Notion surfaces webhook failures as an unhelpful
        # generic error, whereas the reason is already written onto the card.
        return jsonify({"ok": False, "refused": str(exc)})
    except Exception as exc:  # noqa: BLE001
        traceback.print_exc()
        return jsonify({"ok": False, "error": str(exc)}), 500
