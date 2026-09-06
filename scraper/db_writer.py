"""
Upserts scraped data (ScrapedFixture / ScrapedMatchBoxScore) into the schema
defined in db/models.py. Plain get-or-create functions over a SQLAlchemy
Session — no ORM-relationship magic, so each call is easy to trace back to the
table it touches.

Concurrency note: this assumes a single scraper process (the cron job), so a
plain query-then-insert has no meaningful race to guard against. If the
scraper is ever run concurrently, these need a real upsert (INSERT ... ON
CONFLICT) instead.
"""

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from db.models import (
    Coach,
    Competition,
    Match,
    Matchday,
    MatchdayStatus,
    MatchStatus,
    Player,
    PlayerStat,
    Season,
    SeasonStatus,
)
from scraper.parsers.match_page import ScrapedMatchBoxScore
from scraper.parsers.schedule_page import ScrapedFixture


def get_or_create_competition(
    session: Session,
    external_competition_id: int,
    name: str | None = None,
    schedule_url: str | None = None,
) -> Competition:
    source_slug = str(external_competition_id)
    competition = session.scalar(select(Competition).where(Competition.source_slug == source_slug))
    if competition is None:
        competition = Competition(source_slug=source_slug, name=name or source_slug, schedule_url=schedule_url)
        session.add(competition)
        session.flush()
    elif schedule_url and not competition.schedule_url:
        competition.schedule_url = schedule_url
    return competition


def get_or_create_active_season(session: Session, competition: Competition) -> Season:
    """
    Get the competition's current ACTIVE season, or create a placeholder one.

    v1 simplification: season creation/rollover isn't a solved product flow yet
    (see docs, Section 7, Next Steps — "stand up the three auto-created global
    leagues"). This just ensures *a* season exists so matchdays/matches have
    somewhere to attach during scraper development; start_date/end_date are
    placeholders.
    """
    season = session.scalar(
        select(Season).where(Season.competition_id == competition.id, Season.status == SeasonStatus.ACTIVE)
    )
    if season is None:
        today = datetime.utcnow().date()
        season = Season(
            competition_id=competition.id,
            name=f"{competition.name} — auto-created season",
            status=SeasonStatus.ACTIVE,
            start_date=today,
            end_date=today,
        )
        session.add(season)
        session.flush()
    return season


def get_or_create_matchday(session: Session, season: Season, round_label: str) -> Matchday:
    """
    Keyed by (season, label) — the round's text label is its real identity.
    `number` is a best-effort sort key only; two different non-numeric labels
    (e.g. "Semifinal" and "Final") must never collide, which a number-only key
    would do (both would fall back to the same placeholder).
    """
    matchday = session.scalar(
        select(Matchday).where(Matchday.season_id == season.id, Matchday.label == round_label)
    )
    if matchday is None:
        matchday = Matchday(
            season_id=season.id,
            label=round_label,
            number=_round_number(round_label),
            status=MatchdayStatus.UPCOMING,
        )
        session.add(matchday)
        session.flush()
    return matchday


# Known non-numeric playoff round labels, ordered after the regular season
# (offsets chosen with gaps in case a quarterfinal round is seen later).
_SPECIAL_ROUND_ORDER = {
    "quarterfinal": 9000,
    "semifinal": 9100,
    "bronze medal": 9200,
    "final": 9300,
}


def _round_number(round_label: str) -> int:
    """"Round 7" -> 7. Known playoff round names (Semifinal, Bronze medal,
    Final, ...) map to fixed offsets past the regular season so they still
    sort in a sensible order. Anything else unrecognized and non-numeric maps
    to a stable hash-derived number -- not meaningfully ordered, but at least
    distinct, so it can never silently collide with another round the way a
    flat fallback to 0 would."""
    digits = "".join(ch for ch in round_label.split()[-1] if ch.isdigit())
    if digits:
        return int(digits)
    known = _SPECIAL_ROUND_ORDER.get(round_label.strip().lower())
    if known is not None:
        return known
    return 900_000 + (hash(round_label) % 100_000)


def upsert_fixture(session: Session, matchday: Matchday, fixture: ScrapedFixture) -> Match:
    match = session.scalar(select(Match).where(Match.external_id == str(fixture.external_match_id)))
    if match is None:
        match = Match(matchday_id=matchday.id, external_id=str(fixture.external_match_id))
        session.add(match)

    match.home_club = fixture.home_team.name
    match.away_club = fixture.away_team.name
    match.home_score = fixture.home_score
    match.away_score = fixture.away_score
    match.status = MatchStatus.FINISHED if fixture.status == "FINISHED" else MatchStatus.UPCOMING
    session.flush()
    return match


def get_or_create_player(
    session: Session, competition: Competition, external_player_id: int | None, name: str, real_club: str
) -> Player:
    """
    Field players (external_player_id set) resolve by (competition, external_id).
    Goalkeepers (external_player_id is None) resolve by (competition, name,
    real_club) instead — see scraper/player_resolver.py for why.
    """
    if external_player_id is not None:
        player = session.scalar(
            select(Player).where(
                Player.competition_id == competition.id,
                Player.external_id == str(external_player_id),
            )
        )
    else:
        player = session.scalar(
            select(Player).where(
                Player.competition_id == competition.id,
                Player.external_id.is_(None),
                Player.name == name,
                Player.real_club == real_club,
            )
        )

    if player is None:
        player = Player(
            competition_id=competition.id,
            external_id=str(external_player_id) if external_player_id is not None else None,
            name=name,
            real_club=real_club,
        )
        session.add(player)
        session.flush()
    return player


def upsert_box_score(session: Session, competition: Competition, match: Match, box: ScrapedMatchBoxScore) -> None:
    for p in box.players:
        club = box.home_team.name if p.team_side == "HOME" else box.away_team.name
        player = get_or_create_player(session, competition, p.external_player_id, p.name, club)

        stat = session.scalar(
            select(PlayerStat).where(PlayerStat.match_id == match.id, PlayerStat.player_id == player.id)
        )
        if stat is None:
            stat = PlayerStat(match_id=match.id, player_id=player.id)
            session.add(stat)

        stat.goals = p.goals
        stat.assists = p.assists
        stat.fouls_drawn = p.fouls_drawn
        stat.steals = p.steals
        stat.blocks = p.blocks
        stat.swimoffs_won = p.swimoffs_won
        stat.misses = p.misses
        stat.personal_fouls = p.personal_fouls
        stat.turnovers = p.turnovers
        stat.offensive_fouls = p.offensive_fouls
        stat.saves = p.saves
        stat.goals_conceded = p.goals_conceded
        stat.updated_at = datetime.utcnow()

    match.home_score = box.home_score
    match.away_score = box.away_score
    match.status = MatchStatus.FINISHED if box.status.lower() == "finished" else MatchStatus.LIVE
    session.flush()


def get_or_create_placeholder_coach(session: Session, competition: Competition, real_club: str) -> Coach:
    """
    Placeholder until real coach data is provided (see docs, Section 7, Next
    Steps) -- one generic coach per (competition, club), name clearly marked
    TBD so it's obvious in the data which rows still need replacing with the
    real name/mapping once that arrives.
    """
    coach = session.scalar(
        select(Coach).where(Coach.competition_id == competition.id, Coach.real_club == real_club)
    )
    if coach is None:
        coach = Coach(
            competition_id=competition.id,
            name=f"{real_club} — trener TBD",
            real_club=real_club,
        )
        session.add(coach)
        session.flush()
    return coach


def create_placeholder_coaches_for_competition(session: Session, competition: Competition) -> int:
    """Create a placeholder coach for every club with at least one scraped
    player in this competition. Idempotent -- safe to re-run."""
    clubs = {
        row[0]
        for row in session.query(Player.real_club).filter(Player.competition_id == competition.id).distinct().all()
    }
    for club in clubs:
        get_or_create_placeholder_coach(session, competition, club)
    session.commit()
    return len(clubs)
