"""
Run BEFORE a load test that's meant to exercise transfer()/save_lineup()'s
success path (not just their 409 path). Every real matchday in the dev DB is
a finished historical round with no deadline (a fully-played, already-
scraped season), so transfer()/save_lineup()'s current_window() check would
409 every single write attempt otherwise -- fast to fail, but useless for
measuring write-lock/contention behavior under load, which is the actual
point of testing those endpoints.

Creates one throwaway UPCOMING matchday with a far-future deadline for every
season that currently exists, so create_team's season pick (latest by
start_date) always has a matching open window. Safe to run repeatedly
(skips a competition/season that already has one). Clean up afterward with
--cleanup.

Usage:
  .venv/bin/python -m backend.loadtest.prepare_upcoming_matchday
  .venv/bin/python -m backend.loadtest.prepare_upcoming_matchday --cleanup
"""

import argparse
import asyncio
import sys
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

sys.path.insert(0, ".")
sys.path.insert(0, "backend")

from app.core.db import async_session  # noqa: E402
from db.models import Matchday, MatchdayStatus, Season  # noqa: E402

LOADTEST_LABEL = "Loadtest Upcoming Round"


async def prepare() -> None:
    async with async_session() as db:
        seasons = list((await db.scalars(select(Season))).all())
        created = 0
        for season in seasons:
            existing = await db.scalar(
                select(Matchday).where(Matchday.season_id == season.id, Matchday.label == LOADTEST_LABEL)
            )
            if existing is not None:
                continue
            db.add(
                Matchday(
                    season_id=season.id,
                    label=LOADTEST_LABEL,
                    number=999997,
                    status=MatchdayStatus.UPCOMING,
                    deadline=datetime.now(timezone.utc) + timedelta(days=7),
                )
            )
            created += 1
        await db.commit()
        print(f"created {created} loadtest matchday(s) across {len(seasons)} season(s)")


async def cleanup() -> None:
    async with async_session() as db:
        rows = list((await db.scalars(select(Matchday).where(Matchday.label == LOADTEST_LABEL))).all())
        for row in rows:
            await db.delete(row)
        await db.commit()
        print(f"removed {len(rows)} loadtest matchday(s)")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--cleanup", action="store_true")
    args = parser.parse_args()
    asyncio.run(cleanup() if args.cleanup else prepare())
