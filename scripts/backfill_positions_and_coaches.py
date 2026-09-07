"""
Backfill players.position and Coach.name -- versioned and idempotent.

An independent review (Codex, problemV17) correctly pointed out that the
original position/coach backfill was done via throwaway one-off scripts,
never committed -- `git diff --stat` between those commits showed only
documentation changes, so a fresh checkout + migration could not reproduce
the 348 positioned players or the 13 real coach names at all. This script
is the actual reproducible import: it reads the versioned source file
(scripts/data/rosteri2.0.txt, the user's own manually-reviewed roster
export, committed unmodified) and applies the same coach-name research
already documented in CONTINUE.md.

Matching strategy: by (real_club, normalized name) -- NOT by a hardcoded
local UUID, which would not exist in a fresh database. See "Duplicate
identity handling" below for the one place external_id is also used.

Safe to re-run: every write is a plain UPDATE keyed by (real_club, name) or
(real_club, external_id) for the duplicate-pair correction below, so running
this twice produces the same end state, not duplicate or compounding
changes. It also does not touch any player/coach the source file has no
data for (e.g. the two "- -" unresolved-name rows -- see CONTINUE.md).

## Duplicate identity handling (problemV17's other finding)

24 (club, name) pairs have TWO distinct Player rows sharing one name: one
WITH a stable `external_id` (a normally-scraped field player -- see
scraper/parsers/match_page.py) and one WITHOUT (matching the documented,
independently-verified scraper behavior that goalkeepers never get a
stable id -- see scraper/player_resolver.py's docstring). The original
backfill applied one file-given position to BOTH rows, which an independent
review (Codex, problemV17) correctly flagged: it doesn't prove they're the
same person, and risks marking a real field player as a goalkeeper (or vice
versa) just because they share a name.

This script instead treats the row WITHOUT an external_id as the
goalkeeper unconditionally (grounded in the scraper's own documented
mechanics, not a guess about these specific people), and only applies the
source file's given position to the WITH-external_id row when that value
isn't itself "GK" -- a field player is definitionally not the goalkeeper in
this scheme, so if the file's only data point for a shared name was "GK",
the field-player row is left with no position rather than a guessed one.
This is NOT a merge or identity resolution -- both rows remain distinct
players in the catalog, as problemV17 also cautioned against doing anything
riskier than that without real identity verification (external_id, match
history, or an actual source confirming they're the same or different
people).
"""

import asyncio
import re
import sys
import unicodedata
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(ROOT), str(ROOT / "backend")]

from sqlalchemy import select, update  # noqa: E402
from sqlalchemy.ext.asyncio import AsyncSession  # noqa: E402

from app.core.db import engine  # noqa: E402
from db.models import Coach, Player  # noqa: E402

ROSTER_FILE = Path(__file__).parent / "data" / "rosteri2.0.txt"

# Coach names confirmed by web research (not present in the source roster
# file, which only has 7). Sourcing/confidence for each is in CONTINUE.md's
# "problemV16.md" and coach-backfill sections -- not repeated here to avoid
# two copies of the same reasoning drifting apart; this dict is the applied
# RESULT of that research, not where to read the "why".
RESEARCHED_COACH_NAMES = {
    "Jadran m:tel HN": "Petar Radanović",
    "Budućnost One": "Aleksandar Aleksić",
    "Primorac": "Anastasios (Sakis) Kehajas",
    "Budva BDR": "Miloš Popović",
    "Vojvodina": "Darko Bilić",
    "Zemun": "Andrija Vasiljević",
}

# Fictional placeholders, per explicit user request, for the 4 clubs where a
# thorough search found no verifiable real coach (see CONTINUE.md). Clearly
# marked, not sourced from anything -- swap out the moment a real name
# surfaces.
MOCK_COACH_NAMES = {
    "Crvena Zvezda": "Dušan Marković (mock)",
    "Cattaro": "Ivan Radulović (mock)",
    "Nais Niš": "Vladimir Antić (mock)",
    "Stari Grad": "Dejan Simić (mock)",
}

# Cattaro had ZERO position data in the source file (unlike every other
# club) -- this is a hand-assigned, explicitly-fictional placeholder
# distribution chosen only to mirror the other 16 clubs' position mix
# (roughly OT 57%, GK 16%, CB 16%, CF 10%), per explicit user request. Not
# researched, not real -- see Player.position_verified, set to False for
# every name below.
CATTARO_POSITIONS = {
    "Andrej Radic": "GK",
    "Andrija Bjelica": "OT",
    "Andrija Roganovic": "CB",
    "Bruno Perov": "OT",
    "Dragan Marković": "GK",
    "Dušan Milaš": "OT",
    "Ivan Marković": "OT",
    "Lazar Janjusevic": "CB",
    "Ljubomir Kovačić": "CF",
    "Luka Ivanovic": "OT",
    "Martin Petrovic": "OT",
    "Milan Nikaljevic": "GK",
    "Milija Mandić": "OT",
    "Nikola Jovancevic": "CB",
    "Relja Vukanić": "OT",
    "Svetozar Vodovar": "CF",
    "Tomo Vičević": "OT",
    "Uglješa Vukasović": "OT",
    "Vanja Golubović": "CB",
    "Vanja Gopčević": "CF",
    "Veljko Vujovic": "OT",
}


def normalize(name: str) -> str:
    name = unicodedata.normalize("NFKD", name)
    name = "".join(c for c in name if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", name.strip().lower())


def _parse_coach_name(coach_line: str) -> str | None:
    match = re.search(r"trener TBD\s*-?\s*(.+)$", coach_line)
    if match and match.group(1).strip():
        return match.group(1).strip()
    return None


def _parse_player_line(line: str) -> tuple[str, str | None]:
    line = line.strip()
    if line == "- -":
        return ("__UNKNOWN_GK__", None)
    match = re.match(r"^(.+?)\s*-\s*([A-Za-z]+)\??\s*$", line)
    if match:
        return (match.group(1).strip(), match.group(2).strip().upper())
    match = re.match(r"^(.+?)\s{2,}([A-Za-z]+)\s*$", line)
    if match:
        return (match.group(1).strip(), match.group(2).strip().upper())
    return (line, None)


def parse_roster_file() -> list[dict]:
    content = ROSTER_FILE.read_text(encoding="utf-8")
    content = re.split(r"=+", content, maxsplit=1)[1]
    blocks = [b for b in content.strip("\n").split("\n\n") if b.strip()]

    teams = []
    for block in blocks:
        lines = [line for line in block.split("\n") if line.strip()]
        team_name = lines[0].strip()
        coach_name = _parse_coach_name(lines[1].strip())
        players = [_parse_player_line(line) for line in lines[2:]]
        teams.append({"team": team_name, "coach": coach_name, "players": players})
    return teams


async def backfill(session: AsyncSession, dry_run: bool) -> None:
    teams = parse_roster_file()
    total_position_updates = 0
    total_unresolved = 0

    for team in teams:
        club = team["team"]

        if club == "Cattaro":
            given_position_by_name = {normalize(k): v for k, v in CATTARO_POSITIONS.items()}
            position_verified = False
        else:
            given_position_by_name = {}
            for name, position in team["players"]:
                if name == "__UNKNOWN_GK__" or not position:
                    continue
                given_position_by_name.setdefault(normalize(name), position.rstrip("?"))
            position_verified = True

        db_rows = (
            await session.execute(
                select(Player.id, Player.name, Player.external_id).where(Player.real_club == club)
            )
        ).all()
        rows_by_normalized_name: dict[str, list] = defaultdict(list)
        for row in db_rows:
            rows_by_normalized_name[normalize(row.name)].append(row)

        for normalized_name, rows in rows_by_normalized_name.items():
            given = given_position_by_name.get(normalized_name)

            if len(rows) == 1:
                if given is None:
                    total_unresolved += 1
                    continue
                if not dry_run:
                    await session.execute(
                        update(Player)
                        .where(Player.id == rows[0].id)
                        .values(position=given, position_verified=position_verified)
                    )
                total_position_updates += 1
                continue

            # Duplicate-name pair: see this module's docstring. The row
            # without an external_id is treated as the goalkeeper
            # unconditionally; the source file's position only applies to
            # the row WITH an external_id, and only if it isn't "GK".
            without_ext = [r for r in rows if r.external_id is None]
            with_ext = [r for r in rows if r.external_id is not None]
            if len(rows) != 2 or len(without_ext) != 1 or len(with_ext) != 1:
                # Not the documented 1-with/1-without-external_id shape --
                # don't guess, leave untouched, and surface it.
                print(f"  [skip: unexpected duplicate shape] {club} / {normalized_name}: {rows}")
                continue

            if not dry_run:
                await session.execute(
                    update(Player)
                    .where(Player.id == without_ext[0].id)
                    .values(position="GK", position_verified=position_verified)
                )
            total_position_updates += 1

            field_position = given if given and given != "GK" else None
            if not dry_run:
                await session.execute(
                    update(Player)
                    .where(Player.id == with_ext[0].id)
                    .values(position=field_position, position_verified=position_verified)
                )
            if field_position is not None:
                total_position_updates += 1
            else:
                total_unresolved += 1

        coach_name = team["coach"] or RESEARCHED_COACH_NAMES.get(club) or MOCK_COACH_NAMES.get(club)
        if coach_name and not dry_run:
            await session.execute(update(Coach).where(Coach.real_club == club).values(name=coach_name))

    if not dry_run:
        await session.commit()

    print(f"{'[DRY RUN] ' if dry_run else ''}Position updates: {total_position_updates}")
    print(f"{'[DRY RUN] ' if dry_run else ''}Left without a position (no data / GK-only duplicate): {total_unresolved}")


async def main() -> None:
    dry_run = "--dry-run" in sys.argv
    async with AsyncSession(engine) as session:
        await backfill(session, dry_run=dry_run)


if __name__ == "__main__":
    asyncio.run(main())
