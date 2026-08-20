import requests

CIRCLE_BASE = "https://app.circle.so/api/admin/v2"
COMMUNITY_BASE = "https://community.wxrks.com"

# 'Foundations for Linguists' → 'First Steps' — the original hardcoded destination,
# now only a fallback when no course is picked in Slack.
DEFAULT_SPACE_ID = 2710272
DEFAULT_SECTION_ID = 1077562


def _headers(token: str) -> dict:
    return {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }


def _create_embed_sgid(vimeo_url: str, token: str) -> str:
    """
    Circle's rich text editor embeds video via a signed sgid token, not a raw
    iframe (raw <iframe> tags in body_html are stripped by Circle's sanitizer).
    POST /embeds resolves the URL via Circle's oEmbed provider and returns a
    signed token referencing that embed, which can be placed in an `embed`
    node inside rich_text_body (lessons) or tiptap_body (posts).
    """
    r = requests.post(
        f"{CIRCLE_BASE}/embeds",
        headers=_headers(token),
        json={"url": vimeo_url},
    )
    r.raise_for_status()
    return r.json()["sgid"]


# ── Lessons (videos that belong to a course) ──────────────────────────────────

def create_lesson(
    title: str,
    vimeo_url: str,
    token: str,
    space_id: int = DEFAULT_SPACE_ID,
    section_id: int = DEFAULT_SECTION_ID,
) -> dict:
    """
    Create a published lesson in a course with the Vimeo video embedded.
    Returns the created lesson data.
    """
    sgid = _create_embed_sgid(vimeo_url, token)
    r = requests.post(
        f"{CIRCLE_BASE}/course_lessons",
        headers=_headers(token),
        json={
            "space_id": space_id,
            "section_id": section_id,
            "name": title,
            "rich_text_body": {
                "body": {
                    "type": "doc",
                    "content": [
                        {"type": "embed", "attrs": {"sgid": sgid}},
                    ],
                },
            },
            "status": "published",
            "is_comments_enabled": False,
        },
    )
    r.raise_for_status()
    return r.json()


def lesson_url(lesson: dict) -> str:
    return f"{COMMUNITY_BASE}/courses/{lesson.get('space_id')}/lessons/{lesson.get('id')}"


# ── Posts (standalone videos published to a community space) ──────────────────

def create_post(title: str, description: str, vimeo_url: str, token: str, space_id: int) -> dict:
    """
    Create a published post in a regular space with the Vimeo video embedded.

    Posts use `tiptap_body` where lessons use `rich_text_body`, but the `embed`
    node carrying the sgid is identical in both.
    """
    sgid = _create_embed_sgid(vimeo_url, token)

    content = [{"type": "embed", "attrs": {"sgid": sgid}}]
    if description:
        for para in [p for p in description.split("\n") if p.strip()]:
            content.append({
                "type": "paragraph",
                "content": [{"type": "text", "text": para.strip()}],
            })

    r = requests.post(
        f"{CIRCLE_BASE}/posts",
        headers=_headers(token),
        json={
            "space_id": space_id,
            "name": title,
            "status": "published",
            "tiptap_body": {"body": {"type": "doc", "content": content}},
            "is_comments_enabled": True,
        },
    )
    r.raise_for_status()
    return r.json()


def post_url(post: dict) -> str:
    """The create-post response nests the record under `post` and carries a full url."""
    record = post.get("post", post)
    return record.get("url") or f"{COMMUNITY_BASE}/c/{record.get('space_slug', '')}"


# ── Lookups that feed the Slack destination dropdown ──────────────────────────

def _paginated(path: str, token: str, params: dict = None) -> list:
    """Walk Circle's `{records: [...], has_next_page: bool}` envelope."""
    records = []
    page = 1
    while True:
        r = requests.get(
            f"{CIRCLE_BASE}{path}",
            headers=_headers(token),
            params={**(params or {}), "page": page, "per_page": 100},
            timeout=30,
        )
        r.raise_for_status()
        data = r.json()
        batch = data.get("records", data if isinstance(data, list) else [])
        records.extend(batch)
        if not data.get("has_next_page") or not batch:
            return records
        page += 1


def list_spaces(token: str, space_type: str = None) -> list:
    """
    All spaces in the community, optionally filtered by space_type
    ('course' for course spaces, 'basic' for regular post spaces).
    """
    spaces = _paginated("/spaces", token)
    if space_type:
        spaces = [s for s in spaces if s.get("space_type") == space_type]
    return spaces


def list_course_sections(space_id: int, token: str) -> list:
    return _paginated("/course_sections", token, params={"space_id": space_id})
