"""pattern engine -> selects applicable patterns for a task and maps their operations to
concrete query strategies the osint engine understands.

    route -> patterns (trigger/preconditions satisfied) -> operations -> strategies

this is the control plane: shepherd decides which pattern applies and what operation comes
next; the engine modules execute the operation.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..engine.seed import IdentitySeed
from .registry import Pattern, Registry, load_registry
from .router import Route, route


@dataclass(frozen=True)
class AppliedPattern:
    pattern: Pattern
    satisfied: bool
    operations: tuple[str, ...]
    strategies: tuple[str, ...]


def _preconditions_met(pattern: Pattern, feats: set[str]) -> bool:
    mapping = {
        "seed_has_name": "seed_has_name",
        "seed_has_username": "seed_has_username",
        "seed_has_domain_or_email": None,  # handled below
        "seed_has_organization": "seed_has_organization",
        "candidate_has_identifier": "seed_has_name",  # any anchor counts at start
        "at_least_one_supported_finding": None,  # runtime finding, assume attemptable
        "two_claims_share_subject": None,
        "hypothesis_formed": None,
    }
    for pre in pattern.preconditions:
        if pre == "seed_has_domain_or_email":
            if not ({"seed_has_domain", "seed_has_email"} & feats):
                return False
            continue
        mapped = mapping.get(pre, pre)
        if mapped is None:
            continue  # runtime-only precondition -> not blocking at planning time
        if mapped not in feats:
            return False
    return True


def _operations_to_strategies(operations: tuple[str, ...], registry: Registry) -> list[str]:
    routing = registry.rules.get("routing", {})
    op_map = routing.get("operation_to_strategy", {})
    strategies: list[str] = []
    for op in operations:
        strategies.extend(op_map.get(op, []))
    # dedupe preserving order
    seen: set[str] = set()
    out: list[str] = []
    for s in strategies:
        if s not in seen:
            seen.add(s)
            out.append(s)
    return out


def select_patterns(seed: IdentitySeed, *, has_image: bool = False, registry: Registry | None = None) -> tuple[Route, list[AppliedPattern]]:
    reg = registry or load_registry()
    r = route(seed, has_image=has_image, registry=reg)
    feats = set(r.features)

    applied: list[AppliedPattern] = []
    for pid in r.pattern_ids:
        pattern = reg.by_id(pid)
        if pattern is None:
            continue
        satisfied = _preconditions_met(pattern, feats)
        strategies = tuple(_operations_to_strategies(pattern.operations, reg))
        applied.append(
            AppliedPattern(
                pattern=pattern,
                satisfied=satisfied,
                operations=pattern.operations,
                strategies=strategies,
            )
        )
    return r, applied
