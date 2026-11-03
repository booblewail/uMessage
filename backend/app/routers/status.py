from typing import Annotated

from fastapi import APIRouter, Depends

from app.adapters.protocols import MessageSource
from app.config import Settings
from app.dependencies import (
    get_first_import,
    get_message_source,
    get_plan_detection,
    get_settings,
)
from app.first_import import FirstImport
from app.plan_detection import PlanDetection
from app.schemas import FirstImportOut, MessageSourceStatusOut, PlanDetectionOut, StatusOut

router = APIRouter()


@router.get("/status")
async def get_status(
    settings: Annotated[Settings, Depends(get_settings)],
    message_source: Annotated[MessageSource, Depends(get_message_source)],
    first_import: Annotated[FirstImport, Depends(get_first_import)],
    plan_detection: Annotated[PlanDetection, Depends(get_plan_detection)],
) -> StatusOut:
    source_status = await message_source.status()
    progress = first_import.progress
    detection = plan_detection.status
    return StatusOut(
        mode=settings.umessage_mode,
        message_source=MessageSourceStatusOut(
            name=source_status.name, running=source_status.running
        ),
        first_import=FirstImportOut(
            state=progress.state,
            chats_total=progress.chats_total,
            chats_imported=progress.chats_imported,
            error=progress.error,
        ),
        plan_detection=PlanDetectionOut(
            enabled=detection.enabled, reason=detection.reason, last_error=detection.last_error
        ),
    )
