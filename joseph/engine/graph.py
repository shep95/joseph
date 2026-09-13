"""evidence graph.

builds a small directed graph linking the subject to organizations, locations,
documents, domains, profiles, and pages, with typed edges backed by the result that
produced each link. degree centrality is computed deterministically so the report can
highlight the most connected nodes.

this is a lightweight adjacency structure, not a full graph database; community
detection and link prediction are deliberately left as extension points.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .entities import Entity
from .normalize import Result
from .resolution import ResolvedEntity
from .seed import IdentitySeed


@dataclass
class Node:
    id: str
    kind: str          # person | organization | location | document | domain | profile | page | username | email
    label: str
    attrs: dict = field(default_factory=dict)


@dataclass
class Edge:
    source: str
    target: str
    relation: str      # WORKS_AT | LOCATED_IN | AUTHORED | ASSOCIATED_WITH | USES | MENTIONED_IN
    evidence: str = "" # canonical url or query origin
    confidence: float = 0.0


@dataclass
class EvidenceGraph:
    nodes: dict[str, Node] = field(default_factory=dict)
    edges: list[Edge] = field(default_factory=list)

    def add_node(self, node: Node) -> None:
        if node.id not in self.nodes:
            self.nodes[node.id] = node

    def add_edge(self, edge: Edge) -> None:
        self.edges.append(edge)

    def degree(self) -> dict[str, int]:
        deg: dict[str, int] = {nid: 0 for nid in self.nodes}
        for e in self.edges:
            deg[e.source] = deg.get(e.source, 0) + 1
            deg[e.target] = deg.get(e.target, 0) + 1
        return deg

    def top_nodes(self, limit: int = 10) -> list[tuple[Node, int]]:
        deg = self.degree()
        ranked = sorted(self.nodes.values(), key=lambda n: (-deg.get(n.id, 0), n.id))
        return [(n, deg.get(n.id, 0)) for n in ranked[:limit]]


def _nid(kind: str, value: str) -> str:
    return f"{kind}:{value.lower()}"


def build_graph(
    seed: IdentitySeed,
    results: list[Result],
    resolved: list[ResolvedEntity],
) -> EvidenceGraph:
    g = EvidenceGraph()

    subject_label = seed.name or (seed.usernames[0] if seed.usernames else "subject")
    subject_id = _nid("person", subject_label)
    g.add_node(Node(id=subject_id, kind="person", label=subject_label, attrs={"seed": True}))

    # seed-derived context nodes
    for org in seed.organizations:
        oid = _nid("organization", org)
        g.add_node(Node(id=oid, kind="organization", label=org))
        g.add_edge(Edge(subject_id, oid, "WORKS_AT", evidence="seed", confidence=0.5))
    for loc in seed.locations:
        lid = _nid("location", loc)
        g.add_node(Node(id=lid, kind="location", label=loc))
        g.add_edge(Edge(subject_id, lid, "LOCATED_IN", evidence="seed", confidence=0.4))
    for user in seed.usernames:
        uid = _nid("username", user)
        g.add_node(Node(id=uid, kind="username", label=user))
        g.add_edge(Edge(subject_id, uid, "USES", evidence="seed", confidence=0.8))

    # resolved entities become nodes with confidence from their verdict score
    for r in resolved:
        e = r.entity
        kind = "profile" if e.kind == "profile" else e.kind
        label = f"{e.surface}:{e.value}" if e.surface else e.value
        eid = _nid(kind, label)
        g.add_node(Node(id=eid, kind=kind, label=label, attrs={"verdict": r.verdict, "features": list(r.features)}))
        relation = "USES" if kind in {"username", "handle", "profile", "email"} else "ASSOCIATED_WITH"
        g.add_edge(Edge(subject_id, eid, relation, evidence=e.source_url, confidence=r.score))

    # pages/documents become nodes linked by mention
    for res in results:
        is_doc = any(res.path.lower().endswith(ext) for ext in (".pdf", ".doc", ".docx", ".ppt", ".pptx", ".xls", ".xlsx"))
        kind = "document" if is_doc else "page"
        pid = _nid(kind, res.canonical)
        g.add_node(Node(id=pid, kind=kind, label=res.title or res.canonical, attrs={"url": res.canonical, "relevance": res.relevance}))
        relation = "AUTHORED" if is_doc else "MENTIONED_IN"
        g.add_edge(Edge(subject_id, pid, relation, evidence=res.canonical, confidence=min(1.0, res.relevance / 5.0)))
        # link page to its domain
        if res.domain:
            did = _nid("domain", res.domain)
            g.add_node(Node(id=did, kind="domain", label=res.domain))
            g.add_edge(Edge(pid, did, "ASSOCIATED_WITH", evidence=res.canonical, confidence=0.3))

    return g
