import subprocess
import tempfile
from pathlib import Path

import requests

ELEVEN_BASE = "https://api.elevenlabs.io/v1"
STT_MODEL = "scribe_v1"


def extract_audio(video_path: str, output_path: str = None) -> str:
    """
    Pull a small mono 16 kHz mp3 out of the video. Speech-to-text accepts mp4
    directly, but uploading a ~500 MB video to transcribe a few minutes of
    speech is wasteful — the audio is typically under 2 MB.
    """
    if output_path is None:
        output_path = str(Path(tempfile.gettempdir()) / f"{Path(video_path).stem}_audio.mp3")

    subprocess.run([
        "ffmpeg", "-y", "-i", video_path,
        "-vn", "-ac", "1", "-ar", "16000", "-b:a", "64k",
        output_path,
    ], check=True, capture_output=True)
    return output_path


def transcribe(audio_path: str, api_key: str, language_code: str = None) -> str:
    """
    Transcribe an audio (or video) file with ElevenLabs Scribe.
    Returns the plain transcript text.
    """
    data = {"model_id": STT_MODEL}
    if language_code:
        data["language_code"] = language_code

    with open(audio_path, "rb") as fh:
        r = requests.post(
            f"{ELEVEN_BASE}/speech-to-text",
            headers={"xi-api-key": api_key},
            data=data,
            files={"file": (Path(audio_path).name, fh, "audio/mpeg")},
            timeout=600,
        )
    r.raise_for_status()
    return r.json().get("text", "").strip()


def transcribe_video(video_path: str, api_key: str, language_code: str = None) -> str:
    """Convenience wrapper: extract audio, transcribe, clean up the temp mp3."""
    audio_path = extract_audio(video_path)
    try:
        return transcribe(audio_path, api_key, language_code=language_code)
    finally:
        Path(audio_path).unlink(missing_ok=True)
