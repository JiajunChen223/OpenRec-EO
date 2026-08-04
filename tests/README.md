# Test plan (draft)

The candidate now ports the Phase 0.5/0.6 test registry into executable, versioned tests in `test_authority_contracts.py`.

- 18 static and boundary contracts: thresholds, two-year runs, missing-year interruptions, endpoint finiteness, domain composition, signed diagnostics, and Eq10 denominator conditions.
- Formula-code mathematical checks: no FAIL across Eq01–Eq10.
- Numeric-anchor checks: 27 declared anchors across all approved carriers, with zero failures.
- FIA preprocessing check: pair/event fields generated with `1e-6`, mismatch count zero or within the declared `1e-12` tolerance.
- Current run: 18 passed and 2 skipped in the workstation environment; the two skips preserve the unresolved historical-source records STATIC-004/005.
- Smoke tests on synthetic inputs, clearly separated from full-data reproduction tests.

Tests must report environment and input-manifest hashes. No test may download data, access a secret, or depend on an author's local absolute path. The current result is not a clean-environment release gate until the dependency lock is independently tested.
