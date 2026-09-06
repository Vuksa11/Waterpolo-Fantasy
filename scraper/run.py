"""
Orchestrator entrypoint — invoked by a cron/systemd timer in production, or by
the dev-only sleep loop in docker-compose.yml. Never invoked by Claude/an agent
at runtime — the pipeline is fully deterministic. See
docs/Fantasy_Waterpolo_Arhitektura_v2.md, Section 4.4.

Pipeline (per docs/Fantasy_Waterpolo_Arhitektura_v2.md, Section 4.2):
  1. Refresh the fixture list for each target competition (fetch_schedule).
  2. Select matches needing a box-score scrape: FINISHED/LIVE with no
     player_stats yet. (Re-scraping a LIVE match's still-changing box score
     mid-game isn't handled here -- see docs, Section 7.)
  3. Scrape and upsert box scores for those matches (fetch_boxscore).
  4. Recompute fantasy_scores for every matchday touched in this run
     (scoring.engine.recompute_matchday_scores).
  5. Recompute prices for those same matchdays, in ascending matchday-number
     order per season (scoring.price.recompute_prices_for_matchday) -- price
     is a rolling calculation, so it must run in that order (see
     scoring/price.py module docstring).
  6. Log the run to scrape_runs.
"""

import os
from datetime import datetime

from db.models import Match, MatchStatus, Matchday, PlayerStat, ScrapeRun
from db.session import make_session_factory
from scoring.engine import recompute_matchday_scores
from scoring.price import recompute_prices_for_matchday
from scraper.fetch_boxscore import fetch_boxscore
from scraper.fetch_schedule import fetch_schedule

# (name, schedule_url) for each league this project actually tracks.
# Super liga Srbije / Prva liga Srbije are not on totalwaterpolo.com -- the
# two VRL regional leagues are what's covered instead (see project history).
TARGET_COMPETITIONS: list[tuple[str, str]] = [
    ("Regionalna liga (VRL Premier Liga 2025/26)", "https://total-waterpolo.com/vrl-premier-liga-2025-26/"),
    ("VRL Prva Liga 2025/26 (druga regionalna liga)", "https://total-waterpolo.com/vrl-prva-liga-2025-26/"),
]


def main() -> None:
    started_at = datetime.utcnow()
    database_url = os.environ["DATABASE_URL_SYNC"]
    session_factory = make_session_factory(database_url)

    matches_processed = 0
    errors: list[str] = []

    with session_factory() as session:
        for name, schedule_url in TARGET_COMPETITIONS:
            try:
                fetch_schedule(session, schedule_url, competition_name=name)
            except Exception as e:
                errors.append(f"fetch_schedule({name}): {e}")

        pending = (
            session.query(Match)
            .outerjoin(PlayerStat, PlayerStat.match_id == Match.id)
            .filter(Match.status.in_([MatchStatus.FINISHED, MatchStatus.LIVE]))
            .filter(PlayerStat.id.is_(None))
            .all()
        )

        touched_matchday_ids: set = set()
        for match in pending:
            try:
                fetch_boxscore(session, int(match.external_id))
                touched_matchday_ids.add(match.matchday_id)
                matches_processed += 1
            except Exception as e:
                errors.append(f"fetch_boxscore({match.external_id}): {e}")

        touched_matchdays = sorted(
            (session.get(Matchday, mid) for mid in touched_matchday_ids),
            key=lambda md: (md.season_id, md.number),
        )
        for matchday in touched_matchdays:
            recompute_matchday_scores(session, matchday)
        for matchday in touched_matchdays:
            recompute_prices_for_matchday(session, matchday)

        session.add(
            ScrapeRun(
                started_at=started_at,
                finished_at=datetime.utcnow(),
                matches_processed=matches_processed,
                error_count=len(errors),
                notes="\n".join(errors) if errors else None,
            )
        )
        session.commit()

    print(f"Processed {matches_processed} matches, {len(errors)} errors.")
    for e in errors:
        print(f"  ERROR: {e}")


if __name__ == "__main__":
    main()
