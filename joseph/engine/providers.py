"""search provider adapters.

two modes:

    plan mode (default) -> for each scored query, emit ready-to-run provider urls. no
        network calls are made. this is always available and never fails.

    live mode (opt-in)  -> execute the top-ranked queries through the duckduckgo html
        endpoint, a public interface that returns organic result links without an api
        key. best-effort: timeouts and failures degrade to plan mode for that query.

joseph does not scrape google/bing html (against their terms). it only builds their
query urls for a human to open, and uses ddg's public html interface for automated
collection.
"""

from __future__ import annotations

import asyncio
import html
import re
import urllib.parse
from dataclasses import dataclass, field

from .grammar import Query, providers as _providers
from .scoring import ScoredQuery


@dataclass(frozen=True)
class RawResult:
    url: str
    title: str
    snippet: str
    provider: str
    query: str
    strategy: str
    rank: int


@dataclass
class QueryPlan:
    """what to run for a single scored query, across providers."""

    scored: ScoredQuery
    urls: dict[str, str] = field(default_factory=dict)

    @property
    def query(self) -> Query:
        return self.scored.query


def build_plan(scored_queries: list[ScoredQuery]) -> list[QueryPlan]:
    plans: list[QueryPlan] = []
    for sq in scored_queries:
        urls = {p: sq.query.url(p) for p in _providers()}
        plans.append(QueryPlan(scored=sq, urls=urls))
    return plans


# ---- live collection through the duckduckgo html endpoint ----

_DDG_ENDPOINT = "https://html.duckduckgo.com/html/"
_UA = "Mozilla/5.0 (compatible; joseph-osint/1.0; +https://github.com/shep95/joseph)"

# ddg html result anchors: <a rel="nofollow" class="result__a" href="...">title</a>
_RESULT_A_RE = re.compile(r'<a[^>]+class="result__a"[^>]+href="([^"]+)"[^>]*>(.*?)</a>', re.DOTALL)
_SNIPPET_RE = re.compile(r'<a[^>]+class="result__snippet"[^>]*>(.*?)</a>', re.DOTALL)
_TAG_RE = re.compile(r"<[^>]+>")


def _strip_html(text: str) -> str:
    return html.unescape(_TAG_RE.sub("", text)).strip()


def _unwrap_ddg(href: str) -> str:
    """ddg wraps external links as /l/?uddg=<encoded-url>. unwrap to the real target."""
    if href.startswith("//"):
        href = "https:" + href
    parsed = urllib.parse.urlparse(href)
    if parsed.path.startswith("/l/") or "uddg=" in (parsed.query or ""):
        qs = urllib.parse.parse_qs(parsed.query)
        if "uddg" in qs:
            return urllib.parse.unquote(qs["uddg"][0])
    return href


def _parse_ddg(body: str, provider_query: str, strategy: str) -> list[RawResult]:
    titles = _RESULT_A_RE.findall(body)
    snippets = _SNIPPET_RE.findall(body)
    snippet_texts = [_strip_html(s) for s in snippets]
    results: list[RawResult] = []
    for i, (href, title_html) in enumerate(titles):
        url = _unwrap_ddg(href)
        snippet = snippet_texts[i] if i < len(snippet_texts) else ""
        results.append(
            RawResult(
                url=url,
                title=_strip_html(title_html),
                snippet=snippet,
                provider="ddg",
                query=provider_query,
                strategy=strategy,
                rank=i + 1,
            )
        )
    return results


async def _fetch_one(session, plan: QueryPlan, timeout: int) -> list[RawResult]:
    q = plan.query.render("ddg")
    if not q:
        return []
    data = {"q": q}
    try:
        async with session.post(
            _DDG_ENDPOINT,
            data=data,
            headers={"User-Agent": _UA},
            timeout=timeout,
        ) as resp:
            if resp.status != 200:
                return []
            body = await resp.text()
    except Exception:
        return []
    return _parse_ddg(body, q, plan.query.strategy)


async def verify_links(urls: list[str], *, timeout: int, max_concurrency: int = 8) -> dict[str, bool]:
    """check that each url actually resolves (status < 400).

    tries a lightweight HEAD first, falls back to a ranged GET for servers that reject
    HEAD. returns {url: working}. best-effort -> import of aiohttp is local, failures map
    to False rather than raising. this is what makes /joseph dork return *working* links.
    """
    try:
        import aiohttp
    except Exception:
        return {u: False for u in urls}

    sem = asyncio.Semaphore(max_concurrency)
    results: dict[str, bool] = {}

    async def _check(session, url: str) -> None:
        ok = False
        async with sem:
            for method in ("head", "get"):
                try:
                    req = getattr(session, method)
                    headers = {"User-Agent": _UA}
                    if method == "get":
                        headers["Range"] = "bytes=0-2048"
                    async with req(url, headers=headers, timeout=timeout, allow_redirects=True) as resp:
                        if resp.status < 400:
                            ok = True
                            break
                        # some hosts 405 on HEAD -> let the get attempt decide
                        if method == "head" and resp.status in (403, 405, 501):
                            continue
                        break
                except Exception:
                    continue
        results[url] = ok

    async with aiohttp.ClientSession() as session:
        await asyncio.gather(*(_check(session, u) for u in urls))
    return results


async def collect_live(
    plans: list[QueryPlan],
    *,
    max_queries: int,
    timeout: int,
    pause_seconds: float = 1.0,
) -> list[RawResult]:
    """execute the top plans sequentially (polite, rate-limited) via ddg html.

    returns a flat list of raw results. import of aiohttp is local so plan mode has zero
    hard dependency on it.
    """
    try:
        import aiohttp
    except Exception:
        return []

    out: list[RawResult] = []
    async with aiohttp.ClientSession() as session:
        for plan in plans[:max_queries]:
            results = await _fetch_one(session, plan, timeout)
            out.extend(results)
            if pause_seconds:
                await asyncio.sleep(pause_seconds)
    return out
