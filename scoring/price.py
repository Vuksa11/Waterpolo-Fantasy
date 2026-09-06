"""
Player price-change formula, per docs/Fantasy_Waterpolo_Arhitektura_v2.md,
Section OQ-2 (resolved). Price tracks a rolling average of a player's own
recent scoring output, smoothed to avoid single-game volatility.

Must be run in matchday order (ascending `number`, within a season) -- each
step's "old price" is whatever the previous step left in `players.current_cost`,
so processing out of order corrupts the whole progression. recompute_all_prices
enforces this; don't call recompute_prices_for_matchday directly on a matchday
without having already processed every earlier one for that season.
"""

from datetime import datetime

from sqlalchemy.orm import Session

from db.models import EntityType, FantasyScore, Matchday, Player, PriceHistoryEntry, Season

BASE_PRICE = 7.0
MAX_RISE = 1.0
MAX_DROP = 1.0
FLOOR = 4.0
CEILING = 20.0
SMOOTHING = 0.3
ROLLING_WINDOW = 3


def compute_new_price(old_price: float, target_price: float) -> float:
    gap = target_price - old_price
    step = max(-MAX_DROP, min(MAX_RISE, SMOOTHING * gap))
    return max(FLOOR, min(CEILING, old_price + step))


def recompute_prices_for_matchday(session: Session, matchday: Matchday) -> int:
    """
    For every player with a fantasy_scores entry in this matchday, recompute
    their price from the average raw_points over their last (up to)
    ROLLING_WINDOW matchdays played in this season, including this one.
    Writes price_history and updates players.current_cost. Returns the number
    of players whose price changed.
    """
    scores_this_md = (
        session.query(FantasyScore)
        .filter(FantasyScore.matchday_id == matchday.id, FantasyScore.entity_type == EntityType.PLAYER)
        .all()
    )

    updated = 0
    for score in scores_this_md:
        player = session.get(Player, score.entity_id)
        if player is None:
            continue

        recent = (
            session.query(FantasyScore)
            .join(Matchday, Matchday.id == FantasyScore.matchday_id)
            .filter(
                FantasyScore.entity_type == EntityType.PLAYER,
                FantasyScore.entity_id == player.id,
                Matchday.season_id == matchday.season_id,
                Matchday.number <= matchday.number,
            )
            .order_by(Matchday.number.desc())
            .limit(ROLLING_WINDOW)
            .all()
        )
        target_price = float(sum(r.raw_points for r in recent)) / len(recent)

        old_price = float(player.current_cost)
        new_price = compute_new_price(old_price, target_price)

        if new_price != old_price:
            session.add(
                PriceHistoryEntry(
                    entity_type=EntityType.PLAYER,
                    entity_id=player.id,
                    matchday_id=matchday.id,
                    old_cost=old_price,
                    new_cost=new_price,
                )
            )
            player.current_cost = new_price
            player.updated_at = datetime.utcnow()
            updated += 1

    session.commit()
    return updated


def recompute_all_prices(session: Session) -> int:
    """
    Recompute prices for every season, matchday by matchday in ascending
    order. Convenience for backfills; the real pipeline calls
    recompute_prices_for_matchday once per newly-finalized matchday, in the
    order matchdays actually finalize (see docs, Section 7).
    """
    total = 0
    for season in session.query(Season).all():
        matchdays = (
            session.query(Matchday)
            .filter(Matchday.season_id == season.id)
            .order_by(Matchday.number.asc())
            .all()
        )
        for matchday in matchdays:
            total += recompute_prices_for_matchday(session, matchday)
    return total
