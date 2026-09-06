import uuid
from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.db import get_db
from app.schemas import CoachOut
from db.models import Coach

router = APIRouter(prefix='/api/coaches', tags=['coaches'])

@router.get('', response_model=list[CoachOut])
async def list_coaches(competition_id: uuid.UUID | None = None, db: AsyncSession = Depends(get_db)):
    query = select(Coach)
    if competition_id is not None:
        query = query.where(Coach.competition_id == competition_id)
    return list((await db.execute(query.order_by(Coach.name, Coach.id))).scalars())
