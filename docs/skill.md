# Skill

## Purpose
This skill defines a standard, reusable procedure for analyzing CMOS / MOSFET analog circuits.  
It is intended for an agent that needs to:
1. determine DC operating points (Q-points),
2. identify transistor operating regions,
3. derive low-frequency small-signal behavior,
4. extend to high-frequency analysis,
5. relate poles and zeros to the circuit structure.

This skill is especially useful for:
- single-stage amplifiers,
- source followers,
- common-gate stages,
- cascodes,
- current-mirror biased stages,
- multi-transistor analog subcircuits.

---

## Core Principle

Always analyze in this order:

1. **Recognize topology**
2. **Solve DC / large-signal bias point (Q-point)**
3. **Verify transistor operating regions**
4. **Build low-frequency small-signal model**
5. **Compute gain / Rin / Rout**
6. **Add parasitic and load capacitances for high-frequency analysis**
7. **Derive or approximate poles and zeros**
8. **Check whether the result is physically and structurally reasonable**

Do **not** start from `gm`, `ro`, poles, or zeros before establishing the DC operating point.

---

## Definitions

### Q-point
The Q-point (quiescent point) is the DC operating point of the circuit when all small-signal inputs are set to zero.

For each MOSFET, the Q-point typically includes:
- `VG`, `VS`, `VD`, `VB`
- `VGS`, `VDS`, `VBS`
- `ID`
- operating region:
  - cutoff
  - triode
  - saturation

### Large-signal analysis
Large-signal analysis uses the MOSFET's nonlinear DC equations to determine bias currents and node voltages.

### Small-signal analysis
Small-signal analysis linearizes each MOSFET around its Q-point and studies how small perturbations propagate.

### Low-frequency analysis
Low-frequency small-signal analysis ignores parasitic capacitances and focuses on gain and resistance behavior.

### High-frequency analysis
High-frequency analysis includes parasitic and explicit capacitors, then studies bandwidth, poles, zeros, and phase.

---

## Inputs Expected by This Skill

The agent should gather, infer, or be provided with:

- circuit topology / connectivity,
- transistor types (`NMOS`, `PMOS`),
- supply voltages,
- bias voltages / bias currents,
- resistor values,
- capacitor values (explicit and parasitic if available),
- transistor parameters when needed:
  - threshold voltage `VTH`,
  - transconductance parameter `k = μCox(W/L)` or equivalent,
  - channel-length modulation `λ`,
  - body-effect coefficient if relevant.

If numerical values are not available, symbolic analysis is allowed, but Q-point conditions must still be stated explicitly.

---

## Required Analysis Workflow

# Step 1: Recognize the topology

Identify:
- input node,
- output node,
- bias network,
- active load / current-source load,
- whether the stage is:
  - common source,
  - source follower,
  - common gate,
  - cascode,
  - differential pair,
  - current mirror based,
  - composite / multistage.

Record:
- which transistor converts `vgs` to current,
- which element converts current to output voltage,
- which nodes are likely high-impedance,
- which nodes are likely candidates for dominant poles.

---

# Step 2: Convert the circuit to DC form

For DC / Q-point analysis:
- set AC signal sources to zero,
- open-circuit capacitors,
- short-circuit inductors,
- keep DC supplies and bias sources active.

This produces the pure bias network.

---

# Step 3: Solve the Q-point using large-signal equations

For each MOSFET, define:
- `VGS = VG - VS`
- `VDS = VD - VS`
- `VBS = VB - VS`

For PMOS, often use:
- `VSG = VS - VG`
- `VSD = VS - VD`

## NMOS operating-region conditions

### Cutoff
Condition:
`VGS < VTH`

Approximation:
`ID ≈ 0`

### Triode
Condition:
`VGS > VTH` and `VDS < VGS - VTH`

Equation:
`ID = k_n[(VGS - VTH)VDS - VDS^2/2]`

### Saturation
Condition:
`VGS > VTH` and `VDS >= VGS - VTH`

Without channel-length modulation:
`ID = (1/2) k_n (VGS - VTH)^2`

With channel-length modulation:
`ID = (1/2) k_n (VGS - VTH)^2 (1 + λVDS)`

## PMOS operating-region conditions

### Cutoff
Condition:
`VSG < |VTP|`

Approximation:
`|ID| ≈ 0`

### Triode
Condition:
`VSG > |VTP|` and `VSD < VSG - |VTP|`

Equation:
`|ID| = k_p[(VSG - |VTP|)VSD - VSD^2/2]`

### Saturation
Condition:
`VSG > |VTP|` and `VSD >= VSG - |VTP|`

Without channel-length modulation:
`|ID| = (1/2) k_p (VSG - |VTP|)^2`

With channel-length modulation:
`|ID| = (1/2) k_p (VSG - |VTP|)^2 (1 + λVSD)`

## DC solution procedure

For each transistor:
1. make an initial region assumption,
2. write the corresponding large-signal current equation,
3. combine with KCL/KVL and resistor/source relations,
4. solve for currents and node voltages,
5. verify the assumed region,
6. if the condition fails, switch region and solve again.

### Typical supporting circuit equations
Examples:
- resistor current: `I = V / R`
- drain node with resistor load: `VD = VDD - ID * RD`
- source degeneration: `VS = ID * RS`
- thus `VGS = VG - ID * RS`
- and `VDS = VD - VS`

Important:  
The Q-point is a **self-consistent DC solution**, not just a direct substitution into one MOS equation.

---

# Step 4: Sanity-check the Q-point

After solving, always check:
- are all transistor currents physically reasonable?
- are all node voltages within supply rails?
- does each transistor actually satisfy its assumed region?
- is there enough headroom for saturation?
- does the output DC level leave room for signal swing?

If any answer is no, the Q-point is invalid or incomplete.

---

# Step 5: Build the low-frequency small-signal model

Only after the Q-point is known, compute small-signal parameters.

## Common small-signal parameters

For a MOSFET in saturation:

- overdrive:
  `VOV = VGS - VTH`

- transconductance:
  `gm = ∂ID/∂VGS |_Q`

Common equivalent forms:
- `gm = k_n VOV`
- `gm = 2ID / VOV`

If channel-length modulation is included:
- `ro ≈ 1 / (λ ID)`

If body effect matters:
- include `gmb vbs`

## Low-frequency small-signal model elements
Use:
- dependent current source `gm vgs`,
- output resistance `ro`,
- optionally `gmb vbs`.

Ignore parasitic capacitances in low-frequency analysis.

---

# Step 6: Compute low-frequency gain and impedances

Depending on topology, derive:
- voltage gain `Av`,
- current gain if needed,
- input resistance `Rin`,
- output resistance `Rout`.

Typical examples:

## Common source
Approximate low-frequency gain:
`Av ≈ -gm (RD || ro || Rload_equivalent)`

## Source follower
Approximate gain:
`Av ≈ gm * Req / (1 + gm * Req)`
where `Req` is the effective small-signal resistance seen at the source.

## Common gate
Often:
- low input resistance,
- current-buffering behavior,
- voltage gain depends on output load and `gm`.

Do not rely on memorized formulas blindly.  
Always map the small-signal model to the actual circuit first.

---

# Step 7: Extend to high-frequency analysis

Now include:
- `Cgs`
- `Cgd`
- `Cdb`
- `Csb`
- explicit load capacitor `CL`
- coupling / bypass capacitors if present

Determine:
- which nodes are high-impedance,
- which capacitances are attached to those nodes,
- whether Miller multiplication applies,
- whether feedforward paths exist.

High-frequency analysis usually aims to obtain:
`H(s) = Vo(s) / Vi(s)`

---

# Step 8: Find poles and zeros

## Key principle
Poles and zeros belong to the **linearized small-signal transfer function**, not directly to the nonlinear large-signal circuit.

Therefore:
- Q-point first,
- small-signal model second,
- capacitances third,
- poles/zeros last.

## Pole intuition
Poles usually come from:
- high resistance × significant capacitance,
- internal high-impedance nodes,
- output node loading.

A common estimate:
`p ≈ -1 / (R_eq C_eq)`

The lowest-frequency pole is often the dominant pole.

## Zero intuition
Zeros often come from:
- feedforward paths,
- `Cgd`,
- compensation networks,
- numerator factors introduced by current splitting paths.

Watch for:
- left-half-plane zeros (often helpful or neutral),
- right-half-plane zeros (often harmful for phase).

---

## Recommended approximation methods
When exact transfer functions are cumbersome, use:
- Miller approximation,
- open-circuit time constants (OCTC),
- time-constant based pole estimation,
- transfer-constant / time-constant methods when appropriate.

---

## Relationship Between Analysis Layers

The agent should preserve this dependency chain:

`Large-signal bias -> Q-point -> gm, ro -> low-frequency small-signal behavior -> capacitance-aware model -> poles and zeros`

Interpretation:
- Q-point determines `gm` and `ro`,
- `gm` and `ro` determine low-frequency gain,
- node resistances plus capacitances determine poles,
- feedforward capacitive/current paths can create zeros.

---

## Output Format Recommended for the Agent

When analyzing a circuit, the agent should structure the answer like this:

### 1. Topology identification
- circuit type,
- input/output nodes,
- role of each transistor.

### 2. DC / Q-point analysis
- equations used,
- unknowns,
- solved node voltages and currents,
- operating region of each transistor.

### 3. Small-signal parameter extraction
- `gm`,
- `ro`,
- optional `gmb`.

### 4. Low-frequency result
- gain,
- `Rin`,
- `Rout`,
- phase inversion or non-inversion.

### 5. High-frequency result
- relevant capacitances,
- dominant nodes,
- estimated poles,
- possible zeros,
- comments on bandwidth / stability.

### 6. Physical interpretation
- what sets gain,
- what limits bandwidth,
- what changes if bias current or load changes,
- whether the result matches circuit intuition.

---

## Checklist Before Finalizing an Analysis

The agent must check all of the following:

- [ ] Was the topology identified correctly?
- [ ] Were all capacitors removed for DC analysis?
- [ ] Was the Q-point solved before using `gm` or `ro`?
- [ ] Was each MOS operating region explicitly verified?
- [ ] Are the small-signal parameters tied to the Q-point?
- [ ] Were parasitics included only in the high-frequency stage?
- [ ] Are poles associated with actual RC nodes?
- [ ] Are zeros explained by actual circuit paths?
- [ ] Does the sign of gain match the topology?
- [ ] Are the results physically plausible?

---

## Common Failure Modes

### Failure 1: Starting from `gm` without solving Q-point
This is incorrect because `gm` depends on `ID` and `VOV`, which come from the Q-point.

### Failure 2: Assuming saturation without verification
Common and dangerous. Always verify:
`VDS >= VGS - VTH` for NMOS saturation  
or
`VSD >= VSG - |VTP|` for PMOS saturation.

### Failure 3: Mixing large-signal and small-signal equations
Do not use small-signal formulas to determine DC bias.

### Failure 4: Discussing poles/zeros before adding capacitances
A resistor-only small-signal circuit does not generate frequency poles/zeros in the same way.

### Failure 5: Blind formula substitution without topology reasoning
Even familiar stages can have altered gain and pole locations if the load, biasing, or output resistance changes.

---

## Minimal Example Template

Use this template when the circuit is simple:

1. Set AC sources to zero and open capacitors.
2. Write `VGS`, `VDS`, and any resistor relations.
3. Assume operating region.
4. Use the corresponding DC current equation.
5. Solve for `ID`, `VD`, `VS`, etc.
6. Verify region conditions.
7. Compute `gm`, `ro`.
8. Draw/construct small-signal model.
9. Solve for low-frequency gain.
10. Add capacitances and estimate poles/zeros.

---

## When Symbolic Analysis Is Acceptable

Symbolic analysis is acceptable when:
- the user requests structural understanding,
- the device parameters are not fully specified,
- the objective is derivation rather than numerical design.

Even then, the agent should still:
- state region assumptions clearly,
- keep the Q-point relationships explicit,
- distinguish symbolic Q-point expressions from actual numerical operating points.

---

## When Numerical Analysis Is Required

Numerical analysis is required when:
- the user asks for an actual Q-point,
- `gm`, `ro`, gain, bandwidth, poles, or zeros must be numerically evaluated,
- saturation/headroom must be checked concretely,
- comparison across design options is needed.

---

## Final Rule

For MOS analog circuits, the agent must think in this order:

**Bias first. Linearize second. Frequency response third. Poles and zeros last.**

If this order is violated, the analysis is likely unreliable.


---

## Mandatory Result Recording and Saving

After completing any analysis, the agent must **save the final result using the standard analysis record template**.

### Required Behavior
The agent must produce analysis results in **two forms**:
1. a human-readable structured report following the template sections,
2. a machine-storable result file using the same section order and field names.

### Standard Output File Naming
Unless the user specifies otherwise, save the analysis record using:

- Markdown report:
  `analysis_result_<circuit_name_or_id>.md`

Optional additional export:
- YAML or JSON summary:
  `analysis_result_<circuit_name_or_id>.yaml`
  or
  `analysis_result_<circuit_name_or_id>.json`

### Required Template for Saved Results
The saved analysis result must follow the file:
`cmos_mosfet_analysis_result_template.md`

The agent must not omit any section silently.  
If a field is unavailable, write one of:
- `not provided`
- `not applicable`
- `not derived`
- `requires additional parameters`

### Minimum Required Saved Sections
Every saved analysis result must contain all of the following sections in order:

1. `Analysis Metadata`
2. `Circuit Metadata`
3. `Inputs and Assumptions`
4. `DC / Large-Signal Q-Point Analysis`
5. `Small-Signal Parameter Extraction`
6. `Low-Frequency Small-Signal Analysis`
7. `High-Frequency Analysis`
8. `Poles and Zeros`
9. `Sensitivity / Design Insight`
10. `Final Validation Checklist`
11. `Final Summary`

### Per-Step Recording Requirements

#### During topology recognition, record:
- topology,
- stage count,
- input/output nodes,
- device inventory,
- high-impedance nodes,
- expected gain polarity.

#### During DC analysis, record:
- all equations used,
- all unknowns solved,
- per-device node voltages and currents,
- assumed and verified operating regions,
- DC output voltage,
- total current and DC power,
- headroom / saturation margins.

#### During small-signal extraction, record:
- `VOV`,
- `gm`,
- `ro`,
- `gmb` if used,
- any equivalent transconductance or resistance values.

#### During low-frequency analysis, record:
- symbolic expressions if derived,
- numerical gain,
- gain sign,
- `Rin`,
- `Rout`,
- stage-by-stage results if multistage,
- short physical interpretation.

#### During high-frequency analysis, record:
- all included capacitances,
- node-wise `Req`, `Ceq`, and time constants where estimated,
- Miller assessment,
- feedforward assessment,
- method used for approximation.

#### During pole-zero analysis, record:
- each pole with expression and numeric location,
- each zero with expression and numeric location,
- whether each zero is LHP or RHP,
- dominant pole,
- bandwidth / UGF / margins if available,
- interpretation of what physically creates each major pole/zero.

#### During finalization, record:
- checklist results,
- confidence level,
- major warnings,
- recommended next action.

### Save Rule
The analysis is **not complete** until the result has been formatted according to the template and saved.

### Compact Summary Requirement
In addition to the full saved report, include a compact machine-readable summary block at the end of the saved result.

### Failure Handling
If the analysis cannot be completed fully, still save a partial result using the same template and explicitly mark unresolved fields as:
- `not solved`
- `ambiguous`
- `insufficient circuit information`

### Final Enforcement Rule
For every analyzed circuit, the agent must follow this order:

`analyze -> populate template -> validate completeness -> save result`

Do not stop at derivation alone.  
A correct analysis workflow includes structured result persistence.
