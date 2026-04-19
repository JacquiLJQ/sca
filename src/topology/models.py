from __future__ import annotations

from typing import Any, Literal, Optional

import numpy as np
from pydantic import BaseModel, Field, model_validator


class Port(BaseModel):
    name: str
    type: Literal["signal_in", "signal_out", "bias_in", "bias_out", "supply"]
    terminal: Literal["G", "D", "S", "B"]
    polarity: Literal["inverting", "non_inverting", "differential"]
    impedance_level: Literal["high", "mid", "low"]
    dc_level: Literal["near_vdd", "mid", "near_gnd", "flexible"]
    differential_partner: Optional[str] = None
    internal_devices: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def check_differential_partner(self) -> Port:
        if self.polarity == "differential" and self.differential_partner is None:
            raise ValueError(
                f"Port '{self.name}': polarity='differential' requires differential_partner to be set"
            )
        return self


_MOSFET_TERMINALS: frozenset[str] = frozenset({"D", "G", "S", "B"})
_TWO_TERMINAL_TERMINALS: frozenset[str] = frozenset({"a", "b"})


class Device(BaseModel):
    id: str
    kind: Literal["nmos", "pmos", "resistor", "capacitor"]
    terminals: list[str]
    metadata: dict[str, Any] = Field(default_factory=dict)
    match_group_id: Optional[str] = None

    @model_validator(mode="after")
    def check_terminals_match_kind(self) -> Device:
        actual = frozenset(self.terminals)
        if self.kind in ("nmos", "pmos"):
            expected = _MOSFET_TERMINALS
        else:
            expected = _TWO_TERMINAL_TERMINALS
        if actual != expected:
            raise ValueError(
                f"Device '{self.id}' (kind='{self.kind}'): "
                f"expected terminals {sorted(expected)}, got {sorted(actual)}"
            )
        return self


class Node(BaseModel):
    id: str
    role: Literal["supply", "ground", "input", "output", "internal"]
    voltage_dc: Optional[float] = None


class IncidenceMatrix(BaseModel):
    nodes: list[str]
    terminals: list[str]
    matrix: list[list[int]]

    def to_numpy(self) -> np.ndarray:
        return np.array(self.matrix, dtype=np.int8)

    @classmethod
    def from_numpy(
        cls,
        arr: np.ndarray,
        nodes: list[str],
        terminals: list[str],
    ) -> IncidenceMatrix:
        return cls(nodes=nodes, terminals=terminals, matrix=arr.tolist())

    def validate_column_sum(self) -> bool:
        arr = self.to_numpy()
        if not bool(np.all((arr == 0) | (arr == 1))):
            return False
        return bool(np.all(arr.sum(axis=0) == 1))

    def node_of_terminal(self, terminal: str) -> str:
        """Return the node id connected to the given terminal column.

        Raises:
            KeyError: if terminal is not in this matrix.
            ValueError: if terminal has no connection (malformed matrix).
        """
        try:
            col_idx = self.terminals.index(terminal)
        except ValueError:
            raise KeyError(f"Terminal '{terminal}' not in incidence matrix")
        for row_idx, row in enumerate(self.matrix):
            if row[col_idx] == 1:
                return self.nodes[row_idx]
        raise ValueError(f"Terminal '{terminal}' has no node connection")

    def n_nodes(self) -> int:
        return len(self.nodes)

    def n_terminals(self) -> int:
        return len(self.terminals)


class Circuit(BaseModel):
    sample_id: str
    incidence: IncidenceMatrix
    devices: dict[str, Device]
    nodes: dict[str, Node]

    def check_consistency(self) -> None:
        expected: set[str] = {
            f"{dev_id}.{t}"
            for dev_id, dev in self.devices.items()
            for t in dev.terminals
        }
        actual = set(self.incidence.terminals)
        if expected != actual:
            missing = expected - actual
            extra = actual - expected
            raise ValueError(
                f"Terminal mismatch. Missing from incidence: {missing}. "
                f"Extra in incidence: {extra}."
            )