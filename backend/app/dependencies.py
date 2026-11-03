"""FastAPI dependencies that hand routes the adapters the app was built with."""

from fastapi import Request

from app.adapters.protocols import Calendar, MessageSource, PlanModel
from app.config import Settings


def get_settings(request: Request) -> Settings:
    return request.app.state.settings


def get_message_source(request: Request) -> MessageSource:
    return request.app.state.message_source


def get_plan_model(request: Request) -> PlanModel:
    return request.app.state.plan_model


def get_calendar(request: Request) -> Calendar:
    return request.app.state.calendar
