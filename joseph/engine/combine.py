"""combine dorks together.

two ways to combine:

    1. parse raw dork text the user types (with operators) into the typed grammar, so their
       own dorks run through the same pipeline (scoring, live collection, link verify).
    2. AND-merge several queries into one compound dork (stack site + filetype + phrase +
       intext, etc.) -> higher-specificity "combined" dorks instead of isolated ones.

parsing maps documented operators back to Term kinds. anything unknown stays a plain
word/phrase, so nothing the user writes is silently dropped from google/bing.
"""

from __future__ import annotations

import re

from .grammar import Query, Term, TermKind

# tokenizer that preserves quotes: op:"quoted", op:bare, "quoted phrase", -term, bare.
_TOKEN_RE = re.compile(r'-?[A-Za-z]+:"[^"]*"|-?[A-Za-z]+:\S+|-?"[^"]*"|-?\S+')

# operator prefix -> term kind (accepts the common bing aliases too)
_OP_MAP: dict[str, TermKind] = {
    "site": TermKind.SITE,
    "filetype": TermKind.FILETYPE,
    "ext": TermKind.FILETYPE,
    "intitle": TermKind.INTITLE,
    "allintitle": TermKind.INTITLE,
    "inurl": TermKind.INURL,
    "allinurl": TermKind.INURL,
    "url": TermKind.INURL,
    "intext": TermKind.INTEXT,
    "inbody": TermKind.INTEXT,
    "inanchor": TermKind.INANCHOR,
    "before": TermKind.BEFORE,
    "after": TermKind.AFTER,
}


def _term_from_token(token: str) -> Term | None:
    token = token.strip()
    if not token:
        return None

    # exclusion: -term or -op:value
    negate = False
    if token.startswith("-") and len(token) > 1:
        negate = True
        token = token[1:]

    quoted = '"' in token
    if ":" in token and not token.startswith('"'):
        op, _, value = token.partition(":")
        kind = _OP_MAP.get(op.lower())
        if kind is not None:
            value = value.strip('"')
            if value:
                if negate:
                    # excluding an operator term -> fall back to excluding the bare value
                    return Term(TermKind.EXCLUDE, value)
                return Term(kind, value)

    token = token.strip('"')
    if not token:
        return None
    if negate:
        return Term(TermKind.EXCLUDE, token)

    # keep OR uppercase as an operator word
    if token == "OR":
        return Term(TermKind.WORD, "OR")
    # a quoted token (even single word) or a multiword token is an exact phrase
    if quoted or any(c.isspace() for c in token):
        return Term(TermKind.PHRASE, token)
    return Term(TermKind.WORD, token)


def parse_dork(line: str, strategy: str = "raw") -> Query:
    """parse a single dork line into a Query, preserving quoted phrases."""
    terms: list[Term] = []
    for tok in _TOKEN_RE.findall(line):
        term = _term_from_token(tok)
        if term is not None:
            terms.append(term)
    return Query(strategy=strategy, terms=tuple(terms), objective="user-supplied dork")


def parse_dorks(text: str) -> list[Query]:
    """parse one dork per line (also splits on ';'). blank lines ignored."""
    if not text:
        return []
    lines: list[str] = []
    for chunk in text.replace(";", "\n").splitlines():
        chunk = chunk.strip()
        if chunk:
            lines.append(chunk)
    out: list[Query] = []
    for i, line in enumerate(lines):
        out.append(parse_dork(line, strategy=f"raw_{i + 1}"))
    return out


def merge(queries: list[Query], strategy: str = "combined") -> Query:
    """AND-merge several queries into one compound dork, de-duplicating identical terms."""
    seen: set[tuple[str, str]] = set()
    terms: list[Term] = []
    for q in queries:
        for t in q.terms:
            key = (t.kind.value, t.value.lower())
            if key in seen:
                continue
            seen.add(key)
            terms.append(t)
    return Query(strategy=strategy, terms=tuple(terms), objective="combined dork (AND of the inputs)")


def combined_family(seed, *, max_queries: int = 20) -> list[Query]:
    """auto-build compound stacked dorks from a seed -> combines anchors with sites,
    filetypes and keywords in a single query rather than emitting them separately."""
    from .seed import IdentitySeed  # local import to avoid cycles

    assert isinstance(seed, IdentitySeed)
    name = seed.name
    out: list[Query] = []

    def phrase(v: str) -> Term:
        return Term(TermKind.PHRASE, v) if any(c.isspace() for c in v) else Term(TermKind.WORD, v)

    anchor = [phrase(name)] if name else []
    org = phrase(seed.organizations[0]) if seed.organizations else None
    loc = phrase(seed.locations[0]) if seed.locations else None

    # anchor + site + filetype
    targets = [_ for _ in (seed.domains + seed.sites)]
    for site in targets[:4]:
        for ft in seed.filetypes[:3]:
            terms = anchor + [Term(TermKind.SITE, site.lower()), Term(TermKind.FILETYPE, ft)]
            if org:
                terms.append(org)
            out.append(Query(strategy=f"combined_site_ft:{site}:{ft}", terms=tuple(terms),
                             objective="anchor + site + filetype combined"))

    # anchor + org/loc + filetype (document exposure with context)
    if name:
        for ctx in [t for t in (org, loc) if t]:
            for ft in seed.filetypes[:4]:
                terms = anchor + [ctx, Term(TermKind.FILETYPE, ft)]
                out.append(Query(strategy=f"combined_ctx_ft:{ft}", terms=tuple(terms),
                                 objective="anchor + context + filetype combined"))

    # anchor + keyword + filetype
    for kw in seed.keywords[:3]:
        for ft in seed.filetypes[:3]:
            terms = anchor + [phrase(kw), Term(TermKind.FILETYPE, ft)]
            out.append(Query(strategy=f"combined_kw_ft:{ft}", terms=tuple(terms),
                             objective="anchor + keyword + filetype combined"))

    return out[:max_queries]
