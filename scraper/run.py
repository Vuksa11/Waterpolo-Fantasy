"""
Orchestrator entrypoint — invoked by a cron/systemd timer in production, or by
the dev-only sleep loop in docker-compose.yml. Never invoked by Claude/an agent
at runtime — the pipeline is fully deterministic. See
docs/Fantasy_Waterpolo_Arhitektura_v2.md, Section 4.4.

Pipeline (per docs/Fantasy_Waterpolo_Arhitektura_v2.md, Section 4.2):
  1. Refresh the fixture list for each of the 3 competitions (fetch_schedule).
  2. Select matches needing a box-score scrape (LIVE/FINISHED, stats missing
     or stale).
  3. Scrape and upsert box scores for those matches (fetch_boxscore).
  4-5. Fantasy score / price-change recalculation — not implemented yet (see
       docs, Section 7, Next Steps — this is scoring-module work, not scraper
       work).
  6. Log the run to scrape_runs.

TODO: step 2's match-selection query and the scrape_runs logging (step 6)
aren't wired up yet. More fundamentally, TARGET_COMPETITIONS below is empty —
the exact totalwaterpolo.com schedule-page URLs for the 3 real target
competitions (Regionalna liga, Super liga Srbije, Prva liga Srbije) haven't
been identified yet. Everything scraped and written to the database so far
was a generic sample (VRL Prva Liga, Montenegro) used only to verify the
parsing and DB-write code paths work end to end.
"""

import os
from datetime import datetime

from db.session import make_session_factory
from scraper.fetch_boxscore import fetch_boxscore
from scraper.fetch_schedule import fetch_schedule
from db.models import Match, MatchStatus

# (name, schedule_url) for each target competition. Empty until the real
# totalwaterpolo.com pages for our 3 leagues are identified.
TARGET_COMPETITIONS: list[tuple[str, str]] = []


def main() -> None:
    started_at = datetime.utcnow()  # noqa: F841
    database_url = os.environ["DATABASE_URL_SYNC"]
    session_factory = make_session_factory(database_url)

    if not TARGET_COMPETITIONS:
        raise NotImplementedError(
            "TARGET_COMPETITIONS is empty — see module docstring. "
            "fetch_schedule()/fetch_boxscore() are implemented and verified; "
            "this orchestrator just has nowhere to point them yet."
        )

    with session_factory() as session:
        for name, schedule_url in TARGET_COMPETITIONS:
            fetch_schedule(session, schedule_url, competition_name=name)

        matches_needing_boxscore = session.query(Match).filter(Match.status != MatchStatus.UPCOMING).all()
        for match in matches_needing_boxscore:
            fetch_boxscore(session, int(match.external_id))


if __name__ == "__main__":
    main()
