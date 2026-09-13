"""entity extraction.

pulls candidate identifiers out of result urls, titles, and snippets using regex only:
emails, usernames/handles, domains, and social-profile handles keyed by surface. these
become new search pivots and graph nodes. no inference about the person is made here,
only extraction of strings that are present in public text.
"""

from __future__ import annotations

import re
import urllib.parse
from dataclasses import dataclass

from .normalize import Result
from .seed import KNOWN_SURFACES

_EMAIL_RE = re.compile(r"\b[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}\b")
_HANDLE_RE = re.compile(r"(?<![\w@])@([A-Za-z0-9_]{3,30})\b")
_DOMAIN_RE = re.compile(r"\b([a-z0-9](?:[a-z0-9\-]{0,61}[a-z0-9])?(?:\.[a-z]{2,})+)\b", re.IGNORECASE)

# reverse map domain -> surface name for profile detection
_DOMAIN_TO_SURFACE = {d: s for s, d in KNOWN_SURFACES.items()}


@dataclass(frozen=True)
class Entity:
    kind: str        # email | handle | domain | profile | username
    value: str
    surface: str = ""   # for profile: the platform
    source_url: str = ""


def _profile_from_url(url: str) -> Entity | None:
    """detect a social profile and its handle from a known-surface url path."""
    try:
        parts = urllib.parse.urlsplit(url)
    except ValueError:
        return None
    host = parts.netloc.lower()
    if host.startswith("www."):
        host = host[4:]
    surface = _DOMAIN_TO_SURFACE.get(host)
    if not surface:
        return None
    segments = [s for s in parts.path.split("/") if s]
    if not segments:
        return None
    # linkedin uses /in/<handle>; most others use /<handle>
    handle = segments[1] if (surface == "linkedin" and segments[0] == "in" and len(segments) > 1) else segments[0]
    handle = handle.strip()
    if not handle or handle in {"in", "user", "channel", "watch", "search"}:
        return None
    return Entity(kind="profile", value=handle, surface=surface, source_url=url)


def extract(results: list[Result]) -> list[Entity]:
    found: dict[tuple[str, str, str], Entity] = {}

    def add(e: Entity) -> None:
        key = (e.kind, e.value.lower(), e.surface.lower())
        if key not in found:
            found[key] = e

    for r in results:
        text = f"{r.title} {r.snippet}"
        for m in _EMAIL_RE.findall(text):
            add(Entity(kind="email", value=m, source_url=r.canonical))
        for h in _HANDLE_RE.findall(text):
            add(Entity(kind="handle", value=h, source_url=r.canonical))
        prof = _profile_from_url(r.url)
        if prof:
            add(prof)
        # domains from snippet text (excluding the result's own host, already known)
        for d in _DOMAIN_RE.findall(text):
            dl = d.lower()
            if dl == r.domain or dl.endswith(".png") or dl.endswith(".jpg"):
                continue
            add(Entity(kind="domain", value=dl, source_url=r.canonical))

    # deterministic order
    return sorted(found.values(), key=lambda e: (e.kind, e.surface, e.value.lower()))
