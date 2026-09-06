import uuid

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db
from app.schemas import CoachOut
from db.models import Coach

router = APIRouter(prefix="/api/coaches", tags=["coaches"])


@router.get("", response_model=list[CoachOut])
async def list_coaches(
    competition_id: uuid.UUID | None = None, db: AsyncSession = Depends(get_db)
) -> list[Coach]:
    """
    Missing entirely until now -- discovered live via the frontend session's
    running app (its team-builder calls this to populate the coach picker;
    every club currently has a generic placeholder coach, see
    scraper/db_writer.create_placeholder_coaches_for_competition).
    """
    query = select(Coach)
    if competition_id is not None:
        query = query.where(Coach.competition_id == competition_id)
    result = await db.execute(query.order_by(Coach.current_cost.desc()))
    return list(result.scalars().all())
