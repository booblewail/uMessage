"""API request/response models: snake_case in Python, camelCase in JSON."""

from typing import Literal

from pydantic import BaseModel, ConfigDict
from pydantic.alias_generators import to_camel


class ApiModel(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)


class HealthOut(ApiModel):
    status: Literal["ok"]
    database: Literal["ok"]


class MessageSourceStatusOut(ApiModel):
    name: str
    running: bool


class StatusOut(ApiModel):
    mode: Literal["real", "demo"]
    message_source: MessageSourceStatusOut
