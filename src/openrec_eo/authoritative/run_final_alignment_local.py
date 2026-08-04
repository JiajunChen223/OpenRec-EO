from __future__ import annotations

import argparse
import hashlib
import json
import platform
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import scipy
from scipy import stats
from statsmodels.stats.multitest import multipletests


TAUS = (0.85, 0.90, 0.95)
RUN = 2
DELTA = 0.20
STRICT_COMPLETION_YEAR_MAX = 2018
SENTINEL = -9999
PRIMARY_PROXIES = {
    "NDVI": "forest_burned_NDVI_mean",
    "NBR": "forest_burned_NBR_mean",
}
COMPONENTS = ("rh98", "cover", "pai")
DOMAINS = {
    "contextual": "lrsd_contextual",
    "balanced": "lrsd_balanced",
    "height": "lrsd_height",
    "canopy_amount": "lrsd_canopy_amount",
}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def clean_numeric(series: pd.Series) -> pd.Series:
    values = pd.to_numeric(series, errors="coerce")
    return values.mask(values.eq(SENTINEL))


def json_clean(value):
    if isinstance(value, dict):
        return {key: json_clean(item) for key, item in value.items()}
    if isinstance(value, list):
        return [json_clean(item) for item in value]
    if isinstance(value, np.generic):
        value = value.item()
    if isinstance(value, float) and not np.isfinite(value):
        return None
    return value


def write_csv(frame: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(path, index=False, encoding="utf-8", lineterminator="\n")


def load_exports(raw_dir: Path) -> tuple[pd.DataFrame, list[dict[str, object]]]:
    paths = sorted(raw_dir.glob("openrec_forest_aligned_v2_*.csv"))
    if len(paths) != 320:
        raise RuntimeError(f"Expected 320 forest-aligned exports, found {len(paths)}")
    frames = []
    inventory = []
    for path in paths:
        frame = pd.read_csv(path)
        event_ids = frame["Event_ID"].astype(str).unique()
        if len(event_ids) != 1:
            raise RuntimeError(f"{path.name}: expected one Event_ID")
        if int(frame["row_kind"].eq("forest_aligned_structure").sum()) != 3:
            raise RuntimeError(f"{path.name}: expected three structure rows")
        frames.append(frame)
        inventory.append(
            {
                "file": path.name,
                "bytes": path.stat().st_size,
                "sha256": sha256(path),
                "Event_ID": str(event_ids[0]),
                "rows": int(len(frame)),
                "proxy_rows": int(frame["row_kind"].eq("forest_aligned_proxy").sum()),
                "structure_rows": int(
                    frame["row_kind"].eq("forest_aligned_structure").sum()
                ),
            }
        )
    raw = pd.concat(frames, ignore_index=True)
    raw["Event_ID"] = raw["Event_ID"].astype(str)
    if raw["Event_ID"].nunique() != 320:
        raise RuntimeError("Forest-aligned raw exports do not contain 320 unique events")
    return raw, inventory


def event_trajectory(sub: pd.DataFrame, value_col: str) -> tuple[int, float, pd.DataFrame]:
    fire_year = int(pd.to_numeric(sub["fire_year"], errors="coerce").dropna().iloc[0])
    values = sub[["relative_year", value_col]].copy()
    values["relative_year"] = pd.to_numeric(values["relative_year"], errors="coerce")
    values["value"] = clean_numeric(values[value_col])
    values = (
        values[["relative_year", "value"]]
        .dropna(subset=["relative_year"])
        .drop_duplicates("relative_year", keep="last")
        .sort_values("relative_year")
        .reset_index(drop=True)
    )
    pre = values.loc[values["relative_year"].isin([-3, -2, -1]), "value"].dropna()
    baseline = float(pre.median()) if len(pre) == 3 else np.nan
    if np.isfinite(baseline) and baseline != 0:
        values["ratio"] = values["value"] / baseline
    else:
        values["ratio"] = np.nan
    return fire_year, baseline, values


def first_completion(
    values: pd.DataFrame,
    tau: float,
    required_decline: float | None = None,
) -> tuple[float, float, bool]:
    post = values.loc[values["relative_year"].ge(1) & values["ratio"].notna()].copy()
    if post.empty:
        return np.nan, np.nan, False
    years = post["relative_year"].astype(int).to_numpy()
    ratios = post["ratio"].to_numpy(float)
    for start_index in range(len(post)):
        end_index = start_index + RUN
        if end_index > len(post):
            continue
        selected_years = years[start_index:end_index]
        selected_ratios = ratios[start_index:end_index]
        if not (
            np.all(np.diff(selected_years) == 1)
            and np.all(selected_ratios >= tau)
        ):
            continue
        if required_decline is not None and not np.any(
            ratios[:start_index] < required_decline
        ):
            continue
        return float(selected_years[0]), float(selected_years[-1]), True
    return np.nan, np.nan, False


def build_proxy_status(
    proxy_rows: pd.DataFrame, fixed_ids: set[str]
) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    proxy_rows = proxy_rows[proxy_rows["Event_ID"].isin(fixed_ids)].copy()
    for event_id, sub in proxy_rows.groupby("Event_ID", sort=False):
        for proxy, value_col in PRIMARY_PROXIES.items():
            fire_year, baseline, values = event_trajectory(sub, value_col)
            for tau in TAUS:
                start, end, attained = first_completion(values, tau=tau)
                strict = bool(
                    attained and fire_year + end <= STRICT_COMPLETION_YEAR_MAX
                )
                rows.append(
                    {
                        "Event_ID": event_id,
                        "proxy": proxy,
                        "tau": tau,
                        "run": RUN,
                        "fire_year": fire_year,
                        "baseline": baseline,
                        "attainment_start_relative_year": start,
                        "attainment_completion_relative_year": end,
                        "attainment_completion_calendar_year": (
                            fire_year + end if attained else np.nan
                        ),
                        "attainment_original": bool(attained),
                        "attainment_strict": strict,
                    }
                )
            initial_start, initial_end, initial = first_completion(values, tau=0.90)
            re_start, re_end, reattained = first_completion(
                values, tau=0.90, required_decline=0.90
            )
            post = values.loc[
                values["relative_year"].ge(1) & values["ratio"].notna(),
                ["relative_year", "ratio"],
            ]
            prior_to_initial = (
                post.loc[post["relative_year"].lt(initial_start), "ratio"]
                if initial
                else pd.Series(dtype=float)
            )
            rows.append(
                {
                    "Event_ID": event_id,
                    "proxy": proxy,
                    "tau": "re_attainment_090",
                    "run": RUN,
                    "fire_year": fire_year,
                    "baseline": baseline,
                    "attainment_start_relative_year": re_start,
                    "attainment_completion_relative_year": re_end,
                    "attainment_completion_calendar_year": (
                        fire_year + re_end if reattained else np.nan
                    ),
                    "attainment_original": bool(reattained),
                    "attainment_strict": bool(
                        reattained
                        and fire_year + re_end <= STRICT_COMPLETION_YEAR_MAX
                    ),
                    "initial_attainment_strict": bool(
                        initial
                        and fire_year + initial_end <= STRICT_COMPLETION_YEAR_MAX
                    ),
                    "decline_before_initial_attainment": bool(
                        initial and np.any(prior_to_initial < 0.90)
                    ),
                }
            )
    return pd.DataFrame(rows)


def build_structure_endpoints(
    structure_rows: pd.DataFrame, fixed_ids: set[str]
) -> tuple[pd.DataFrame, pd.DataFrame]:
    use = structure_rows[structure_rows["Event_ID"].isin(fixed_ids)].copy()
    for component in COMPONENTS:
        burned = clean_numeric(use[f"forest_burned_{component}_mean"])
        reference = clean_numeric(use[f"forest_reference_{component}_mean"])
        use[f"q_{component}_annual"] = burned / reference.where(reference.gt(0))
        use[f"burned_{component}_valid_count"] = clean_numeric(
            use[f"forest_burned_{component}_count"]
        )
    endpoint_rows = []
    support_rows = []
    for event_id, sub in use.groupby("Event_ID", sort=False):
        q = {
            component: (
                float(sub[f"q_{component}_annual"].median(skipna=True))
                if sub[f"q_{component}_annual"].notna().any()
                else np.nan
            )
            for component in COMPONENTS
        }
        signed = {
            component: 1.0 - value if np.isfinite(value) else np.nan
            for component, value in q.items()
        }
        deficit = {
            component: max(0.0, value) if np.isfinite(value) else np.nan
            for component, value in signed.items()
        }
        height = deficit["rh98"]
        canopy = (
            float(np.median([deficit["cover"], deficit["pai"]]))
            if np.isfinite(deficit["cover"]) and np.isfinite(deficit["pai"])
            else np.nan
        )
        contextual = (
            float(np.median([deficit[c] for c in COMPONENTS]))
            if all(np.isfinite(deficit[c]) for c in COMPONENTS)
            else np.nan
        )
        balanced = (
            (height + canopy) / 2.0
            if np.isfinite(height) and np.isfinite(canopy)
            else np.nan
        )
        endpoint_rows.append(
            {
                "Event_ID": event_id,
                "q_rh98": q["rh98"],
                "q_cover": q["cover"],
                "q_pai": q["pai"],
                "lrsd_contextual": contextual,
                "lrsd_balanced": balanced,
                "lrsd_height": height,
                "lrsd_canopy_amount": canopy,
                "signed_height": signed["rh98"],
                "signed_canopy_amount": (
                    1.0
                    - float(np.median([q["cover"], q["pai"]]))
                    if np.isfinite(q["cover"]) and np.isfinite(q["pai"])
                    else np.nan
                ),
                "valid_structure_year_n": int(
                    sub[[f"q_{c}_annual" for c in COMPONENTS]]
                    .notna()
                    .any(axis=1)
                    .sum()
                ),
            }
        )
        support_rows.append(
            {
                "Event_ID": event_id,
                "median_burned_rh98_valid_cells": float(
                    sub["burned_rh98_valid_count"].median(skipna=True)
                ),
                "median_burned_cover_valid_cells": float(
                    sub["burned_cover_valid_count"].median(skipna=True)
                ),
                "median_burned_pai_valid_cells": float(
                    sub["burned_pai_valid_count"].median(skipna=True)
                ),
                "support_ge_20": bool(
                    sub["burned_rh98_valid_count"].median(skipna=True) >= 20
                ),
            }
        )
    return pd.DataFrame(endpoint_rows), pd.DataFrame(support_rows)


def summarize_domains(
    cohort: pd.DataFrame,
    identifying: dict[str, object],
) -> list[dict[str, object]]:
    rows = []
    for domain, column in DOMAINS.items():
        values = cohort[column].dropna()
        rows.append(
            {
                **identifying,
                "domain": domain,
                "cohort_n": int(len(cohort)),
                "endpoint_n": int(len(values)),
                "tail_n": int(values.gt(DELTA).sum()),
                "tail_fraction": (
                    float(values.gt(DELTA).mean()) if len(values) else np.nan
                ),
                "median_lrsd": float(values.median()) if len(values) else np.nan,
            }
        )
    return rows


def threshold_and_support_summaries(
    status: pd.DataFrame,
    endpoints: pd.DataFrame,
    support: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    numeric_status = status[pd.to_numeric(status["tau"], errors="coerce").notna()].copy()
    numeric_status["tau"] = pd.to_numeric(numeric_status["tau"])
    merged = numeric_status.merge(endpoints, on="Event_ID", how="left").merge(
        support, on="Event_ID", how="left"
    )
    threshold_rows = []
    for (proxy, tau), sub in merged.groupby(["proxy", "tau"], sort=True):
        cohort = sub[sub["attainment_strict"].astype(bool)].copy()
        threshold_rows.extend(
            summarize_domains(
                cohort,
                {"proxy": proxy, "tau": float(tau), "run": RUN},
            )
        )
    threshold = pd.DataFrame(threshold_rows)

    primary = merged[merged["tau"].eq(0.90) & merged["attainment_strict"]].copy()
    support_rows = []
    for proxy, sub in primary.groupby("proxy", sort=True):
        retained = sub[sub["support_ge_20"].astype(bool)].copy()
        support_rows.extend(
            summarize_domains(
                retained,
                {
                    "proxy": proxy,
                    "support_rule": "median_burned_rh98_valid_25m_cells_ge_20",
                    "primary_cohort_n": int(len(sub)),
                    "retained_n": int(len(retained)),
                },
            )
        )
    return threshold, pd.DataFrame(support_rows), merged


def weighted_rank_correlation(
    x: np.ndarray, y: np.ndarray, weights: np.ndarray
) -> float:
    rx = stats.rankdata(x)
    ry = stats.rankdata(y)
    weights = np.asarray(weights, dtype=float)
    wx = np.average(rx, weights=weights)
    wy = np.average(ry, weights=weights)
    cov = np.average((rx - wx) * (ry - wy), weights=weights)
    sx = np.sqrt(np.average((rx - wx) ** 2, weights=weights))
    sy = np.sqrt(np.average((ry - wy) ** 2, weights=weights))
    return float(cov / (sx * sy))


def fia_associations(
    fia_path: Path,
    endpoints: pd.DataFrame,
    expected_path: Path,
) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, object]]:
    fia = pd.read_csv(fia_path)
    fia["Event_ID"] = fia["Event_ID"].astype(str)
    if len(fia) != 40 or fia["Event_ID"].nunique() != 40:
        raise RuntimeError("FIA event panel must contain 40 unique events")
    endpoint_use = endpoints[
        ["Event_ID", "lrsd_canopy_amount", "lrsd_height"]
    ].copy()
    merged = fia.merge(endpoint_use, on="Event_ID", how="left", validate="one_to_one")
    if merged["lrsd_canopy_amount"].notna().sum() != 40:
        raise RuntimeError("Forest-aligned canopy endpoint is not available for all 40 FIA events")

    definitions = [
        (
            "canopy_amount",
            "basal_area",
            "log_ratio_basal_area_ft2_ac",
        ),
        ("canopy_amount", "biomass", "log_ratio_biomass_lb_ac"),
        ("canopy_amount", "tree_density", "log_ratio_tree_density_ac"),
        ("height", "BA_weighted_height", "log_ratio_ba_weighted_height_ft"),
        ("height", "QMD", "log_ratio_qmd_in"),
    ]
    expected = pd.read_csv(expected_path)
    expected_lookup = {
        (row["domain"], row["comparison"]): row
        for _, row in expected.iterrows()
    }
    full_reproduction = []
    aligned_rows = []
    raw_ps = []
    for domain, comparison, metric in definitions:
        old_endpoint = "rsrd_canopy" if domain == "canopy_amount" else "rsrd_height"
        new_endpoint = (
            "lrsd_canopy_amount" if domain == "canopy_amount" else "lrsd_height"
        )
        old_sub = merged[
            ["Event_ID", "state", "fia_plot_pairs", old_endpoint, metric]
        ].dropna()
        old_test = stats.spearmanr(old_sub[old_endpoint], old_sub[metric])
        expected_row = expected_lookup[(domain, comparison)]
        rho_diff = abs(float(old_test.statistic) - float(expected_row["spearman_rho"]))
        p_diff = abs(float(old_test.pvalue) - float(expected_row["raw_p"]))
        full_reproduction.append(
            {
                "domain": domain,
                "comparison": comparison,
                "n": int(len(old_sub)),
                "computed_rho": float(old_test.statistic),
                "expected_rho": float(expected_row["spearman_rho"]),
                "rho_abs_diff": rho_diff,
                "computed_p": float(old_test.pvalue),
                "expected_p": float(expected_row["raw_p"]),
                "p_abs_diff": p_diff,
                "exact_within_1e_12": bool(rho_diff < 1e-12 and p_diff < 1e-12),
            }
        )
        sub = merged[
            ["Event_ID", "state", "fia_plot_pairs", new_endpoint, metric]
        ].dropna()
        expected_n = 40 if domain == "canopy_amount" else 35
        if len(sub) != expected_n:
            raise RuntimeError(
                f"Aligned FIA {domain}/{comparison}: expected n={expected_n}, got {len(sub)}"
            )
        test = stats.spearmanr(sub[new_endpoint], sub[metric])
        more_than_one = sub[sub["fia_plot_pairs"].gt(1)]
        no_one_test = stats.spearmanr(
            more_than_one[new_endpoint], more_than_one[metric]
        )
        leave_one_state = []
        for state in sorted(sub["state"].unique()):
            loo = sub[sub["state"].ne(state)]
            leave_one_state.append(
                float(stats.spearmanr(loo[new_endpoint], loo[metric]).statistic)
            )
        raw_ps.append(float(test.pvalue))
        aligned_rows.append(
            {
                "domain": domain,
                "comparison": comparison,
                "fia_metric": metric,
                "aligned_endpoint": new_endpoint,
                "n": int(len(sub)),
                "state_n": int(sub["state"].nunique()),
                "aligned_spearman_rho": float(test.statistic),
                "aligned_raw_p": float(test.pvalue),
                "aligned_pair_weighted_rank_correlation": weighted_rank_correlation(
                    sub[new_endpoint].to_numpy(),
                    sub[metric].to_numpy(),
                    sub["fia_plot_pairs"].to_numpy(),
                ),
                "aligned_n_plot_pairs_gt_1": int(len(more_than_one)),
                "aligned_rho_plot_pairs_gt_1": float(no_one_test.statistic),
                "aligned_p_plot_pairs_gt_1": float(no_one_test.pvalue),
                "aligned_leave_one_state_out_rho_min": float(
                    np.min(leave_one_state)
                ),
                "aligned_leave_one_state_out_rho_max": float(
                    np.max(leave_one_state)
                ),
                "full_perimeter_sensitivity_rho": float(old_test.statistic),
                "full_perimeter_sensitivity_raw_p": float(old_test.pvalue),
            }
        )
    adjusted = multipletests(raw_ps, method="holm")[1]
    for row, adjusted_p in zip(aligned_rows, adjusted):
        row["aligned_holm_p"] = float(adjusted_p)
    reproduction = pd.DataFrame(full_reproduction)
    if not reproduction["exact_within_1e_12"].all():
        raise RuntimeError("Full-perimeter FIA reproduction failed")
    audit = {
        "fia_events": int(len(merged)),
        "states": int(merged["state"].nunique()),
        "canopy_endpoint_nonmissing": int(
            merged["lrsd_canopy_amount"].notna().sum()
        ),
        "height_endpoint_nonmissing": int(merged["lrsd_height"].notna().sum()),
        "full_perimeter_reproduction_pass": True,
    }
    return pd.DataFrame(aligned_rows), merged, {
        "audit": audit,
        "full_perimeter_reproduction": full_reproduction,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--raw-dir", required=True, type=Path)
    parser.add_argument("--package", required=True, type=Path)
    parser.add_argument("--existing-endpoints", required=True, type=Path)
    parser.add_argument("--fia-panel", required=True, type=Path)
    parser.add_argument("--fia-expected", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)

    internal_path = args.package / "05_INTERNAL_EO_RESULTS.json"
    internal = json.loads(internal_path.read_text(encoding="utf-8"))
    primary = pd.DataFrame(internal["compact_primary_event_panel"])
    primary["Event_ID"] = primary["Event_ID"].astype(str)
    fixed_ids = set(primary["Event_ID"])
    if len(fixed_ids) != 318:
        raise RuntimeError(f"Expected 318 fixed events, found {len(fixed_ids)}")

    raw, raw_inventory = load_exports(args.raw_dir)
    proxy_rows = raw[raw["row_kind"].eq("forest_aligned_proxy")].copy()
    structure_rows = raw[raw["row_kind"].eq("forest_aligned_structure")].copy()
    status = build_proxy_status(proxy_rows, fixed_ids)
    endpoints, support = build_structure_endpoints(structure_rows, fixed_ids)
    if len(endpoints) != 318 or endpoints["Event_ID"].nunique() != 318:
        raise RuntimeError("Recomputed forest-aligned endpoints are not one row per fixed event")

    existing = pd.read_csv(args.existing_endpoints)
    compare_columns = list(DOMAINS.values())
    check = existing[["Event_ID", *compare_columns]].merge(
        endpoints[["Event_ID", *compare_columns]],
        on="Event_ID",
        suffixes=("_existing", "_recomputed"),
        validate="one_to_one",
    )
    endpoint_max_abs_diff = {}
    for column in compare_columns:
        difference = (
            check[f"{column}_existing"] - check[f"{column}_recomputed"]
        ).abs()
        endpoint_max_abs_diff[column] = float(difference.max(skipna=True))
        if endpoint_max_abs_diff[column] > 1e-12:
            raise RuntimeError(
                f"Endpoint reproduction failed for {column}: "
                f"{endpoint_max_abs_diff[column]}"
            )

    threshold, support_summary, merged_event_panel = threshold_and_support_summaries(
        status, endpoints, support
    )
    expected_primary = {
        ("NDVI", "cohort_n"): 227,
        ("NBR", "cohort_n"): 153,
        ("NDVI", "tail_n"): 70,
        ("NBR", "tail_n"): 37,
    }
    primary_context = threshold[
        threshold["tau"].eq(0.90) & threshold["domain"].eq("contextual")
    ]
    for proxy in PRIMARY_PROXIES:
        row = primary_context[primary_context["proxy"].eq(proxy)].iloc[0]
        if int(row["cohort_n"]) != expected_primary[(proxy, "cohort_n")]:
            raise RuntimeError(f"{proxy} primary strict cohort regression failed")
        if int(row["tail_n"]) != expected_primary[(proxy, "tail_n")]:
            raise RuntimeError(f"{proxy} primary contextual tail regression failed")

    re_status = status[status["tau"].eq("re_attainment_090")].copy()
    re_counts = (
        re_status.groupby("proxy")["attainment_strict"].sum().astype(int).to_dict()
    )
    strict_initial = re_status[
        re_status["initial_attainment_strict"].fillna(False).astype(bool)
    ]
    initial_decline_counts = (
        strict_initial.groupby("proxy")["decline_before_initial_attainment"]
        .sum()
        .astype(int)
        .to_dict()
    )
    if re_counts != {"NBR": 75, "NDVI": 90}:
        raise RuntimeError(f"Post-decline re-attainment regression failed: {re_counts}")
    if initial_decline_counts != {"NBR": 59, "NDVI": 84}:
        raise RuntimeError(
            "Decline-before-initial-attainment regression failed: "
            f"{initial_decline_counts}"
        )

    fia_summary, fia_event_panel, fia_audit = fia_associations(
        args.fia_panel, endpoints, args.fia_expected
    )

    outputs = {
        "final_alignment_raw_input_manifest.csv": pd.DataFrame(raw_inventory),
        "forest_aligned_proxy_threshold_event_status.csv": status,
        "forest_aligned_threshold_sensitivity.csv": threshold,
        "forest_aligned_structure_event_endpoints_recomputed.csv": endpoints,
        "forest_aligned_gedi_support_event_panel.csv": support,
        "forest_aligned_gedi_support_sensitivity.csv": support_summary,
        "forest_aligned_primary_event_analysis_panel.csv": merged_event_panel,
        "forest_aligned_fia_event_panel.csv": fia_event_panel,
        "forest_aligned_fia_associations.csv": fia_summary,
        "full_perimeter_fia_reproduction.csv": pd.DataFrame(
            fia_audit["full_perimeter_reproduction"]
        ),
    }
    for name, frame in outputs.items():
        write_csv(frame, args.output_dir / name)

    audit = {
        "status": "FINAL_ALIGNMENT_LOCAL_ANALYSES_COMPLETE",
        "fixed_event_count": len(fixed_ids),
        "raw_export_event_count": int(raw["Event_ID"].nunique()),
        "raw_export_file_count": len(raw_inventory),
        "parameters": {
            "taus": list(TAUS),
            "run": RUN,
            "strict_completion_calendar_year_max": STRICT_COMPLETION_YEAR_MAX,
            "delta": DELTA,
            "gedi_support_rule": "median annual burned RH98 valid 25-m composite cells >=20",
        },
        "baseline_regressions": {
            "primary_contextual": primary_context.to_dict(orient="records"),
            "post_decline_re_attainment_strict_counts": re_counts,
            "decline_before_initial_attainment_counts": initial_decline_counts,
            "endpoint_max_abs_difference": endpoint_max_abs_diff,
            "fia": fia_audit["audit"],
        },
        "runtime": {
            "python": sys.version,
            "platform": platform.platform(),
            "pandas": pd.__version__,
            "numpy": np.__version__,
            "scipy": scipy.__version__,
        },
        "inputs": {},
        "outputs": {},
    }
    input_paths = {
        "internal_results": internal_path,
        "existing_endpoints": args.existing_endpoints,
        "fia_panel": args.fia_panel,
        "fia_expected": args.fia_expected,
        "analysis_script": Path(__file__),
    }
    for key, path in input_paths.items():
        audit["inputs"][key] = {
            "path": str(path),
            "bytes": path.stat().st_size,
            "sha256": sha256(path),
        }
    for name in outputs:
        path = args.output_dir / name
        audit["outputs"][name] = {
            "bytes": path.stat().st_size,
            "sha256": sha256(path),
            "rows": int(len(outputs[name])),
        }
    audit_path = args.output_dir / "final_alignment_local_analysis_audit.json"
    audit_path.write_text(
        json.dumps(json_clean(audit), indent=2, ensure_ascii=False, allow_nan=False)
        + "\n",
        encoding="utf-8",
    )
    print(json.dumps(json_clean(audit["baseline_regressions"]), indent=2))


if __name__ == "__main__":
    main()
