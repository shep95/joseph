"""pattern creator -> a deterministic compiler, not an ai.

it derives candidate patterns from structured event logs (repeated operation sequences),
normalizes and classifies them, scores them, tests them against history, and proposes
them as `candidate` patterns with provenance. it never auto-promotes and never overwrites
an existing version -> promotion goes through the validation rules.

    mine -> normalize -> classify -> score -> test -> propose(candidate)
    compose / adapt / retire operate on existing registry patterns.
"""

from __future__ import annotations

import hashlib
from collections import Counter
from dataclasses import dataclass, field

from .registry import Pattern, Registry, load_registry


@dataclass
class Event:
    """one recorded step of a research run."""

    operation: str
    domain: str = ""
    outcome: str = ""     # success | failure | neutral
    context: str = ""


@dataclass
class CandidatePattern:
    id: str
    trigger: str
    operations: tuple[str, ...]
    domain: tuple[str, ...]
    score: float
    provenance: dict
    status: str = "candidate"
    version: int = 1

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "version": self.version,
            "status": self.status,
            "domain": list(self.domain),
            "trigger": self.trigger,
            "operations": list(self.operations),
            "confidence": round(self.score, 4),
            "scope": "task",
            "provenance": self.provenance,
        }


def _ngram_sequences(ops: list[str], n: int = 3) -> Counter:
    grams: Counter = Counter()
    for i in range(len(ops) - n + 1):
        grams[tuple(ops[i : i + n])] += 1
    return grams


def mine(events: list[Event], *, min_support: int = 2, n: int = 3) -> list[CandidatePattern]:
    """PatternMiner + Normalizer + Scorer -> repeated successful operation sequences."""
    successful = [e for e in events if e.outcome != "failure"]
    ops = [e.operation for e in successful]
    grams = _ngram_sequences(ops, n=n)

    # domain vote per operation
    domain_by_op: dict[str, Counter] = {}
    for e in successful:
        if e.domain:
            domain_by_op.setdefault(e.operation, Counter())[e.domain] += 1

    candidates: list[CandidatePattern] = []
    for seq, support in grams.items():
        if support < min_support:
            continue
        domains = []
        for op in seq:
            votes = domain_by_op.get(op)
            if votes:
                domains.append(votes.most_common(1)[0][0])
        domains = sorted(set(domains))
        seq_id = hashlib.sha256("|".join(seq).encode()).hexdigest()[:8]
        score = min(0.9, 0.4 + 0.1 * support)
        candidates.append(
            CandidatePattern(
                id=f"mined.seq_{seq_id}",
                trigger=f"observed_sequence:{seq[0]}",
                operations=seq,
                domain=tuple(domains) or ("KNO",),
                score=score,
                provenance={"support": support, "source": "event_log_mining", "n": n},
            )
        )
    # deterministic order: strongest support first, then id
    candidates.sort(key=lambda c: (-c.score, c.id))
    return candidates


def classify(candidate: CandidatePattern) -> str:
    """PatternClassifier -> assign a coarse family from the operations."""
    ops = " ".join(candidate.operations)
    if "query" in ops:
        return "research"
    if "extract" in ops or "compare" in ops:
        return "resolution"
    if "contradiction" in ops or "test" in ops:
        return "audit"
    return "general"


def test_against_history(candidate: CandidatePattern, events: list[Event]) -> bool:
    """PatternTester -> does the candidate's first operation actually precede its rest in
    the recorded history at least once? a minimal historical-replay check."""
    ops = [e.operation for e in events]
    seq = list(candidate.operations)
    for i in range(len(ops) - len(seq) + 1):
        if ops[i : i + len(seq)] == seq:
            return True
    return False


def compose(a: Pattern, b: Pattern) -> CandidatePattern:
    """PatternComposer -> sequence two patterns into a candidate composite."""
    ops = tuple(list(a.operations) + list(b.operations))
    domains = tuple(sorted(set(a.domain) | set(b.domain)))
    cid = f"composed.{a.id.split('.')[-1]}_{b.id.split('.')[-1]}"
    score = round(min(0.85, (a.confidence + b.confidence) / 2), 4)
    return CandidatePattern(
        id=cid,
        trigger=a.trigger,
        operations=ops,
        domain=domains,
        score=score,
        provenance={"source": "composition", "parents": [a.key, b.key]},
    )


def adapt_on_failure(pattern: Pattern, *, root_cause: str, repair: str) -> dict:
    """PatternAdapter -> propose the next version of a pattern that failed, without
    overwriting the old one. returns a new pattern dict (status experimental)."""
    d = dict(pattern.raw)
    d["version"] = pattern.version + 1
    d["status"] = "experimental"
    d["parent"] = pattern.key
    d.setdefault("provenance", {})
    d["provenance"] = {"reason_for_change": root_cause, "repair": repair, "parent": pattern.key}
    return d


def retire(pattern: Pattern, *, reason: str) -> dict:
    """PatternRetirement -> mark a pattern deprecated (new version), never delete."""
    d = dict(pattern.raw)
    d["version"] = pattern.version + 1
    d["status"] = "deprecated"
    d["parent"] = pattern.key
    d["provenance"] = {"reason_for_retirement": reason, "parent": pattern.key}
    return d
