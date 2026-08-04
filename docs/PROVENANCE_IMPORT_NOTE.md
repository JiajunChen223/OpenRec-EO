# Authority import note (release candidate)

This directory is an independent staging copy. The four Python files below were copied byte-for-byte from the frozen Phase 0.6/V7 authority sources; the source files were not edited.

| staged path | source role | SHA-256 |
|---|---|---|
| `src/openrec_eo/authoritative/analyze_forest_aligned_results.py` | V7 forest-aligned primary analysis | `e01491c1edff7a3c347a4c2d7c95234d10e671aa617777c610556d54a784e64a` |
| `src/openrec_eo/authoritative/run_final_alignment_local.py` | V7 final alignment and endpoint reproduction | `8466057e7e25d8be8f477ef50066c1a6cbcc594be9acb8bae86056e5bfb45429` |
| `src/openrec_eo/authoritative/analyze_forest_aligned_10_20km.py` | V7 comparator reproduction | `dcae7ee6065106e0238edd839470f66b524d1f8ff39336a501f8b428b108e4ee` |
| `src/openrec_eo/fia/extract_fia_continuous_structure.py` | Phase 0.6 canonical FIA preprocessing | `b56c31c28484466b03ea2a9ebc5fc5b8abc7e5c07b7c50cd07d29741d673539a` |
| `src/openrec_eo/authoritative/submit_forest_aligned_exports.py` | Optional Earth Engine acquisition sibling required by the frozen analyzer's audit hash check | `0fa08e375d802ae97c66b34bb950e2b39e5f7c1c6e3e935da0cc73c93772d2f7` |

The historical files `build_endpoints.py`, `analysis_config.json`, and `run_incremental_internal_audit.py` were not recovered. They are not represented here as recovered assets. Any public wrapper must cite the signed alternative-authority decision and the ten-equation crosswalk.

The FIA script expects sibling input metadata and FIA TREE files. Those inputs are intentionally absent from this candidate until redistribution rights, de-identification, and a public-data access route are documented. The Earth Engine sibling is staged byte-for-byte only to preserve the frozen analyzer's hash contract; it is an optional, owner/data-rights-unresolved module and is not authorized for public release. The code is therefore not yet a complete end-to-end release.
