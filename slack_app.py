import hashlib
import hmac
import json
import os
import re
import threading
import time
import uuid

import requests
from dotenv import load_dotenv
from flask import Flask, jsonify, request

from src import circle
from src.download_slack import is_video
from src.quiz import format_for_slack

load_dotenv()

app = Flask(__name__)

LOOM_RE = re.compile(r'https://(?:www\.)?loom\.com/share/[a-zA-Z0-9]+')

SLACK_BOT_TOKEN = os.environ.get("SLACK_BOT_TOKEN", "")
SLACK_SIGNING_SECRET = os.environ.get("SLACK_SIGNING_SECRET", "")

# Jobs waiting on the poster's answers, keyed by job id.
# Safe as a plain dict: the Dockerfile runs gunicorn with a single worker, and
# the lock covers the 8 request threads. A redeploy drops these — see _expired().
PENDING = {}
PENDING_LOCK = threading.Lock()

QUESTIONS = [
    ("dub",    "1️⃣  Dub it PT-BR → EN?",        [("Yes", "yes"), ("No, already English", "no")]),
    ("series", "2️⃣  Part of a training series?", [("Yes", "yes"), ("No, standalone", "no")]),
    ("quiz",   "3️⃣  Does it change a quiz?",     [("Yes", "yes"), ("No", "no")]),
]
ANSWER_LABELS = {
    ("dub", "yes"): "Dub PT-BR → EN",
    ("dub", "no"): "Already in English",
    ("series", "yes"): "Part of a series",
    ("series", "no"): "Standalone",
    ("quiz", "yes"): "Quiz needs updating",
    ("quiz", "no"): "No quiz change",
}


# ── Slack helpers ─────────────────────────────────────────────────────────────

def _verify_signature(req) -> bool:
    timestamp = req.headers.get("X-Slack-Request-Timestamp", "")
    if not timestamp or abs(time.time() - int(timestamp)) > 300:
        return False
    body = req.get_data(as_text=True)
    base = f"v0:{timestamp}:{body}"
    expected = "v0=" + hmac.new(
        SLACK_SIGNING_SECRET.encode(),
        base.encode(),
        hashlib.sha256,
    ).hexdigest()
    return hmac.compare_digest(expected, req.headers.get("X-Slack-Signature", ""))


def _api(method: str, payload: dict) -> dict:
    r = requests.post(
        f"https://slack.com/api/{method}",
        headers={"Authorization": f"Bearer {SLACK_BOT_TOKEN}"},
        json=payload,
        timeout=10,
    )
    return r.json()


def _post(channel: str, thread_ts: str, text: str, blocks: list = None) -> dict:
    payload = {"channel": channel, "thread_ts": thread_ts, "text": text}
    if blocks:
        payload["blocks"] = blocks
    return _api("chat.postMessage", payload)


def _update(channel: str, ts: str, text: str, blocks: list = None) -> dict:
    payload = {"channel": channel, "ts": ts, "text": text}
    payload["blocks"] = blocks if blocks else []
    return _api("chat.update", payload)


# ── Question blocks ───────────────────────────────────────────────────────────

def _question_blocks(job_id: str, answers: dict, label: str) -> list:
    """Render the intake message: answered questions collapse to a ✅ line,
    the next unanswered one shows its buttons."""
    blocks = [{
        "type": "section",
        "text": {"type": "mrkdwn", "text": f"🎥 Got *{label}*. A few quick questions:"},
    }]

    for key, prompt, options in QUESTIONS:
        if key in answers:
            blocks.append({
                "type": "context",
                "elements": [{
                    "type": "mrkdwn",
                    "text": f"✅ {prompt.split('  ', 1)[-1]}  *{ANSWER_LABELS[(key, answers[key])]}*",
                }],
            })
        else:
            blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": prompt}})
            blocks.append({
                "type": "actions",
                "elements": [{
                    "type": "button",
                    "text": {"type": "plain_text", "text": text},
                    "value": value,
                    "action_id": f"{job_id}|{key}|{value}",
                } for text, value in options],
            })
            return blocks  # one question at a time

    # All three answered — ask where it should be published.
    blocks.extend(_destination_blocks(job_id, answers))
    return blocks


def _destination_blocks(job_id: str, answers: dict) -> list:
    """Question 4, built from Circle at answer time so the list is never stale."""
    token = os.environ.get("CIRCLE_API_TOKEN")
    if not token:
        return [{
            "type": "context",
            "elements": [{"type": "mrkdwn", "text": "⚠️ CIRCLE_API_TOKEN not set — publishing without Circle."}],
        }]

    series = answers.get("series") == "yes"
    try:
        options = _destination_options(token, series)
    except Exception as exc:
        return [{
            "type": "context",
            "elements": [{"type": "mrkdwn", "text": f"⚠️ Couldn't load Circle spaces: `{exc}`"}],
        }]

    if not options:
        return [{
            "type": "context",
            "elements": [{"type": "mrkdwn", "text": "⚠️ No matching Circle spaces found."}],
        }]

    prompt = "4️⃣  Which course and section?" if series else "4️⃣  Which space should the post go to?"
    return [
        {"type": "section", "text": {"type": "mrkdwn", "text": prompt}},
        {
            "type": "actions",
            "elements": [{
                "type": "static_select",
                "placeholder": {"type": "plain_text", "text": "Pick a destination"},
                # Slack caps a static_select at 100 options.
                "options": [{
                    "text": {"type": "plain_text", "text": name[:75]},
                    "value": value,
                } for name, value in options[:100]],
                "action_id": f"{job_id}|dest|select",
            }],
        },
    ]


def _destination_options(token: str, series: bool) -> list:
    """Returns [(label, "space_id:section_id"), ...] for courses, or
    [(label, "space_id:"), ...] for regular spaces."""
    if not series:
        # Only "basic" spaces take regular posts — course/event/chat/members spaces don't.
        spaces = circle.list_spaces(token, space_type="basic")
        return [(s.get("name", str(s["id"])), f"{s['id']}:") for s in spaces]

    options = []
    for space in circle.list_spaces(token, space_type="course"):
        try:
            sections = circle.list_course_sections(space["id"], token)
        except Exception:
            sections = []
        if sections:
            for section in sections:
                options.append((
                    f"{space.get('name', space['id'])} → {section.get('name', section['id'])}",
                    f"{space['id']}:{section['id']}",
                ))
        else:
            options.append((space.get("name", str(space["id"])), f"{space['id']}:"))
    return options


# ── Background worker ─────────────────────────────────────────────────────────

def _process(job: dict) -> None:
    from src.pipeline import run_pipeline

    channel, thread_ts = job["channel"], job["thread_ts"]
    answers = job["answers"]
    sources = job["sources"]

    count = len(sources)
    summary = ", ".join(
        ANSWER_LABELS[(key, answers[key])] for key, _, _ in QUESTIONS if key in answers
    )
    noun = "video" if count == 1 else f"{count} videos"
    _post(channel, thread_ts, f"⏳ Starting pipeline for {noun} — _{summary}_")

    for i, source in enumerate(sources, 1):
        prefix = f"*[{i}/{count}]* " if count > 1 else ""
        try:
            result = run_pipeline(
                source,
                dub=answers.get("dub") == "yes",
                series=answers.get("series") == "yes",
                circle_space_id=job.get("space_id"),
                circle_section_id=job.get("section_id"),
                draft_quiz=answers.get("quiz") == "yes",
            )
            errors = result.get("errors") or []
            icon = "⚠️" if errors else "✅"
            lines = [f"{icon} {prefix}*{result['title']}*", f"Vimeo: {result['vimeo_url']}"]
            if result.get("youtube_url"):
                lines.append(f"YouTube: {result['youtube_url']}")
            if result.get("circle_url"):
                lines.append(f"Circle: {result['circle_url']}")
            # Partial failures still report whatever did publish.
            for err in errors:
                lines.append(f"❌ {err}")
            _post(channel, thread_ts, "\n".join(lines))

            if result.get("quiz_questions"):
                _post(channel, thread_ts, format_for_slack(result["quiz_questions"]))
        except Exception as exc:
            label = source.get("url") or source.get("file", {}).get("name", "video")
            _post(channel, thread_ts, f"❌ {prefix}Pipeline failed for `{label}`:\n`{exc}`")


# ── Intake ────────────────────────────────────────────────────────────────────

def _start_job(sources: list, label: str, channel: str, thread_ts: str) -> None:
    job_id = uuid.uuid4().hex[:12]
    job = {
        "sources": sources,
        "label": label,
        "channel": channel,
        "thread_ts": thread_ts,
        "answers": {},
        "message_ts": None,
    }
    with PENDING_LOCK:
        PENDING[job_id] = job

    resp = _post(
        channel, thread_ts,
        f"Got {label} — a few quick questions before publishing.",
        _question_blocks(job_id, {}, label),
    )
    with PENDING_LOCK:
        job["message_ts"] = resp.get("ts")


def _expired(payload: dict) -> None:
    channel = payload["channel"]["id"]
    ts = payload["message"]["ts"]
    _update(channel, ts, "⚠️ That request expired (the bot restarted). Please re-post the video.")


# ── Routes ────────────────────────────────────────────────────────────────────

@app.route("/health")
def health():
    return "ok"


@app.route("/slack/events", methods=["POST"])
def slack_events():
    # Ignore Slack retries — the job is already running
    if request.headers.get("X-Slack-Retry-Num"):
        return jsonify({"ok": True})

    if not _verify_signature(request):
        return "Unauthorized", 401

    data = request.get_json(force=True)

    # Slack URL verification handshake
    if data.get("type") == "url_verification":
        return jsonify({"challenge": data["challenge"]})

    if data.get("type") == "event_callback":
        event = data.get("event", {})
        # File uploads arrive as a message with subtype "file_share"; plain text
        # messages have no subtype at all. Everything else (edits, joins, bots) is noise.
        is_user_message = (
            event.get("type") == "message"
            and "bot_id" not in event
            and event.get("subtype") in (None, "file_share")
        )
        if is_user_message:
            channel = event["channel"]
            thread_ts = event.get("thread_ts") or event["ts"]

            videos = [f for f in event.get("files", []) or [] if is_video(f)]
            urls = LOOM_RE.findall(event.get("text", ""))

            if videos:
                sources = [
                    {"kind": "slack_file", "file": f, "bot_token": SLACK_BOT_TOKEN}
                    for f in videos
                ]
                label = f'"{videos[0]["name"]}"' if len(videos) == 1 else f"{len(videos)} videos"
            elif urls:
                sources = [{"kind": "loom", "url": u} for u in urls]
                label = f"`{urls[0]}`" if len(urls) == 1 else f"{len(urls)} Loom videos"
            else:
                return jsonify({"ok": True})

            threading.Thread(
                target=_start_job,
                args=(sources, label, channel, thread_ts),
                daemon=True,
            ).start()

    # Always respond within 3 s or Slack will retry
    return jsonify({"ok": True})


@app.route("/slack/interactive", methods=["POST"])
def slack_interactive():
    # Interactivity payloads are form-encoded, but the signature is still computed
    # over the raw body, so _verify_signature works unchanged.
    if not _verify_signature(request):
        return "Unauthorized", 401

    payload = json.loads(request.form["payload"])
    if payload.get("type") == "block_actions":
        # Rebuilding question 4 hits the Circle API; Slack only waits 3 s for this
        # response, so acknowledge now and do the work in the background.
        threading.Thread(target=_handle_action, args=(payload,), daemon=True).start()
    return "", 200


def _handle_action(payload: dict) -> None:
    action = payload["actions"][0]
    job_id, key, _ = action["action_id"].split("|", 2)

    with PENDING_LOCK:
        job = PENDING.get(job_id)
    if job is None:
        _expired(payload)
        return

    channel = job["channel"]
    ts = job["message_ts"] or payload["message"]["ts"]

    if key == "dest":
        selected = action["selected_option"]
        space_id, _, section_id = selected["value"].partition(":")
        with PENDING_LOCK:
            job["space_id"] = int(space_id)
            job["section_id"] = int(section_id) if section_id else None
            PENDING.pop(job_id, None)

        _update(
            channel, ts,
            f"✅ Publishing to *{selected['text']['text']}* — progress below.",
        )
        _process(job)
        return

    with PENDING_LOCK:
        job["answers"][key] = action["value"]
        answers = dict(job["answers"])

    _update(
        channel, ts,
        f"Answering questions for {job['label']} ...",
        _question_blocks(job_id, answers, job["label"]),
    )


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 3000))
    app.run(host="0.0.0.0", port=port)
