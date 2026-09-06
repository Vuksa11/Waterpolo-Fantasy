"""
Fantasy point calculation, per docs/Fantasy_Waterpolo_Arhitektura_v2.md,
Section 5.2. Kept as its own top-level package (a sibling of db/ and scraper/)
because it's invoked by both the scraper pipeline (step 4: recompute scores
after a box score is ingested) and, later, the backend API -- neither should
have to depend on the other's package to reach it.

Design clarification (resolves an ambiguity in the original v1 architecture
doc): `fantasy_scores` has no fantasy_team_id column -- it holds ONE row per
player per matchday, not one per (team, player, matchday). Bench (x0.5) and
captain (x2.0) multipliers are properties of a specific fantasy team's lineup
choice, not of the player, so they cannot live in this table's `final_points`
despite the v1 doc's column comment suggesting otherwise. Here, `final_points`
equals `raw_points` -- multipliers are applied later, per fantasy team, when
computing that team's matchday total from its lineup (not yet implemented --
see docs, Section 7).
"""

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from db.models import (
    EntityType,
    FantasyScore,
    Match,
    Matchday,
    MatchdayStatus,
    MatchStatus,
    PlayerStat,
)


def player_raw_points(stat: PlayerStat) -> float:
    """
    One formula for both field players and goalkeepers: the goalkeeper-only
    terms (saves, goals_conceded) are always 0 for a field player's stat row,
    so no position/role lookup is needed to score correctly.
    """
    return (
        3.0 * stat.goals
        + 1.0 * stat.assists
        + 1.0 * stat.fouls_drawn
        + 1.0 * stat.steals
        + 1.0 * stat.blocks
        + 1.0 * stat.swimoffs_won
        - 0.5 * stat.misses
        - 1.0 * stat.personal_fouls
        - 1.0 * stat.turnovers
        - 1.0 * stat.offensive_fouls
        + 1.5 * stat.saves
        - 0.5 * stat.goals_conceded
    )


def coach_points(goal_difference: int) -> float:
    """goal_difference = coach's team goals minus opponent goals."""
    if goal_difference == 0:
        return 0.0
    margin = abs(goal_difference)
    if goal_difference > 0:
        if margin <= 2:
            points = 4.0
        elif margin <= 5:
            points = 6.0
        elif margin <= 8:
            points = 10.0
        else:
            points = 12.0
    else:
        if margin <= 2:
            points = -2.0
        elif margin <= 5:
            points = -4.0
        elif margin <= 8:
            points = -6.0
        else:
            points = -8.0
    return points


def _matchday_status(matches: list[Match]) -> MatchdayStatus:
    if all(m.status == MatchStatus.FINISHED for m in matches):
        return MatchdayStatus.FINISHED
    if any(m.status in (MatchStatus.FINISHED, MatchStatus.LIVE) for m in matches):
        return MatchdayStatus.ACTIVE
    return MatchdayStatus.UPCOMING


def recompute_matchday_scores(session: Session, matchday: Matchday) -> int:
    """
    Aggregate raw points per player across every match in this matchday and
    upsert into fantasy_scores. Also refreshes matchday.status from its
    matches' actual status (the scraper never sets it directly -- see
    scraper/db_writer.py). Coaches are not scored here yet: no coach_stats
    have been scraped (see docs, Section 7, Next Steps).

    Returns the number of fantasy_scores rows written.
    """
    matches = session.query(Match).filter(Match.matchday_id == matchday.id).all()
    if not matches:
        return 0

    matchday.status = _matchday_status(matches)
    is_finalized = matchday.status == MatchdayStatus.FINISHED

    match_ids = [m.id for m in matches]
    stats = session.query(PlayerStat).filter(PlayerStat.match_id.in_(match_ids)).all()

    totals: dict[uuid.UUID, float] = {}
    for stat in stats:
        totals[stat.player_id] = totals.get(stat.player_id, 0.0) + player_raw_points(stat)

    written = 0
    for player_id, raw_points in totals.items():
        score = session.scalar(
            select(FantasyScore).where(
                FantasyScore.matchday_id == matchday.id,
                FantasyScore.entity_type == EntityType.PLAYER,
                FantasyScore.entity_id == player_id,
            )
        )
        if score is None:
            score = FantasyScore(
                matchday_id=matchday.id, entity_type=EntityType.PLAYER, entity_id=player_id
            )
            session.add(score)
        score.raw_points = raw_points
        score.final_points = raw_points  # see module docstring
        score.is_finalized = is_finalized
        written += 1

    session.commit()
    return written


def recompute_all(session: Session) -> int:
    """Recompute every matchday in the database. Convenience for backfills;
    the real pipeline calls recompute_matchday_scores per-matchday right
    after that matchday's box scores are fetched (see scraper/run.py)."""
    total = 0
    for matchday in session.query(Matchday).all():
        total += recompute_matchday_scores(session, matchday)
    return total
