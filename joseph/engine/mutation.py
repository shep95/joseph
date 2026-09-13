"""query mutation engine.

applies the pattern-forge synthesis grammar to an existing query family to explore the
query space by structure rather than by adding random operators. every mutation is a
pure, deterministic transformation of typed terms.

    SPECIALIZE   -> add a constraint (a documented lens or filetype)
    GENERALIZE   -> drop the weakest constraint
    COMBINE      -> merge two compatible queries
    SWAP_DOMAIN  -> retarget a site: term to another known surface
    INVERT       -> turn a positive anchor into a negative-space probe

mutation never invents identifiers that are not already present in the family, so it can
never fabricate a subject attribute.
"""

from __future__ import annotations

from .grammar import Query, Term, TermKind
from .seed import IdentitySeed, KNOWN_SURFACES


def _has_kind(q: Query, kind: TermKind) -> bool:
    return any(t.kind is kind for t in q.terms)


def specialize(q: Query, seed: IdentitySeed) -> list[Query]:
    """add a documented filetype constraint to a query that has none."""
    out: list[Query] = []
    if _has_kind(q, TermKind.FILETYPE):
        return out
    for ft in seed.filetypes[:3]:
        terms = q.terms + (Term(TermKind.FILETYPE, ft),)
        out.append(Query(strategy=f"{q.strategy}+specialize:{ft}", terms=terms, objective=q.objective))
    return out


def swap_domain(q: Query, seed: IdentitySeed) -> list[Query]:
    """retarget a site: constraint to other known surfaces (identifier-preserving)."""
    out: list[Query] = []
    site_idx = next((i for i, t in enumerate(q.terms) if t.kind is TermKind.SITE), None)
    if site_idx is None:
        return out
    current = q.terms[site_idx].value.lower()
    for surface, domain in KNOWN_SURFACES.items():
        if domain == current:
            continue
        terms = list(q.terms)
        terms[site_idx] = Term(TermKind.SITE, domain)
        out.append(Query(strategy=f"{q.strategy}+swap:{surface}", terms=tuple(terms), objective=q.objective))
    return out


def generalize(q: Query) -> list[Query]:
    """drop the last non-anchor constraint to broaden recall."""
    if len(q.terms) <= 1:
        return []
    # keep phrase/word anchors; prefer dropping a lens/exclude
    droppable = [i for i, t in enumerate(q.terms) if t.kind in {TermKind.EXCLUDE, TermKind.INTEXT, TermKind.INANCHOR}]
    if not droppable:
        return []
    idx = droppable[-1]
    terms = tuple(t for i, t in enumerate(q.terms) if i != idx)
    return [Query(strategy=f"{q.strategy}+generalize", terms=terms, objective=q.objective)]


def mutate_family(seed: IdentitySeed, queries: list[Query], *, max_swaps: int = 0) -> list[Query]:
    """expand a family with deterministic mutations.

    swap_domain is intentionally gated (max_swaps) because it is combinatorially large;
    the generator already emits primary site: queries for known surfaces.
    """
    extra: list[Query] = []
    for q in queries:
        extra.extend(specialize(q, seed))
        extra.extend(generalize(q))
    if max_swaps:
        swapped = 0
        for q in queries:
            if swapped >= max_swaps:
                break
            s = swap_domain(q, seed)
            if s:
                extra.extend(s)
                swapped += 1
    return _dedupe(queries + extra)


def _dedupe(queries: list[Query]) -> list[Query]:
    seen: set[str] = set()
    out: list[Query] = []
    for q in queries:
        sig = q.signature()
        if sig in seen:
            continue
        seen.add(sig)
        out.append(q)
    return out
