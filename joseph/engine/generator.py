"""query family generator.

given an identity seed, deterministically produce a family of typed queries across
strategies (direct identity, organization, location, occupation, username, email,
domain, document discovery, title/url lenses, social profile, temporal, negative space).

the generator never emits a single "the dork". it produces a search space that the
scorer then prioritizes.
"""

from __future__ import annotations

from .grammar import Query, Term, TermKind
from .seed import IdentitySeed, KNOWN_SURFACES


def _phrase(value: str) -> Term:
    return Term(TermKind.PHRASE, value) if any(c.isspace() for c in value) else Term(TermKind.WORD, value)


def _resolve_site(token: str) -> str:
    """map a friendly surface name to a domain, else assume it is already a domain."""
    return KNOWN_SURFACES.get(token.lower(), token.lower())


def _temporal_terms(seed: IdentitySeed) -> list[Term]:
    terms: list[Term] = []
    if seed.after_value():
        terms.append(Term(TermKind.AFTER, seed.after_value()))
    if seed.before_value():
        terms.append(Term(TermKind.BEFORE, seed.before_value()))
    return terms


def _exclusion_terms(seed: IdentitySeed) -> list[Term]:
    return [Term(TermKind.EXCLUDE, x) for x in seed.exclusions]


def generate(seed: IdentitySeed) -> list[Query]:
    """produce the full deterministic query family for a seed."""
    queries: list[Query] = []
    name = seed.name

    excl = _exclusion_terms(seed)
    temporal = _temporal_terms(seed)

    def emit(strategy: str, terms: list[Term], objective: str) -> None:
        terms = [t for t in terms if t is not None]
        if not terms:
            return
        queries.append(Query(strategy=strategy, terms=tuple(terms + excl), objective=objective))

    # ---- identity-anchored strategies ----
    if name:
        emit("identity_direct", [_phrase(name)], "locate any indexed page naming the subject")

        for org in seed.organizations:
            emit(
                "identity_org",
                [_phrase(name), _phrase(org)],
                "co-occurrence of subject and organization",
            )
        for loc in seed.locations:
            emit(
                "identity_location",
                [_phrase(name), _phrase(loc)],
                "co-occurrence of subject and location",
            )
        for occ in seed.occupations:
            emit(
                "identity_occupation",
                [_phrase(name), _phrase(occ)],
                "co-occurrence of subject and occupation",
            )
        # full-context single query if we have multiple anchors
        context_terms = [_phrase(name)]
        context_terms += [_phrase(o) for o in seed.organizations[:1]]
        context_terms += [_phrase(l) for l in seed.locations[:1]]
        context_terms += [_phrase(o) for o in seed.occupations[:1]]
        if len(context_terms) >= 3:
            emit("identity_full_context", context_terms, "high-specificity multi-anchor confirmation")

        emit("title_lens", [Term(TermKind.INTITLE, name)], "pages whose title names the subject")

    # ---- username strategies ----
    for user in seed.usernames:
        emit("username_direct", [_phrase(user)], "locate the raw username string")
        emit("username_url_lens", [Term(TermKind.INURL, user)], "urls that embed the username")
        for surface, domain in KNOWN_SURFACES.items():
            emit(
                f"username_site:{surface}",
                [Term(TermKind.SITE, domain), _phrase(user)],
                f"candidate {surface} account for the username",
            )

    # ---- email strategies ----
    for email in seed.emails:
        emit("email_direct", [_phrase(email)], "pages exposing the email address")
        # email-domain pivot
        if "@" in email:
            edomain = email.split("@", 1)[1].strip().lower()
            if edomain:
                emit(
                    "email_domain_pivot",
                    [Term(TermKind.SITE, edomain)] + ([_phrase(name)] if name else []),
                    "content hosted on the email domain",
                )

    # ---- domain strategies ----
    for domain in seed.domains:
        d = _resolve_site(domain)
        emit(
            "domain_site",
            [Term(TermKind.SITE, d)] + ([_phrase(name)] if name else []),
            "subject references on a known domain",
        )
        emit("domain_url_lens", [Term(TermKind.INURL, d)], "urls referencing the domain")

    # ---- explicit site targets ----
    for site in seed.sites:
        d = _resolve_site(site)
        base = [Term(TermKind.SITE, d)]
        if name:
            base.append(_phrase(name))
        for user in seed.usernames[:1]:
            base.append(_phrase(user))
        emit(f"site_target:{d}", base, "constrained search on an explicit site target")

    # ---- document discovery ----
    if name:
        for ft in seed.filetypes:
            emit(
                f"document:{ft}",
                [_phrase(name), Term(TermKind.FILETYPE, ft)],
                f"authored or referencing {ft} documents",
            )
        for org in seed.organizations[:2]:
            emit(
                "org_document",
                [_phrase(org), _phrase(name), Term(TermKind.FILETYPE, "pdf")],
                "organizational documents mentioning the subject",
            )

    # ---- temporal-constrained identity ----
    if name and temporal:
        emit("temporal_identity", [_phrase(name)] + temporal, "subject references inside a time window")

    # ---- negative-space / contradiction seeds ----
    # a corroboration variant that pairs two independent anchors when available
    anchors = seed.anchors()
    if len(anchors) >= 2:
        a, b = anchors[0], anchors[1]
        emit(
            "cross_source_corroboration",
            [_phrase(a), _phrase(b)],
            "independent corroboration of two anchors together",
        )

    return _dedupe(queries)


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
