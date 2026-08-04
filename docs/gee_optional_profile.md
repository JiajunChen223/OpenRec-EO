# Optional Earth Engine profile

**Profile:** `gee` (optional, non-default)  
**Status:** `SELECTED_ROUTE_PENDING_OWNER_AND_DATA_RIGHTS`  
**Offline core:** Earth Engine is not required and must not be imported or
authenticated for offline analysis.

## Why this file is staged

The frozen forest-aligned analyzer records the SHA-256 of a co-located
`submit_forest_aligned_exports.py` sibling. The candidate keeps that sibling
byte-for-byte so the current scientific authority contract can be checked. The
sibling is an acquisition/submission helper, not part of the offline analysis
estimand.

```text
submit_forest_aligned_exports.py
SHA-256 = 0fa08e375d802ae97c66b34bb950e2b39e5f7c1c6e3e935da0cc73c93772d2f7
earthengine-api = 1.7.32 (optional profile only)
```

The exact sibling contains owner-specific Earth Engine project/Drive
identifiers and provider asset references. It is therefore **not yet
authorized for public execution or redistribution**. The owner, institution,
and relevant providers must approve those references before the public gate
can close.

## Installation profiles

- Offline core: install the project dependencies from `pyproject.toml` or
  `environment.yml`; neither includes `earthengine-api`.
- Optional GEE profile: use the separately documented `environment-gee.yml`
  or `pip install -e ".[gee]"` after the owner/rights decision is closed.

Do not add GEE to the offline core merely to make the sibling importable. A
clean offline run consumes user-supplied exported CSV/JSON inputs and must not
authenticate to Earth Engine.

## Operational restrictions

1. Authentication, project selection, and export submission are always
   user-supplied and interactive; no default project or credential is shipped.
2. Do not commit OAuth tokens, service-account keys, local credential files,
   task exports, private asset IDs, or Drive outputs.
3. Do not redistribute MTBS, LCMAP, Landsat, GEDI, or other provider products
   unless the provider's terms explicitly permit it. The public repository
   should ship retrieval/version/checksum instructions instead.
4. Do not edit the byte-preserved sibling in this candidate. Any owner-safe
   parameterization requires a new implementation-authority audit and hash.
5. Do not claim that Earth Engine acquisition is reproduced by the offline
   fixture tests; the acquisition route is separately gated.

## Gate record

```text
GEE_PROFILE = OPTIONAL_NONDEFAULT
GEE_CORE_DEPENDENCY = NO
GEE_ACQUISITION_EXECUTION = NOT_RUN
SIBLING_HASH_CONTRACT = PRESERVED
OWNER_AND_DATA_RIGHTS = UNRESOLVED
PUBLIC_EXECUTION = NOT_AUTHORIZED
```
