"""
Parses a rendered totalwaterpolo.com competition page into its full fixture list.

Like the match page (see match_page.py), this must be called on the fully
rendered DOM (headless browser), not a raw HTTP response — confirmed against a
real saved competition page ("VRL Prva Liga 2025/26"): the same plugin
architecture applies.

DOM contract (verified against the real saved page):

- `.tw_preload_competition[tw-competition-id]` (or any of several other
  elements sharing the same attribute) — the competition id.
- `.tw_competition_round[tw_round_id]` — one per round ("Termin N" in the
  sampled page; this is the site's own round label, used directly as the
  matchday identifier — there is no separate numeric round index exposed).
  Every round's markup is fully populated in the DOM even when visually
  hidden behind pagination (`tw-hidden` class) — no per-round click/AJAX
  needed to reveal it.
- Within a round, `.tw_match_basic[tw-match-id]` — one per fixture:
    - `[tw-data="hometeamlogo"] img[onclick]` / `[tw-data="awayteamlogo"]
      img[onclick]` — `OpenTeamPage(<external_team_id>, '<name>')`, same
      pattern as the match page.
    - `[tw-data="hometeamgoals"]` / `[tw-data="awayteamgoals"]` — final score.
    - `[tw-data="matchdetailslink"] a[href]` — canonical match URL, whose
      trailing path segment is the same external_match_id already present on
      `tw-match-id`.

Known gap: the sampled page's rounds were all already played (a 12-team
season near/at completion), so no genuinely upcoming (unscored) fixture was
available to verify against. `home_score`/`away_score` are treated as None
(status UPCOMING) whenever the goals cell isn't a plain integer — this is a
reasonable assumption, not yet verified against a real upcoming fixture. Flag
if a live scrape produces UPCOMING matches that don't look right.

Also unresolved: no kickoff date/time is exposed in this fixture-list view
(only the round label). Per-match kickoff_at, if needed for `matchdays.deadline`,
has to come from the individual match page instead (`[tw-data="matchdetails"]`,
e.g. "18/02/2026 19:00" — seen on the match page but not yet wired into
match_page.py's parser output).
"""

from dataclasses import dataclass

from bs4 import BeautifulSoup

from scraper.parsers.common import extract_id_name, optional_int, text


@dataclass
class ScrapedTeamRef:
    external_team_id: int
    name: str


@dataclass
class ScrapedFixture:
    external_match_id: int
    round_label: str
    home_team: ScrapedTeamRef
    away_team: ScrapedTeamRef
    home_score: int | None
    away_score: int | None
    status: str  # "FINISHED" | "UPCOMING"
    match_url: str | None


def parse_schedule_page(html: str) -> tuple[int, list[ScrapedFixture]]:
    """Returns (external_competition_id, fixtures) for every round on the page."""
    soup = BeautifulSoup(html, "lxml")

    competition_el = soup.select_one("[tw-competition-id]")
    external_competition_id = int(competition_el["tw-competition-id"])

    fixtures: list[ScrapedFixture] = []
    for round_div in soup.select(".tw_competition_round[tw_round_id]"):
        round_label = round_div["tw_round_id"]
        for match_row in round_div.select(".tw_match_basic[tw-match-id]"):
            external_match_id = int(match_row["tw-match-id"])

            home_img = match_row.find(attrs={"tw-data": "hometeamlogo"}).find("img")
            away_img = match_row.find(attrs={"tw-data": "awayteamlogo"}).find("img")
            home_id_name = extract_id_name(home_img.get("onclick"))
            away_id_name = extract_id_name(away_img.get("onclick"))

            home_score = optional_int(match_row.find(attrs={"tw-data": "hometeamgoals"}))
            away_score = optional_int(match_row.find(attrs={"tw-data": "awayteamgoals"}))

            link_wrap = match_row.find(attrs={"tw-data": "matchdetailslink"})
            link = link_wrap.find("a") if link_wrap else None
            match_url = link.get("href") if link else None

            fixtures.append(
                ScrapedFixture(
                    external_match_id=external_match_id,
                    round_label=round_label,
                    home_team=ScrapedTeamRef(*home_id_name),
                    away_team=ScrapedTeamRef(*away_id_name),
                    home_score=home_score,
                    away_score=away_score,
                    status="FINISHED" if home_score is not None and away_score is not None else "UPCOMING",
                    match_url=match_url,
                )
            )

    return external_competition_id, fixtures
