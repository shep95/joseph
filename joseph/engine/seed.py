"""identity seed model -> the structured investigation objective.

the seed is the single source of truth for what the investigator knows going in.
every downstream stage reads from it. it is deterministic and hashable so an entire
investigation can be fingerprinted for reproducible reports.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field, asdict


# documented, well-known surfaces mapped to their canonical domains. used by the
# generator to emit site:-scoped queries. this is public knowledge, not a target list.
KNOWN_SURFACES: dict[str, str] = {
    "github": "github.com",
    "gitlab": "gitlab.com",
    "linkedin": "linkedin.com",
    "x": "x.com",
    "twitter": "twitter.com",
    "reddit": "reddit.com",
    "instagram": "instagram.com",
    "facebook": "facebook.com",
    "youtube": "youtube.com",
    "medium": "medium.com",
    "keybase": "keybase.io",
    "stackoverflow": "stackoverflow.com",
    "about": "about.me",
    "angellist": "wellfound.com",
    "crunchbase": "crunchbase.com",
}

DEFAULT_FILETYPES: tuple[str, ...] = ("pdf", "doc", "docx", "ppt", "pptx", "xls", "xlsx", "txt")

_DATE_RE = re.compile(r"^\d{4}(-\d{2}(-\d{2})?)?$")


def _clean_list(values) -> list[str]:
    """normalize a comma/newline separated string or iterable into a stable, unique list."""
    if values is None:
        return []
    if isinstance(values, str):
        parts = re.split(r"[,\n;]+", values)
    else:
        parts = list(values)
    out: list[str] = []
    seen: set[str] = set()
    for p in parts:
        token = str(p).strip()
        if not token:
            continue
        key = token.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(token)
    return out


@dataclass(frozen=True)
class IdentitySeed:
    """what the investigator knows about the subject at the start."""

    name: str = ""
    usernames: list[str] = field(default_factory=list)
    emails: list[str] = field(default_factory=list)
    organizations: list[str] = field(default_factory=list)
    locations: list[str] = field(default_factory=list)
    occupations: list[str] = field(default_factory=list)
    domains: list[str] = field(default_factory=list)
    phones: list[str] = field(default_factory=list)
    keywords: list[str] = field(default_factory=list)
    sites: list[str] = field(default_factory=list)  # explicit site: targets by name or domain
    filetypes: list[str] = field(default_factory=lambda: list(DEFAULT_FILETYPES))
    exclusions: list[str] = field(default_factory=list)
    since: str = ""  # YYYY or YYYY-MM or YYYY-MM-DD
    until: str = ""

    @classmethod
    def build(cls, **kwargs) -> "IdentitySeed":
        """construct a normalized seed from loose keyword arguments."""
        since = str(kwargs.get("since", "") or "").strip()
        until = str(kwargs.get("until", "") or "").strip()
        return cls(
            name=str(kwargs.get("name", "") or "").strip(),
            usernames=_clean_list(kwargs.get("usernames")),
            emails=_clean_list(kwargs.get("emails")),
            organizations=_clean_list(kwargs.get("organizations")),
            locations=_clean_list(kwargs.get("locations")),
            occupations=_clean_list(kwargs.get("occupations")),
            domains=_clean_list(kwargs.get("domains")),
            phones=_clean_list(kwargs.get("phones")),
            keywords=_clean_list(kwargs.get("keywords")),
            sites=_clean_list(kwargs.get("sites")),
            filetypes=_clean_list(kwargs.get("filetypes")) or list(DEFAULT_FILETYPES),
            exclusions=_clean_list(kwargs.get("exclusions")),
            since=since if _DATE_RE.match(since) else "",
            until=until if _DATE_RE.match(until) else "",
        )

    @property
    def is_empty(self) -> bool:
        return not any(
            [
                self.name,
                self.usernames,
                self.emails,
                self.organizations,
                self.locations,
                self.occupations,
                self.domains,
                self.phones,
                self.keywords,
            ]
        )

    def anchors(self) -> list[str]:
        """the strong identifiers that meaningfully constrain a query."""
        out: list[str] = []
        if self.name:
            out.append(self.name)
        out.extend(self.usernames)
        out.extend(self.emails)
        out.extend(self.domains)
        return out

    @staticmethod
    def _normalize_date(value: str, *, end: bool) -> str:
        """expand a partial YYYY / YYYY-MM date into a full YYYY-MM-DD for before:/after:.

        end=True fills toward the end of the period (december / 28th) so a range is
        inclusive; end=False fills toward the start.
        """
        value = (value or "").strip()
        if not _DATE_RE.match(value):
            return ""
        parts = value.split("-")
        if len(parts) == 1:
            return f"{parts[0]}-12-28" if end else f"{parts[0]}-01-01"
        if len(parts) == 2:
            return f"{parts[0]}-{parts[1]}-28" if end else f"{parts[0]}-{parts[1]}-01"
        return value

    def after_value(self) -> str:
        return self._normalize_date(self.since, end=False)

    def before_value(self) -> str:
        return self._normalize_date(self.until, end=True)

    def to_dict(self) -> dict:
        return asdict(self)

    def fingerprint(self) -> str:
        payload = json.dumps(self.to_dict(), sort_keys=True, ensure_ascii=False)
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]
