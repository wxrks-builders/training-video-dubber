"""
Per-video thumbnail icon, generated with OpenAI's gpt-image-1.

Returns PNG with a real alpha channel (background="transparent"), so the icon
composites onto the black thumbnail canvas with its own drop shadow rather than
carrying a rectangle of near-black with it.
"""

import base64
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import requests

_API = "https://api.openai.com/v1/images/generations"
_MODEL = "gpt-image-1"

# The house style. Only the subject changes between videos, so thumbnails stay
# recognisably part of one set.
_STYLE = (
    "A single glassy translucent 3D icon in vivid greens, depicting {subject}. "
    "Frosted glass layered over a brighter emerald-green shape, subtle internal "
    "refraction, soft highlights along the top edge, floating slightly with a soft "
    "drop shadow beneath. Centred, filling most of the frame, viewed straight on. "
    "Flat premium tech-editorial finish, high contrast, clean and minimal. "
    "No text, no letters, no numbers, no photographs, no people, no background "
    "scenery — the icon only, on a fully transparent background."
)


def build_prompt(subject: str) -> str:
    return _STYLE.format(subject=subject.strip().rstrip("."))


def generate_icon(
    subject: str,
    api_key: str,
    output_path: str,
    quality: str = "medium",
    timeout: int = 180,
) -> str:
    """
    Render an icon for `subject` and write it to output_path.
    Raises on failure — the caller decides whether to fall back.
    """
    r = requests.post(
        _API,
        headers={"Authorization": f"Bearer {api_key}",
                 "Content-Type": "application/json"},
        json={
            "model": _MODEL,
            "prompt": build_prompt(subject),
            "n": 1,
            "size": "1024x1024",
            # transparent requires png or webp
            "background": "transparent",
            "output_format": "png",
            "quality": quality,
        },
        timeout=timeout,
    )
    if not r.ok:
        raise RuntimeError(f"gpt-image-1 returned {r.status_code}: {r.text[:300]}")

    data = r.json()["data"][0]
    if "b64_json" not in data:
        raise RuntimeError(f"No image payload in response: {str(data)[:200]}")

    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "wb") as fh:
        fh.write(base64.b64decode(data["b64_json"]))
    return output_path


def generate_icons(
    subjects: list,
    api_key: str,
    output_dir: str,
    stem: str,
    quality: str = "medium",
) -> list:
    """
    Render one icon per subject, concurrently — three in sequence would be two
    minutes of the pipeline sitting idle.

    Returns [(subject, path), ...] for the ones that succeeded, in input order.
    """
    def one(idx_subject):
        idx, subject = idx_subject
        path = str(Path(output_dir) / f"{stem}_icon{idx + 1}.png")
        return subject, generate_icon(subject, api_key, path, quality=quality)

    results = []
    with ThreadPoolExecutor(max_workers=len(subjects) or 1) as pool:
        futures = [pool.submit(one, item) for item in enumerate(subjects)]
        for f in futures:
            try:
                results.append(f.result())
            except Exception:
                results.append(None)
    return [r for r in results if r]
