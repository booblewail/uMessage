"""FastAPI entrypoint.

`create_app` builds the app from settings plus the three adapters; tests and demo mode
inject fakes. `build_app` is the zero-argument factory uvicorn runs
(`uvicorn --factory app.main:build_app`, single worker, bound to 127.0.0.1).
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import APIRouter, Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.adapters.beeper_desktop import BeeperDesktopMessageSource
from app.adapters.fakes import FakeCalendar, FakeMessageSource, FakePlanModel
from app.adapters.protocols import Calendar, MessageSource, PlanModel
from app.auth import require_api_token
from app.config import Settings
from app.db import create_engine
from app.routers import health, status


def create_app(
    settings: Settings,
    *,
    message_source: MessageSource,
    plan_model: PlanModel,
    calendar: Calendar,
) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        engine = create_engine(settings.database_url)
        app.state.sessionmaker = async_sessionmaker(engine, expire_on_commit=False)
        try:
            yield
        finally:
            await engine.dispose()

    app = FastAPI(title="uMessage", lifespan=lifespan)
    app.state.settings = settings
    app.state.message_source = message_source
    app.state.plan_model = plan_model
    app.state.calendar = calendar

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.allowed_origins,
        allow_methods=["*"],
        allow_headers=["Authorization", "Content-Type"],
    )

    app.include_router(health.router, prefix="/api")
    protected = APIRouter(prefix="/api", dependencies=[Depends(require_api_token)])
    protected.include_router(status.router)
    app.include_router(protected)
    return app


def build_app(settings: Settings | None = None) -> FastAPI:
    """Build the app for `UMESSAGE_MODE`: fakes in demo mode, real adapters otherwise."""
    settings = settings or Settings()  # type: ignore[call-arg]  # API_TOKEN comes from env
    if settings.umessage_mode == "demo":
        message_source: MessageSource = FakeMessageSource(running=settings.demo_beeper_running)
    else:
        message_source = BeeperDesktopMessageSource(settings.beeper_api_url)
    # TODO(#8, #9): the Gemini Plan Model and Google Calendar adapters replace these
    # once those interfaces have operations.
    return create_app(
        settings,
        message_source=message_source,
        plan_model=FakePlanModel(),
        calendar=FakeCalendar(),
    )
