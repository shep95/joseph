"""search operator grammar.

instead of hardcoding random dork strings, joseph builds queries from a small formal
grammar of typed terms, then serializes them per provider using only operators that the
provider officially documents.

    google  -> site:, filetype:, intitle:, inurl:, intext:, before:, after:, "phrase", -exclude, OR
    bing    -> site:, filetype:, ext:, intitle:, inbody:, inanchor:, url:, "phrase", -exclude, OR
    ddg     -> site:, filetype:, intitle:, inurl:, "phrase", -exclude

a term the provider cannot express is dropped for that provider rather than emitted as a
literal string that would pollute the query.
"""

from __future__ import annotations

import urllib.parse
from dataclasses import dataclass, field
from enum import Enum


class TermKind(str, Enum):
    PHRASE = "phrase"        # "exact phrase"
    WORD = "word"            # bare token
    SITE = "site"            # site:domain
    FILETYPE = "filetype"    # filetype:pdf / ext:pdf
    INTITLE = "intitle"      # intitle:...
    INURL = "inurl"          # inurl:...  (bing: url:)
    INTEXT = "intext"        # intext:... (bing: inbody:)
    INANCHOR = "inanchor"    # bing only
    BEFORE = "before"        # before:YYYY-MM-DD (google/ddg)
    AFTER = "after"          # after:YYYY-MM-DD  (google/ddg)
    EXCLUDE = "exclude"      # -token
    OR_GROUP = "or_group"    # (a OR b OR c)


# which term kinds each provider can express, and how to serialize the operator prefix.
_PROVIDER_CAPS: dict[str, dict[TermKind, str | None]] = {
    "google": {
        TermKind.PHRASE: "",
        TermKind.WORD: "",
        TermKind.SITE: "site:",
        TermKind.FILETYPE: "filetype:",
        TermKind.INTITLE: "intitle:",
        TermKind.INURL: "inurl:",
        TermKind.INTEXT: "intext:",
        TermKind.INANCHOR: None,
        TermKind.BEFORE: "before:",
        TermKind.AFTER: "after:",
        TermKind.EXCLUDE: "-",
        TermKind.OR_GROUP: "",
    },
    "bing": {
        TermKind.PHRASE: "",
        TermKind.WORD: "",
        TermKind.SITE: "site:",
        TermKind.FILETYPE: "ext:",
        TermKind.INTITLE: "intitle:",
        TermKind.INURL: "url:",
        TermKind.INTEXT: "inbody:",
        TermKind.INANCHOR: "inanchor:",
        TermKind.BEFORE: None,
        TermKind.AFTER: None,
        TermKind.EXCLUDE: "-",
        TermKind.OR_GROUP: "",
    },
    "ddg": {
        TermKind.PHRASE: "",
        TermKind.WORD: "",
        TermKind.SITE: "site:",
        TermKind.FILETYPE: "filetype:",
        TermKind.INTITLE: "intitle:",
        TermKind.INURL: "inurl:",
        TermKind.INTEXT: None,
        TermKind.INANCHOR: None,
        TermKind.BEFORE: None,
        TermKind.AFTER: None,
        TermKind.EXCLUDE: "-",
        TermKind.OR_GROUP: "",
    },
}

_SEARCH_URLS: dict[str, str] = {
    "google": "https://www.google.com/search?q=",
    "bing": "https://www.bing.com/search?q=",
    "ddg": "https://duckduckgo.com/?q=",
}


def _needs_quotes(value: str) -> bool:
    return any(c.isspace() for c in value.strip())


@dataclass(frozen=True)
class Term:
    kind: TermKind
    value: str
    # for OR_GROUP the value is ignored; members carries the alternatives
    members: tuple[str, ...] = field(default=())

    def render(self, provider: str) -> str | None:
        caps = _PROVIDER_CAPS[provider]
        prefix = caps.get(self.kind)
        if prefix is None:
            return None  # provider cannot express this term

        if self.kind is TermKind.OR_GROUP:
            alts = [m for m in self.members if m]
            if len(alts) < 2:
                return _quote(alts[0]) if alts else None
            return "(" + " OR ".join(_quote(a) for a in alts) + ")"

        if self.kind is TermKind.PHRASE:
            return f"\"{self.value}\""

        if self.kind is TermKind.WORD:
            return self.value

        if self.kind is TermKind.EXCLUDE:
            v = self.value
            return f"-{_quote(v)}"

        # operator-prefixed terms
        v = self.value
        if self.kind in {TermKind.SITE, TermKind.FILETYPE, TermKind.BEFORE, TermKind.AFTER}:
            return f"{prefix}{v}"
        # lens operators quote multiword values
        return f"{prefix}{_quote(v)}"


def _quote(value: str) -> str:
    return f"\"{value}\"" if _needs_quotes(value) else value


@dataclass(frozen=True)
class Query:
    """a provider-agnostic query: an ordered list of typed terms plus metadata."""

    strategy: str
    terms: tuple[Term, ...]
    objective: str = ""

    def render(self, provider: str = "google") -> str:
        rendered: list[str] = []
        for term in self.terms:
            piece = term.render(provider)
            if piece:
                rendered.append(piece)
        return " ".join(rendered).strip()

    def signature(self) -> str:
        """structural signature for deduplication -> ignores provider, keeps meaning."""
        parts = sorted(f"{t.kind.value}:{t.value.lower()}:{'|'.join(m.lower() for m in t.members)}" for t in self.terms)
        return "&".join(parts)

    def url(self, provider: str = "google") -> str:
        base = _SEARCH_URLS.get(provider, _SEARCH_URLS["google"])
        return base + urllib.parse.quote_plus(self.render(provider))

    def constraint_count(self) -> int:
        """number of meaningful constraints -> used by the scorer for specificity."""
        return sum(1 for t in self.terms if t.kind is not TermKind.WORD or t.value)


def providers() -> tuple[str, ...]:
    return ("google", "bing", "ddg")
