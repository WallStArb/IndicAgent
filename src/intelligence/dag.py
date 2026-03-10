from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from typing import Any


@dataclass
class DagNode:
    node_id: str
    node_type: str  # plugin | join | sink | source
    config: dict[str, Any] = field(default_factory=dict)
    inputs: list[str] = field(default_factory=list)


@dataclass
class Dag:
    nodes: dict[str, DagNode] = field(default_factory=dict)
    edges: list[tuple[str, str]] = field(default_factory=list)  # (from, to)

    def add_node(self, node: DagNode) -> None:
        self.nodes[node.node_id] = node

    def add_edge(self, src: str, dst: str) -> None:
        self.edges.append((src, dst))

    def topological_order(self) -> list[str]:
        # Simple Kahn topo-sort
        indeg: dict[str, int] = {k: 0 for k in self.nodes}
        for _a, b in self.edges:
            indeg[b] += 1
        queue = deque([k for k, v in indeg.items() if v == 0])
        order: list[str] = []
        adj: dict[str, list[str]] = {}
        for a, b in self.edges:
            adj.setdefault(a, []).append(b)
        while queue:
            n = queue.popleft()
            order.append(n)
            for m in adj.get(n, []):
                indeg[m] -= 1
                if indeg[m] == 0:
                    queue.append(m)
        if len(order) != len(self.nodes):
            raise ValueError("DAG contains a cycle")
        return order
