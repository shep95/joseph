"""pattern knowledge graph.

builds a directed graph from the registry where nodes are patterns (and the concepts they
reference) and edges are typed by the relation algebra. the engine traverses known
relations; it does not infer what a relation means.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .registry import Registry, load_registry


@dataclass
class KnowledgeGraph:
    edges: list[tuple[str, str, str]] = field(default_factory=list)  # (source, relation, target)
    _out: dict[str, list[tuple[str, str]]] = field(default_factory=dict)

    def add(self, source: str, relation: str, target: str) -> None:
        self.edges.append((source, relation, target))
        self._out.setdefault(source, []).append((relation, target))

    def neighbors(self, node: str, relation: str | None = None) -> list[tuple[str, str]]:
        out = self._out.get(node, [])
        if relation is None:
            return list(out)
        return [(r, t) for (r, t) in out if r == relation]

    def related(self, node: str, relation: str) -> list[str]:
        return [t for (r, t) in self.neighbors(node, relation)]

    def conflicts(self, node: str) -> list[str]:
        return self.related(node, "CONTRADICTS") + self.related(node, "COMPETES_WITH")

    def composed_with(self, node: str) -> list[str]:
        return self.related(node, "COMPOSED_WITH") + self.related(node, "COMPLEMENTS")

    def repairs_for(self, node: str) -> list[str]:
        return self.related(node, "REPAIRS")


def build_graph(registry: Registry | None = None) -> KnowledgeGraph:
    reg = registry or load_registry()
    g = KnowledgeGraph()
    for p in reg.patterns.values():
        for relation, targets in p.relations.items():
            for target in targets:
                g.add(p.id, relation, target)
    return g
