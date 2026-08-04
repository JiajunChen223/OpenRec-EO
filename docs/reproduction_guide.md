# Reproduction guide (draft)

## Status

This guide is an internal draft. It does not promise that the input data are redistributable or that a clean-environment run has already been completed.

## 1. Prepare a clean checkout

Use a tagged public release only after the release gate is PASS. Create a new environment from the reviewed `pyproject.toml` or `environment.yml`. Exact dependency pins and the supported Python/OS matrix are to be filled after the first independent clean-environment run.

## 2. Obtain and verify inputs

Read `data/DATA_SOURCES.md`. Download restricted products directly from their providers, accepting the provider's terms. Place them in user-selected paths outside version control and validate the input manifest before running code. Do not copy raw FIA TREE files or third-party rasters into this repository unless the rights review explicitly permits it.

## 3. Run the frozen implementations

The forest-aligned analyzer performs an audit hash check against the co-located
`submit_forest_aligned_exports.py` sibling. The candidate stages that file
byte-for-byte as an optional Earth Engine module, but it must not be executed
without the user's own authenticated project, provider terms, and owner
approval. The offline core does not require an Earth Engine session once
legally obtained exported inputs are available.

The wrappers should expose explicit paths. The current frozen interfaces require arguments equivalent to:

```text
analyze_forest_aligned_results.py --raw-dir <raw_dir> --package <package_dir> --manifest <manifest.csv> --output-dir <output_dir>
run_final_alignment_local.py --raw-dir <raw_dir> --package <package_dir> --existing-endpoints <endpoints.csv> --fia-panel <fia_panel.csv> --fia-expected <fia_expected.csv> --output-dir <output_dir>
analyze_forest_aligned_10_20km.py --primary-raw-dir <primary_raw_dir> --alternative-raw-dir <alternative_raw_dir> --primary-endpoints <endpoints.csv> --proxy-status <proxy_status.csv> --output-dir <output_dir>
```

The final release must document the exact command lines and expected file schemas. Commands must work from any checkout location and must not contain the author's local absolute paths.

## 4. Required checks

Run `pytest` for the 18 static/boundary contracts; run the formula-code crosswalk and numeric-anchor audit; and run the FIA validation. The FIA contract applies `log((post + 1e-6) / (pre + 1e-6))`, checks 280 pair rows, 40 event rows, and five metrics, and requires zero mismatches or differences within the predeclared `1e-12` tolerance.

## 5. Record and interpret outputs

Save a machine-readable run record containing code commit/hash, environment, input manifest hash, command, output manifest, and timestamps. Compare expected anchors only when the input manifest and analysis scope match. Synthetic smoke-test output demonstrates interface health, not the paper's numerical result.

## 6. Troubleshooting and limitations

Missing licensed inputs, endpoint/cohort-count mismatches, missing years, or dependency-version differences must be reported in the run record. Do not change thresholds, formulas, sample definitions, or statistical methods to force an expected number.
