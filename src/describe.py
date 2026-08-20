import json
import re

import requests

_ANTHROPIC_API = "https://api.anthropic.com/v1/messages"
_MODEL = "claude-haiku-4-5-20251001"
_COMPANY_NAME = "wxrks"


def _enforce_company_name(text: str) -> str:
    """The company is always lowercase 'wxrks', never 'Works' — belt and braces
    regardless of what the model returned."""
    return re.sub(r"\bworks\b", _COMPANY_NAME, text, flags=re.IGNORECASE)


def generate_video_copy(transcript: str, api_key: str, filename_hint: str = None) -> dict:
    """
    Derive publishing copy from what the video actually says.

    Returns {'title': ..., 'description': ..., 'thumbnail_text': ...}.
    The transcript is truncated because titles and descriptions are decided in the
    first few minutes, and the whole thing is needlessly expensive for Haiku.
    """
    excerpt = (transcript or "").strip()[:12000]
    hint = (
        f'The uploaded file was named "{filename_hint}" — useful only if it looks '
        "descriptive, ignore it if it is a generic recording name.\n\n"
        if filename_hint else ""
    )

    r = requests.post(
        _ANTHROPIC_API,
        headers={
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        },
        json={
            "model": _MODEL,
            "max_tokens": 500,
            "messages": [{
                "role": "user",
                "content": (
                    "Here is the transcript of a training video from wxrks:\n\n"
                    f"{excerpt}\n\n"
                    f"{hint}"
                    'The company name is always written in lowercase as "wxrks" — never "Works".\n\n'
                    "Respond with a JSON object containing exactly three keys:\n"
                    '1. "title": An English video title describing what this video actually '
                    "teaches. Under 70 characters, no clickbait, no quotes around it.\n"
                    '2. "description": Two short lines for the YouTube video description. '
                    "Line 1 states what the viewer will learn, based on the transcript. "
                    "Line 2 mentions wxrks and links to community.wxrks.com. "
                    "Total under 200 characters.\n"
                    '3. "thumbnail_text": 1 to 4 words (ALL CAPS) that capture the core '
                    "topic — punchy enough to stand alone on a dark YouTube thumbnail.\n\n"
                    "Return ONLY the JSON object, no markdown or explanation."
                ),
            }],
        },
        timeout=60,
    )
    r.raise_for_status()
    raw = r.json()["content"][0]["text"].strip()
    raw = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw, flags=re.MULTILINE).strip()
    copy = json.loads(raw)

    return {
        "title": _enforce_company_name(copy.get("title", "").strip()),
        "description": _enforce_company_name(copy.get("description", "").strip()),
        "thumbnail_text": _enforce_company_name(copy.get("thumbnail_text", "").strip()),
    }
