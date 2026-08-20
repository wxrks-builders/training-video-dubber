#!/usr/bin/env python3
"""
Publish a training video to Vimeo, Circle and YouTube.

Usage:
    python main.py <loom_url>                       # dub PT-BR → EN, publish as a course lesson
    python main.py --file video.mp4 --no-dub \
                   --standalone --space-id 123456   # English video → standalone Circle post

Environment variables (or .env file):
    ELEVENLABS_API_KEY   — ElevenLabs API key (dubbing + speech-to-text)
    VIMEO_ACCESS_TOKEN   — Vimeo API token (upload + edit scopes)
    ANTHROPIC_API_KEY    — Anthropic API key (title, description, quiz drafting)
    CIRCLE_API_TOKEN     — Circle Admin V2 token
    YOUTUBE_*            — see .env.example
    VIMEO_FOLDER_ID      — Vimeo folder/showcase ID (optional)
    DOWNLOAD_DIR         — Where to save source videos (default: downloads)
"""

import argparse
import sys

from src.pipeline import run_pipeline


def main():
    parser = argparse.ArgumentParser(description="Publish a training video")
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("loom_url", nargs="?", help="Loom share URL")
    source.add_argument("--file", help="Path to a local video file")

    parser.add_argument("--no-dub", action="store_true",
                        help="Video is already in English — skip ElevenLabs dubbing")
    parser.add_argument("--standalone", action="store_true",
                        help="Not part of a course: no outro, Circle post instead of a "
                             "lesson, and no YouTube playlist")
    parser.add_argument("--space-id", type=int, help="Circle space ID (course or post space)")
    parser.add_argument("--section-id", type=int, help="Circle course section ID")
    parser.add_argument("--quiz", action="store_true",
                        help="Draft quiz questions from the transcript")
    parser.add_argument("--description",
                        help="What the video is about. Required only for silent "
                             "videos, where there is no narration to work from.")
    args = parser.parse_args()

    if args.file:
        src = {"kind": "local", "path": args.file}
    else:
        src = {"kind": "loom", "url": args.loom_url}

    result = run_pipeline(
        src,
        dub=not args.no_dub,
        series=not args.standalone,
        circle_space_id=args.space_id,
        circle_section_id=args.section_id,
        draft_quiz=args.quiz,
        ask_description=(lambda: args.description) if args.description else None,
    )

    print("\nDone!")
    print(f"  Title        : {result['title']}")
    print(f"  Video        : {result['output_path']}")
    print(f"  Vimeo URL    : {result['vimeo_url']}")
    print(f"  Circle URL   : {result['circle_url']}")
    print(f"  YouTube URL  : {result['youtube_url']}")

    if result.get("quiz_questions"):
        print("\nSuggested quiz questions:")
        for i, q in enumerate(result["quiz_questions"], 1):
            print(f"\n  {i}. {q['question']}")
            for opt in q["options"]:
                print(f"     {'*' if opt == q['answer'] else ' '} {opt}")


if __name__ == "__main__":
    main()
