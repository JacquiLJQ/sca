# Template

Use this template to record the full analysis result for a CMOS / MOSFET analog circuit.

---

## 0. Analysis Metadata
- analysis_id:
- timestamp:
- analyst_or_agent:
- source_circuit_name:
- source_netlist_path:
- result_file_path:
- analysis_mode: symbolic / numerical / mixed
- notes:

---

## 1. Circuit Metadata
- topology:
- stage_count:
- input_node:
- output_node:
- supply_nodes:
- ground_node:
- bias_scheme:
- load_type:
- intended_function:

### 1.1 Device Inventory
List all active and key passive elements.

| element_id | type | role | connected_nodes | key_parameters |
|---|---|---|---|---|
| M1 | NMOS/PMOS | input transistor / active load / cascode / bias transistor / etc. |  |  |
| R1 | resistor | load / degeneration / bias |  |  |
| C1 | capacitor | load / compensation / parasitic / coupling / bypass |  |  |

### 1.2 Structural Interpretation
- transistor converting input voltage to current:
- element converting current to output voltage:
- likely high-impedance nodes:
- likely dominant-pole candidates:
- expected gain polarity:
- comments:

---

## 2. Inputs and Assumptions

### 2.1 Given Numerical Inputs
- VDD:
- VSS / GND:
- Vin,DC:
- bias voltages:
- bias currents:
- resistor values:
- capacitor values:
- load values:
- transistor model parameters:
  - VTH / VTP:
  - kn / kp:
  - lambda_n / lambda_p:
  - body-effect parameters:
  - W/L if relevant:

### 2.2 Modeling Assumptions
- channel-length modulation included: yes / no
- body effect included: yes / no
- parasitic capacitances included: yes / no
- subthreshold leakage ignored: yes / no
- bulk tied to:
- symbolic assumptions:
- other assumptions:

### 2.3 DC Reduction Performed
- AC sources set to zero: yes / no
- capacitors opened for DC: yes / no
- inductors shorted for DC: yes / no
- resulting DC subcircuit notes:

---

## 3. DC / Large-Signal Q-Point Analysis

### 3.1 Unknowns Solved
- unknown node voltages:
- unknown branch currents:
- unknown device voltages/currents:

### 3.2 Governing Equations Used
List all DC equations actually used.

- Equation 1:
- Equation 2:
- Equation 3:
- KCL/KVL constraints:
- resistor/source relations:
- operating-region assumptions:

### 3.3 Per-Device Q-Point Table

| device | type | VG | VS | VD | VB | VGS/VSG | VDS/VSD | VBS/VSB | ID magnitude | assumed_region | verified_region |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---|---|
| M1 | NMOS/PMOS |  |  |  |  |  |  |  |  |  |  |

### 3.4 Circuit-Level DC Summary
- Vout_DC:
- total_supply_current:
- total_tail_or_bias_current:
- P_DC:
- output_swing_headroom_high:
- output_swing_headroom_low:
- saturation_margin_comments:

### 3.5 Q-Point Verification
- all node voltages within rails: yes / no
- all operating regions verified: yes / no
- physically reasonable currents: yes / no
- enough headroom for intended operation: yes / no
- Q-point status: valid / invalid / conditional
- failure or warning notes:

---

## 4. Small-Signal Parameter Extraction

### 4.1 Per-Device Small-Signal Parameters

| device | region_used_for_small_signal | VOV | gm | ro | gmb | comments |
|---|---|---:|---:|---:|---:|---|
| M1 | saturation |  |  |  |  |  |

### 4.2 Node/Port-Level Equivalent Quantities
- effective input transconductance:
- equivalent output resistance:
- intermediate node resistances:
- comments:

---

## 5. Low-Frequency Small-Signal Analysis

### 5.1 Model Construction Notes
- parasitic capacitances ignored: yes / no
- low-frequency small-signal subcircuit description:
- dependent sources included:
- source degeneration included:
- active load effects included:

### 5.2 Main Derived Expressions
- Av symbolic:
- Rin symbolic:
- Rout symbolic:
- other transfer metrics:

### 5.3 Numerical Low-Frequency Results
- Av_numeric:
- Av_magnitude:
- Av_dB:
- sign: inverting / non-inverting
- Rin_numeric:
- Rout_numeric:
- current_gain_numeric:
- transconductance_numeric:
- transresistance_numeric:

### 5.4 Stage-by-Stage Breakdown (if multistage)
| stage | description | gain | Rin | Rout | comments |
|---|---|---:|---:|---:|---|

### 5.5 Low-Frequency Interpretation
- dominant gain-setting devices:
- why gain has this sign:
- what limits Rout:
- what limits Rin:
- comments:

---

## 6. High-Frequency Analysis

### 6.1 Capacitances Included
| capacitor | type | connected_nodes | value | included_in_analysis | comments |
|---|---|---|---:|---|---|
| Cgs1 | parasitic |  |  | yes/no |  |

### 6.2 High-Impedance Nodes and Time-Constant Candidates
| node | estimated Req | estimated Ceq | time_constant | likely_pole_role | comments |
|---|---:|---:|---:|---|---|
| vo |  |  |  | dominant / non-dominant / uncertain |  |

### 6.3 Miller / Feedforward Assessment
- Miller effect present: yes / no
- capacitor(s) responsible:
- equivalent Miller input capacitance:
- equivalent Miller output capacitance:
- feedforward path present: yes / no
- path description:
- possible zero generation mechanism:

### 6.4 Transfer Function Form
- H(s) symbolic:
- numerator structure:
- denominator structure:
- approximation method used: exact / Miller / OCTC / TTC / other
- derivation notes:

---

## 7. Poles and Zeros

### 7.1 Pole Table
| pole_id | expression | numerical_value_rad_per_s | numerical_value_Hz | dominant? | originating_node_or_mechanism | comments |
|---|---|---:|---:|---|---|---|
| p1 |  |  |  | yes/no |  |  |

### 7.2 Zero Table
| zero_id | expression | numerical_value_rad_per_s | numerical_value_Hz | LHP_or_RHP | originating_mechanism | comments |
|---|---|---:|---:|---|---|---|
| z1 |  |  |  | LHP/RHP |  |  |

### 7.3 Frequency Response Metrics
- DC_gain:
- midband_gain:
- -3dB_bandwidth:
- unity_gain_frequency:
- gain_bandwidth_product:
- phase_margin:
- gain_margin:
- rolloff_summary:
- phase_shift_summary:

### 7.4 Frequency-Response Interpretation
- dominant-pole mechanism:
- non-dominant pole mechanisms:
- zero effects on magnitude:
- zero effects on phase:
- bandwidth-limiting factor:
- stability comments:

---

## 8. Sensitivity / Design Insight

### 8.1 Parameter Sensitivity
- if ID increases:
- if W/L increases:
- if RD or active-load resistance increases:
- if CL increases:
- if Cgd increases:
- if ro decreases:
- other sensitivities:

### 8.2 Design Recommendations
- improve gain by:
- improve bandwidth by:
- improve headroom by:
- reduce harmful zero(s) by:
- improve bias robustness by:

---

## 9. Final Validation Checklist
- topology identified correctly:
- DC reduction performed correctly:
- Q-point solved before gm/ro usage:
- operating regions verified:
- small-signal parameters tied to Q-point:
- high-frequency parasitics included only in HF stage:
- poles tied to real RC nodes:
- zeros tied to real feedforward / numerator mechanisms:
- gain sign consistent with topology:
- results physically plausible:
- overall analysis confidence: high / medium / low

---

## 10. Final Summary

### 10.1 Executive Summary
- circuit type:
- valid operating point found: yes / no
- key DC result:
- key gain result:
- key bandwidth result:
- key pole/zero result:
- primary limitation:
- recommended next action:

### 10.2 Machine-Readable Compact Summary
```yaml
analysis_id:
topology:
valid_q_point:
vout_dc:
total_supply_current:
p_dc:
devices:
  - name:
    type:
    region:
    id:
    vgs_or_vsg:
    vds_or_vsd:
    gm:
    ro:
low_frequency:
  av:
  rin:
  rout:
high_frequency:
  dominant_pole_hz:
  other_poles_hz:
  zeros_hz:
  bandwidth_hz:
  ugf_hz:
  phase_margin_deg:
interpretation:
  gain_limiter:
  bandwidth_limiter:
  major_warning:
```
