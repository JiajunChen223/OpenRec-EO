# Provenance and authority

This draft repository follows the Phase 0.6 implementation-authority decision (`P0-006-DECISION-20260803`). Three historical implementation files were searched by registered filename and SHA-256 but were not recovered. The frozen active V7 scripts are therefore the alternative implementation authority for the current study; the Methods source remains the definition and equation-numbering authority.

## Staged authority files

The release manifest must contain the original path, staged path, observed SHA-256, size, and copy result for:

| Staged role | Recorded SHA-256 | Release status |
|---|---|---|
| Forest-aligned primary reproduction | `e01491c1edff7a3c347a4c2d7c95234d10e671aa617777c610556d54a784e64a` | staged under `05_release_candidate/repo/src/openrec_eo/authoritative/`; hash match PASS |
| Alignment/endpoint/FIA association reproduction | `8466057e7e25d8be8f477ef50066c1a6cbcc594be9acb8bae86056e5bfb45429` | staged under `05_release_candidate/repo/src/openrec_eo/authoritative/`; hash match PASS |
| Distance comparator reproduction | `dcae7ee6065106e0238edd839470f66b524d1f8ff39336a501f8b428b108e4ee` | staged under `05_release_candidate/repo/src/openrec_eo/authoritative/`; hash match PASS |
| Canonical FIA pre/post preprocessing | `b56c31c28484466b03ea2a9ebc5fc5b8abc7e5c07b7c50cd07d29741d673539a` | staged under `05_release_candidate/repo/src/openrec_eo/fia/`; hash match PASS |
| Earth Engine acquisition sibling (optional) | `0fa08e375d802ae97c66b34bb950e2b39e5f7c1c6e3e935da0cc73c93772d2f7` | staged byte-preserved for the analyzer hash contract; owner/data-rights approval unresolved |

The source-of-truth evidence is retained in the private Phase 0.6 workspace. Public documentation should use staged relative paths and hashes; it must not expose unnecessary local workstation paths.

## Reproducibility claims

The Phase 0.6 evidence reports 18 static/boundary tests passed, 27 numeric anchors with 1,556 appearances and zero failures, and FIA log-ratio validation over 280 pair rows, 40 event rows, and five metrics with zero mismatches under a `1e-12` tolerance. These are audit baselines, not evidence that the public scaffold has already reproduced them. The release record must attach fresh clean-environment logs.

## Data and output provenance

Raw third-party products and FIA TREE files are not bundled by this scaffold. Each released output must identify the input manifest, code hash, command, environment, and output hash. A result generated from synthetic data must be labelled a smoke test and must not be presented as the paper result.
