# OpenRec-EO: Reproducible Event-Level Post-Fire Forest Monitoring

**Public-code repository status: DRAFT — not yet released.**

This is an internal release candidate for the reproducible analysis code of
the locked OpenRec-EO RSE manuscript. It contains byte-preserved authority
scripts and release documentation. It is not public and must not be cited or
redistributed as an official release. Raw third-party data are not included.

## Before use

The proposed code licence is MIT. The recorded copyright holder is Jiajun Chen
(陈家骏), College of Earth Sciences, Jilin University; see `LICENSE` and the
workspace decision record `04_deliverables/COPYRIGHT_AND_LICENSE_DECISION.md`.
The release remains blocked until provider/rights, clean-environment, data,
and independent-review gates are closed. Do not cite or redistribute this
draft as an official software release.

## Planned contents

- `src/openrec_eo/authoritative/`: hash-verified, byte-preserved V7 analysis
  scripts.
- `src/openrec_eo/fia/`: hash-verified FIA preprocessing candidate; inputs are
  intentionally absent.
- `src/openrec_eo/authoritative/submit_forest_aligned_exports.py`:
  byte-preserved Earth Engine sibling required by the frozen analyzer's audit
  hash check; optional, non-default, and not publicly authorized until
  owner/provider rights close. See `docs/gee_optional_profile.md`.
- `runners/`: path-safe entry points with no local absolute paths.
- `tests/`: formula, boundary, and input-contract tests.
- `data/`: schemas and acquisition/licence instructions; no raw data by
  default.
- `docs/`: provenance, formula crosswalk, and reproduction guidance.
- `docs/data_release_policy.md` and `THIRD_PARTY_NOTICES.md`: staged data boundary and dependency-notice drafts.

The offline core does not depend on Earth Engine. The optional `gee` extra in
`pyproject.toml` and `environment-gee.yml` is documented for later review and
must not be executed in this staging candidate. The final release will state a
tag and DOI only after author/institution approval.
