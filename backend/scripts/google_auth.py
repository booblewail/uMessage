"""Sign in to Google once, so uMessage can put Confirmed plans on your Google Calendar.

Run it with `make google-auth` (from the repo root). It opens Google's sign-in page in your
browser using the OAuth client in GOOGLE_CREDENTIALS_PATH (see the README for creating one),
asks for access to your calendar's events only, and saves the sign-in to GOOGLE_TOKEN_PATH,
where the running app picks it up (no restart needed).
"""

import sys

from google_auth_oauthlib.flow import InstalledAppFlow

from app.adapters.google_calendar import SCOPES, save_token
from app.config import GoogleSettings


def main() -> int:
    settings = GoogleSettings()
    client = settings.google_credentials_path
    if not client.exists():
        print(
            f"No OAuth client at {client}.\n"
            "Create a 'Desktop app' OAuth client in Google Cloud, download its JSON there\n"
            "(or set GOOGLE_CREDENTIALS_PATH), then run `make google-auth` again.\n"
            "The README's 'Connecting Google Calendar' section walks through it.",
            file=sys.stderr,
        )
        return 1
    flow = InstalledAppFlow.from_client_secrets_file(str(client), SCOPES)
    # `prompt=consent` makes Google hand out a refresh token even when signing in again.
    credentials = flow.run_local_server(port=0, prompt="consent")
    save_token(settings.google_token_path, credentials)  # type: ignore[arg-type]
    print(f"Google Calendar connected: sign-in saved to {settings.google_token_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
