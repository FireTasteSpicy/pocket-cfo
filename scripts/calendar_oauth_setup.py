#!/usr/bin/env python3
"""One-time Google Calendar OAuth consent flow (Desktop-app client).

Run this ONCE to authorize Pocket CFO's Calendar agent to create events in your
REAL Google Calendar via the standard Calendar v3 API -- no Workspace Developer
Preview needed (that is only required for the hosted Calendar MCP endpoint;
this is the plain, GA Calendar API instead).

Prerequisites (one-time, in Cloud Console for your GCP project):
  1. APIs & Services -> Library -> enable "Google Calendar API".
  2. APIs & Services -> OAuth consent screen -> configure it if you haven't
     already for this project (External is fine; add your own email as a test
     user if the app is in "Testing" publishing status).
  3. APIs & Services -> Credentials -> Create Credentials -> OAuth client ID ->
     Application type: "Desktop app" -> Create -> Download JSON.
  4. Save that downloaded file as: app/data/calendar_client_secret.json
     (gitignored -- never commit it; it's your own project's OAuth client, not
     a value that belongs in source control).

Then run:
    uv run python scripts/calendar_oauth_setup.py

It prints an authorization URL and waits. Open that URL in ANY browser (on
WSL2, opening it in your Windows browser works: WSL2 forwards localhost to
Windows by default), sign in, and click Allow. The flow captures the redirect
automatically and this script exits.

After this, app/data/calendar_token.json holds a refresh token (gitignored). The
Calendar agent's `sync_money_dates_to_calendar` tool uses it automatically from
then on -- no further browser interaction needed (tokens auto-refresh).
"""

from __future__ import annotations

from app.tools.calendar_api import CALENDAR_SCOPES, CLIENT_SECRET_PATH, TOKEN_PATH


def main() -> None:
    if not CLIENT_SECRET_PATH.exists():
        raise SystemExit(
            f"Missing {CLIENT_SECRET_PATH}.\n\n"
            "Download your Desktop-app OAuth client JSON from Google Cloud Console "
            "and save it at that exact path first -- see the steps in this "
            "script's module docstring (scripts/calendar_oauth_setup.py)."
        )

    from google_auth_oauthlib.flow import InstalledAppFlow

    flow = InstalledAppFlow.from_client_secrets_file(
        str(CLIENT_SECRET_PATH), CALENDAR_SCOPES
    )
    # open_browser=False: WSL has no browser binary to launch: the library would
    # otherwise raise trying to invoke one. It still PRINTS the URL either way.
    creds = flow.run_local_server(port=0, open_browser=False)

    TOKEN_PATH.parent.mkdir(parents=True, exist_ok=True)
    TOKEN_PATH.write_text(creds.to_json(), encoding="utf-8")
    print(f"\nAuthorized. Token saved to {TOKEN_PATH}")


if __name__ == "__main__":
    main()
