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


def generate_video_copy(
    source_text: str,
    api_key: str,
    filename_hint: str = None,
    source_kind: str = "transcript",
) -> dict:
    """
    Derive publishing copy from what the video is about.

    source_kind is "transcript" for what the video says, or "description" for a
    summary written by the person who posted it (used when the video is silent).
    Either way the same recipe produces the title, description and thumbnail text.

    Returns title, description, thumbnail_headline (with *asterisks* marking the
    words to set bold), thumbnail_subline, and icon_subject for the thumbnail
    illustration.
    The source is truncated because titles and descriptions are decided in the
    first few minutes, and the whole thing is needlessly expensive for Haiku.
    """
    excerpt = (source_text or "").strip()[:12000]
    hint = (
        f'The uploaded file was named "{filename_hint}" — useful only if it looks '
        "descriptive, ignore it if it is a generic recording name.\n\n"
        if filename_hint else ""
    )

    if source_kind == "description":
        preamble = (
            "This is a training video from wxrks. It has no narration, so the "
            "person who recorded it described what it covers:"
        )
    else:
        preamble = "Here is the transcript of a training video from wxrks:"

    r = requests.post(
        _ANTHROPIC_API,
        headers={
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        },
        json={
            "model": _MODEL,
            "max_tokens": 700,
            "messages": [{
                "role": "user",
                "content": (
                    f"{preamble}\n\n"
                    f"{excerpt}\n\n"
                    f"{hint}"
                    'The company name is always written in lowercase as "wxrks" — never "Works".\n\n'
                    "Respond with a JSON object containing exactly five keys:\n"
                    '1. "title": An English video title describing what this video actually '
                    "teaches. Under 70 characters, no clickbait, no quotes around it.\n"
                    '2. "description": Two short lines for the YouTube video description. '
                    "Line 1 states what the viewer will learn, based on the text above. "
                    "Line 2 mentions wxrks and links to community.wxrks.com. "
                    "Total under 200 characters.\n"
                    '3. "thumbnail_headline": 3 to 6 words in sentence case for the '
                    "thumbnail. Wrap the 1-3 most important words in asterisks to mark "
                    'them for bold, e.g. "*Bulk import* glossary terms". Not all caps.\n'
                    '4. "thumbnail_subline": one short supporting line for the thumbnail, '
                    "under 60 characters, sentence case, no full stop.\n"
                    '5. "icon_subject": a single concrete object or simple visual metaphor '
                    "for this video, described in under 12 words, that an illustrator could "
                    'draw as one icon — e.g. "a funnel filtering documents into a neat stack". '
                    "No text or letters in it, no people, and do not mention colours — "
                    "the icon is always rendered in the brand's greens.\n\n"
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
        "thumbnail_headline": _enforce_company_name(
            copy.get("thumbnail_headline", "").strip()),
        "thumbnail_subline": _enforce_company_name(
            copy.get("thumbnail_subline", "").strip()),
        "icon_subject": copy.get("icon_subject", "").strip(),
    }
