import json
import re

import requests

_ANTHROPIC_API = "https://api.anthropic.com/v1/messages"
_MODEL = "claude-haiku-4-5-20251001"


def draft_quiz_questions(transcript: str, title: str, api_key: str, count: int = 5) -> list:
    """
    Draft multiple-choice quiz questions from a video transcript.

    Circle's Admin V2 API has no quiz endpoints, so these are posted back to Slack
    for someone to paste into the Circle quiz by hand.

    Returns a list of {'question': str, 'options': [str, ...], 'answer': str}.
    """
    r = requests.post(
        _ANTHROPIC_API,
        headers={
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        },
        json={
            "model": _MODEL,
            "max_tokens": 1500,
            "messages": [{
                "role": "user",
                "content": (
                    f'Here is the transcript of a wxrks training video titled "{title}":\n\n'
                    f"{transcript}\n\n"
                    f"Write {count} multiple-choice quiz questions that check whether someone "
                    "actually watched and understood this video. Base every question strictly on "
                    "the transcript — do not invent facts. Each question needs exactly 4 options "
                    "and one correct answer.\n\n"
                    'Respond with ONLY a JSON array, each element an object with keys "question" '
                    '(string), "options" (array of 4 strings) and "answer" (the correct option, '
                    "copied verbatim from options). No markdown, no explanation."
                ),
            }],
        },
        timeout=120,
    )
    r.raise_for_status()
    raw = r.json()["content"][0]["text"].strip()
    raw = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw, flags=re.MULTILINE).strip()
    return json.loads(raw)


def format_for_slack(questions: list) -> str:
    """Render drafted questions as Slack mrkdwn ready to paste into Circle."""
    if not questions:
        return ""
    lines = ["📝 *Suggested quiz questions* (Circle's API can't write these — paste them in manually):"]
    for i, q in enumerate(questions, 1):
        lines.append(f"\n*{i}. {q.get('question', '')}*")
        for opt in q.get("options", []):
            marker = "✅" if opt == q.get("answer") else "•"
            lines.append(f"    {marker} {opt}")
    return "\n".join(lines)
