# Multi-Stage SPICE Validation Failure Analysis

**Status: under investigation, manual analysis needed**

Generated: 2026-04-28
Batch: data/raw_l2v6 (50 samples, level 2, max-stages 3)
Result: 30 PASS / 20 FAIL

---

## Conclusion

The DAG's **independent-stage bias assumption** does not fully hold once stages are
physically connected. In a multi-stage circuit, shared nodes create KCL couplings
that the per-stage DC design ignores. Additionally, one failure class is a pure
ngspice simulation artifact unrelated to DAG correctness.

---

## Root Cause 1 — ngspice false convergence (SF source node)

**Topologies affected:** `cs_current_source+sf_resistor`,
`cs_current_source+cg_resistor+sf_resistor`, `cs_current_source+sf_resistor+cg_resistor`,
and any topology where an SF stage's source node has only an Rs to GND.

**Mechanism:**  
ngspice's DC operating-point solver starts every node at 0 V. For the SF stage the
source node `sout` has a unique equation:

```
ID_SF(VGS=VG−Vsout, VDS=VDD−Vsout) = Vsout / Rs
```

The correct solution is `Vsout ≈ 2 V`, `ID ≈ 7×10⁻⁵ A`. However Newton-Raphson
can converge to a KCL-violating false fixed point near `Vsout = 0 V` where the
MOSFET reports `VGS = 1.0 V`, `ID = 1.38×10⁻⁴ A` internally, while the circuit
node voltage (and hence Rs current) remains ≈ 0.

**Proof:** Adding `.NODESET V(sout)=2.0` to the netlist makes ngspice converge to
`Vsout = 2.019 V`, `ID = 7.15×10⁻⁵ A` — matching the DAG prediction (7.08×10⁻⁵ A)
to < 1 % error.

**Implication:** The DAG is computing the correct answer for this class; the SPICE
validation is reporting a spurious FAIL. Fix: emit `.NODESET` hints for SF source
nodes in the netlist writer, initialising them to `VG_DC - VGS_design`.

---

## Root Cause 2 — CG current injection into CS+ICS drain node

**Topologies affected:** `cs_current_source+cg_resistor+...`

**Mechanism:**  
When a CG stage has its source connected to the CS+ICS drain node, the CG
transistor's conventional drain current flows *into* that shared node:

```
KCL at drain:  I1 (current source) + ID_CG = ID_M1 (CS+ICS)
```

DAG assumes `ID_M1 = I1` (independent bias). In practice the extra `ID_CG` term
forces VD to rise until VGS_CG = Vg_bias − VD ≤ Vth, i.e. the CG transistor
enters cutoff. Measured shift: VD rises from designed 1.91 V to ≈ 2.32 V;
SPICE then reports `ID_CG ≈ 2.7×10⁻⁶ A` (effectively off) vs `ID_CG_dag ≈ 8.5×10⁻⁵ A`.

**Implication:** The CS+ICS drain node Q-point is valid only when loaded by the
*designed* gate current of the next stage (which is zero for MOSFET gates). A CG
stage whose source connects here adds non-zero DC current and invalidates the
independent-bias assumption.

---

## Root Cause 3 — Shared source-node Rs in SF → CG cascade

**Topologies affected:** `sf_resistor+cg_resistor`, `sf_resistor+cg_resistor+sf_resistor`

**Mechanism:**  
The compositor correctly connects SF source → CG source (standard cascade). Both
transistors' currents flow through the single Rs to GND:

```
V_source = (ID_SF + ID_CG) × Rs
```

DAG designs the SF stage assuming `V_source = ID_SF × Rs` and separately designs
the CG stage with `Vin_DC = V_source_designed`. At the designed individual currents
the combined VS = (1.03×10⁻⁵ + 1.08×10⁻⁴) × 109 kΩ > VDD — physically impossible.

SPICE equilibrium: VS rises until SF enters cutoff (`VGS_SF < Vth`), leaving only
CG conducting. SPICE reports `ID_SF ≈ 5×10⁻¹²` (off) and `ID_CG ≈ 1.3×10⁻⁵ A`
(vs `ID_CG_dag ≈ 1.08×10⁻⁴ A`).

**Implication:** For cascades sharing a source-node Rs, the parametrisation must
solve for both transistors' operating points jointly, accounting for `V_source =
(ΣID) × Rs`.

---

## Summary Table

| Root cause | Affected topologies (examples) | DAG correct? | Fix direction |
|---|---|---|---|
| 1. ngspice false convergence | `cs_current_source+sf_*` | **Yes** | Add `.NODESET` for SF source |
| 2. CG injects into CS+ICS drain | `cs_current_source+cg_*` | No — KCL coupling ignored | Joint drain-node Q-point solve |
| 3. SF+CG shared Rs | `sf_*+cg_*` | No — ΣID through Rs ignored | Joint source-node Q-point solve |
