from __future__ import annotations

import importlib.util
from pathlib import Path

import numpy as np
import pandas as pd
import pytest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "src" / "openrec_eo" / "authoritative" / "run_final_alignment_local.py"
SPEC = importlib.util.spec_from_file_location("openrec_alignment_authority", SCRIPT)
assert SPEC and SPEC.loader
AUTH = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(AUTH)


def trajectory(years: list[int], ratios: list[float]) -> pd.DataFrame:
    return pd.DataFrame({"relative_year": years, "ratio": ratios})


def structure_frame(
    rh98_burned: float, rh98_reference: float,
    cover_burned: float, cover_reference: float,
    pai_burned: float, pai_reference: float,
) -> pd.DataFrame:
    row = {"Event_ID": "SYNTH-001"}
    for component, burned, reference in (
        ("rh98", rh98_burned, rh98_reference),
        ("cover", cover_burned, cover_reference),
        ("pai", pai_burned, pai_reference),
    ):
        row[f"forest_burned_{component}_mean"] = burned
        row[f"forest_reference_{component}_mean"] = reference
        row[f"forest_burned_{component}_count"] = 25
    return pd.DataFrame([row])


# ATT-001–004: two-year attainment contracts.
def test_att_001_adjacent_years_return_second_year():
    start, end, ok = AUTH.first_completion(trajectory([1, 2, 3], [0.80, 0.90, 0.90]), 0.90)
    assert ok and start == 2 and end == 3


def test_att_002_one_qualifying_year_does_not_attain():
    assert AUTH.first_completion(trajectory([1], [0.90]), 0.90)[2] is False


def test_att_003_missing_calendar_year_interrupts_pair():
    assert AUTH.first_completion(trajectory([1, 3], [0.90, 0.90]), 0.90)[2] is False


def test_att_004_exact_tau_boundary_is_included():
    start, end, ok = AUTH.first_completion(trajectory([1, 2], [0.90, 0.90]), 0.90)
    assert ok and start == 1 and end == 2


def test_re_001_decline_then_two_year_reattainment():
    start, end, ok = AUTH.first_completion(
        trajectory([1, 2, 3, 4], [0.80, 0.80, 0.90, 0.90]),
        tau=0.90,
        required_decline=0.90,
    )
    assert ok and start == 3 and end == 4


# LRSD-001–004: component ratio and non-negative deficit contracts.
def test_lrsd_001_burned_below_reference():
    endpoints, _ = AUTH.build_structure_endpoints(structure_frame(5, 10, 5, 10, 5, 10), {"SYNTH-001"})
    assert endpoints.loc[0, "lrsd_height"] == 0.5


def test_lrsd_002_burned_equal_to_reference():
    endpoints, _ = AUTH.build_structure_endpoints(structure_frame(10, 10, 10, 10, 10, 10), {"SYNTH-001"})
    assert endpoints.loc[0, "lrsd_height"] == 0.0


def test_lrsd_003_burned_above_reference_is_truncated_to_zero():
    endpoints, _ = AUTH.build_structure_endpoints(structure_frame(12, 10, 12, 10, 12, 10), {"SYNTH-001"})
    assert endpoints.loc[0, "lrsd_height"] == 0.0


def test_lrsd_004_nonpositive_reference_is_invalid():
    endpoints, _ = AUTH.build_structure_endpoints(structure_frame(5, 0, 5, 10, 5, 10), {"SYNTH-001"})
    assert np.isnan(endpoints.loc[0, "lrsd_height"])


# DOM-001–003: domain aggregation contracts.
def test_dom_001_canopy_amount_median():
    cohort = pd.DataFrame({"lrsd_contextual": [0.2, 0.4, 0.6], "lrsd_balanced": [0.35] * 3, "lrsd_height": [0.1] * 3, "lrsd_canopy_amount": [0.4, 0.5, 0.6]})
    rows = AUTH.summarize_domains(cohort, {})
    assert next(row for row in rows if row["domain"] == "canopy_amount")["median_lrsd"] == 0.5


def test_dom_002_contextual_median_of_three_components():
    cohort = pd.DataFrame({"lrsd_contextual": [0.2, 0.4, 0.6], "lrsd_balanced": [0.35] * 3, "lrsd_height": [0.1] * 3, "lrsd_canopy_amount": [0.5] * 3})
    rows = AUTH.summarize_domains(cohort, {})
    assert next(row for row in rows if row["domain"] == "contextual")["median_lrsd"] == 0.4


def test_dom_003_balanced_domain_uses_equal_domain_mean():
    cohort = pd.DataFrame({"lrsd_contextual": [0.4] * 3, "lrsd_balanced": [0.35] * 3, "lrsd_height": [0.2] * 3, "lrsd_canopy_amount": [0.5] * 3})
    rows = AUTH.summarize_domains(cohort, {})
    assert next(row for row in rows if row["domain"] == "balanced")["median_lrsd"] == 0.35


# TAIL-001–003: Eq10 strict tail threshold.
def test_tail_001_below_delta_is_not_high_deficit():
    cohort = pd.DataFrame({"lrsd_contextual": [0.1999], "lrsd_balanced": [0.1999], "lrsd_height": [0.1999], "lrsd_canopy_amount": [0.1999]})
    row = next(row for row in AUTH.summarize_domains(cohort, {}) if row["domain"] == "contextual")
    assert row["tail_n"] == 0


def test_tail_002_exact_delta_is_not_high_deficit_for_strict_gt():
    cohort = pd.DataFrame({"lrsd_contextual": [0.2000], "lrsd_balanced": [0.2000], "lrsd_height": [0.2000], "lrsd_canopy_amount": [0.2000]})
    row = next(row for row in AUTH.summarize_domains(cohort, {}) if row["domain"] == "contextual")
    assert row["tail_n"] == 0


def test_tail_003_above_delta_is_high_deficit():
    cohort = pd.DataFrame({"lrsd_contextual": [0.2001], "lrsd_balanced": [0.2001], "lrsd_height": [0.2001], "lrsd_canopy_amount": [0.2001]})
    row = next(row for row in AUTH.summarize_domains(cohort, {}) if row["domain"] == "contextual")
    assert row["tail_n"] == 1


# STATIC-001–003: public candidate metadata and frozen constants.
def test_static_001_public_crosswalk_has_ten_equations():
    text = (ROOT / "docs" / "formula_code_crosswalk.md").read_text(encoding="utf-8")
    assert sum(1 for line in text.splitlines() if line.startswith("| Eq") and line[4].isdigit()) == 10


def test_static_002_active_alignment_code_exposes_primary_constants():
    assert AUTH.TAUS == (0.85, 0.90, 0.95)
    assert AUTH.RUN == 2
    assert AUTH.DELTA == 0.20
    assert set(AUTH.COMPONENTS) == {"rh98", "cover", "pai"}


def test_static_003_primary_code_exposes_bootstrap_reproducibility_constants():
    text = (ROOT / "src" / "openrec_eo" / "authoritative" / "analyze_forest_aligned_results.py").read_text(encoding="utf-8")
    assert "BOOT_REPS = 5000" in text
    assert "SEED = 20260723" in text


@pytest.mark.skip(reason="STATIC-004 remains unresolved because the historical endpoint builder was not recovered")
def test_static_004_historical_endpoint_builder_exists():
    raise AssertionError("UNRESOLVED_PRIMARY_IMPLEMENTATION_SOURCE")


@pytest.mark.skip(reason="STATIC-005 remains unresolved in the historical active-package registry; canonical FIA source is separately staged")
def test_static_005_historical_fia_source_registry_exists():
    raise AssertionError("UNRESOLVED_PRIMARY_IMPLEMENTATION_SOURCE")
