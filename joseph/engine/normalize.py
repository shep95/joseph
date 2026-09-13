"""result normalization + deduplication.

every raw result is normalized into a stable record with a canonical url, extracted
domain/path, and provenance (which query and provider produced it). duplicates are
folded by canonical url while preserving every query origin that surfaced them, which is
itself corroboration signal.
"""

from __future__ import annotations

import urllib.parse
from dataclasses import dataclass, field

from .providers import RawResult

_TRACKING_PARAMS = {
    "utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content",
    "gclid", "fbclid", "ref", "ref_src", "spm", "mc_cid", "mc_eid",
}


def canonical_url(url: str) -> str:
    """produce a stable canonical form: lowercase scheme/host, drop tracking params,
    strip fragments and trailing slashes."""
    try:
        p = urllib.parse.urlsplit(url.strip())
    except ValueError:
        return url.strip()
    scheme = (p.scheme or "https").lower()
    netloc = p.netloc.lower()
    if netloc.startswith("www."):
        netloc = netloc[4:]
    query_pairs = [
        (k, v)
        for k, v in urllib.parse.parse_qsl(p.query, keep_blank_values=False)
        if k.lower() not in _TRACKING_PARAMS
    ]
    query_pairs.sort()
    query = urllib.parse.urlencode(query_pairs)
    path = p.path.rstrip("/") or "/"
    return urllib.parse.urlunsplit((scheme, netloc, path, query, ""))


def domain_of(url: str) -> str:
    try:
        netloc = urllib.parse.urlsplit(url).netloc.lower()
    except ValueError:
        return ""
    return netloc[4:] if netloc.startswith("www.") else netloc


def path_of(url: str) -> str:
    try:
        return urllib.parse.urlsplit(url).path or "/"
    except ValueError:
        return "/"


@dataclass
class Result:
    canonical: str
    url: str
    domain: str
    path: str
    title: str
    snippet: str
    providers: set[str] = field(default_factory=set)
    strategies: set[str] = field(default_factory=set)
    queries: set[str] = field(default_factory=set)
    best_rank: int = 999
    relevance: float = 0.0

    @property
    def corroboration(self) -> int:
        """number of distinct query strategies that independently surfaced this url."""
        return len(self.strategies)


def normalize(raws: list[RawResult]) -> list[Result]:
    by_canon: dict[str, Result] = {}
    for r in raws:
        canon = canonical_url(r.url)
        if not canon:
            continue
        rec = by_canon.get(canon)
        if rec is None:
            rec = Result(
                canonical=canon,
                url=r.url,
                domain=domain_of(r.url),
                path=path_of(r.url),
                title=r.title,
                snippet=r.snippet,
                best_rank=r.rank,
            )
            by_canon[canon] = rec
        rec.providers.add(r.provider)
        rec.strategies.add(r.strategy)
        rec.queries.add(r.query)
        rec.best_rank = min(rec.best_rank, r.rank)
        # prefer the longest snippet/title we have seen (more context)
        if len(r.snippet) > len(rec.snippet):
            rec.snippet = r.snippet
        if len(r.title) > len(rec.title):
            rec.title = r.title
    # stable ordering by (best_rank, canonical) for determinism
    return sorted(by_canon.values(), key=lambda x: (x.best_rank, x.canonical))
