from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats


SENTINEL = -9999
DELTA = 0.20
COMPONENTS = ("rh98", "cover", "pai")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def clean_numeric(series: pd.Series) -> pd.Series:
    values = pd.to_numeric(series, errors="coerce")
    return values.mask(values.eq(SENTINEL))


def write_csv(frame: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(path, index=False, encoding="utf-8", lineterminator="\n")


def endpoint_from_annual(frame: pd.DataFrame, reference_prefix: str) -> pd.DataFrame:
    use = frame.copy()
    for component in COMPONENTS:
        burned = clean_numeric(use[f"forest_burned_{component}_mean"])
        reference = clean_numeric(use[f"{reference_prefix}_{component}_mean"])
        use[f"q_{component}"] = burned / reference.where(reference.gt(0))
    rows = []
    for event_id, sub in use.groupby("Event_ID", sort=False):
        q = {
            component: (
                float(sub[f"q_{component}"].median(skipna=True))
                if sub[f"q_{component}"].notna().any()
                else np.nan
            )
            for component in COMPONENTS
        }
        deficit = {
            component: max(0.0, 1.0 - value) if np.isfinite(value) else np.nan
            for component, value in q.items()
        }
        contextual = (
            float(np.median([deficit[c] for c in COMPONENTS]))
            if all(np.isfinite(deficit[c]) for c in COMPONENTS)
            else np.nan
        )
        rows.append(
            {
                "Event_ID": str(event_id),
                "q_rh98_10_20km": q["rh98"],
                "q_cover_10_20km": q["cover"],
                "q_pai_10_20km": q["pai"],
                "lrsd_contextual_10_20km": contextual,
                "lrsd_height_10_20km": deficit["rh98"],
                "lrsd_canopy_amount_10_20km": (
                    float(np.median([deficit["cover"], deficit["pai"]]))
                    if np.isfinite(deficit["cover"]) and np.isfinite(deficit["pai"])
                    else np.nan
                ),
            }
        )
    return pd.DataFrame(rows)


def cohen_kappa(a: pd.Series, b: pd.Series) -> float:
    a = a.astype(bool)
    b = b.astype(bool)
    agreement = float(a.eq(b).mean())
    pa = float(a.mean())
    pb = float(b.mean())
    chance = pa * pb + (1.0 - pa) * (1.0 - pb)
    return float((agreement - chance) / (1.0 - chance)) if chance < 1 else np.nan


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--primary-raw-dir", required=True, type=Path)
    parser.add_argument("--alternative-raw-dir", required=True, type=Path)
    parser.add_argument("--primary-endpoints", required=True, type=Path)
    parser.add_argument("--proxy-status", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)

    primary_paths = sorted(
        args.primary_raw_dir.glob("openrec_forest_aligned_v2_*.csv")
    )
    alternative_paths = sorted(
        args.alternative_raw_dir.glob("openrec_forest_aligned_10_20km_v1_*.csv")
    )
    if len(primary_paths) != 320 or len(alternative_paths) != 320:
        raise RuntimeError(
            f"Expected 320+320 input files, got "
            f"{len(primary_paths)}+{len(alternative_paths)}"
        )
    primary_frames = []
    for path in primary_paths:
        frame = pd.read_csv(path)
        primary_frames.append(
            frame[frame["row_kind"].eq("forest_aligned_structure")].copy()
        )
    primary = pd.concat(primary_frames, ignore_index=True)
    alternative = pd.concat(
        [pd.read_csv(path) for path in alternative_paths], ignore_index=True
    )
    primary["Event_ID"] = primary["Event_ID"].astype(str)
    alternative["Event_ID"] = alternative["Event_ID"].astype(str)
    if alternative["Event_ID"].nunique() != 320:
        raise RuntimeError("Alternative exports do not contain 320 unique events")
    if not alternative["buffer_label"].eq("buf10_20km").all():
        raise RuntimeError("Alternative buffer label is not uniformly buf10_20km")
    if not pd.to_numeric(
        alternative["control_inner_buffer_m"], errors="coerce"
    ).eq(10000).all():
        raise RuntimeError("Alternative inner buffer is not uniformly 10000 m")
    if not pd.to_numeric(
        alternative["control_outer_buffer_m"], errors="coerce"
    ).eq(20000).all():
        raise RuntimeError("Alternative outer buffer is not uniformly 20000 m")
    if not alternative["forest_definition"].eq(
        "LCMAP_class4_frequency_gte_0.5_prefire3"
    ).all():
        raise RuntimeError("Alternative forest definition differs from primary")

    key = ["Event_ID", "obs_year"]
    ref_columns = [
        f"forest_reference_{component}_{suffix}"
        for component in COMPONENTS
        for suffix in ("mean", "stdDev", "count")
    ]
    annual = primary.merge(
        alternative[key + ref_columns],
        on=key,
        how="inner",
        validate="one_to_one",
        suffixes=("_2_10km", "_10_20km"),
    )
    if len(annual) != 960:
        raise RuntimeError(f"Expected 960 paired annual rows, got {len(annual)}")
    for component in COMPONENTS:
        annual[f"forest_alt_reference_{component}_mean"] = annual[
            f"forest_reference_{component}_mean_10_20km"
        ]
    alternative_endpoints = endpoint_from_annual(
        annual, reference_prefix="forest_alt_reference"
    )

    primary_endpoints = pd.read_csv(args.primary_endpoints)
    primary_endpoints["Event_ID"] = primary_endpoints["Event_ID"].astype(str)
    endpoint_panel = primary_endpoints[
        ["Event_ID", "lrsd_contextual"]
    ].merge(
        alternative_endpoints,
        on="Event_ID",
        how="inner",
        validate="one_to_one",
    )
    if len(endpoint_panel) != 318:
        raise RuntimeError(
            f"Expected 318 fixed paired endpoints, got {len(endpoint_panel)}"
        )

    status = pd.read_csv(args.proxy_status)
    status["Event_ID"] = status["Event_ID"].astype(str)
    status["tau_numeric"] = pd.to_numeric(status["tau"], errors="coerce")
    strict = status[
        status["tau_numeric"].eq(0.90)
        & status["attainment_strict"].astype(bool)
    ][["Event_ID", "proxy"]]
    summary_rows = []
    for proxy, cohort in strict.groupby("proxy", sort=True):
        use = cohort.merge(
            endpoint_panel, on="Event_ID", how="left", validate="one_to_one"
        ).dropna(subset=["lrsd_contextual", "lrsd_contextual_10_20km"])
        primary_class = use["lrsd_contextual"].gt(DELTA)
        alternative_class = use["lrsd_contextual_10_20km"].gt(DELTA)
        test = stats.spearmanr(
            use["lrsd_contextual"], use["lrsd_contextual_10_20km"]
        )
        summary_rows.append(
            {
                "proxy": proxy,
                "primary_comparator": "2--10 km",
                "alternative_comparator": "10--20 km",
                "cohort_n": int(len(cohort)),
                "paired_endpoint_n": int(len(use)),
                "primary_tail_n": int(primary_class.sum()),
                "primary_tail_fraction": float(primary_class.mean()),
                "alternative_tail_n": int(alternative_class.sum()),
                "alternative_tail_fraction": float(alternative_class.mean()),
                "spearman_rho": float(test.statistic),
                "median_absolute_difference": float(
                    np.median(
                        np.abs(
                            use["lrsd_contextual"]
                            - use["lrsd_contextual_10_20km"]
                        )
                    )
                ),
                "cohen_kappa": cohen_kappa(primary_class, alternative_class),
                "reclassified_n": int(primary_class.ne(alternative_class).sum()),
            }
        )
    summary = pd.DataFrame(summary_rows)

    write_csv(annual, args.output_dir / "forest_aligned_10_20km_annual_panel.csv")
    write_csv(
        alternative_endpoints,
        args.output_dir / "forest_aligned_10_20km_event_endpoints.csv",
    )
    write_csv(
        endpoint_panel,
        args.output_dir / "forest_aligned_comparator_paired_event_endpoints.csv",
    )
    write_csv(
        summary,
        args.output_dir / "forest_aligned_comparator_sensitivity.csv",
    )
    inventory = []
    for path in alternative_paths:
        frame = pd.read_csv(path)
        inventory.append(
            {
                "file": path.name,
                "bytes": path.stat().st_size,
                "sha256": sha256(path),
                "rows": int(len(frame)),
                "Event_ID": str(frame["Event_ID"].iloc[0]),
            }
        )
    write_csv(
        pd.DataFrame(inventory),
        args.output_dir / "forest_aligned_10_20km_raw_manifest.csv",
    )
    audit = {
        "status": "FOREST_ALIGNED_10_20KM_COMPARATOR_COMPLETE",
        "primary_raw_files": len(primary_paths),
        "alternative_raw_files": len(alternative_paths),
        "alternative_raw_events": int(alternative["Event_ID"].nunique()),
        "alternative_rows": int(len(alternative)),
        "paired_annual_rows": int(len(annual)),
        "fixed_endpoint_events": int(len(endpoint_panel)),
        "parameters": {
            "primary_comparator": "2--10 km",
            "alternative_comparator": "10--20 km",
            "delta": DELTA,
            "forest_definition": "LCMAP class 4 frequency >=0.5 over fire-year-3 to fire-year-1",
            "historical_burn_exclusion": True,
            "gedi_years": [2019, 2020, 2021],
            "gedi_scale_m": 25,
        },
        "summary": summary.to_dict(orient="records"),
        "inputs": {
            "script": {"path": str(Path(__file__)), "sha256": sha256(Path(__file__))},
            "primary_endpoints": {
                "path": str(args.primary_endpoints),
                "sha256": sha256(args.primary_endpoints),
            },
            "proxy_status": {
                "path": str(args.proxy_status),
                "sha256": sha256(args.proxy_status),
            },
        },
    }
    audit_path = args.output_dir / "forest_aligned_comparator_audit.json"
    audit_path.write_text(
        json.dumps(audit, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(audit["summary"], indent=2))


if __name__ == "__main__":
    main()
