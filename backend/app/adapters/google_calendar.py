"""The Calendar adapter for the user's primary Google Calendar.

The user signs in once with `make google-auth` (`scripts/google_auth.py`), which saves an
authorized-user token to `GOOGLE_TOKEN_PATH`. This adapter loads it when first needed (so
signing in while the app runs works without a restart), refreshes it when it has expired
and saves the refreshed token back. The Google API client is blocking: every call to it
runs in a worker thread (`asyncio.to_thread`), one at a time.

Each Calendar Entry gets its own id, derived from the request's `entry_key` (`entry_id`), so
inserting it twice can't make two: Google answers the second insert with HTTP 409, and that
existing entry is the one (put back if it was deleted from the calendar meanwhile).
"""

import asyncio
import base64
import hashlib
import logging
import threading
from collections.abc import Callable
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from google.auth.exceptions import RefreshError
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from app.adapters.protocols import CalendarEntryRequest, CalendarStatus, CalendarUnavailableError

logger = logging.getLogger(__name__)

SCOPES = ["https://www.googleapis.com/auth/calendar.events"]
CALENDAR_ID = "primary"
SIGN_IN = "Run `make google-auth` to connect Google Calendar."

ServiceFactory = Callable[[Credentials], Any]


def calendar_service(credentials: Credentials) -> Any:
    """A Google Calendar v3 client (from the discovery document bundled with the library)."""
    return build("calendar", "v3", credentials=credentials, cache_discovery=False)


def entry_id(entry_key: str) -> str:
    """The Google Calendar event id for a Calendar Entry key: stable, and valid for Google
    (base32hex digits 0-9 and a-v, 5 to 1024 of them): "um" and the key's SHA-256."""
    digest = hashlib.sha256(entry_key.encode()).digest()
    return "um" + base64.b32hexencode(digest).decode().rstrip("=").lower()


def entry_body(request: CalendarEntryRequest) -> dict[str, Any]:
    """The Google Calendar `events.insert` body for a Calendar Entry.

    Timed: `dateTime` in the user's time zone, with `timeZone`. All-day: `date`s, and since
    Google's all-day end date is exclusive, the day after the plan's last day.
    """
    body: dict[str, Any] = {
        "id": entry_id(request.entry_key),
        "summary": request.title,
        "description": request.description,
    }
    if request.location:
        body["location"] = request.location
    if request.all_day:
        assert isinstance(request.start, date) and isinstance(request.end, date)
        body["start"] = {"date": request.start.isoformat()}
        body["end"] = {"date": (request.end + timedelta(days=1)).isoformat()}
    else:
        assert isinstance(request.start, datetime) and isinstance(request.end, datetime)
        body["start"] = _timed(request.start, request.timezone)
        body["end"] = _timed(request.end, request.timezone)
    return body


def _timed(value: datetime, timezone: str) -> dict[str, str]:
    return {"dateTime": value.astimezone(ZoneInfo(timezone)).isoformat(), "timeZone": timezone}


def save_token(path: Path, credentials: Credentials) -> None:
    """Write the sign-in to `path`, readable by the user only."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.touch(mode=0o600, exist_ok=True)
    path.chmod(0o600)
    path.write_text(credentials.to_json())


class GoogleCalendar:
    """Creates Calendar Entries on the user's primary Google Calendar."""

    def __init__(self, token_path: Path, *, service_factory: ServiceFactory = calendar_service):
        self._token_path = token_path
        self._service_factory = service_factory
        self._credentials: Credentials | None = None
        self._service: Any = None
        self._lock = threading.Lock()  # the Google API client isn't thread-safe

    async def status(self) -> CalendarStatus:
        return await asyncio.to_thread(self._status)

    async def create_entry(self, request: CalendarEntryRequest) -> str:
        return await asyncio.to_thread(self._insert, entry_body(request))

    def _status(self) -> CalendarStatus:
        with self._lock:
            try:
                self._load()
            except CalendarUnavailableError as exc:
                return CalendarStatus(connected=False, reason=str(exc))
            return CalendarStatus(connected=True, reason=None)

    def _insert(self, body: dict[str, Any]) -> str:
        with self._lock:
            credentials = self._load()
            if not credentials.valid:
                self._refresh(credentials)
            if self._service is None:
                self._service = self._service_factory(credentials)
            events = self._service.events()
            try:
                created = events.insert(calendarId=CALENDAR_ID, body=body).execute()
            except HttpError as exc:
                if exc.resp.status != 409:
                    raise
                return self._existing(events, body)
            return str(created["id"])

    def _existing(self, events: Any, body: dict[str, Any]) -> str:
        """The Calendar Entry with `body`'s id already exists (an earlier insert got through):
        that is the one; if it was deleted from the calendar since, it is put back."""
        existing = events.get(calendarId=CALENDAR_ID, eventId=body["id"]).execute()
        logger.info("Calendar Entry %s already exists; using it", body["id"])
        if existing.get("status") == "cancelled":
            restored = {**body, "status": "confirmed"}
            events.update(calendarId=CALENDAR_ID, eventId=body["id"], body=restored).execute()
        return str(body["id"])

    def _load(self) -> Credentials:
        """The signed-in user's credentials, read from the token file once it exists."""
        if self._credentials is not None:
            return self._credentials
        if not self._token_path.exists():
            raise CalendarUnavailableError(f"Google Calendar isn't connected. {SIGN_IN}")
        try:
            credentials = Credentials.from_authorized_user_file(str(self._token_path), SCOPES)
        except (OSError, ValueError) as exc:
            raise CalendarUnavailableError(
                f"Google Calendar's sign-in in {self._token_path} can't be read ({exc}). {SIGN_IN}"
            ) from exc
        if not credentials.valid and not credentials.refresh_token:
            raise CalendarUnavailableError(f"Google Calendar's sign-in has expired. {SIGN_IN}")
        self._credentials = credentials
        return credentials

    def _refresh(self, credentials: Credentials) -> None:
        try:
            credentials.refresh(Request())
        except RefreshError as exc:
            # Revoked, or expired for good: nothing works until the user signs in again.
            # Forget it, so a fresh `make google-auth` is picked up without a restart.
            logger.warning("Refreshing the Google sign-in failed: %s", exc)
            self._credentials = self._service = None
            raise CalendarUnavailableError(
                f"Google Calendar's sign-in was revoked or has expired. {SIGN_IN}"
            ) from exc
        save_token(self._token_path, credentials)
        logger.info("Refreshed the Google sign-in and saved it to %s", self._token_path)
