"""relevance scoring via deterministic tf-idf over result text.

builds a tiny in-memory corpus from result titles + snippets, computes tf-idf weighted
overlap between each result and the seed's anchor terms, and blends that with rank
position and corroboration count. pure python, no external nlp.
"""

from __future__ import annotations

import math
import re
from collections import Counter

from .normalize import Result
from .seed import IdentitySeed

_TOKEN_RE = re.compile(r"[a-z0-9]+")
_STOP = {
    "the", "a", "an", "and", "or", "of", "to", "in", "on", "for", "at", "by", "with",
    "is", "are", "was", "were", "be", "as", "from", "that", "this", "it", "his", "her",
}


def _tokens(text: str) -> list[str]:
    return [t for t in _TOKEN_RE.findall(text.lower()) if t not in _STOP and len(t) > 1]


def _seed_terms(seed: IdentitySeed) -> set[str]:
    bag: list[str] = []
    for v in [seed.name, *seed.usernames, *seed.emails, *seed.organizations,
              *seed.locations, *seed.occupations, *seed.domains, *seed.keywords]:
        bag.extend(_tokens(v))
    return set(bag)


def score_relevance(seed: IdentitySeed, results: list[Result]) -> list[Result]:
    if not results:
        return results

    docs = [_tokens(f"{r.title} {r.snippet}") for r in results]
    n = len(docs)

    # document frequency
    df: Counter[str] = Counter()
    for doc in docs:
        for term in set(doc):
            df[term] += 1

    def idf(term: str) -> float:
        return math.log((1 + n) / (1 + df.get(term, 0))) + 1.0

    seed_terms = _seed_terms(seed)

    for r, doc in zip(results, docs):
        if not doc:
            r.relevance = 0.0
            continue
        tf = Counter(doc)
        length = len(doc)
        # tf-idf mass concentrated on terms that match the seed
        overlap = 0.0
        for term in seed_terms:
            if term in tf:
                overlap += (tf[term] / length) * idf(term)
        # domain-in-anchor bonus (e.g. seed domain appears in the url domain)
        domain_bonus = 0.0
        for d in seed.domains:
            if d.lower() in r.domain:
                domain_bonus += 0.5
        rank_factor = 1.0 / math.sqrt(r.best_rank) if r.best_rank else 0.3
        corroboration = 0.15 * max(0, r.corroboration - 1)
        r.relevance = round(overlap * 2.0 + domain_bonus + rank_factor + corroboration, 4)

    results.sort(key=lambda x: (-x.relevance, x.best_rank, x.canonical))
    return results
