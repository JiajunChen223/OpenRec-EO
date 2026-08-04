# Data release policy (draft, user-approved default)

The public code release is code-first and data-minimal.

## Included

- analysis source and formula provenance;
- schema-only contracts;
- official provider and acquisition instructions;
- synthetic non-scientific fixtures only if a later test requires them.

## Excluded

- raw or derived MTBS, LCMAP, Landsat, GEDI and Earth Engine exports;
- raw FIA TREE tables;
- FIA plot/measurement identifiers, coordinates, geometry, or plot-level
  associations;
- event-level FIA aggregates unless a separate rights/privacy review approves
  their release.

These exclusions are release controls, not claims about provider licences. Each
provider's current terms and the copyright/data-rights owner's decision must be
recorded before a public tag is created.

Current status: `SCHEMA_AND_SYNTHETIC_ONLY_PENDING_RIGHTS_CONFIRMATION`.
