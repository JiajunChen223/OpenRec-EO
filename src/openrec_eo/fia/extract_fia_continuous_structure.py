from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd


HERE = Path(__file__).resolve().parent
FIA = HERE / "source_metadata" / "fia"
ASSOCIATIONS = HERE / "fia_strict_measurement_event_associations.csv"
CANDIDATES = HERE / "fia_strict_repeated_plot_candidates.csv"
TREE_MANIFEST = HERE / "fia_tree_download_manifest.json"
PROTOCOL = HERE / "FIA_CONTINUOUS_STRUCTURE_PROTOCOL_FROZEN.md"
EPS = 1e-6
TREE_COLS = ["PLT_CN", "STATUSCD", "DIA", "TPA_UNADJ", "DRYBIO_AG", "HT"]
METRICS = ["basal_area_ft2_ac", "biomass_lb_ac", "tree_density_ac", "qmd_in", "ba_weighted_height_ft"]


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def metric_row(group: pd.DataFrame) -> dict:
    live = group[
        group["STATUSCD"].eq(1)
        & group["DIA"].gt(0)
        & group["TPA_UNADJ"].gt(0)
        & group["DIA"].ge(5.0)
    ].copy()
    expanded_ba = 0.005454 * live["DIA"].pow(2) * live["TPA_UNADJ"]
    biomass_valid = live["DRYBIO_AG"].notna()
    height_valid = live["HT"].gt(0)
    tpa_sum = live["TPA_UNADJ"].sum()
    return {
        "eligible_tree_records": int(len(live)),
        "basal_area_ft2_ac": float(expanded_ba.sum()),
        "biomass_lb_ac": float((live.loc[biomass_valid, "DRYBIO_AG"] * live.loc[biomass_valid, "TPA_UNADJ"]).sum()),
        "biomass_record_coverage": float(biomass_valid.mean()) if len(live) else np.nan,
        "tree_density_ac": float(tpa_sum),
        "qmd_in": float(np.sqrt((live["DIA"].pow(2) * live["TPA_UNADJ"]).sum() / tpa_sum)) if tpa_sum > 0 else np.nan,
        "ba_weighted_height_ft": float(np.average(live.loc[height_valid, "HT"], weights=expanded_ba.loc[height_valid])) if height_valid.any() and expanded_ba.loc[height_valid].sum() > 0 else np.nan,
        "height_record_coverage": float(height_valid.mean()) if len(live) else np.nan,
    }


def main() -> None:
    manifest = json.loads(TREE_MANIFEST.read_text(encoding="utf-8"))
    if manifest.get("status") != "FIA_TREE_TABLES_DOWNLOADED_FOR_FROZEN_CANDIDATE_STATES":
        raise RuntimeError("TREE download manifest is absent or not frozen")
    if manifest.get("protocol_sha256") != sha256(PROTOCOL):
        raise RuntimeError("Frozen protocol hash changed")

    assoc = pd.read_csv(ASSOCIATIONS, dtype={"plot_measurement_cn": "string"})
    cand = pd.read_csv(CANDIDATES)
    selections = []
    for row in cand.itertuples(index=False):
        group = assoc[(assoc["Event_ID"] == row.Event_ID) & (assoc["stable_plot_key"] == row.stable_plot_key)]
        for period, year in (("pre", row.prefire_year), ("post", row.postfire_year)):
            match = group[group["measure_year"].eq(year)]
            cns = sorted(match["plot_measurement_cn"].dropna().astype(str).unique())
            if len(cns) != 1:
                raise RuntimeError(f"Expected one {period} measurement CN for {row.Event_ID}/{row.stable_plot_key}; got {len(cns)}")
            selections.append({"Event_ID": row.Event_ID, "stable_plot_key": row.stable_plot_key, "state": str(row.Event_ID)[:2], "fire_year": int(row.fire_year), "period": period, "measure_year": int(year), "plot_measurement_cn": cns[0]})
    selected = pd.DataFrame(selections)

    metric_rows = []
    for state, state_sel in selected.groupby("state", sort=True):
        wanted = set(state_sel["plot_measurement_cn"])
        kept = []
        for chunk in pd.read_csv(FIA / f"{state}_TREE.csv", usecols=TREE_COLS, dtype={"PLT_CN": "string"}, chunksize=250_000, low_memory=False):
            hit = chunk[chunk["PLT_CN"].isin(wanted)].copy()
            if len(hit):
                kept.append(hit)
        trees = pd.concat(kept, ignore_index=True) if kept else pd.DataFrame(columns=TREE_COLS)
        for cn, group in trees.groupby("PLT_CN", sort=False):
            metric_rows.append({"state": state, "plot_measurement_cn": str(cn), **metric_row(group)})
    measurement_metrics = pd.DataFrame(metric_rows)
    selected = selected.merge(measurement_metrics, on=["state", "plot_measurement_cn"], how="left", validate="many_to_one")

    pair_rows = []
    for (event_id, plot_key), group in selected.groupby(["Event_ID", "stable_plot_key"], sort=True):
        if set(group["period"]) != {"pre", "post"}:
            raise RuntimeError("Incomplete pre/post selection")
        pre = group.set_index("period").loc["pre"]
        post = group.set_index("period").loc["post"]
        out = {"Event_ID": event_id, "stable_plot_key": plot_key, "state": pre["state"], "fire_year": int(pre["fire_year"]), "prefire_year": int(pre["measure_year"]), "postfire_year": int(post["measure_year"]), "prefire_tree_records": pre["eligible_tree_records"], "postfire_tree_records": post["eligible_tree_records"]}
        for metric in METRICS:
            a, b = pre[metric], post[metric]
            out[f"pre_{metric}"] = a
            out[f"post_{metric}"] = b
            out[f"delta_{metric}"] = b - a if pd.notna(a) and pd.notna(b) else np.nan
            out[f"ratio_{metric}"] = (b + EPS) / (a + EPS) if pd.notna(a) and pd.notna(b) else np.nan
            out[f"log_ratio_{metric}"] = np.log((b + EPS) / (a + EPS)) if pd.notna(a) and pd.notna(b) else np.nan
        pair_rows.append(out)
    pairs = pd.DataFrame(pair_rows)
    event_cols = [c for c in pairs.columns if c.startswith("log_ratio_") or c.startswith("ratio_") or c.startswith("delta_")]
    events = pairs.groupby("Event_ID", as_index=False)[event_cols].median()
    counts = pairs.groupby("Event_ID", as_index=False).agg(fia_plot_pairs=("stable_plot_key", "nunique"), fire_year=("fire_year", "first"), state=("state", "first"))
    events = counts.merge(events, on="Event_ID", validate="one_to_one")

    selected.to_csv(HERE / "fia_selected_measurement_metrics.csv", index=False, lineterminator="\n")
    pairs.to_csv(HERE / "fia_plot_pair_structure_change.csv", index=False, lineterminator="\n")
    events.to_csv(HERE / "fia_event_structure_change.csv", index=False, lineterminator="\n")
    summary = {
        "status": "FIA_CONTINUOUS_STRUCTURE_EXTRACTION_COMPLETE",
        "selected_measurements": int(len(selected)),
        "measurements_matched_to_tree_records": int(selected["eligible_tree_records"].notna().sum()),
        "plot_pairs": int(len(pairs)),
        "events": int(events["Event_ID"].nunique()),
        "events_by_plot_pair_count": {str(k): int(v) for k, v in events["fia_plot_pairs"].value_counts().sort_index().items()},
        "metric_nonmissing_plot_pairs": {metric: int(pairs[f"log_ratio_{metric}"].notna().sum()) for metric in METRICS},
    }
    summary_path = HERE / "fia_continuous_structure_summary.json"
    summary_path.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    outputs = [HERE / "fia_selected_measurement_metrics.csv", HERE / "fia_plot_pair_structure_change.csv", HERE / "fia_event_structure_change.csv", summary_path]
    extraction_manifest = {"status": "FIA_CONTINUOUS_STRUCTURE_EXTRACTION_FROZEN", "tree_manifest_sha256": sha256(TREE_MANIFEST), "protocol_sha256": sha256(PROTOCOL), "script_sha256": sha256(Path(__file__)), "outputs": [{"path": p.name, "bytes": p.stat().st_size, "sha256": sha256(p)} for p in outputs]}
    (HERE / "fia_continuous_structure_manifest.json").write_text(json.dumps(extraction_manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(summary, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
