"""
Maps a scraped name (player or coach) to an internal players/coaches row.

totalwaterpolo.com has no stable cross-season player ID, so resolution is by
fuzzy match on (name, real_club, position/competition) rather than a direct ID
lookup — see docs/Fantasy_Waterpolo_Arhitektura_v2.md, Section 4.1.

TODO: fuzzy-match implementation pending real scraped sample data (name
formatting, accent handling, transfer-window club changes) to tune against.
"""

import uuid


def resolve_player_id(name: str, club: str, competition_id: uuid.UUID) -> uuid.UUID | None:
    """Return the internal player id for a scraped (name, club), or None if unresolved."""
    raise NotImplementedError("Pending real scraped sample data — see module docstring.")


def resolve_coach_id(name: str, club: str, competition_id: uuid.UUID) -> uuid.UUID | None:
    """Return the internal coach id for a scraped (name, club), or None if unresolved."""
    raise NotImplementedError("Pending real scraped sample data — see module docstring.")
