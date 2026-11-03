from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session
from app.schemas import HealthOut

router = APIRouter()


@router.get("/health")
async def health(session: Annotated[AsyncSession, Depends(get_session)]) -> HealthOut:
    await session.execute(text("SELECT 1"))
    return HealthOut(status="ok", database="ok")
