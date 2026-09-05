"""
Parses a rendered totalwaterpolo.com match page into per-player box-score data.

IMPORTANT — this must be called on the FULLY RENDERED DOM (after the page's own
JavaScript has populated the match widget), not on the raw HTTP response. The
match widget loads its data client-side from a Bearer-token-gated backend
(https://arena.total-waterpolo.com/api/) — see
docs/Fantasy_Waterpolo_Arhitektura_v2.md, Section 4.1a. A plain `requests.get()`
returns the page shell only. Use fetch_boxscore.py's Playwright-based fetch,
which lets the site's own JS acquire the token exactly as it would for any
browser visitor, then reads back `page.content()`.

DOM contract this parser depends on (verified against a real saved match page,
see docs Section 4.1a):

- `.tw_full_match [tw-match-id]` — match id; `.tw_full_match[tw-competition-id]`
  — competition id.
- `[tw-data="hometeamlogo"] img[onclick]` / `[tw-data="awayteamlogo"] img[onclick]`
  — onclick is `OpenTeamPage(<external_team_id>, '<name>')`.
- `[tw-data="hometeamname_short"]` / `[tw-data="awayteamname_short"]` — short codes.
- `[tw-data="hometeamgoals"]` / `[tw-data="awayteamgoals"]` — final score.
- `[tw-data="status"]` — "finished" / "live" / etc.
- `#homePlayers` / `#awayPlayers` — each contains `.tw_match_player[tw-player-id]`
  blocks, one per rostered player:
    - `[tw-data="playerNum"]` — jersey number
    - `[tw-data="playerName"] onclick` — `OpenPlayerPage(<external_player_id>, '<name>')`
      — this id is STABLE across matches/seasons, so player resolution needs no
      fuzzy name matching (see player_resolver.py).
    - `[tw-data="playerPF"]` — personal fouls (also cross-checked via the
      `pf_<player-id>` chart below)
    - nested bar-chart elements `[tw-chart-id="<key>_<player-id>"]`, each with a
      `[tw-data="homeResult"]` span holding a plain integer — despite the name,
      in this nested context it means "this player's count", not home-team.
      Keys used: assists, pfdrawn (= fouls_drawn), steals, blocks, swimoffs,
      ballslost (= turnovers), offensivef (= offensive_fouls), pf.
- `.tw_play_by_play[tw-event-id]` — one row per match event, each with:
    - `.event-label .player-name [tw-data="player"]` — actor's name (text, may
      be last-name-only)
    - `[tw-data="playerNum"]` and `[tw-data="team"]` (short code) — used instead
      of the name to resolve the actor back to a roster player, since PBP names
      are sometimes abbreviated
    - `.event-label .description` — event type text (see GOAL_DESCRIPTIONS /
      MISS_DESCRIPTIONS / SAVE_DESCRIPTION below)
    - `.eventDetails .detailsMetaRow` pairs of (`.col-3.description` label,
      `.col-9.label` value) — used here only for "saved by" (goalkeeper credit
      on a `Shot saved` event). Steals/turnovers/fouls-drawn are read from the
      per-player aggregate charts above instead of re-derived from PBP detail
      fields (`STOLEN BY` / `FOULED PLAYER`), since the aggregate is the site's
      own authoritative total and avoids any risk of double-counting.

Goals, misses, and saves are NOT available as plain-text aggregates — the
equivalent per-player summary (a shots-made/attempted doughnut) renders as a
canvas chart with no scrapeable numeric value in the DOM, so these three are
derived by counting play-by-play events instead.

Known v1 simplifications (see docs, Section 4.1a "Known limitations"):
  - goals_conceded is assigned to whichever goalkeeper on a team recorded the
    most saves in the match (proxy for "the starting/primary keeper"), and set
    to the opponent's full final score. Mid-match keeper substitutions are not
    modeled.
  - "Miss" (-0.5 in scoring) counts only `shot missed` / `Power play shot
    missed` events. A shot that was saved or blocked by the opponent also
    fails to score, but is not counted as a "miss" for the shooter in v1 —
    treated as a contested attempt rather than an error. Revisit if this
    doesn't match expectations once real data is scored.
"""

import re
from dataclasses import dataclass, field

from bs4 import BeautifulSoup
from bs4.element import Tag

_ONCLICK_ID_NAME_RE = re.compile(r"Open(?:Player|Team)Page\((\d+),\s*'([^']*)'\)")

_GOAL_DESCRIPTIONS = {"goal scored", "fastbreak goal scored", "penalty goal scored", "power play goal scored"}
_MISS_DESCRIPTIONS = {"shot missed", "power play shot missed"}
_SAVE_DESCRIPTION = "shot saved"

_CHART_KEY_TO_FIELD = {
    "assists": "assists",
    "pfdrawn": "fouls_drawn",
    "steals": "steals",
    "blocks": "blocks",
    "swimoffs": "swimoffs_won",
    "ballslost": "turnovers",
    "offensivef": "offensive_fouls",
}


@dataclass
class ScrapedTeam:
    external_team_id: int
    name: str
    short_name: str
    side: str  # "HOME" | "AWAY"


@dataclass
class ScrapedPlayerBoxScore:
    match_local_id: str
    external_player_id: int | None
    name: str
    jersey_number: int
    team_side: str  # "HOME" | "AWAY"
    goals: int = 0
    assists: int = 0
    fouls_drawn: int = 0
    steals: int = 0
    blocks: int = 0
    swimoffs_won: int = 0
    misses: int = 0
    personal_fouls: int = 0
    turnovers: int = 0
    offensive_fouls: int = 0
    saves: int = 0
    goals_conceded: int = 0


@dataclass
class ScrapedMatchBoxScore:
    external_match_id: int
    external_competition_id: int
    home_team: ScrapedTeam
    away_team: ScrapedTeam
    home_score: int
    away_score: int
    status: str
    players: list[ScrapedPlayerBoxScore] = field(default_factory=list)


def _extract_id_name(onclick: str | None) -> tuple[int, str] | None:
    if not onclick:
        return None
    m = _ONCLICK_ID_NAME_RE.search(onclick)
    return (int(m.group(1)), m.group(2)) if m else None


def _text(tag: Tag | None) -> str:
    return tag.get_text(strip=True) if tag else ""


def _int_text(tag: Tag | None) -> int:
    t = _text(tag)
    return int(t) if t.lstrip("-").isdigit() else 0


def _chart_value(player_block: Tag, chart_key: str, player_id: str) -> int:
    chart = player_block.find(attrs={"tw-chart-id": f"{chart_key}_{player_id}"})
    if chart is None:
        return 0
    value_span = chart.find(attrs={"tw-data": "homeResult"})
    return _int_text(value_span)


def _parse_roster_section(section: Tag, side: str) -> dict[str, ScrapedPlayerBoxScore]:
    """Returns {jersey_number: ScrapedPlayerBoxScore} for one team's player list."""
    players: dict[str, ScrapedPlayerBoxScore] = {}
    for block in section.select(".tw_match_player[tw-player-id]"):
        player_id = block["tw-player-id"]
        jersey = _text(block.find(attrs={"tw-data": "playerNum"}))
        name_el = block.find(attrs={"tw-data": "playerName"})
        if name_el is None:
            continue
        id_name = _extract_id_name(name_el.get("onclick"))
        # Field players expose a stable external id via the OpenPlayerPage onclick.
        # Goalkeepers (in #home/#awayGoalkeepers) do not — their name-label has no
        # onclick at all. external_player_id is None for these; player_resolver.py
        # must resolve them by name against a team squad lookup instead.
        external_id, name = id_name if id_name else (None, _text(name_el))

        stat = ScrapedPlayerBoxScore(
            match_local_id=player_id,
            external_player_id=external_id,
            name=name,
            jersey_number=int(jersey) if jersey.isdigit() else 0,
            team_side=side,
            personal_fouls=_chart_value(block, "pf", player_id) or _int_text(block.find(attrs={"tw-data": "playerPF"})),
        )
        for chart_key, field_name in _CHART_KEY_TO_FIELD.items():
            setattr(stat, field_name, _chart_value(block, chart_key, player_id))

        players[jersey] = stat
    return players


def _event_detail_field(event: Tag, label: str) -> str | None:
    for row in event.select(".eventDetails .detailsMetaRow"):
        desc = row.select_one(".col-3.description")
        value = row.select_one(".col-9.label")
        if desc and value and _text(desc).lower() == label.lower():
            return _text(value)
    return None


def _apply_play_by_play(
    soup: BeautifulSoup,
    home_players: dict[str, ScrapedPlayerBoxScore],
    away_players: dict[str, ScrapedPlayerBoxScore],
    home_short: str,
    away_short: str,
) -> None:
    name_to_player = {p.name.strip(): p for p in [*home_players.values(), *away_players.values()]}

    for event in soup.select(".tw_play_by_play[tw-event-id]"):
        team_code = _text(event.find(attrs={"tw-data": "team"}))
        jersey = _text(event.find(attrs={"tw-data": "playerNum"}))
        description = _text(event.select_one(".event-label .description")).lower()

        roster = home_players if team_code == home_short else away_players if team_code == away_short else None
        actor = roster.get(jersey) if roster else None
        if actor is None:
            continue

        if description in _GOAL_DESCRIPTIONS:
            actor.goals += 1
        elif description in _MISS_DESCRIPTIONS:
            actor.misses += 1
        elif description == _SAVE_DESCRIPTION:
            actor.misses += 1
            saved_by_name = _event_detail_field(event, "saved by")
            goalkeeper = name_to_player.get(saved_by_name.strip()) if saved_by_name else None
            if goalkeeper:
                goalkeeper.saves += 1


def _assign_goals_conceded(
    home_players: dict[str, ScrapedPlayerBoxScore],
    away_players: dict[str, ScrapedPlayerBoxScore],
    home_score: int,
    away_score: int,
) -> None:
    """v1 approximation: credit/debit the player with the most saves per team
    (proxy for the starting goalkeeper) with the opponent's full score."""
    if home_players:
        gk = max(home_players.values(), key=lambda p: p.saves)
        if gk.saves > 0:
            gk.goals_conceded = away_score
    if away_players:
        gk = max(away_players.values(), key=lambda p: p.saves)
        if gk.saves > 0:
            gk.goals_conceded = home_score


def parse_match_page(html: str) -> ScrapedMatchBoxScore:
    soup = BeautifulSoup(html, "lxml")

    competition_root = soup.select_one(".tw_full_match[tw-competition-id]")
    external_competition_id = int(competition_root["tw-competition-id"])
    external_match_id = int(competition_root["tw-match-id"])

    home_logo_img = soup.find(attrs={"tw-data": "hometeamlogo"}).find("img")
    away_logo_img = soup.find(attrs={"tw-data": "awayteamlogo"}).find("img")
    home_id_name = _extract_id_name(home_logo_img.get("onclick"))
    away_id_name = _extract_id_name(away_logo_img.get("onclick"))

    home_short = _text(soup.find(attrs={"tw-data": "hometeamname_short"}))
    away_short = _text(soup.find(attrs={"tw-data": "awayteamname_short"}))

    home_team = ScrapedTeam(home_id_name[0], home_id_name[1], home_short, "HOME")
    away_team = ScrapedTeam(away_id_name[0], away_id_name[1], away_short, "AWAY")

    home_score = _int_text(soup.find(attrs={"tw-data": "hometeamgoals"}))
    away_score = _int_text(soup.find(attrs={"tw-data": "awayteamgoals"}))
    status = _text(soup.find(attrs={"tw-data": "status"}))

    home_players: dict[str, ScrapedPlayerBoxScore] = {}
    away_players: dict[str, ScrapedPlayerBoxScore] = {}
    for section_id, target in (
        ("#homePlayers", home_players),
        ("#homeGoalkeepers", home_players),
        ("#awayPlayers", away_players),
        ("#awayGoalkeepers", away_players),
    ):
        section = soup.select_one(section_id)
        if section:
            side = "HOME" if section_id.startswith("#home") else "AWAY"
            target.update(_parse_roster_section(section, side))

    _apply_play_by_play(soup, home_players, away_players, home_short, away_short)
    _assign_goals_conceded(home_players, away_players, home_score, away_score)

    return ScrapedMatchBoxScore(
        external_match_id=external_match_id,
        external_competition_id=external_competition_id,
        home_team=home_team,
        away_team=away_team,
        home_score=home_score,
        away_score=away_score,
        status=status,
        players=[*home_players.values(), *away_players.values()],
    )
