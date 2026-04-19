# ADR 005: YAML Numeric Loading Gotcha

## Status
Accepted, 2026-04-19.

## Context
PyYAML uses the YAML 1.1 specification by default. Under this spec, values
like `8e-5` (no decimal point) are parsed as strings, not floats. Only forms
with a decimal point — e.g. `8.0e-5` — are reliably parsed as floats.

During Step 8.4, golden YAML values for ID and gm were written as `8e-5` and
`4e-4`. When the test loaded them via `yaml.safe_load`, the values arrived as
Python `str` objects. The assertion `_rel_error(actual_float, "8e-5")` then
raised `TypeError: unsupported operand type(s) for -: 'float' and 'str'`
rather than a comparison failure, masking the real intent of the check.

## Decision
Enforce robustness at two levels:

1. **Consumption (mandatory):** All code that reads numeric values from golden
   YAML must wrap them in `float()` before arithmetic. This applies to every
   getter in `tests/golden_helpers.py` and every assertion in end-to-end tests.

2. **Authorship (convention):** Golden YAML values should be written with a
   decimal point — `8.0e-5` rather than `8e-5` — so that `yaml.safe_load`
   parses them as floats automatically and the intent is unambiguous to readers.

## Consequences
- Golden YAML files accept both forms (`8e-5` and `8.0e-5`) without breaking
  downstream code, because consumption always casts to `float()`.
- Future golden-YAML authors default to the decimal-point form for readability
  and to avoid surprising type behavior during debugging.
- If a value is accidentally written as a string (e.g. `"8e-5"` with quotes),
  `float()` still converts it correctly, giving an additional safety layer.

## Reference
- Step 8.4 test failure: `TypeError` on `m1["id"]` vs `"8e-5"`, 2026-04-19.
- Fix applied in `tests/test_end_to_end_case1.py` assertions.
