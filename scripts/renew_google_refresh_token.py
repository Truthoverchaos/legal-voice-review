#!/usr/bin/env python3
"""
Renew the Google refresh token for Legal Voice Review and push it straight to
Render, without hand-editing the Render dashboard.

WHY THIS EXISTS: while the app's OAuth consent screen is in "Testing" status
(the normal state for a personal, single-user tool that hasn't gone through
Google's app-verification review), Google auto-expires refresh tokens after
7 days. All the one-time setup (OAuth client, consent screen, enabled APIs,
test user) is permanent and never needs to be redone -- only the refresh
token itself needs periodic renewal. This script automates the "push the new
token into Render and redeploy" half of that; the "get a fresh authorization
code from Google" half still has to be you, since only you can grant consent
to your own account.

USAGE
-----
1. Open this URL in a browser (already filled in with your OAuth client and
   the Drive + Docs scopes) and sign in / click Allow:

   https://accounts.google.com/o/oauth2/v2/auth?client_id=902950166902-qtep0p0lnrud073leeb21hvvb6hqt6g.apps.googleusercontent.com&redirect_uri=https://developers.google.com/oauthplayground&response_type=code&scope=https://www.googleapis.com/auth/drive%20https://www.googleapis.com/auth/documents&access_type=offline&prompt=consent

2. Google redirects you to a Google OAuth Playground page. If Playground
   still has your Client ID/Secret saved in its settings (gear icon, "Use
   your own OAuth credentials"), Step 2 will already show your Authorization
   Code -- click "Exchange authorization code for tokens" and copy the
   "refresh_token" value from the JSON response.
   If Playground's settings got reset (e.g. different browser/profile),
   reopen the gear icon, re-check "Use your own OAuth credentials", paste in
   your Client ID and Client Secret again, THEN click "Exchange authorization
   code for tokens".

3. Run this script:

       python renew_google_refresh_token.py

   It will prompt for:
     - Your Render API key (create one at https://dashboard.render.com/u/settings#api-keys
       if you don't already have one saved -- this only needs to be done once
       per API key; you can reuse the same key every time you run this script)
     - The new refresh token you just copied from Playground

   It then updates GOOGLE_REFRESH_TOKEN in the "legal-voice-env" environment
   group via Render's API. Render automatically redeploys every service
   linked to that group as soon as the value changes -- no separate deploy
   step needed.

Nothing here is stored on disk. Both values are only held in memory for the
life of this script's run.
"""

import getpass
import json
import os
import sys
import urllib.error
import urllib.request

ENV_GROUP_ID = "evg-dai2ham743jc73dpv07g"  # "legal-voice-env" -- not secret, just an identifier
ENV_VAR_KEY = "GOOGLE_REFRESH_TOKEN"
RENDER_API_BASE = "https://api.render.com/v1"


def render_api_put_env_var(api_key: str, new_value: str) -> dict:
    url = f"{RENDER_API_BASE}/env-groups/{ENV_GROUP_ID}/env-vars/{ENV_VAR_KEY}"
    body = json.dumps({"value": new_value}).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=body,
        method="PUT",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
    )
    with urllib.request.urlopen(req, timeout=20) as resp:
        return json.loads(resp.read().decode("utf-8"))


def main() -> int:
    print(__doc__.split("USAGE")[0].strip())
    print()
    print("Step 1's authorization URL is printed above in this file's docstring --")
    print("scroll up in your terminal, or open renew_google_refresh_token.py directly.")
    print()

    api_key = os.environ.get("RENDER_API_KEY") or getpass.getpass(
        "Render API key (input hidden, from https://dashboard.render.com/u/settings#api-keys): "
    )
    if not api_key.strip():
        print("No API key entered. Aborting.")
        return 1

    new_refresh_token = getpass.getpass(
        "New refresh token from the Playground JSON response (input hidden): "
    )
    if not new_refresh_token.strip():
        print("No refresh token entered. Aborting.")
        return 1
    if not new_refresh_token.startswith("1//"):
        print(
            "Warning: Google refresh tokens normally start with '1//'. "
            "Double-check you copied the 'refresh_token' field, not 'access_token' "
            "(which starts with 'ya29.')."
        )
        if input("Continue anyway? [y/N] ").strip().lower() != "y":
            return 1

    try:
        result = render_api_put_env_var(api_key, new_refresh_token.strip())
    except urllib.error.HTTPError as e:
        print(f"Render API error {e.code}: {e.read().decode('utf-8', errors='replace')}")
        return 1
    except urllib.error.URLError as e:
        print(f"Network error reaching Render API: {e}")
        return 1

    print()
    print(f"Success. Updated '{ENV_VAR_KEY}' in environment group '{result.get('name', ENV_GROUP_ID)}'.")
    print("Render will redeploy legal-voice-review automatically now.")
    print("Give it a minute, then check https://legal-voice-review.onrender.com/api/documents")
    print("to confirm it's listing your real Drive files again.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
