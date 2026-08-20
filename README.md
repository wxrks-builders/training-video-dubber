# training-video-dubber

Publishes training videos to Vimeo, Circle and YouTube from Slack.

Post a video in Slack — either a Loom URL or a directly uploaded file — and the bot
asks four questions in-thread, then runs the matching pipeline:

| Question | Controls |
|---|---|
| Dub it PT-BR → EN? | ElevenLabs dubbing with the Hugo voice |
| Part of a training series? | Outro, Circle lesson vs. post, YouTube playlist |
| Does it change a quiz? | Drafts quiz questions from the transcript |
| Which destination? | Circle course + section, or the space to post in |

Title, description and thumbnail text are always generated from the video's transcript.
Dubbed videos reuse the ElevenLabs SRT; English videos are transcribed with Scribe.

Silent videos — a screen recording with no narration, or one with the mic muted —
have no transcript to work from, so the bot asks the person who posted it what the
video covers and runs that answer through the same recipe. Nothing is published
until they answer; after 30 minutes the job is abandoned rather than published under
a filename-derived title.

Circle's Admin V2 API has no quiz endpoints, so drafted quiz questions are posted back
to the Slack thread to be pasted in by hand.

## Thumbnails

Rendered at 1280x720 by [src/thumbnail.py](src/thumbnail.py): black canvas, emerald
radial glow rising from the bottom-left corner with a faint grid inside it, a glassy
3D icon, thin-line outline glyphs, a mixed-weight headline (bold white + extra-light
gray on one line), an extra-light subline, an arrow cue and the wxrks wordmark.

The headline, subline and icon subject all come from the same copy step as the title
([src/describe.py](src/describe.py)); asterisks in the headline mark the words set in
bold. The icon is generated per video with `gpt-image-1`
([src/icon.py](src/icon.py)) on a transparent background. If `OPENAI_API_KEY` is unset
or generation fails, a built-in glass shape is used and the video still publishes.

Assets live in `assets/` — `logo.png` (the wordmark, extracted from the outro) and
`fonts/` (Poppins, OFL-licensed).

## Deployment

Runs on Coolify at <https://video-upload.agents.wxrks.app> — Dockerfile build pack,
port 3000, health check `/health`.

The Slack app (<https://api.slack.com/apps>) needs:

- **Bot scopes:** `channels:history`, `groups:history`, `chat:write`, `files:read`
- **Event Subscriptions** → `https://video-upload.agents.wxrks.app/slack/events`
- **Interactivity** → `https://video-upload.agents.wxrks.app/slack/interactive`

Interactivity is required. Without it the question buttons do nothing and no video is
ever published, including Loom URLs.

Environment variables are set in the Coolify UI — see [.env.example](.env.example) for
the full list and where each credential comes from.

## Running locally

```bash
pip install -r requirements.txt          # needs ffmpeg on PATH
cp .env.example .env                     # then fill it in

# Dub a Loom video and publish it as a course lesson
python main.py https://loom.com/share/xxxx

# Publish an English file as a standalone Circle post
python main.py --file video.mp4 --no-dub --standalone --space-id 1752465

python main.py --help                    # --section-id, --quiz
```

The Slack webhook is a Flask app: `python slack_app.py`, or via Docker as in production.
