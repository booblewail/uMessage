from typing import Annotated

from fastapi import APIRouter, Depends

from app.adapters.protocols import MessageSource
from app.config import Settings
from app.dependencies import get_message_source, get_settings
from app.schemas import MessageSourceStatusOut, StatusOut

router = APIRouter()


@router.get("/status")
async def get_status(
    settings: Annotated[Settings, Depends(get_settings)],
    message_source: Annotated[MessageSource, Depends(get_message_source)],
) -> StatusOut:
    source_status = await message_source.status()
    return StatusOut(
        mode=settings.umessage_mode,
        message_source=MessageSourceStatusOut(
            name=source_status.name, running=source_status.running
        ),
    )
