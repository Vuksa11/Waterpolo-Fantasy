"""
Fetches and upserts the fixture list for one competition.

Pipeline step 1 in docs/Fantasy_Waterpolo_Arhitektura_v2.md, Section 4.2.
"""

import uuid

import requests

from scraper.parsers.schedule_page import parse_schedule_page


def fetch_schedule(competition_id: uuid.UUID, source_slug: str) -> None:
    """
    Fetch the fixture-list page for a competition and upsert into matches/matchdays.

    TODO: source URL pattern is not yet known — pending a sample fixture-list URL
    per competition (see Section 7, Next Steps). Once known, this should:
      1. GET the fixture-list page for `source_slug`.
      2. Parse it with parse_schedule_page().
      3. Upsert each fixture into `matches` keyed by external_id, grouping into
         `matchdays` by round/date.
    """
    raise NotImplementedError("Pending source URL pattern — see module docstring.")
