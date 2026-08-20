"""
One-time script to generate a YouTube OAuth refresh token.

Run once locally:
    python3 scripts/youtube_auth.py

It will open a browser for Google login, then print the three values
you need to add to Coolify's environment variables (and your local .env).

Requirements:
    pip install google-auth-oauthlib
"""

import json
import sys

try:
    from google_auth_oauthlib.flow import InstalledAppFlow
except ImportError:
    sys.exit("Run: pip install google-auth-oauthlib")

SCOPES = ["https://www.googleapis.com/auth/youtube"]

print("""
=== YouTube OAuth Setup ===

You need a Google Cloud project with YouTube Data API v3 enabled.
If you haven't done that yet:

  1. Go to https://console.cloud.google.com/
  2. Create a project (or select existing)
  3. APIs & Services → Enable APIs → search "YouTube Data API v3" → Enable
  4. APIs & Services → Credentials → Create Credentials → OAuth 2.0 Client ID
     - Application type: Desktop app
     - Download the JSON file
  5. Paste the path to that JSON file below (or press Enter to type values manually)
""")

json_path = input("Path to client_secret_*.json (or press Enter to input manually): ").strip()

if json_path:
    flow = InstalledAppFlow.from_client_secrets_file(json_path, SCOPES)
else:
    client_id = input("Client ID: ").strip()
    client_secret = input("Client Secret: ").strip()
    client_config = {
        "installed": {
            "client_id": client_id,
            "client_secret": client_secret,
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "redirect_uris": ["urn:ietf:wg:oauth:2.0:oob", "http://localhost"],
        }
    }
    flow = InstalledAppFlow.from_client_config(client_config, SCOPES)

creds = flow.run_local_server(port=0, open_browser=True)

print("\n✅  Authentication successful!\n")
print("Add these to your .env file AND to Coolify's environment variables:\n")
print(f"YOUTUBE_CLIENT_ID={creds.client_id}")
print(f"YOUTUBE_CLIENT_SECRET={creds.client_secret}")
print(f"YOUTUBE_REFRESH_TOKEN={creds.refresh_token}")
print()
print("Optional — find your playlist ID in the playlist URL on YouTube")
print("(e.g. youtube.com/playlist?list=PLxxxxxxxx  →  YOUTUBE_PLAYLIST_ID=PLxxxxxxxx)")
