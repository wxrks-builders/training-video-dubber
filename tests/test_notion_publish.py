"""Guards on the Notion publish trigger.

Publishing to YouTube cannot be undone, so these are the tests that matter:
who is allowed to fire it, and what it refuses. Nothing here touches the
network — Notion is stubbed.
"""

import os
import sys
import types

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

os.environ["NOTION_HOOK_SECRET"] = "shhh-secret"
os.environ["NOTION_API_KEY"] = "fake-notion-key"

from src import notion_publish as np  # noqa: E402

PASS, FAIL = [], []


def check(name, condition, detail=""):
    (PASS if condition else FAIL).append(name)
    print(f"{'ok  ' if condition else 'FAIL'} {name}"
          + (f"  — {detail}" if detail and not condition else ""))


# --- finding the page id across Notion's several payload shapes ---

for label, payload in (
        ("page_id", {"page_id": "abc-123"}),
        ("id", {"id": "abc-123"}),
        ("data.id", {"data": {"id": "abc-123"}}),
        ("entity.id", {"entity": {"id": "abc-123"}}),
        ("page.id", {"page": {"id": "abc-123"}})):
    try:
        check(f"page id read from {label}", np.page_id_from(payload) == "abc-123")
    except np.Refused as e:
        check(f"page id read from {label}", False, str(e))

for label, payload in (("an empty body", {}),
                       ("a list", []),
                       ("a blank id", {"id": "   "})):
    try:
        np.page_id_from(payload)
        check(f"{label} is refused", False, "no Refused raised")
    except np.Refused:
        check(f"{label} is refused", True)


# --- what publishes and what does not ---

def card(**over):
    base = {"title": "A lesson", "type": "video", "status": "Approved",
            "source": "https://loom.com/share/abc", "headline": "", "subline": "",
            "style": "youtube-deck", "live_url": ""}
    base.update(over)
    return base


try:
    np.check(card())
    check("a complete video card passes", True)
except np.Refused as e:
    check("a complete video card passes", False, str(e))

for label, bad, expect in (
        ("a blog card", card(type="blog"), "not 'video'"),
        ("a card with no Type", card(type=""), "not 'video'"),
        ("a card with no source", card(source=""), "No Source video"),
        ("an already-published card", card(status="Published"), "Already Published")):
    try:
        np.check(bad)
        check(f"{label} is refused", False, "no Refused raised")
    except np.Refused as e:
        check(f"{label} is refused", expect in str(e), str(e))


# --- property flattening ---

check("rich text flattens",
      np._plain({"type": "rich_text",
                 "rich_text": [{"plain_text": "one "}, {"plain_text": "two"}]})
      == "one two")
check("a select reads its name",
      np._plain({"type": "select", "select": {"name": "video"}}) == "video")
check("an empty select is blank",
      np._plain({"type": "select", "select": None}) == "")
check("a url reads through", np._plain({"type": "url", "url": "x"}) == "x")
check("a missing property is blank", np._plain(None) == "")


# --- the HTTP boundary ---

from flask import Flask  # noqa: E402

app = Flask(__name__)
app.register_blueprint(np.notion_bp)
client = app.test_client()

r = client.post("/notion/publish", json={"id": "abc"})
check("no secret is 401", r.status_code == 401, str(r.status_code))

r = client.post("/notion/publish", json={"id": "abc"},
                headers={"Authorization": "Bearer wrong"})
check("a wrong secret is 401", r.status_code == 401)

# With no secret configured at all the door stays shut.
os.environ["NOTION_HOOK_SECRET"] = ""
r = client.post("/notion/publish", json={"id": "abc"},
                headers={"Authorization": "Bearer "})
check("an unconfigured secret is still 401", r.status_code == 401)
os.environ["NOTION_HOOK_SECRET"] = "shhh-secret"

# Stub Notion so the happy and refused paths can run without the network.
fetched = {}
published = []


class FakeResponse:
    def __init__(self, status, body=None):
        self.status_code = status
        self._body = body or {}

    def json(self):
        return self._body


def fake_get(url, **kwargs):
    return FakeResponse(200, {"properties": fetched})


np.requests = types.SimpleNamespace(
    get=fake_get,
    patch=lambda *a, **k: FakeResponse(200))
np._publish = lambda page_id, card: published.append((page_id, card))

fetched = {
    "Name": {"type": "title", "title": [{"plain_text": "Sharing projects"}]},
    "Type": {"type": "select", "select": {"name": "video"}},
    "Status": {"type": "select", "select": {"name": "Approved"}},
    "Source video": {"type": "url", "url": "https://loom.com/share/abc"},
}
r = client.post("/notion/publish", json={"data": {"id": "page-1"}},
                headers={"Authorization": "Bearer shhh-secret"})
check("an authorised video card starts a publish",
      r.status_code == 200 and r.get_json().get("started") is True,
      f"{r.status_code} {r.get_data(as_text=True)[:160]}")

fetched["Type"] = {"type": "select", "select": {"name": "blog"}}
r = client.post("/notion/publish", json={"data": {"id": "page-2"}},
                headers={"Authorization": "Bearer shhh-secret"})
body = r.get_json()
check("a blog card is refused with a reason, not a 500",
      r.status_code == 200 and "refused" in body, str(body))

fetched["Type"] = {"type": "select", "select": {"name": "video"}}
fetched["Source video"] = {"type": "url", "url": ""}
r = client.post("/notion/publish", json={"data": {"id": "page-3"}},
                headers={"Authorization": "Bearer shhh-secret"})
check("a card with no source is refused",
      "No Source video" in str(r.get_json()), str(r.get_json()))

print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
if FAIL:
    for name in FAIL:
        print(f"  FAILED: {name}")
    sys.exit(1)
