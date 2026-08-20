import json
import os
from pathlib import Path

from dotenv import load_dotenv

from src import circle
from src.describe import generate_video_copy
from src.download_loom import download_loom
from src.download_slack import download_slack_file
from src.elevenlabs_dub import (
    build_dubbed_video,
    create_basic_dub,
    fetch_srt,
    group_segments,
    parse_srt,
    wait_for_dubbed,
)
from src.outro import append_outro
from src.quiz import draft_quiz_questions
from src.thumbnail import generate_thumbnail
from src.transcribe import transcribe_video
from src.translate_title import translate_title
from src.vimeo_upload import upload_to_vimeo
from src.youtube_upload import upload_to_youtube


def _playlist_for(space_id, default_playlist_id):
    """
    Map a Circle course space to its YouTube playlist via YOUTUBE_PLAYLIST_MAP,
    e.g. {"2710272": "PLN-79sRivLm0"}. Falls back to YOUTUBE_PLAYLIST_ID.
    """
    raw = os.environ.get("YOUTUBE_PLAYLIST_MAP", "").strip()
    if raw and space_id:
        try:
            return json.loads(raw).get(str(space_id)) or default_playlist_id
        except json.JSONDecodeError:
            pass
    return default_playlist_id


def _download(source: dict, download_dir: str) -> dict:
    """Fetch the video regardless of where it came from.
    Both downloaders return {path, filename, stem}."""
    if source["kind"] == "loom":
        return download_loom(source["url"], output_dir=download_dir)
    if source["kind"] == "slack_file":
        return download_slack_file(
            source["file"], source["bot_token"], output_dir=download_dir
        )
    if source["kind"] == "local":
        path = Path(source["path"]).resolve()
        if not path.exists():
            raise FileNotFoundError(f"No such video file: {path}")
        return {"path": str(path), "filename": path.name, "stem": path.stem}
    raise ValueError(f"Unknown source kind: {source['kind']!r}")


def run_pipeline(
    source,
    *,
    dub: bool = True,
    series: bool = True,
    circle_space_id: int = None,
    circle_section_id: int = None,
    draft_quiz: bool = False,
    log=print,
) -> dict:
    """
    Publish a video to Vimeo, Circle and YouTube.

    source          — a Loom URL string, or {"kind": "loom"|"slack_file", ...}
    dub             — run ElevenLabs PT-BR → EN dubbing with the Hugo voice
    series          — the video belongs to a training course: append the outro,
                      publish it as a Circle *lesson*, and add it to the course
                      playlist. Otherwise it becomes a standalone Circle *post*
                      and an unlisted-from-any-playlist YouTube video.
    draft_quiz      — draft quiz questions from the transcript and return them
    """
    load_dotenv()

    if isinstance(source, str):
        source = {"kind": "loom", "url": source}

    api_key         = os.environ["ELEVENLABS_API_KEY"]
    vimeo_token     = os.environ["VIMEO_ACCESS_TOKEN"]
    anthropic_key   = os.environ["ANTHROPIC_API_KEY"]
    download_dir    = os.environ.get("DOWNLOAD_DIR", "downloads")
    vimeo_folder_id = os.environ.get("VIMEO_FOLDER_ID") or None
    outro_path      = os.environ.get("OUTRO_PATH", "assets/outro.mp4")
    circle_token    = os.environ.get("CIRCLE_API_TOKEN")
    yt_client_id    = os.environ.get("YOUTUBE_CLIENT_ID")
    yt_client_secret = os.environ.get("YOUTUBE_CLIENT_SECRET")
    yt_refresh_token = os.environ.get("YOUTUBE_REFRESH_TOKEN")
    yt_playlist_id  = os.environ.get("YOUTUBE_PLAYLIST_ID") or None

    # ── 1. Download ───────────────────────────────────────────────────────────
    log("[1/8] Downloading source video ...")
    video = _download(source, download_dir)
    log(f"      Saved : {video['path']}")

    # ── 2-4. Dub (optional) ───────────────────────────────────────────────────
    if dub:
        log("[2/8] Submitting to ElevenLabs (PT-BR → EN) ...")
        dubbing_id = create_basic_dub(
            video["path"], api_key, target_lang="en", source_lang="pt", name=video["stem"]
        )
        log(f"      Dubbing ID: {dubbing_id}")

        log("[3/8] Waiting for ElevenLabs dubbing ...")
        wait_for_dubbed(dubbing_id, api_key)

        log("[4/8] Fetching SRT and building Hugo-voiced video ...")
        srt_text = fetch_srt(dubbing_id, api_key, language_code="en")
        segments = parse_srt(srt_text)
        groups = group_segments(segments)
        log(f"      {len(groups)} speech groups found.")
        # The dubbing SRT doubles as the transcript — no extra transcription call.
        transcript = " ".join(text for _, _, text in groups)
        dubbed_path = str(Path("dubbed") / f"{video['stem']}_dubbed.mp4")
        build_dubbed_video(video["path"], groups, api_key, dubbed_path)
        processed_path = dubbed_path
    else:
        log("[2/8] Already in English — skipping dubbing.")
        log("[3/8] Transcribing audio with ElevenLabs Scribe ...")
        transcript = transcribe_video(video["path"], api_key, language_code="eng")
        log(f"      {len(transcript)} characters transcribed.")
        log("[4/8] Using the source video as-is.")
        processed_path = video["path"]

    # ── 5. Append outro (course videos only) ──────────────────────────────────
    output_path = processed_path
    if not series:
        log("[5/8] Standalone video — skipping outro.")
    elif Path(outro_path).exists():
        log("[5/8] Appending outro ...")
        output_path = str(Path("dubbed") / f"{video['stem']}.mp4")
        append_outro(processed_path, outro_path, output_path)
    else:
        log(f"[5/8] No outro at {outro_path!r}, skipping.")

    # ── 6. Title, description and thumbnail text from the transcript ──────────
    log("[6/8] Generating title, description and thumbnail text ...")
    try:
        copy = generate_video_copy(transcript, anthropic_key, filename_hint=video["stem"])
        title = copy["title"] or translate_title(video["stem"], anthropic_key)
    except Exception as exc:
        # A bad transcript shouldn't sink the publish — fall back to the filename.
        log(f"      Transcript-based copy failed ({exc}); falling back to the filename.")
        title = translate_title(video["stem"], anthropic_key)
        copy = {"description": title, "thumbnail_text": title}
    description = copy.get("description") or title
    thumbnail_text = copy.get("thumbnail_text") or title
    log(f"      Title : {title}")
    log(f"      Desc  : {description!r}")
    log(f"      Thumb : {thumbnail_text!r}")

    # ── 7. Upload to Vimeo ────────────────────────────────────────────────────
    log("[7/8] Uploading to Vimeo ...")
    _, vimeo_url = upload_to_vimeo(
        file_path=output_path,
        name=title,
        token=vimeo_token,
        privacy="unlisted",
        # The Vimeo folder is the training archive — standalone videos stay out of it.
        folder_id=vimeo_folder_id if series else None,
    )
    log(f"      Vimeo : {vimeo_url}")

    # ── 8a. Circle: a course lesson, or a standalone post ─────────────────────
    circle_url = None
    if not circle_token:
        log("[8/8] CIRCLE_API_TOKEN not set — skipping Circle.")
    elif series:
        log("[8/8] Creating lesson in Circle ...")
        lesson = circle.create_lesson(
            title,
            vimeo_url,
            circle_token,
            space_id=circle_space_id or circle.DEFAULT_SPACE_ID,
            section_id=circle_section_id or circle.DEFAULT_SECTION_ID,
        )
        circle_url = circle.lesson_url(lesson)
        log(f"      Lesson: {circle_url}")
    elif circle_space_id:
        log("[8/8] Creating post in Circle ...")
        post = circle.create_post(
            title, description, vimeo_url, circle_token, space_id=circle_space_id
        )
        circle_url = circle.post_url(post)
        log(f"      Post  : {circle_url}")
    else:
        log("[8/8] No Circle space selected — skipping Circle.")

    # ── 8b. YouTube upload ────────────────────────────────────────────────────
    youtube_url = None
    if yt_client_id and yt_client_secret and yt_refresh_token:
        log("[8/8] Generating thumbnail and uploading to YouTube ...")
        thumbnail_path = str(Path("dubbed") / f"{video['stem']}_thumb.jpg")
        generate_thumbnail(thumbnail_text, thumbnail_path)
        log(f"      Thumbnail: {thumbnail_path}")
        # Standalone videos are regular uploads — never added to a course playlist.
        playlist_id = _playlist_for(circle_space_id, yt_playlist_id) if series else None
        youtube_url = upload_to_youtube(
            file_path=output_path,
            title=title,
            description=description,
            thumbnail_path=thumbnail_path,
            client_id=yt_client_id,
            client_secret=yt_client_secret,
            refresh_token=yt_refresh_token,
            playlist_id=playlist_id,
        )
        log(f"      YouTube: {youtube_url}")
    else:
        log("[8/8] YOUTUBE_* env vars not set — skipping YouTube upload.")

    # ── 9. Quiz questions (Circle has no quiz API — these go back to Slack) ───
    quiz_questions = None
    if draft_quiz:
        log("      Drafting quiz questions from the transcript ...")
        try:
            quiz_questions = draft_quiz_questions(transcript, title, anthropic_key)
        except Exception as exc:
            log(f"      Quiz drafting failed ({exc}).")

    return {
        "title": title,
        "output_path": output_path,
        "vimeo_url": vimeo_url,
        "circle_url": circle_url,
        # Kept for backwards compatibility with anything reading the old key.
        "lesson_url": circle_url,
        "youtube_url": youtube_url,
        "quiz_questions": quiz_questions,
    }
