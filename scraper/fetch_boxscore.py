"""
Fetches and upserts the box score for a single match.

Pipeline steps 2-3 in docs/Fantasy_Waterpolo_Arhitektura_v2.md, Section 4.2.
"""

import uuid

import requests

from scraper.parsers.match_page import parse_match_page
from scraper.player_resolver import resolve_coach_id, resolve_player_id


def fetch_boxscore(match_id: uuid.UUID, match_url: str, competition_id: uuid.UUID) -> None:
    """
    Fetch a match's box-score page and upsert per-player/coach statistics.

    Upserts are keyed by (match_id, player_id) / (match_id, coach_id) — never
    insert-only — so a re-run after a parser fix self-heals previously bad rows.

    TODO: pending real match page access (see module docstrings in
    scraper/parsers/match_page.py and scraper/player_resolver.py).
    """
    raise NotImplementedError("Pending real match page access — see module docstring.")
