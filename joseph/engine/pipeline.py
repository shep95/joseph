"""investigation pipeline -> orchestrates the deterministic stages end to end.

    seed -> generate -> mutate -> prioritize -> plan
         -> (optional) live collect -> normalize -> relevance
         -> extract -> resolve -> graph -> findings

the pipeline works with zero network access (plan-only): it still produces the ranked
query family and a report scaffold. with live collection enabled it additionally fills
the evidence layers from real public results.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from . import generator, mutation, scoring, providers, normalize, relevance, entities, resolution, graph, evidence
from .providers import QueryPlan, RawResult
from .seed import IdentitySeed


@dataclass
class Investigation:
    seed: IdentitySeed
    plans: list[QueryPlan]
    raws: list[RawResult] = field(default_factory=list)
    results: list = field(default_factory=list)
    entities: list = field(default_factory=list)
    resolved: list = field(default_factory=list)
    graph: graph.EvidenceGraph | None = None
    assessment: evidence.Assessment | None = None
    live_executed: bool = False

    @property
    def query_count(self) -> int:
        return len(self.plans)


def plan_only(seed: IdentitySeed, *, mutate: bool = True, max_swaps: int = 0) -> Investigation:
    """produce the scored, ranked query family without any collection."""
    family = generator.generate(seed)
    if mutate:
        family = mutation.mutate_family(seed, family, max_swaps=max_swaps)
    scored = scoring.prioritize(family)
    plans = providers.build_plan(scored)
    return Investigation(seed=seed, plans=plans)


def analyze(seed: IdentitySeed, raws: list[RawResult], investigation: Investigation) -> Investigation:
    """run the analysis stages over collected raw results."""
    results = normalize.normalize(raws)
    results = relevance.score_relevance(seed, results)
    ents = entities.extract(results)
    resolved = resolution.resolve(seed, ents)
    g = graph.build_graph(seed, results, resolved)
    assessment = evidence.build_findings(seed, results, resolved, g)

    investigation.raws = raws
    investigation.results = results
    investigation.entities = ents
    investigation.resolved = resolved
    investigation.graph = g
    investigation.assessment = assessment
    return investigation


async def investigate(
    seed: IdentitySeed,
    *,
    live: bool,
    max_live_queries: int,
    http_timeout: int,
    mutate: bool = True,
) -> Investigation:
    """full pipeline. when live is false, returns the plan plus an empty evidence layer."""
    inv = plan_only(seed, mutate=mutate)

    raws: list[RawResult] = []
    if live and inv.plans:
        raws = await providers.collect_live(
            inv.plans,
            max_queries=max_live_queries,
            timeout=http_timeout,
        )
        inv.live_executed = True

    return analyze(seed, raws, inv)
