"""
Orchestrator entrypoint — invoked by a cron/systemd timer in production, or by
the dev-only sleep loop in docker-compose.yml. Never invoked by Claude/an agent
at runtime — the pipeline is fully deterministic. See
docs/Fantasy_Waterpolo_Arhitektura_v2.md, Section 4.4.

Pipeline (per docs/Fantasy_Waterpolo_Arhitektura_v2.md, Section 4.2):
  1. Refresh the fixture list for each of the 3 competitions.
  2. Select matches needing a box-score scrape (LIVE/FINISHED, stats missing or stale).
  3. Scrape and upsert box scores for those matches.
  4. Trigger fantasy score recalculation for affected matchdays.
  5. On matchday finalization, run the price-change step and write price_history.
  6. Log the run to scrape_runs.
"""

from datetime import datetime


def main() -> None:
    started_at = datetime.utcnow()  # noqa: F841

    # TODO: steps 1-5 depend on fetch_schedule/fetch_boxscore being implemented
    # against real page structure — see their module docstrings and
    # docs/Fantasy_Waterpolo_Arhitektura_v2.md, Section 7 (Next Steps).
    # Step 6 (scrape_runs logging) can be wired up once steps 1-5 exist to log.
    raise NotImplementedError("Pending fetch_schedule/fetch_boxscore implementation.")


if __name__ == "__main__":
    main()
