import re
from pathlib import Path

import requests

# Slack file objects report a mimetype; only these are worth running through the pipeline.
VIDEO_MIMETYPES = ("video/",)


def is_video(file_obj: dict) -> bool:
    mimetype = file_obj.get("mimetype", "")
    return any(mimetype.startswith(prefix) for prefix in VIDEO_MIMETYPES)


def _safe_stem(name: str) -> str:
    """Slack filenames arrive verbatim from the uploader's disk — strip anything
    that would break a shell path or an ffmpeg output filename."""
    stem = Path(name).stem
    stem = re.sub(r"[^\w\s.-]", "", stem, flags=re.UNICODE).strip()
    stem = re.sub(r"\s+", " ", stem)
    return stem or "slack-upload"


def download_slack_file(file_obj: dict, bot_token: str, output_dir: str = "downloads") -> dict:
    """
    Download a file shared in Slack using the bot token.

    Requires the `files:read` scope — `url_private_download` returns an HTML login
    page (HTTP 200!) instead of the file when the token is missing or unscoped, so
    the content type is checked explicitly.

    Returns the same dict shape as download_loom(): {path, filename, stem}.
    """
    Path(output_dir).mkdir(parents=True, exist_ok=True)

    url = file_obj.get("url_private_download") or file_obj["url_private"]
    stem = _safe_stem(file_obj.get("name") or file_obj["id"])
    ext = file_obj.get("filetype") or Path(file_obj.get("name", "")).suffix.lstrip(".") or "mp4"
    target = Path(output_dir) / f"{stem}.{ext}"

    with requests.get(
        url,
        headers={"Authorization": f"Bearer {bot_token}"},
        stream=True,
        timeout=300,
    ) as r:
        r.raise_for_status()
        if "text/html" in r.headers.get("Content-Type", ""):
            raise RuntimeError(
                "Slack returned an HTML page instead of the file — the bot token is "
                "missing the `files:read` scope, or has no access to that channel."
            )
        with open(target, "wb") as fh:
            for chunk in r.iter_content(chunk_size=8 * 1024 * 1024):
                fh.write(chunk)

    return {
        "path": str(target.resolve()),
        "filename": target.name,
        "stem": stem,
    }
