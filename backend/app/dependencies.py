"""FastAPI dependencies that hand routes the adapters the app was built with."""

import asyncio

from fastapi import Request

from app.adapters.protocols import Calendar, MessageSource, PlanModel
from app.config import Settings
from app.first_import import FirstImport
from app.ws_manager import ConnectionManager


def get_settings(request: Request) -> Settings:
    return request.app.state.settings


def get_message_source(request: Request) -> MessageSource:
    return request.app.state.message_source


def get_plan_model(request: Request) -> PlanModel:
    return request.app.state.plan_model


def get_calendar(request: Request) -> Calendar:
    return request.app.state.calendar


def get_first_import(request: Request) -> FirstImport:
    return request.app.state.first_import


def get_connections(request: Request) -> ConnectionManager:
    return request.app.state.connections


def get_inbox_lock(request: Request) -> asyncio.Lock:
    return request.app.state.inbox_lock
