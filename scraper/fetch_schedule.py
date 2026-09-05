"""
Fetches and upserts the fixture list for one competition.

Pipeline step 1 in docs/Fantasy_Waterpolo_Arhitektura_v2.md, Section 4.2.

The match page (see fetch_boxscore.py) confirmed that this plugin renders data
client-side against a token-gated API, so the fixture-list page almost
certainly needs the same headless-browser approach — but this hasn't been
verified against a real saved fixture-list page yet. Once a sample is
available (Section 7, Next Steps), a schedule_page.py parser can be written
the same way match_page.py was: inspect the real rendered DOM, map its
tw-data attributes, and verify against known results before trusting it.
"""

import uuid


def fetch_schedule(competition_id: uuid.UUID, source_slug: str) -> None:
    """
    Fetch the fixture-list page for a competition and upsert into matches/matchdays.

    TODO: pending a sample fixture-list page (see module docstring).
    """
    raise NotImplementedError("Pending a sample fixture-list page — see module docstring.")
