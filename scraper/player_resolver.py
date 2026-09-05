"""
Resolves a goalkeeper (or any roster row without a stable external id) to an
internal players row by name.

Field players carry a stable external id directly in the match page's box
score (ScrapedPlayerBoxScore.external_player_id, read from the OpenPlayerPage
onclick payload embedded next to their name) — resolving them is a plain
upsert-by-external_id, no fuzzy matching needed. Goalkeepers are the one
exception: their name-label has no onclick at all on the match page (verified
against a real saved match — see docs/Fantasy_Waterpolo_Arhitektura_v2.md,
Section 4.1a), so they must be resolved by name instead.

TODO: build this against a team squad/roster page (not yet sampled) which
should expose a stable id per goalkeeper the same way field players get one on
the match page — that would eliminate fuzzy matching entirely rather than
working around its absence here.
"""

import uuid


def resolve_goalkeeper_id(name: str, club: str, competition_id: uuid.UUID) -> uuid.UUID | None:
    """Return the internal player id for a goalkeeper by (name, club), or None if unresolved."""
    raise NotImplementedError("Pending a team squad/roster page sample — see module docstring.")
