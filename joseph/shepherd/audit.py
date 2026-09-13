"""model audit engine.

runs the osint-active subset of the universal flaw taxonomy plus the contradiction rules
over an assessment. produces named audit findings the report can surface. deterministic;
no ai judgement.
"""

from __future__ import annotations

from dataclasses import dataclass

from .registry import Registry, load_registry


@dataclass(frozen=True)
class AuditFinding:
    flaw_class: str
    detail: str
    severity: str  # info | warn | high


def audit_assessment(assessment, results, resolved, *, registry: Registry | None = None) -> list[AuditFinding]:
    reg = registry or load_registry()
    out: list[AuditFinding] = []

    # 10_evidence -> single-source findings
    single_source = [f for f in getattr(assessment, "findings", []) if f.corroboration <= 1 and f.epistemic != "observation"]
    if single_source:
        out.append(AuditFinding("10_evidence", f"{len(single_source)} findings rest on a single source (weak evidence)", "warn"))

    # 11_uncertainty -> any 'high' confidence with only one corroboration
    overconf = [f for f in getattr(assessment, "findings", []) if f.confidence_band == "high" and f.corroboration <= 1]
    if overconf:
        out.append(AuditFinding("11_uncertainty", f"{len(overconf)} findings claim high confidence on thin corroboration", "high"))

    # 25_meta -> name-only weak resolutions that could be false positives
    name_only = [r for r in resolved if r.verdict == "weak" and any("similarity" in feat for feat in r.features)]
    if name_only:
        out.append(AuditFinding("25_meta", f"{len(name_only)} weak matches rest on name/username similarity only -> false-positive risk", "warn"))

    # 26_metadata / source collision -> many results from one domain masquerading as many
    if results:
        domains = {}
        for r in results:
            domains[r.domain] = domains.get(r.domain, 0) + 1
        dominant = max(domains.values()) if domains else 0
        if dominant >= max(3, int(0.7 * len(results))):
            out.append(AuditFinding("26_metadata", "most results share one domain -> possible source collision (independence overstated)", "warn"))

    # contradictions surfaced by the assessment
    for c in getattr(assessment, "contradictions", []) or []:
        out.append(AuditFinding("3_logic", c, "high"))

    return out
