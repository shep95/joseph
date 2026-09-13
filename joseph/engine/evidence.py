"""evidence + confidence engine.

turns resolved entities and graph edges into structured findings, each with a claim,
supporting evidence, corroboration count, contradictions, and a graded confidence. keeps
the epistemic firewall from pattern-forge intact: observation, inference, and assessment
never silently collapse into one another.

confidence is a bounded deterministic function of independent support and verdict
strength. it is never asserted as certainty.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .graph import EvidenceGraph, Node
from .normalize import Result
from .resolution import ResolvedEntity
from .seed import IdentitySeed

CONFIDENCE_BANDS = (
    (0.85, "high"),
    (0.6, "moderate"),
    (0.35, "low"),
    (0.0, "insufficient"),
)


def band(score: float) -> str:
    for threshold, label in CONFIDENCE_BANDS:
        if score >= threshold:
            return label
    return "insufficient"


@dataclass
class Finding:
    finding_id: str
    claim: str
    epistemic: str            # observation | inference | assessment
    evidence: list[str] = field(default_factory=list)
    corroboration: int = 0
    confidence: float = 0.0
    confidence_band: str = "insufficient"
    contradictions: list[str] = field(default_factory=list)
    status: str = "supported"  # supported | unresolved | contested


@dataclass
class Assessment:
    subject: str
    overall_confidence: float
    overall_band: str
    findings: list[Finding]
    unresolved: list[str]
    contradictions: list[str]


def build_findings(
    seed: IdentitySeed,
    results: list[Result],
    resolved: list[ResolvedEntity],
    graph: EvidenceGraph,
) -> Assessment:
    subject = seed.name or (seed.usernames[0] if seed.usernames else "subject")
    findings: list[Finding] = []
    unresolved: list[str] = []
    counter = 0

    def next_id() -> str:
        nonlocal counter
        counter += 1
        return f"F-{counter:03d}"

    # findings from strong/moderate resolved entities
    for r in resolved:
        if r.verdict in {"strong", "moderate"}:
            e = r.entity
            desc = f"{e.surface} " if e.surface else ""
            claim = f"the {desc}{e.kind} '{e.value}' is associated with {subject}"
            conf = min(1.0, r.score)
            findings.append(
                Finding(
                    finding_id=next_id(),
                    claim=claim,
                    epistemic="inference",
                    evidence=[e.source_url] if e.source_url else [],
                    corroboration=1,
                    confidence=round(conf, 4),
                    confidence_band=band(conf),
                    status="supported",
                )
            )
        elif r.verdict == "weak":
            unresolved.append(
                f"possible but unconfirmed: {r.entity.kind} '{r.entity.value}' "
                f"({', '.join(r.features) or 'weak similarity only'})"
            )

    # corroborated pages -> observation findings
    for res in results:
        if res.corroboration >= 2:
            claim = f"'{res.title or res.canonical}' surfaced under {res.corroboration} independent query strategies"
            conf = min(0.9, 0.4 + 0.15 * res.corroboration)
            findings.append(
                Finding(
                    finding_id=next_id(),
                    claim=claim,
                    epistemic="observation",
                    evidence=[res.canonical],
                    corroboration=res.corroboration,
                    confidence=round(conf, 4),
                    confidence_band=band(conf),
                    status="supported",
                )
            )

    # contradiction detection: same surface, multiple distinct strong handles
    contradictions = _detect_contradictions(resolved)

    overall = _overall_confidence(findings)
    return Assessment(
        subject=subject,
        overall_confidence=overall,
        overall_band=band(overall),
        findings=findings,
        unresolved=sorted(set(unresolved)),
        contradictions=contradictions,
    )


def _detect_contradictions(resolved: list[ResolvedEntity]) -> list[str]:
    """flag when one surface has multiple competing strong identity candidates."""
    by_surface: dict[str, list[str]] = {}
    for r in resolved:
        e = r.entity
        if e.kind == "profile" and e.surface and r.verdict in {"strong", "moderate"}:
            by_surface.setdefault(e.surface, []).append(e.value)
    out: list[str] = []
    for surface, handles in sorted(by_surface.items()):
        distinct = sorted(set(h.lower() for h in handles))
        if len(distinct) > 1:
            out.append(
                f"multiple competing {surface} profiles resolved to the subject: "
                f"{', '.join(distinct)} -> treat as unresolved, not confirmed"
            )
    return out


def _overall_confidence(findings: list[Finding]) -> float:
    if not findings:
        return 0.0
    # combine independent supported findings with a bounded noisy-or so more corroboration
    # raises confidence without ever reaching 1.0
    complement = 1.0
    for f in findings:
        if f.status == "supported":
            complement *= (1.0 - min(0.95, f.confidence))
    return round(min(0.97, 1.0 - complement), 4)
