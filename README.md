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

Circle's Admin V2 API has no quiz endpoints, so drafted quiz questions are posted back
to the Slack thread to be pasted in by hand.

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
