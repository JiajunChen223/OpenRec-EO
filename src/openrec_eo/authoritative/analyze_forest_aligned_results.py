from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd


TAU = 0.90
RUN = 2
DELTA = 0.20
PRIMARY_PROXIES = {"NDVI": "forest_burned_NDVI_mean", "NBR": "forest_burned_NBR_mean"}
COMPONENTS = ["rh98", "cover", "pai"]
SENTINEL = -9999
BOOT_REPS = 5000
SEED = 20260723


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


def load_exports(raw_dir: Path) -> pd.DataFrame:
    paths = sorted(raw_dir.glob("openrec_forest_aligned_v2_*.csv"))
    if not paths:
        raise RuntimeError(f"No v2 exports found in {raw_dir}")
    frames = []
    for path in paths:
        frame = pd.read_csv(path)
        if frame["Event_ID"].astype(str).nunique() != 1:
            raise RuntimeError(f"Unexpected event count in {path.name}")
        if int(frame["row_kind"].eq("forest_aligned_structure").sum()) != 3:
            raise RuntimeError(f"Expected three structure rows in {path.name}")
        frames.append(frame)
    out = pd.concat(frames, ignore_index=True)
    out["Event_ID"] = out["Event_ID"].astype(str)
    return out


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
    values["ratio"] = (
        values["value"] / baseline
        if np.isfinite(baseline) and baseline != 0
        else np.nan
    )
    return fire_year, baseline, values


def first_completion(
    values: pd.DataFrame, required_decline: float | None = None
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
        if not (np.all(np.diff(selected_years) == 1) and np.all(selected_ratios >= TAU)):
            continue
        if required_decline is not None and not np.any(
            ratios[:start_index] < required_decline
        ):
            continue
        return float(selected_years[0]), float(selected_years[-1]), True
    return np.nan, np.nan, False


def proxy_status(proxy_rows: pd.DataFrame, fixed_ids: set[str]) -> pd.DataFrame:
    rows = []
    proxy_rows = proxy_rows[proxy_rows["Event_ID"].isin(fixed_ids)].copy()
    for event_id, sub in proxy_rows.groupby("Event_ID", sort=False):
        for proxy, value_col in PRIMARY_PROXIES.items():
            fire_year, baseline, values = event_trajectory(sub, value_col)
            attain_start, attain_end, attained = first_completion(values)
            ret90_start, ret90_end, ret90 = first_completion(values, 0.90)
            ret85_start, ret85_end, ret85 = first_completion(values, 0.85)
            post = values.loc[
                values["relative_year"].ge(1) & values["ratio"].notna(),
                ["relative_year", "ratio"],
            ]
            fire_year_ratio = values.loc[
                values["relative_year"].eq(0), "ratio"
            ]
            postfire_year1_ratio = values.loc[
                values["relative_year"].eq(1), "ratio"
            ]
            before = (
                post.loc[post["relative_year"].lt(attain_start), "ratio"]
                if attained
                else pd.Series(dtype=float)
            )
            rows.append(
                {
                    "Event_ID": event_id,
                    "proxy": proxy,
                    "fire_year": fire_year,
                    "baseline": baseline,
                    "prefire_valid_year_n": int(
                        values.loc[
                            values["relative_year"].isin([-3, -2, -1]), "value"
                        ].notna().sum()
                    ),
                    "postfire_valid_year_n": int(len(post)),
                    "fire_year_ratio": (
                        float(fire_year_ratio.iloc[0])
                        if len(fire_year_ratio)
                        else np.nan
                    ),
                    "postfire_year1_ratio": (
                        float(postfire_year1_ratio.iloc[0])
                        if len(postfire_year1_ratio)
                        else np.nan
                    ),
                    "postfire_min_ratio": (
                        float(post["ratio"].min()) if len(post) else np.nan
                    ),
                    "attainment_start_relative_year": attain_start,
                    "attainment_completion_relative_year": attain_end,
                    "attainment_completion_calendar_year": (
                        fire_year + attain_end if attained else np.nan
                    ),
                    "attainment_original": bool(attained),
                    "attainment_strict": bool(
                        attained and fire_year + attain_end <= 2018
                    ),
                    "attainment_direct_year1_2": bool(
                        attained and attain_start == 1
                    ),
                    "observed_decline_lt_090_before_attainment": bool(
                        attained and np.any(before < 0.90)
                    ),
                    "observed_decline_lt_085_before_attainment": bool(
                        attained and np.any(before < 0.85)
                    ),
                    "return090_completion_relative_year": ret90_end,
                    "return090_completion_calendar_year": (
                        fire_year + ret90_end if ret90 else np.nan
                    ),
                    "return090_original": bool(ret90),
                    "return090_strict": bool(
                        ret90 and fire_year + ret90_end <= 2018
                    ),
                    "return085_completion_relative_year": ret85_end,
                    "return085_completion_calendar_year": (
                        fire_year + ret85_end if ret85 else np.nan
                    ),
                    "return085_original": bool(ret85),
                    "return085_strict": bool(
                        ret85 and fire_year + ret85_end <= 2018
                    ),
                }
            )
    return pd.DataFrame(rows)


def structure_endpoints(structure_rows: pd.DataFrame, fixed_ids: set[str]) -> pd.DataFrame:
    use = structure_rows[structure_rows["Event_ID"].isin(fixed_ids)].copy()
    for component in COMPONENTS:
        burned = clean_numeric(use[f"forest_burned_{component}_mean"])
        reference = clean_numeric(use[f"forest_reference_{component}_mean"])
        use[f"q_{component}_annual"] = burned / reference.where(reference.gt(0))

    rows = []
    for event_id, sub in use.groupby("Event_ID", sort=False):
        q = {
            component: float(sub[f"q_{component}_annual"].median(skipna=True))
            if sub[f"q_{component}_annual"].notna().any()
            else np.nan
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
        signed_height = signed["rh98"]
        signed_canopy = (
            float(np.median([signed["cover"], signed["pai"]]))
            if np.isfinite(signed["cover"]) and np.isfinite(signed["pai"])
            else np.nan
        )
        height = deficit["rh98"]
        canopy = (
            float(np.median([deficit["cover"], deficit["pai"]]))
            if np.isfinite(deficit["cover"]) and np.isfinite(deficit["pai"])
            else np.nan
        )
        contextual = (
            float(np.median([deficit["rh98"], deficit["cover"], deficit["pai"]]))
            if all(np.isfinite(deficit[component]) for component in COMPONENTS)
            else np.nan
        )
        balanced = (
            (height + canopy) / 2.0
            if np.isfinite(height) and np.isfinite(canopy)
            else np.nan
        )
        valid_years = sub.loc[
            sub[[f"q_{c}_annual" for c in COMPONENTS]].notna().any(axis=1),
            "obs_year",
        ]
        rows.append(
            {
                "Event_ID": event_id,
                "q_rh98": q["rh98"],
                "q_cover": q["cover"],
                "q_pai": q["pai"],
                "lrsd_contextual": contextual,
                "lrsd_balanced": balanced,
                "lrsd_height": height,
                "lrsd_canopy_amount": canopy,
                "signed_height": signed_height,
                "signed_canopy_amount": signed_canopy,
                "signed_canopy_minus_height": (
                    signed_canopy - signed_height
                    if np.isfinite(signed_canopy) and np.isfinite(signed_height)
                    else np.nan
                ),
                "valid_structure_year_n": int(valid_years.nunique()),
                "first_valid_structure_year": (
                    int(pd.to_numeric(valid_years).min())
                    if len(valid_years)
                    else np.nan
                ),
            }
        )
    return pd.DataFrame(rows)


def bootstrap_intervals(sub: pd.DataFrame, value_col: str) -> dict[str, float]:
    clean = sub.dropna(subset=[value_col, "state_code"]).copy()
    if clean.empty:
        return {
            "event_boot_low": np.nan,
            "event_boot_high": np.nan,
            "state_boot_low": np.nan,
            "state_boot_high": np.nan,
        }
    rng = np.random.default_rng(SEED)
    values = clean[value_col].to_numpy(float)
    event_est = []
    for _ in range(BOOT_REPS):
        sample = rng.choice(values, size=len(values), replace=True)
        event_est.append(np.mean(sample > DELTA))
    states = clean["state_code"].astype(str).unique()
    state_groups = {
        state: clean.loc[clean["state_code"].astype(str).eq(state), value_col].to_numpy(float)
        for state in states
    }
    state_est = []
    for _ in range(BOOT_REPS):
        sampled_states = rng.choice(states, size=len(states), replace=True)
        sample = np.concatenate([state_groups[state] for state in sampled_states])
        state_est.append(np.mean(sample > DELTA))
    return {
        "event_boot_low": float(np.quantile(event_est, 0.025)),
        "event_boot_high": float(np.quantile(event_est, 0.975)),
        "state_boot_low": float(np.quantile(state_est, 0.025)),
        "state_boot_high": float(np.quantile(state_est, 0.975)),
    }


def endpoint_summary(
    status: pd.DataFrame, endpoints: pd.DataFrame, primary: pd.DataFrame
) -> pd.DataFrame:
    merged = status.merge(endpoints, on="Event_ID", how="left").merge(
        primary[["Event_ID", "state_code"]], on="Event_ID", how="left"
    )
    definitions = [
        ("attainment_original", "attainment_original"),
        ("attainment_strict", "attainment_strict"),
        ("return090_strict", "return090_strict"),
        ("return085_strict", "return085_strict"),
    ]
    domains = {
        "contextual": "lrsd_contextual",
        "balanced": "lrsd_balanced",
        "height": "lrsd_height",
        "canopy_amount": "lrsd_canopy_amount",
    }
    rows = []
    for proxy in PRIMARY_PROXIES:
        proxy_data = merged[merged["proxy"].eq(proxy)]
        for definition, flag in definitions:
            cohort = proxy_data[proxy_data[flag].astype(bool)].copy()
            for domain, value_col in domains.items():
                values = cohort[value_col].dropna()
                row = {
                    "proxy": proxy,
                    "definition": definition,
                    "domain": domain,
                    "cohort_n": int(len(cohort)),
                    "endpoint_n": int(len(values)),
                    "missing_endpoint_n": int(len(cohort) - len(values)),
                    "tail_n": int(values.gt(DELTA).sum()),
                    "tail_fraction": float(values.gt(DELTA).mean())
                    if len(values)
                    else np.nan,
                    "median_lrsd": float(values.median()) if len(values) else np.nan,
                }
                if definition == "attainment_strict" and domain == "contextual":
                    row.update(bootstrap_intervals(cohort, value_col))
                rows.append(row)
    return pd.DataFrame(rows)


def cohort_comparison(status: pd.DataFrame, temporal: pd.DataFrame) -> pd.DataFrame:
    old = temporal[temporal["proxy"].isin(PRIMARY_PROXIES)].copy()
    old["old_original"] = old["apparent_recovered"].astype(bool)
    old["old_strict"] = old["ordering_status"].eq("STRICT_GLOBAL_PREWINDOW")
    old["old_completion"] = pd.to_numeric(
        old["completion_relative_year"], errors="coerce"
    )
    merged = old.merge(status, on=["Event_ID", "proxy"], how="inner", validate="one_to_one")
    rows = []
    for proxy in PRIMARY_PROXIES:
        sub = merged[merged["proxy"].eq(proxy)]
        for definition, old_col, new_col in [
            ("original", "old_original", "attainment_original"),
            ("strict", "old_strict", "attainment_strict"),
        ]:
            old_ids = set(sub.loc[sub[old_col].astype(bool), "Event_ID"])
            new_ids = set(sub.loc[sub[new_col].astype(bool), "Event_ID"])
            intersection = old_ids & new_ids
            union = old_ids | new_ids
            common = sub[sub["Event_ID"].isin(intersection)].copy()
            changed = (
                pd.to_numeric(
                    common["attainment_completion_relative_year"], errors="coerce"
                )
                .fillna(-999)
                .ne(common["old_completion"].fillna(-999))
            )
            rows.append(
                {
                    "proxy": proxy,
                    "definition": definition,
                    "full_perimeter_n": len(old_ids),
                    "forest_aligned_n": len(new_ids),
                    "intersection_n": len(intersection),
                    "union_n": len(union),
                    "jaccard": len(intersection) / len(union) if union else np.nan,
                    "newly_included_n": len(new_ids - old_ids),
                    "excluded_n": len(old_ids - new_ids),
                    "completion_year_changed_n_among_intersection": int(changed.sum()),
                }
            )
    return pd.DataFrame(rows)


def prefire_similarity(proxy_rows: pd.DataFrame, fixed_ids: set[str]) -> tuple[pd.DataFrame, pd.DataFrame]:
    pre = proxy_rows[
        proxy_rows["Event_ID"].isin(fixed_ids)
        & pd.to_numeric(proxy_rows["relative_year"], errors="coerce").isin([-3, -2, -1])
    ].copy()
    event_rows = []
    for event_id, sub in pre.groupby("Event_ID", sort=False):
        for proxy in PRIMARY_PROXIES:
            burned = clean_numeric(sub[f"forest_burned_{proxy}_mean"]).median()
            reference = clean_numeric(sub[f"forest_reference_{proxy}_mean"]).median()
            event_rows.append(
                {
                    "Event_ID": event_id,
                    "proxy": proxy,
                    "burned_prefire_median": burned,
                    "reference_prefire_median": reference,
                    "difference_burned_minus_reference": burned - reference,
                    "absolute_difference": abs(burned - reference),
                }
            )
    event = pd.DataFrame(event_rows)
    summary = []
    for proxy, sub in event.groupby("proxy"):
        clean = sub.dropna(
            subset=[
                "burned_prefire_median",
                "reference_prefire_median",
                "difference_burned_minus_reference",
            ]
        )
        diff = clean["difference_burned_minus_reference"]
        sd = diff.std(ddof=1)
        summary.append(
            {
                "proxy": proxy,
                "n": len(clean),
                "burned_median": clean["burned_prefire_median"].median(),
                "reference_median": clean["reference_prefire_median"].median(),
                "difference_median": diff.median(),
                "difference_iqr_low": diff.quantile(0.25),
                "difference_iqr_high": diff.quantile(0.75),
                "absolute_difference_median": clean["absolute_difference"].median(),
                "paired_standardized_mean_difference": (
                    diff.mean() / sd if np.isfinite(sd) and sd > 0 else np.nan
                ),
                "pearson_burned_reference": clean[
                    ["burned_prefire_median", "reference_prefire_median"]
                ].corr().iloc[0, 1],
            }
        )
    return event, pd.DataFrame(summary)


def write_csv(frame: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(path, index=False, encoding="utf-8", lineterminator="\n")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--raw-dir", required=True)
    parser.add_argument("--package", required=True)
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--output-dir", required=True)
    args = parser.parse_args()

    raw_dir = Path(args.raw_dir)
    package = Path(args.package)
    manifest_path = Path(args.manifest)
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    manifest = pd.read_csv(manifest_path)
    if len(manifest) != 320 or not manifest["task_state"].eq("COMPLETED").all():
        raise RuntimeError("Analysis requires 320 completed v2 tasks.")

    internal = json.loads(
        (package / "05_INTERNAL_EO_RESULTS.json").read_text(encoding="utf-8")
    )
    primary = pd.DataFrame(internal["compact_primary_event_panel"])
    temporal = pd.DataFrame(internal["compact_proxy_temporal_panel"])
    primary["Event_ID"] = primary["Event_ID"].astype(str)
    temporal["Event_ID"] = temporal["Event_ID"].astype(str)
    fixed_ids = set(primary["Event_ID"])

    raw = load_exports(raw_dir)
    if raw["Event_ID"].nunique() != 320:
        raise RuntimeError(f"Expected 320 raw event files, found {raw['Event_ID'].nunique()}")
    proxy_rows = raw[raw["row_kind"].eq("forest_aligned_proxy")].copy()
    structure_rows = raw[raw["row_kind"].eq("forest_aligned_structure")].copy()
    status = proxy_status(proxy_rows, fixed_ids)
    endpoints = structure_endpoints(structure_rows, fixed_ids)
    summary = endpoint_summary(status, endpoints, primary)
    comparison = cohort_comparison(status, temporal)
    prefire_event, prefire_summary = prefire_similarity(proxy_rows, fixed_ids)

    outputs = {
        "forest_aligned_proxy_event_status.csv": status,
        "forest_aligned_structure_event_endpoints.csv": endpoints,
        "forest_aligned_endpoint_summary.csv": summary,
        "full_perimeter_vs_forest_aligned_cohorts.csv": comparison,
        "prefire_comparator_event_similarity.csv": prefire_event,
        "prefire_comparator_summary.csv": prefire_summary,
    }
    raw_inventory_rows = []
    for path in sorted(raw_dir.glob("openrec_forest_aligned_v2_*.csv")):
        frame = pd.read_csv(path)
        raw_inventory_rows.append(
            {
                "file": path.name,
                "bytes": path.stat().st_size,
                "sha256": sha256(path),
                "rows": len(frame),
                "event_id": str(frame["Event_ID"].iloc[0]),
                "proxy_rows": int(frame["row_kind"].eq("forest_aligned_proxy").sum()),
                "structure_rows": int(
                    frame["row_kind"].eq("forest_aligned_structure").sum()
                ),
            }
        )
    outputs["raw_export_manifest.csv"] = pd.DataFrame(raw_inventory_rows)
    for name, frame in outputs.items():
        write_csv(frame, output_dir / name)

    strict_context = summary[
        summary["definition"].eq("attainment_strict")
        & summary["domain"].eq("contextual")
    ]
    strict_domain = summary[summary["definition"].eq("attainment_strict")]
    return_context = summary[
        summary["definition"].isin(["return090_strict", "return085_strict"])
        & summary["domain"].eq("contextual")
    ]
    audit = {
        "status": "FOREST_ALIGNED_EXPERIMENT_COMPLETE",
        "fixed_event_count": len(fixed_ids),
        "raw_export_event_count": int(raw["Event_ID"].nunique()),
        "proxy_row_count": int(len(proxy_rows)),
        "structure_row_count": int(len(structure_rows)),
        "parameters": {
            "tau": TAU,
            "run": RUN,
            "strict_completion_calendar_year_max": 2018,
            "delta": DELTA,
            "forest_mask": "LCMAP class 4 frequency >=0.5 over fire-year-3 to fire-year-1",
            "comparator": "2-10 km annulus with historical MTBS burn exclusion",
            "landsat_scale_m": 90,
            "gedi_scale_m": 25,
            "gedi_years": [2019, 2021],
        },
        "five_questions": {
            "strict_cohorts": strict_context[
                ["proxy", "cohort_n", "endpoint_n"]
            ].to_dict(orient="records"),
            "cohort_jaccard": comparison[
                comparison["definition"].eq("strict")
            ].to_dict(orient="records"),
            "contextual_lrsd": strict_context.to_dict(orient="records"),
            "canopy_vs_height": strict_domain[
                strict_domain["domain"].isin(["height", "canopy_amount"])
            ].to_dict(orient="records"),
            "return_after_decline": return_context.to_dict(orient="records"),
        },
        "inputs": {
            "manifest": {
                "path": str(manifest_path),
                "bytes": manifest_path.stat().st_size,
                "sha256": sha256(manifest_path),
            },
            "package_internal_results": {
                "path": str(package / "05_INTERNAL_EO_RESULTS.json"),
                "bytes": (package / "05_INTERNAL_EO_RESULTS.json").stat().st_size,
                "sha256": sha256(package / "05_INTERNAL_EO_RESULTS.json"),
            },
            "submit_script": {
                "path": str(Path(__file__).with_name("submit_forest_aligned_exports.py")),
                "sha256": sha256(
                    Path(__file__).with_name("submit_forest_aligned_exports.py")
                ),
            },
            "analysis_script": {
                "path": str(Path(__file__)),
                "sha256": sha256(Path(__file__)),
            },
        },
        "outputs": {},
    }
    for name in outputs:
        path = output_dir / name
        audit["outputs"][name] = {
            "bytes": path.stat().st_size,
            "sha256": sha256(path),
        }
    audit_path = output_dir / "forest_aligned_experiment_audit.json"
    audit_path.write_text(
        json.dumps(json_clean(audit), indent=2, ensure_ascii=False, allow_nan=False)
        + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "status": audit["status"],
                "strict_contextual": audit["five_questions"]["contextual_lrsd"],
                "strict_jaccard": audit["five_questions"]["cohort_jaccard"],
                "prefire_comparator": prefire_summary.to_dict(orient="records"),
                "output_dir": str(output_dir),
            },
            indent=2,
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
