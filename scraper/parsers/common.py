"""Shared helpers used by both schedule_page.py and match_page.py."""

import re

from bs4.element import Tag

_ONCLICK_ID_NAME_RE = re.compile(r"Open(?:Player|Team)Page\((\d+),\s*'([^']*)'\)")


def extract_id_name(onclick: str | None) -> tuple[int, str] | None:
    """Pull (external_id, name) out of an `onclick="Open{Player,Team}Page(id, 'name')"` attribute."""
    if not onclick:
        return None
    m = _ONCLICK_ID_NAME_RE.search(onclick)
    return (int(m.group(1)), m.group(2)) if m else None


def text(tag: Tag | None) -> str:
    return tag.get_text(strip=True) if tag else ""


def optional_int(tag: Tag | None) -> int | None:
    t = text(tag)
    return int(t) if t.lstrip("-").isdigit() else None
