"""Stage compositor: builds a Circuit by merging StageSpec incidence matrices.

Uses Union-Find to merge nodes across stage instances (ADR-007 D4).

Public API:
    compose_stages(instances, interconnections, given) → Circuit

'instances' is a list of (stage_id, StageSpec) pairs.
'interconnections' is a list of (left_ref, right_ref) string pairs where each
ref has the form  "stage_id.port_name", e.g. ("cs1.vout", "load1.load_bot").
'given' is the parameter dict (used to populate Node.voltage_dc).

The compositor does NOT import rules.py or dag_executor.py.
"""

from __future__ import annotations

import uuid
from typing import Optional

from src.topology.models import Circuit, Device, IncidenceMatrix, Node
from src.topology.stage_spec import StageSpec


# ---------------------------------------------------------------------------
# Union-Find (path-compressed, rank-based)
# ---------------------------------------------------------------------------

class _UnionFind:
    def __init__(self) -> None:
        self._parent: dict[str, str] = {}
        self._rank:   dict[str, int] = {}

    def add(self, x: str) -> None:
        if x not in self._parent:
            self._parent[x] = x
            self._rank[x]   = 0

    def find(self, x: str) -> str:
        while self._parent[x] != x:
            self._parent[x] = self._parent[self._parent[x]]  # path compression
            x = self._parent[x]
        return x

    def union(self, a: str, b: str) -> None:
        ra, rb = self.find(a), self.find(b)
        if ra == rb:
            return
        if self._rank[ra] < self._rank[rb]:
            ra, rb = rb, ra
        self._parent[rb] = ra
        if self._rank[ra] == self._rank[rb]:
            self._rank[ra] += 1

    def representatives(self) -> set[str]:
        return {self.find(x) for x in self._parent}


# ---------------------------------------------------------------------------
# Node role resolution
# ---------------------------------------------------------------------------

_PORT_KIND_TO_ROLE: dict[str, str] = {
    "supply":   "supply",
    "ground":   "ground",
    "input":    "input",
    "output":   "output",
    "load_top": "output",
    "load_bot": "output",
}


def _merge_role(current: Optional[str], port_kind: str) -> str:
    """Priority: supply > ground > input > output > internal.

    Special case (ADR-008 D2): when an output node is merged with an input
    node the resulting node is internal — it is driven by the previous stage
    and must NOT receive a V_ bias source from netlist_writer.
    """
    _PRIORITY = {"supply": 4, "ground": 3, "input": 2, "output": 1, "internal": 0}
    new_role = _PORT_KIND_TO_ROLE.get(port_kind, "internal")
    if current is None:
        return new_role
    # output ↔ input merge → internal (inter-stage driven node)
    if {current, new_role} == {"output", "input"}:
        return "internal"
    return current if _PRIORITY.get(current, 0) >= _PRIORITY.get(new_role, 0) else new_role


# ---------------------------------------------------------------------------
# Public compositor
# ---------------------------------------------------------------------------

def compose_stages(
    instances: list[tuple[str, StageSpec]],
    interconnections: list[tuple[str, str]],
    given: dict[str, float],
    sample_id: Optional[str] = None,
    stage_indices: Optional[list[int]] = None,
) -> Circuit:
    """Compose a list of stage instances into a single Circuit.

    Args:
        instances:        [(stage_id, StageSpec), …] in signal-first order.
        interconnections: [("stage_a.port_name", "stage_b.port_name"), …]
        given:            Parameter dict; used for Node.voltage_dc.
        sample_id:        Optional Circuit sample identifier.
        stage_indices:    If set, a list of 1-based stage numbers parallel to instances.
                          When provided, device param lookup tries the suffixed key first
                          (e.g. "RD_s2") before the bare key ("RD").

    Returns: Circuit with merged IncidenceMatrix, devices, and nodes.
    """
    uf = _UnionFind()

    # Build stage-id → stage-index map early (used for DC voltage + device param lookup)
    _stage_idx_map: dict[str, int] = {}
    if stage_indices is not None:
        for (sid, _), idx in zip(instances, stage_indices):
            _stage_idx_map[sid] = idx

    def _given_lookup(key: str, stage_id: str) -> Optional[float]:
        """Look up given-dict key, trying the stage-suffixed form first."""
        s_idx = _stage_idx_map.get(stage_id)
        if s_idx is not None:
            v = given.get(f"{key}_s{s_idx}")
            if v is not None:
                return float(v)
        v = given.get(key)
        return float(v) if v is not None else None

    # Map: (stage_id, local_node) → prefixed node name
    def _pnode(stage_id: str, local_node: str) -> str:
        return f"{stage_id}.{local_node}"

    # Register all stage-local nodes
    for stage_id, spec in instances:
        for local_node in spec.local_nodes:
            uf.add(_pnode(stage_id, local_node))

    # Register and add global supply / ground singletons
    uf.add("VDD")
    uf.add("GND")

    # Merge supply ports → VDD, ground ports → GND
    # Only ports with role=="vdd" connect to the global VDD rail; other supply-kind
    # ports (e.g., CG gate-bias supply) are independent nodes.
    for stage_id, spec in instances:
        for port in spec.ports.values():
            if port.kind == "supply" and port.role == "vdd" and port.node_ref:
                uf.union(_pnode(stage_id, port.node_ref), "VDD")
            elif port.kind == "ground" and port.node_ref:
                uf.union(_pnode(stage_id, port.node_ref), "GND")

    # Merge interconnections
    for left_ref, right_ref in interconnections:
        stage_a, port_a = left_ref.split(".", 1)
        stage_b, port_b = right_ref.split(".", 1)
        spec_a = dict(instances)[stage_a]
        spec_b = dict(instances)[stage_b]
        node_a = _pnode(stage_a, spec_a.ports[port_a].node_ref)
        node_b = _pnode(stage_b, spec_b.ports[port_b].node_ref)
        uf.add(node_a)
        uf.add(node_b)
        uf.union(node_a, node_b)

    # Build a canonical name for each representative
    # Prefer "VDD" / "GND" as canonical names; otherwise use short descriptive names
    rep_to_name: dict[str, str] = {}
    rep_to_role: dict[str, Optional[str]] = {}
    rep_to_dc:   dict[str, Optional[float]] = {}

    def _assign_rep(rep: str) -> None:
        if rep not in rep_to_name:
            if rep == "VDD" or uf.find("VDD") == rep:
                rep_to_name[rep] = "VDD"
                rep_to_role[rep] = "supply"
                rep_to_dc[rep]   = float(given.get("VDD", 0.0))
            elif rep == "GND" or uf.find("GND") == rep:
                rep_to_name[rep] = "GND"
                rep_to_role[rep] = "ground"
                rep_to_dc[rep]   = 0.0
            else:
                # Derive from the representative string: "stage_id.local_node" → local_node
                rep_to_name[rep] = rep.split(".", 1)[-1] if "." in rep else rep
                rep_to_role[rep] = None
                rep_to_dc[rep]   = None

    for stage_id, spec in instances:
        for local_node in spec.local_nodes:
            pn = _pnode(stage_id, local_node)
            rep = uf.find(pn)
            _assign_rep(rep)

    # Always register VDD and GND reps
    _assign_rep(uf.find("VDD"))
    _assign_rep(uf.find("GND"))

    # Accumulate port metadata onto representatives
    for stage_id, spec in instances:
        for port_name, port in spec.ports.items():
            if not port.node_ref:
                continue
            pn  = _pnode(stage_id, port.node_ref)
            rep = uf.find(pn)
            _assign_rep(rep)
            # Role
            rep_to_role[rep] = _merge_role(rep_to_role.get(rep), port.kind)
            # DC voltage (try stage-suffixed key first, then bare key)
            if port.dc_from_given and rep_to_dc.get(rep) is None:
                v = _given_lookup(port.dc_from_given, stage_id)
                rep_to_dc[rep] = v if v is not None else 0.0

    # Fill in any remaining "input" port DC values not yet set
    for stage_id, spec in instances:
        for port_name, port in spec.ports.items():
            if not port.node_ref or not port.dc_from_given:
                continue
            pn  = _pnode(stage_id, port.node_ref)
            rep = uf.find(pn)
            if rep_to_dc.get(rep) is None:
                v = _given_lookup(port.dc_from_given, stage_id)
                rep_to_dc[rep] = v if v is not None else 0.0

    # Deduplicate node names (handle collisions by appending stage_id suffix)
    name_to_rep: dict[str, str] = {}
    for rep, name in list(rep_to_name.items()):
        if name in name_to_rep and name_to_rep[name] != rep:
            # Collision: rename with suffix
            stage_hint = rep.split(".")[0] if "." in rep else rep
            new_name = f"{name}_{stage_hint}"
            rep_to_name[rep] = new_name
            name = new_name
        name_to_rep[name] = rep

    # Collect unique representatives (drop duplicates from re-mapping)
    unique_reps = list({uf.find(pn) for stage_id, spec in instances
                        for pn in [_pnode(stage_id, ln) for ln in spec.local_nodes]}
                       | {uf.find("VDD"), uf.find("GND")})

    # Build global nodes dict
    global_nodes: dict[str, Node] = {}
    for rep in unique_reps:
        _assign_rep(rep)
        node_name = rep_to_name[rep]
        role = rep_to_role.get(rep) or "internal"
        dc   = rep_to_dc.get(rep)
        global_nodes[node_name] = Node(id=node_name, role=role, voltage_dc=dc)

    # Build global devices dict and merged incidence terminals
    # Collect: for each device terminal, which global node is it connected to?
    global_devices:  dict[str, Device] = {}
    all_terminals:   list[str] = []
    terminal_to_node: dict[str, str] = {}   # terminal_key → global node name

    for stage_id, spec in instances:
        for dev_spec in spec.devices:
            dev_id = dev_spec.local_id   # keep original ID (M1, RD, I1, …)

            # Disambiguate collisions across stages
            if dev_id in global_devices:
                dev_id = f"{dev_spec.local_id}_{stage_id}"

            def _get(key: str, _sid: str = stage_id) -> Optional[float]:
                return _given_lookup(key, _sid)

            # Build metadata from given dict
            meta: dict = {}
            if dev_spec.kind in ("nmos", "pmos"):
                meta["W"] = float(_get("W") or 1e-6)
                meta["L"] = float(_get("L") or 1e-7)
            elif dev_spec.kind == "resistor":
                val = None
                for pk in dev_spec.param_keys:
                    val = _get(pk)
                    if val is not None:
                        break
                meta["value"] = float(val) if val is not None else 1e4
            elif dev_spec.kind == "current_source":
                meta["value"] = float(_get("Iload") or 1e-4)

            global_devices[dev_id] = Device(
                id=dev_id,
                kind=dev_spec.kind,
                terminals=dev_spec.terminals,
                metadata=meta,
            )

            # Use the stage's local_incidence to map each terminal to its local node
            # local_inc uses dev_spec.local_id; global terminals use the (possibly renamed) dev_id
            local_inc = spec.local_incidence
            for term in dev_spec.terminals:
                local_term  = f"{dev_spec.local_id}.{term}"   # key in local_incidence
                global_term = f"{dev_id}.{term}"              # key in global IncidenceMatrix
                local_node  = local_inc.node_of_terminal(local_term)
                pn  = _pnode(stage_id, local_node)
                rep = uf.find(pn)
                global_node_name = rep_to_name[rep]
                terminal_to_node[global_term] = global_node_name
                all_terminals.append(global_term)

    # Rebuild global IncidenceMatrix
    global_node_list = list(global_nodes.keys())
    n_rows = len(global_node_list)
    n_cols = len(all_terminals)
    matrix = [[0] * n_cols for _ in range(n_rows)]
    for col_idx, term in enumerate(all_terminals):
        node_name = terminal_to_node[term]
        row_idx   = global_node_list.index(node_name)
        matrix[row_idx][col_idx] = 1

    global_incidence = IncidenceMatrix(
        nodes=global_node_list,
        terminals=all_terminals,
        matrix=matrix,
    )

    if sample_id is None:
        topo_hint = "_".join(s.stage_type for _, s in instances)
        sample_id = f"{topo_hint}_{uuid.uuid4().hex[:8]}"

    return Circuit(
        sample_id=sample_id,
        incidence=global_incidence,
        devices=global_devices,
        nodes=global_nodes,
    )
