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

# shepherd symbolic control plane -> decides which patterns apply and audits the result
try:
    from ..shepherd import pattern_engine as _shepherd_engine
    from ..shepherd import audit as _shepherd_audit
    from ..shepherd.router import Route as _Route
    _SHEPHERD = True
except Exception:  # shepherd is optional; the engine still runs without it
    _SHEPHERD = False


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
    route: object | None = None            # shepherd Route
    applied_patterns: list = field(default_factory=list)  # shepherd AppliedPattern
    audit_findings: list = field(default_factory=list)     # shepherd AuditFinding

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
    inv = Investigation(seed=seed, plans=plans)

    # shepherd decides the task route + which patterns apply
    if _SHEPHERD:
        try:
            route, applied = _shepherd_engine.select_patterns(seed)
            inv.route = route
            inv.applied_patterns = applied
        except Exception:
            pass
    return inv


def plan_dorks(seed: IdentitySeed, *, raw: str = "", combine: bool = False, mutate: bool = True) -> Investigation:
    """plan a query family that can include user-supplied raw dorks and AND-combined
    compound dorks. this backs `/joseph dork` when the user wants to combine dorks."""
    from . import combine as combine_mod

    family = generator.generate(seed)
    if mutate:
        family = mutation.mutate_family(seed, family, max_swaps=0)

    raw_queries = combine_mod.parse_dorks(raw) if raw else []
    family = list(family) + raw_queries

    if combine:
        # combine the user's raw dorks together if they gave several; otherwise auto-build
        # compound stacked dorks from the seed.
        if len(raw_queries) >= 2:
            merged = combine_mod.merge(raw_queries)
            if merged.terms:
                family.append(merged)
        elif raw_queries:
            # one raw dork + seed anchor -> fold the seed name in as a combined variant
            base = generator.generate(seed)
            if base:
                family.append(combine_mod.merge([raw_queries[0], base[0]]))
        family += combine_mod.combined_family(seed)

    scored = scoring.prioritize(family)
    plans = providers.build_plan(scored)
    inv = Investigation(seed=seed, plans=plans)
    if _SHEPHERD:
        try:
            route, applied = _shepherd_engine.select_patterns(seed)
            inv.route = route
            inv.applied_patterns = applied
        except Exception:
            pass
    return inv


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

    # shepherd model audit over the assessment
    if _SHEPHERD and assessment is not None:
        try:
            investigation.audit_findings = _shepherd_audit.audit_assessment(assessment, results, resolved)
        except Exception:
            investigation.audit_findings = []
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
