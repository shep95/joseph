"""intelligence report data model.

the canonical machine-readable dataset built from an Investigation. this is the source
of truth; renderers (markdown now, pdf later) consume it. it carries provenance so a
report can be reproduced and audited: seed fingerprint, dataset hash, engine version,
and generation timestamp.
"""

from __future__ import annotations

import datetime as _dt
import hashlib
import json
from dataclasses import dataclass, field

from .. import __version__, __agency__
from ..engine.pipeline import Investigation


def _report_id(seed_fp: str, generated_at: str) -> str:
    stamp = generated_at[:10].replace("-", "")
    tail = hashlib.sha256(f"{seed_fp}{generated_at}".encode()).hexdigest()[:5].upper()
    return f"AIA-{stamp}-{tail}"


@dataclass
class ReportDataset:
    report_id: str
    generated_at: str
    engine_version: str
    agency: str
    seed_fingerprint: str
    subject: dict
    objective: str
    executive_assessment: str
    overall_confidence: float
    overall_band: str
    query_family: list[dict]
    findings: list[dict]
    entities: list[dict]
    graph_summary: dict
    sources: list[dict]
    contradictions: list[str]
    unresolved: list[str]
    methodology: dict
    routing: dict = None
    patterns_applied: list = None
    audit: list = None
    data_hash: str = ""

    def to_json(self) -> str:
        payload = {k: v for k, v in self.__dict__.items() if k != "data_hash"}
        body = json.dumps(payload, sort_keys=True, ensure_ascii=False, indent=2)
        self.data_hash = hashlib.sha256(body.encode()).hexdigest()[:16]
        payload["data_hash"] = self.data_hash
        return json.dumps(payload, ensure_ascii=False, indent=2)


def _executive(inv: Investigation) -> str:
    a = inv.assessment
    if a is None:
        return "query plan generated; collection not executed. no evidence layer available."
    if not inv.live_executed:
        return (
            f"deterministic query plan of {inv.query_count} ranked queries produced for the subject. "
            f"live collection was not executed, so no evidence has been correlated yet."
        )
    supported = sum(1 for f in a.findings if f.status == "supported")
    return (
        f"{len(inv.results)} unique sources correlated across {inv.query_count} ranked queries. "
        f"{supported} supported findings; overall confidence assessed as {a.overall_band} "
        f"({a.overall_confidence:.2f}). {len(a.unresolved)} items remain unresolved and "
        f"{len(a.contradictions)} contradictions were detected."
    )


def build_dataset(inv: Investigation, *, top_queries: int = 25, top_sources: int = 40) -> ReportDataset:
    now = _dt.datetime.now(_dt.timezone.utc).replace(microsecond=0).isoformat()
    seed = inv.seed
    seed_fp = seed.fingerprint()

    query_family = [
        {
            "rank": i + 1,
            "strategy": p.query.strategy,
            "objective": p.query.objective,
            "score": p.scored.score,
            "reasons": list(p.scored.reasons),
            "google": p.query.render("google"),
            "urls": p.urls,
        }
        for i, p in enumerate(inv.plans[:top_queries])
    ]

    findings = []
    entities_out = []
    sources = []
    graph_summary = {"nodes": 0, "edges": 0, "top": []}
    contradictions: list[str] = []
    unresolved: list[str] = []
    overall_conf = 0.0
    overall_band = "insufficient"

    if inv.assessment is not None:
        a = inv.assessment
        overall_conf = a.overall_confidence
        overall_band = a.overall_band
        contradictions = a.contradictions
        unresolved = a.unresolved
        findings = [
            {
                "id": f.finding_id,
                "claim": f.claim,
                "epistemic": f.epistemic,
                "confidence": f.confidence,
                "band": f.confidence_band,
                "corroboration": f.corroboration,
                "status": f.status,
                "evidence": f.evidence,
                "contradictions": f.contradictions,
            }
            for f in a.findings
        ]

    for r in inv.resolved:
        entities_out.append(
            {
                "kind": r.entity.kind,
                "value": r.entity.value,
                "surface": r.entity.surface,
                "verdict": r.verdict,
                "score": r.score,
                "features": list(r.features),
                "source": r.entity.source_url,
            }
        )

    for res in inv.results[:top_sources]:
        sources.append(
            {
                "url": res.canonical,
                "domain": res.domain,
                "title": res.title,
                "snippet": res.snippet,
                "relevance": res.relevance,
                "corroboration": res.corroboration,
                "strategies": sorted(res.strategies),
            }
        )

    # shepherd routing + patterns applied + audit
    routing = {}
    patterns_applied = []
    audit = []
    if getattr(inv, "route", None) is not None:
        r = inv.route
        routing = {
            "task_type": r.task_type,
            "domains": list(r.domains),
            "features": list(r.features),
        }
    for ap in getattr(inv, "applied_patterns", []) or []:
        patterns_applied.append(
            {
                "id": ap.pattern.id,
                "version": ap.pattern.version,
                "status": ap.pattern.status,
                "satisfied": ap.satisfied,
                "operations": list(ap.operations),
                "strategies": list(ap.strategies),
                "confidence": ap.pattern.confidence,
            }
        )
    for af in getattr(inv, "audit_findings", []) or []:
        audit.append({"flaw_class": af.flaw_class, "detail": af.detail, "severity": af.severity})

    if inv.graph is not None:
        g = inv.graph
        graph_summary = {
            "nodes": len(g.nodes),
            "edges": len(g.edges),
            "top": [
                {"id": n.id, "kind": n.kind, "label": n.label, "degree": d}
                for n, d in g.top_nodes(10)
            ],
        }

    dataset = ReportDataset(
        report_id=_report_id(seed_fp, now),
        generated_at=now,
        engine_version=__version__,
        agency=__agency__,
        seed_fingerprint=seed_fp,
        subject=seed.to_dict(),
        objective=f"deterministic osint correlation on subject '{seed.name or (seed.usernames[0] if seed.usernames else 'unknown')}'",
        executive_assessment=_executive(inv),
        overall_confidence=overall_conf,
        overall_band=overall_band,
        query_family=query_family,
        findings=findings,
        entities=entities_out,
        graph_summary=graph_summary,
        sources=sources,
        contradictions=contradictions,
        unresolved=unresolved,
        methodology={
            "engine": "joseph",
            "mode": "live-collection" if inv.live_executed else "plan-only",
            "control_plane": "shepherd (symbolic pattern execution)",
            "stages": [
                "seed", "route", "select_patterns", "generate", "mutate", "prioritize", "plan",
                "collect", "normalize", "relevance", "extract",
                "resolve", "graph", "findings", "audit",
            ],
            "boundary": "public sources and documented search operators only; no auth bypass, no private-account access, no restricted records",
            "non_ai": True,
        },
        routing=routing,
        patterns_applied=patterns_applied,
        audit=audit,
    )
    # finalize hash
    dataset.to_json()
    return dataset
