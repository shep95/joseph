"""query prioritization.

every candidate query gets a deterministic score so the engine can rank the search space
and execute only the most promising subset:

    score = identity_relevance + specificity + source_quality + novelty - noise

no query is "elite" because it has many operators; it scores high because it targets a
specific information hypothesis with multiple independently meaningful constraints.
"""

from __future__ import annotations

from dataclasses import dataclass

from .grammar import Query, TermKind

# tiered source quality for site:-scoped queries. higher tier -> stronger evidence.
_SOURCE_TIER: dict[str, float] = {
    "github.com": 3.0,
    "gitlab.com": 3.0,
    "linkedin.com": 3.0,
    "crunchbase.com": 2.5,
    "wellfound.com": 2.5,
    "keybase.io": 2.5,
    "stackoverflow.com": 2.0,
    "medium.com": 1.5,
    "reddit.com": 1.5,
    "x.com": 1.5,
    "twitter.com": 1.5,
    "youtube.com": 1.0,
    "instagram.com": 1.0,
    "facebook.com": 1.0,
}

# strong anchor kinds that genuinely constrain identity
_ANCHOR_BONUS: dict[TermKind, float] = {
    TermKind.PHRASE: 1.2,
    TermKind.FILETYPE: 0.8,
    TermKind.SITE: 0.6,
    TermKind.INTITLE: 0.7,
    TermKind.INURL: 0.6,
    TermKind.INTEXT: 0.4,
    TermKind.BEFORE: 0.3,
    TermKind.AFTER: 0.3,
    TermKind.EXCLUDE: 0.2,
    TermKind.OR_GROUP: 0.5,
    TermKind.WORD: 0.15,
}


@dataclass(frozen=True)
class ScoredQuery:
    query: Query
    score: float
    reasons: tuple[str, ...]


def score_query(q: Query) -> ScoredQuery:
    reasons: list[str] = []
    identity_relevance = 0.0
    specificity = 0.0
    source_quality = 0.0
    noise = 0.0

    phrase_terms = 0
    word_only = 0
    for t in q.terms:
        specificity += _ANCHOR_BONUS.get(t.kind, 0.1)
        if t.kind is TermKind.PHRASE:
            phrase_terms += 1
            identity_relevance += 1.0
        if t.kind is TermKind.WORD:
            word_only += 1
        if t.kind is TermKind.SITE:
            source_quality += _SOURCE_TIER.get(t.value.lower(), 0.8)
        if t.kind in {TermKind.INURL, TermKind.INTITLE}:
            identity_relevance += 0.5

    # multiple independent anchors together are the strongest signal
    if phrase_terms >= 2:
        identity_relevance += 1.5
        reasons.append("multiple exact anchors")

    # a single bare common word is noisy
    if word_only and phrase_terms == 0 and q.constraint_count() <= 1:
        noise += 1.5
        reasons.append("under-constrained")

    if source_quality:
        reasons.append("targets a tiered source")
    if any(t.kind is TermKind.FILETYPE for t in q.terms):
        reasons.append("document discovery")
    if any(t.kind in {TermKind.BEFORE, TermKind.AFTER} for t in q.terms):
        reasons.append("temporal constraint")

    score = round(identity_relevance + specificity + source_quality - noise, 4)
    return ScoredQuery(query=q, score=score, reasons=tuple(reasons))


def prioritize(queries: list[Query]) -> list[ScoredQuery]:
    """score and rank the family. stable secondary sort by signature keeps it deterministic."""
    scored = [score_query(q) for q in queries]
    scored.sort(key=lambda s: (-s.score, s.query.signature()))
    return scored
