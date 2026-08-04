# FIA schema-only contract

These files describe the columns required by the frozen FIA extraction and
association interfaces. They are **schemas only**: no FIA rows, plot keys,
coordinates, tree records, event identifiers, or derived values are included.

The release tiers used here are deliberately conservative:

- `RESTRICTED_INTERNAL_INPUT` — the frozen implementation can consume this
  shape, but the source carrier must stay outside the public repository.
- `CONDITIONAL_EVENT_AGGREGATE` — an event-level, de-identified aggregate may
  be considered only after upstream data-rights and privacy review. The schema
  does not authorize redistribution.
- `CONDITIONAL_AGGREGATE` — summary statistics without plot identifiers or
  geospatial fields; still subject to upstream rights and release approval.
- `FORBIDDEN_PUBLIC_PLOT_OR_GEOSPATIAL` — plot-level, tree-level, stable-key,
  measurement-key, coordinate, geometry, or raw external-product carriers.

The public candidate must not infer a licence from these schemas. Raw USDA FIA
TREE tables, FIA association/selection files, EO export CSVs, and geospatial
carriers remain excluded until the internal rights matrix is explicitly
resolved. If a synthetic fixture is added later, every value must be generated
for testing, contain no source-derived row, and be labelled
`SYNTHETIC_NON_SCIENTIFIC_FIXTURE`.

Source evidence for the field contracts is recorded in
`02_audit/FIA_PRIVACY_AND_PUBLIC_FIXTURE_DECISION.json`.
