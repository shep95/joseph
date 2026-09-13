"""deterministic research router.

classifies a task from seed features into a task_type, then selects the relevant
pattern-forge domains and an ordered list of pattern ids from routing.json. no ai decides
routing -> it is table-driven over observable features.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..engine.seed import IdentitySeed
from .registry import Registry, load_registry


@dataclass(frozen=True)
class Route:
    task_type: str
    domains: tuple[str, ...]
    pattern_ids: tuple[str, ...]
    features: tuple[str, ...]


def _features(seed: IdentitySeed, *, has_image: bool = False) -> set[str]:
    feats: set[str] = set()
    if seed.name:
        feats.add("seed_has_name")
    if seed.usernames:
        feats.add("seed_has_username")
    if seed.emails:
        feats.add("seed_has_email")
    if seed.domains:
        feats.add("seed_has_domain")
    if seed.organizations:
        feats.add("seed_has_organization")
    if seed.locations:
        feats.add("seed_has_location")
    if has_image:
        feats.add("has_image")
    return feats


def route(seed: IdentitySeed, *, has_image: bool = False, registry: Registry | None = None) -> Route:
    reg = registry or load_registry()
    routing = reg.rules.get("routing", {})
    task_types = routing.get("task_types", {})
    feats = _features(seed, has_image=has_image)

    # deterministic priority order -> most specific task first. a task matches only when
    # ALL of its 'when' features are present, so a broad task cannot shadow a specific one.
    priority = ["visual_geo", "document_research", "domain_research", "username_research", "person_research"]
    chosen = None
    for name in priority:
        spec = task_types.get(name)
        if not spec:
            continue
        when = spec.get("when", [])
        if when and all(cond in feats for cond in when):
            chosen = (name, spec)
            break

    if chosen is None:
        # fall back to person_research if any anchor exists, else knowledge-only
        spec = task_types.get("person_research", {"domains": ["KNO"], "patterns": []})
        chosen = ("person_research", spec)

    name, spec = chosen
    return Route(
        task_type=name,
        domains=tuple(spec.get("domains", [])),
        pattern_ids=tuple(spec.get("patterns", [])),
        features=tuple(sorted(feats)),
    )


def domain_names(codes: tuple[str, ...], registry: Registry | None = None) -> list[str]:
    reg = registry or load_registry()
    doms = reg.domains.get("domains", {})
    return [f"{c} ({doms.get(c, {}).get('name', 'unknown')})" for c in codes]
