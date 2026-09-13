"""pattern registry -> loads ontology + pattern objects from json, validates them against
the schema, and holds versioned patterns with a status lifecycle.

the registry is the single inspectable source of executable knowledge. it never mutates
model weights; adaptation happens by adding new pattern versions here.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

from . import ONTOLOGY_DIR, PATTERNS_DIR, RULES_DIR

VALID_STATUSES = ("candidate", "experimental", "validated", "active", "deprecated", "quarantined", "rejected")


def _load_json(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as fh:
        return json.load(fh)


@dataclass(frozen=True)
class Pattern:
    id: str
    version: int
    status: str
    domain: tuple[str, ...]
    trigger: str
    preconditions: tuple[str, ...]
    operations: tuple[str, ...]
    invariants: tuple[str, ...]
    failure_modes: tuple[str, ...]
    tests: tuple[str, ...]
    success_conditions: tuple[str, ...]
    stopping_conditions: tuple[str, ...]
    relations: dict
    confidence: float
    scope: str
    raw: dict = field(default_factory=dict, compare=False)

    @property
    def key(self) -> str:
        return f"{self.id}@{self.version}"

    @classmethod
    def from_dict(cls, d: dict) -> "Pattern":
        return cls(
            id=d["id"],
            version=int(d.get("version", 1)),
            status=d.get("status", "candidate"),
            domain=tuple(d.get("domain", [])),
            trigger=d["trigger"],
            preconditions=tuple(d.get("preconditions", [])),
            operations=tuple(d.get("operations", [])),
            invariants=tuple(d.get("invariants", [])),
            failure_modes=tuple(d.get("failure_modes", [])),
            tests=tuple(d.get("tests", [])),
            success_conditions=tuple(d.get("success_conditions", [])),
            stopping_conditions=tuple(d.get("stopping_conditions", [])),
            relations=dict(d.get("relations", {})),
            confidence=float(d.get("confidence", 0.5)),
            scope=d.get("scope", "domain"),
            raw=d,
        )


@dataclass
class Registry:
    patterns: dict[str, Pattern]          # key id@version -> pattern
    latest: dict[str, Pattern]            # id -> highest active/validated version
    domains: dict
    relations: dict
    flaw_types: dict
    schema: dict
    taxonomy: dict
    rules: dict

    def by_id(self, pattern_id: str) -> Pattern | None:
        return self.latest.get(pattern_id)

    def active(self) -> list[Pattern]:
        return [p for p in self.latest.values() if p.status in ("active", "validated")]

    def validate(self) -> list[str]:
        """schema validation -> returns a list of problems (empty means clean)."""
        problems: list[str] = []
        required = self.schema.get("required", [])
        for p in self.patterns.values():
            for req in required:
                if not getattr(p, req, None):
                    problems.append(f"{p.key}: missing required field '{req}'")
            if p.status not in VALID_STATUSES:
                problems.append(f"{p.key}: invalid status '{p.status}'")
            for rel in p.relations:
                if rel not in self.relations.get("relations", []):
                    problems.append(f"{p.key}: unknown relation '{rel}'")
            for dom in p.domain:
                if dom not in self.domains.get("domains", {}):
                    problems.append(f"{p.key}: unknown domain code '{dom}'")
        return problems


def _load_patterns() -> dict[str, Pattern]:
    out: dict[str, Pattern] = {}
    if not PATTERNS_DIR.exists():
        return out
    for path in sorted(PATTERNS_DIR.rglob("*.json")):
        data = _load_json(path)
        p = Pattern.from_dict(data)
        out[p.key] = p
    return out


def _latest(patterns: dict[str, Pattern]) -> dict[str, Pattern]:
    latest: dict[str, Pattern] = {}
    for p in patterns.values():
        cur = latest.get(p.id)
        if cur is None or p.version > cur.version:
            latest[p.id] = p
    return latest


@lru_cache(maxsize=1)
def load_registry() -> Registry:
    patterns = _load_patterns()
    rules = {}
    if RULES_DIR.exists():
        for path in sorted(RULES_DIR.glob("*.json")):
            rules[path.stem] = _load_json(path)
    reg = Registry(
        patterns=patterns,
        latest=_latest(patterns),
        domains=_load_json(ONTOLOGY_DIR / "domains.json"),
        relations=_load_json(ONTOLOGY_DIR / "relations.json"),
        flaw_types=_load_json(ONTOLOGY_DIR / "flaw_types.json"),
        schema=_load_json(ONTOLOGY_DIR / "pattern_schema.json"),
        taxonomy=_load_json(ONTOLOGY_DIR / "taxonomy.json"),
        rules=rules,
    )
    return reg
