from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any

import ee
import pandas as pd


PROJECT_ID = "openrec-eo-rse-2"
MTBS = "USFS/GTAC/MTBS/burned_area_boundaries/v1"
LCMAP = "projects/sat-io/open-datasets/LCMAP/LCPRI"
LANDSAT = [
    "LANDSAT/LT05/C02/T1_L2",
    "LANDSAT/LE07/C02/T1_L2",
    "LANDSAT/LC08/C02/T1_L2",
    "LANDSAT/LC09/C02/T1_L2",
]
GEDI_L2A = "LARSE/GEDI/GEDI02_A_002_MONTHLY"
GEDI_L2B = "LARSE/GEDI/GEDI02_B_002_MONTHLY"
DRIVE_FOLDER = "OpenRec_EO_RSE_forest_aligned_v2_20260723"
DESCRIPTION_PREFIX = "openrec_forest_aligned_v2"
LANDSAT_SCALE = 90
GEDI_SCALE = 25
INNER_BUFFER_M = 2000
OUTER_BUFFER_M = 10000
PREFIRE_YEARS = 3
START_GEDI_YEAR = 2019
END_GEDI_YEAR = 2021
MAX_OBS_YEAR = 2021
SELECTORS = [
    "Event_ID",
    "Incid_Name",
    "fire_year",
    "obs_year",
    "relative_year",
    "row_kind",
    "forest_definition",
    "forest_burned_NDVI_mean",
    "forest_burned_NDVI_stdDev",
    "forest_burned_NDVI_count",
    "forest_burned_NBR_mean",
    "forest_burned_NBR_stdDev",
    "forest_burned_NBR_count",
    "forest_reference_NDVI_mean",
    "forest_reference_NDVI_stdDev",
    "forest_reference_NDVI_count",
    "forest_reference_NBR_mean",
    "forest_reference_NBR_stdDev",
    "forest_reference_NBR_count",
    "landsat_image_count",
    "landsat_scale_m",
    "prefire_historical_burn_feature_count",
    "forest_burned_rh98_mean",
    "forest_burned_rh98_stdDev",
    "forest_burned_rh98_count",
    "forest_burned_cover_mean",
    "forest_burned_cover_stdDev",
    "forest_burned_cover_count",
    "forest_burned_pai_mean",
    "forest_burned_pai_stdDev",
    "forest_burned_pai_count",
    "forest_reference_rh98_mean",
    "forest_reference_rh98_stdDev",
    "forest_reference_rh98_count",
    "forest_reference_cover_mean",
    "forest_reference_cover_stdDev",
    "forest_reference_cover_count",
    "forest_reference_pai_mean",
    "forest_reference_pai_stdDev",
    "forest_reference_pai_count",
    "buffer_label",
    "control_inner_buffer_m",
    "control_outer_buffer_m",
    "historical_burn_feature_count",
    "gedi_l2a_image_count",
    "gedi_l2b_image_count",
    "gedi_scale_m",
]


def sanitize(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9_-]+", "_", value)[:90].strip("_")


def lcmap_image_for_year(collection: ee.ImageCollection, year: ee.Number) -> ee.Image:
    image_id = ee.String("LCMAP_CU_").cat(year.format("%.0f")).cat("_V13_LCPRI")
    return ee.Image(collection.filter(ee.Filter.eq("system:index", image_id)).first()).select("b1")


def prefire_forest_mask(fire_year: ee.Number) -> ee.Image:
    collection = ee.ImageCollection(LCMAP)
    years = ee.List.sequence(fire_year.subtract(PREFIRE_YEARS), fire_year.subtract(1))
    return (
        ee.ImageCollection.fromImages(
            years.map(lambda y: lcmap_image_for_year(collection, ee.Number(y)).eq(4))
        )
        .mean()
        .gte(0.5)
        .rename("prefire_forest")
    )


def mask_landsat_l2(img: ee.Image) -> ee.Image:
    qa = img.select("QA_PIXEL")
    clear = (
        qa.bitwiseAnd(1 << 0).eq(0)
        .And(qa.bitwiseAnd(1 << 1).eq(0))
        .And(qa.bitwiseAnd(1 << 2).eq(0))
        .And(qa.bitwiseAnd(1 << 3).eq(0))
        .And(qa.bitwiseAnd(1 << 4).eq(0))
        .And(qa.bitwiseAnd(1 << 5).eq(0))
        .And(img.select("QA_RADSAT").eq(0))
    )
    optical = img.select("SR_B.*").multiply(0.0000275).add(-0.2)
    return img.addBands(optical, None, True).updateMask(clear)


def rename_landsat(img: ee.Image) -> ee.Image:
    spacecraft = ee.String(img.get("SPACECRAFT_ID"))
    is_oli = spacecraft.match("LANDSAT_8|LANDSAT_9").length().gt(0)
    oli = img.select(
        ["SR_B2", "SR_B3", "SR_B4", "SR_B5", "SR_B6", "SR_B7"],
        ["blue", "green", "red", "nir", "swir1", "swir2"],
    )
    tm_etm = img.select(
        ["SR_B1", "SR_B2", "SR_B3", "SR_B4", "SR_B5", "SR_B7"],
        ["blue", "green", "red", "nir", "swir1", "swir2"],
    )
    return ee.Image(ee.Algorithms.If(is_oli, oli, tm_etm)).copyProperties(
        img, img.propertyNames()
    )


def add_indices(img: ee.Image) -> ee.Image:
    ndvi = img.normalizedDifference(["nir", "red"]).rename("NDVI")
    nbr = img.normalizedDifference(["nir", "swir2"]).rename("NBR")
    return img.addBands([ndvi, nbr])


def landsat_collection(start: ee.Date, end: ee.Date, geom: ee.Geometry) -> ee.ImageCollection:
    collections = [ee.ImageCollection(asset) for asset in LANDSAT]
    merged = collections[0]
    for collection in collections[1:]:
        merged = merged.merge(collection)
    return (
        merged.filterDate(start, end)
        .filterBounds(geom)
        .map(mask_landsat_l2)
        .map(rename_landsat)
        .map(add_indices)
    )


def annual_gedi_image(obs_year: ee.Number) -> tuple[ee.Image, ee.ImageCollection, ee.ImageCollection]:
    def mask_l2a(img: ee.Image) -> ee.Image:
        mask = (
            img.select("quality_flag").eq(1)
            .And(img.select("degrade_flag").eq(0))
            .And(img.select("sensitivity").gte(0.95))
        )
        return img.updateMask(mask)

    def mask_l2b(img: ee.Image) -> ee.Image:
        mask = (
            img.select("l2b_quality_flag").eq(1)
            .And(img.select("degrade_flag").eq(0))
            .And(img.select("sensitivity").gte(0.95))
        )
        return img.updateMask(mask)

    start = ee.Date.fromYMD(obs_year, 1, 1)
    end = ee.Date.fromYMD(obs_year.add(1), 1, 1)
    l2a = ee.ImageCollection(GEDI_L2A).filterDate(start, end).map(mask_l2a)
    l2b = ee.ImageCollection(GEDI_L2B).filterDate(start, end).map(mask_l2b)
    image = l2a.select(["rh98"]).median().addBands(l2b.select(["cover", "pai"]).median())
    return image, l2a, l2b


def add_fire_year(feature: ee.Feature) -> ee.Feature:
    return feature.set("fire_year", ee.Date(feature.get("Ig_Date")).get("year"))


def historical_burn_free_annulus(
    geom: ee.Geometry, cutoff_year: ee.Number
) -> tuple[ee.Geometry, ee.FeatureCollection]:
    annulus = geom.buffer(OUTER_BUFFER_M, 30).difference(
        geom.buffer(INNER_BUFFER_M, 30), 30
    )
    historical = (
        ee.FeatureCollection(MTBS)
        .filterBounds(annulus)
        .map(add_fire_year)
        .filter(ee.Filter.gte("fire_year", 1984))
        .filter(ee.Filter.lte("fire_year", cutoff_year))
    )
    return annulus.difference(historical.geometry(30), 30), historical


def prefix_stats(
    stats: ee.Dictionary, prefix: str, bands: list[str], suffixes: list[str]
) -> ee.Dictionary:
    values: dict[str, ee.ComputedObject] = {}
    for band in bands:
        for suffix in suffixes:
            key = f"{band}_{suffix}"
            value = stats.get(key)
            values[f"{prefix}{key}"] = ee.Algorithms.If(
                ee.Algorithms.IsEqual(value, None), -9999, value
            )
    return ee.Dictionary(values)


def build_event_collection(
    fire: ee.Feature, event_id: str, incid_name: str, fire_year_value: int
) -> ee.FeatureCollection:
    geom = fire.geometry()
    fire_year = ee.Number(fire_year_value)
    forest = prefire_forest_mask(fire_year)
    proxy_reducer = (
        ee.Reducer.mean()
        .combine(ee.Reducer.stdDev(), "", True)
        .combine(ee.Reducer.count(), "", True)
    )
    structure_reducer = (
        ee.Reducer.mean()
        .combine(ee.Reducer.stdDev(), "", True)
        .combine(ee.Reducer.count(), "", True)
    )
    prefire_reference_geom, prefire_historical = historical_burn_free_annulus(
        geom, fire_year.subtract(1)
    )

    years = ee.List.sequence(fire_year.subtract(PREFIRE_YEARS), MAX_OBS_YEAR)

    def proxy_row(year: ee.Number) -> ee.Feature:
        year = ee.Number(year)
        start = ee.Date.fromYMD(year, 6, 1)
        end = ee.Date.fromYMD(year, 9, 30)
        collection = landsat_collection(start, end, geom.buffer(OUTER_BUFFER_M, 30))
        image = collection.select(["NDVI", "NBR"]).median().updateMask(forest)
        burned = prefix_stats(
            image.reduceRegion(
                reducer=proxy_reducer,
                geometry=geom,
                scale=LANDSAT_SCALE,
                maxPixels=1e10,
                tileScale=4,
            ),
            "forest_burned_",
            ["NDVI", "NBR"],
            ["mean", "stdDev", "count"],
        )
        prefire_reference = ee.Dictionary(
            ee.Algorithms.If(
                year.lt(fire_year),
                prefix_stats(
                    image.reduceRegion(
                        reducer=proxy_reducer,
                        geometry=prefire_reference_geom,
                        scale=LANDSAT_SCALE,
                        maxPixels=1e10,
                        tileScale=4,
                    ),
                    "forest_reference_",
                    ["NDVI", "NBR"],
                    ["mean", "stdDev", "count"],
                ),
                ee.Dictionary(
                    {
                        "forest_reference_NDVI_mean": -9999,
                        "forest_reference_NDVI_stdDev": -9999,
                        "forest_reference_NDVI_count": -9999,
                        "forest_reference_NBR_mean": -9999,
                        "forest_reference_NBR_stdDev": -9999,
                        "forest_reference_NBR_count": -9999,
                    }
                ),
            )
        )
        return ee.Feature(
            None, burned.combine(prefire_reference, overwrite=True)
        ).set(
            {
                "row_kind": "forest_aligned_proxy",
                "Event_ID": event_id,
                "Incid_Name": incid_name,
                "fire_year": fire_year,
                "obs_year": year,
                "relative_year": year.subtract(fire_year),
                "landsat_image_count": collection.size(),
                "prefire_historical_burn_feature_count": prefire_historical.size(),
                "forest_definition": "LCMAP_class4_frequency_gte_0.5_prefire3",
                "landsat_scale_m": LANDSAT_SCALE,
            }
        )

    proxy_rows = ee.FeatureCollection(years.map(proxy_row))

    def structure_row(year: ee.Number) -> ee.Feature:
        year = ee.Number(year)
        image, l2a, l2b = annual_gedi_image(year)
        image = image.updateMask(forest)
        reference_geom, historical = historical_burn_free_annulus(
            geom, year.subtract(1)
        )
        burned = prefix_stats(
            image.reduceRegion(
                reducer=structure_reducer,
                geometry=geom,
                scale=GEDI_SCALE,
                maxPixels=1e10,
                tileScale=4,
            ),
            "forest_burned_",
            ["rh98", "cover", "pai"],
            ["mean", "stdDev", "count"],
        )
        reference = prefix_stats(
            image.reduceRegion(
                reducer=structure_reducer,
                geometry=reference_geom,
                scale=GEDI_SCALE,
                maxPixels=1e10,
                tileScale=4,
            ),
            "forest_reference_",
            ["rh98", "cover", "pai"],
            ["mean", "stdDev", "count"],
        )
        return ee.Feature(None, burned.combine(reference, overwrite=True)).set(
            {
                "row_kind": "forest_aligned_structure",
                "Event_ID": event_id,
                "Incid_Name": incid_name,
                "fire_year": fire_year,
                "obs_year": year,
                "relative_year": year.subtract(fire_year),
                "buffer_label": "buf02_10km",
                "control_inner_buffer_m": INNER_BUFFER_M,
                "control_outer_buffer_m": OUTER_BUFFER_M,
                "historical_burn_feature_count": historical.size(),
                "gedi_l2a_image_count": l2a.filterBounds(geom).size(),
                "gedi_l2b_image_count": l2b.filterBounds(geom).size(),
                "forest_definition": "LCMAP_class4_frequency_gte_0.5_prefire3",
                "gedi_scale_m": GEDI_SCALE,
            }
        )

    structure_years = ee.List.sequence(START_GEDI_YEAR, END_GEDI_YEAR)
    structure_rows = ee.FeatureCollection(structure_years.map(structure_row))
    return proxy_rows.merge(structure_rows)


def load_manifest(path: Path) -> pd.DataFrame:
    if path.exists():
        return pd.read_csv(path)
    return pd.DataFrame()


def submitted_events(manifest: pd.DataFrame) -> set[str]:
    if manifest.empty or "Event_ID" not in manifest:
        return set()
    active = manifest
    if "task_state" in active:
        active = active[
            ~active["task_state"]
            .astype(str)
            .str.upper()
            .isin(["FAILED", "CANCELLED", "CANCELED"])
        ]
    return set(active["Event_ID"].astype(str))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--event-table", required=True)
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--submit-limit", type=int, default=1)
    parser.add_argument("--event-id", action="append", default=None)
    parser.add_argument("--resubmit", action="store_true")
    args = parser.parse_args()

    ee.Initialize(project=PROJECT_ID)
    event_table = Path(args.event_table)
    manifest_path = Path(args.manifest)
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    events = pd.read_csv(event_table)
    if args.event_id:
        wanted = set(args.event_id)
        events = events[events["Event_ID"].astype(str).isin(wanted)].copy()

    existing = load_manifest(manifest_path)
    already = set() if args.resubmit else submitted_events(existing)
    rows: list[dict[str, Any]] = []
    submitted = 0

    for event in events.itertuples(index=False):
        if submitted >= args.submit_limit:
            break
        event_id = str(event.Event_ID)
        if event_id in already:
            continue
        fire = ee.Feature(
            ee.FeatureCollection(MTBS)
            .filter(ee.Filter.eq("Event_ID", event_id))
            .first()
        )
        incid_name = "" if pd.isna(getattr(event, "Incid_Name", "")) else str(
            getattr(event, "Incid_Name", "")
        )
        collection = build_event_collection(
            fire, event_id, incid_name, int(event.fire_year)
        )
        prefix = sanitize(
            f"{DESCRIPTION_PREFIX}_{event_id}_{int(event.fire_year)}_{MAX_OBS_YEAR}"
        )
        task = ee.batch.Export.table.toDrive(
            collection=collection,
            description=prefix,
            folder=DRIVE_FOLDER,
            fileNamePrefix=prefix,
            fileFormat="CSV",
            selectors=SELECTORS,
        )
        task.start()
        status = task.status()
        rows.append(
            {
                "Event_ID": event_id,
                "Incid_Name": incid_name,
                "fire_year": int(event.fire_year),
                "expected_proxy_rows": MAX_OBS_YEAR - int(event.fire_year) + PREFIRE_YEARS + 1,
                "expected_structure_rows": END_GEDI_YEAR - START_GEDI_YEAR + 1,
                "task_id": status.get("id", ""),
                "task_state": status.get("state", ""),
                "description": prefix,
                "drive_folder": DRIVE_FOLDER,
                "file_prefix": prefix,
                "project_id": PROJECT_ID,
            }
        )
        submitted += 1

    new = pd.DataFrame(rows)
    out = pd.concat([existing, new], ignore_index=True) if not existing.empty else new
    if not out.empty:
        out.to_csv(manifest_path, index=False, encoding="utf-8-sig")
    print(
        json.dumps(
            {
                "project_id": PROJECT_ID,
                "submitted": submitted,
                "manifest": str(manifest_path),
                "drive_folder": DRIVE_FOLDER,
                "new_tasks": rows,
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
