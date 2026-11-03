"""FastAPI entrypoint.

`create_app` builds the app from settings plus the three adapters; tests and demo mode
inject fakes. Startup kicks off one tracked background task that runs First Import (until it
has completed once) and then live updates for as long as the app runs; plan detection's
checks run as further tracked tasks, one per Chat waiting to settle. `build_app` is the
zero-argument factory uvicorn runs (`uvicorn --factory app.main:build_app`, single worker,
bound to 127.0.0.1).
"""

import asyncio
from collections.abc import AsyncIterator, Callable, Coroutine, Sequence
from contextlib import asynccontextmanager
from typing import Any

from fastapi import APIRouter, Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.adapters.beeper_desktop import BeeperDesktopMessageSource
from app.adapters.demo_fixtures import demo_message_source, demo_plan_decision, demo_trickle
from app.adapters.fakes import FakeCalendar, FakePlanModel
from app.adapters.gemini import GeminiPlanModel
from app.adapters.protocols import Calendar, MessageSource, PlanModel
from app.auth import require_api_token
from app.background import BackgroundTasks
from app.config import Settings
from app.db import create_engine
from app.first_import import FirstImport, FirstImportState
from app.live_updates import LiveUpdates
from app.plan_detection import PlanDetection, Sleep
from app.routers import chats, events, health, status, ws
from app.ws_manager import ConnectionManager

BackgroundJob = Callable[[], Coroutine[Any, Any, None]]

NO_GEMINI_API_KEY = "Plan detection is off: set GEMINI_API_KEY in .env (see .env.example)"


def create_app(
    settings: Settings,
    *,
    message_source: MessageSource,
    plan_model: PlanModel | None,
    calendar: Calendar,
    retry_seconds: float = 5.0,
    background_jobs: Sequence[BackgroundJob] = (),
    settle_sleep: Sleep = asyncio.sleep,
) -> FastAPI:
    """`plan_model` None turns plan detection off (no Gemini API key).
    `retry_seconds`: how often to retry while the Message Source can't be reached.
    `background_jobs` run as extra tracked tasks (demo mode's trickle of Messages).
    `settle_sleep` waits out plan detection's settle delay (tests pass a fake clock's)."""

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        engine = create_engine(settings.database_url)
        sessionmaker = async_sessionmaker(engine, expire_on_commit=False)
        app.state.sessionmaker = sessionmaker
        app.state.inbox_lock = inbox_lock = asyncio.Lock()
        tasks = BackgroundTasks()
        first_import = FirstImport(sessionmaker, message_source, retry_seconds=retry_seconds)
        app.state.first_import = first_import
        app.state.plan_detection = plan_detection = PlanDetection(
            sessionmaker,
            plan_model,
            app.state.connections,
            tasks,
            timezone=settings.user_timezone,
            settle_seconds=settings.plan_settle_seconds,
            confidence_threshold=settings.plan_confidence_threshold,
            max_concurrent=settings.plan_max_concurrent,
            disabled_reason=NO_GEMINI_API_KEY,
            sleep=settle_sleep,
        )
        live_updates = LiveUpdates(
            sessionmaker,
            message_source,
            app.state.connections,
            inbox_lock,
            plan_detection,
            poll_seconds=settings.new_messages_poll_seconds,
            retry_seconds=retry_seconds,
        )

        async def sync_with_message_source(*, import_first: bool) -> None:
            if import_first:
                await first_import.run()
            if first_import.progress.state is FirstImportState.COMPLETED:
                await live_updates.run()

        try:
            import_first = not await first_import.load_completion()
            tasks.start(
                sync_with_message_source(import_first=import_first), name="message-source-sync"
            )
            for job in background_jobs:
                tasks.start(job(), name=getattr(job, "__name__", "background-job"))
            yield
        finally:
            await tasks.stop()
            await engine.dispose()

    app = FastAPI(title="uMessage", lifespan=lifespan)
    app.state.settings = settings
    app.state.message_source = message_source
    app.state.plan_model = plan_model
    app.state.calendar = calendar
    app.state.connections = ConnectionManager()

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.allowed_origins,
        allow_methods=["*"],
        allow_headers=["Authorization", "Content-Type"],
    )

    app.include_router(health.router, prefix="/api")
    protected = APIRouter(prefix="/api", dependencies=[Depends(require_api_token)])
    protected.include_router(status.router)
    protected.include_router(chats.router)
    protected.include_router(events.router)
    app.include_router(protected)
    app.include_router(ws.router)  # authenticates with `?token=` itself
    return app


def build_app(settings: Settings | None = None) -> FastAPI:
    """Build the app for `UMESSAGE_MODE`: fakes in demo mode, real adapters otherwise."""
    settings = settings or Settings()  # type: ignore[call-arg]  # API_TOKEN comes from env
    background_jobs: list[BackgroundJob] = []
    plan_model: PlanModel | None
    if settings.umessage_mode == "demo":
        plan_model = FakePlanModel(respond=demo_plan_decision)
        demo_source = demo_message_source(running=settings.demo_beeper_running)
        message_source: MessageSource = demo_source
        if settings.demo_new_message_seconds > 0:

            async def demo_new_messages() -> None:
                await demo_trickle(demo_source, every_seconds=settings.demo_new_message_seconds)

            background_jobs.append(demo_new_messages)
    else:
        message_source = BeeperDesktopMessageSource(settings.beeper_api_url)
        key = settings.gemini_api_key
        plan_model = (
            GeminiPlanModel(api_key=key.get_secret_value(), model=settings.gemini_model)
            if key
            else None
        )
    # TODO(#9): the Google Calendar adapter replaces this once Calendar has operations.
    return create_app(
        settings,
        message_source=message_source,
        plan_model=plan_model,
        calendar=FakeCalendar(),
        background_jobs=background_jobs,
    )
