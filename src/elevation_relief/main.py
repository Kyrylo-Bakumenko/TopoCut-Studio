import gc
import json
import re
import time
from pathlib import Path
from typing import Any, Callable, Dict, Optional, Tuple

import click
import numpy as np
from elevation_relief.runtime_env import configure_geospatial_runtime_env

configure_geospatial_runtime_env(force=True)

import rasterio
import yaml
from rasterio import MemoryFile
from rasterio.crs import CRS
from rasterio.transform import Affine
from rasterio.warp import Resampling, calculate_default_transform, reproject
from shapely.affinity import scale, translate
from shapely.geometry import MultiPolygon, Polygon

from elevation_relief.calibration import (
    build_gamma_ladder_definition,
    place_calibration_strip,
    resolve_calibration_config,
)
from elevation_relief.dataio.utils import feature_bounds_from_center
from elevation_relief.export.dxf import save_to_dxf
from elevation_relief.export.plot import (
    save_bed_composite,
    save_cricut_print_png,
    save_composite_bundle_svg,
    save_composite_sheet,
    save_polygons_plot,
)
from elevation_relief.geometry.small_parts import filter_slices_by_physical_area
from elevation_relief.geometry.slicer import slice_terrain
from elevation_relief.imagery.texture import generate_layer_texture
from elevation_relief.nesting.bed_layout import build_bed_layout, resolve_bed_geometry
from elevation_relief.nesting.packer import pack_polygons


def _reproject_raster(
    src_arr: np.ndarray,
    src_prof: Dict[str, Any],
    dst_crs: str,
) -> Tuple[np.ndarray, Affine]:
    """Reproject raster array to destination CRS."""
    dst_crs_obj = CRS.from_string(dst_crs)
    src_crs = src_prof["crs"]
    width = src_prof["width"]
    height = src_prof["height"]
    left = src_prof["transform"].c
    bottom = src_prof["transform"].f + src_prof["transform"].e * height
    right = src_prof["transform"].c + src_prof["transform"].a * width
    top = src_prof["transform"].f

    transform, dst_width, dst_height = calculate_default_transform(
        src_crs, dst_crs_obj, width, height, left, bottom, right, top
    )

    if dst_width is None or dst_height is None:
        raise ValueError("Failed to calculate destination dimensions during reprojection.")

    width, height = int(dst_width), int(dst_height)
    dst_arr = np.zeros((src_arr.shape[0], height, width), dtype=src_arr.dtype)

    for i in range(src_arr.shape[0]):
        reproject(
            source=src_arr[i],
            destination=dst_arr[i],
            src_transform=src_prof["transform"],
            src_crs=src_crs,
            dst_transform=transform,
            dst_crs=dst_crs_obj,
            resampling=Resampling.bilinear,
        )

    return dst_arr, transform


def _parse_layer_id(layer_id: str) -> tuple[int, int]:
    match = re.search(r"layer_(\d+)_elev_(\d+)", layer_id)
    if not match:
        return 0, 0
    return int(match.group(1)), int(match.group(2))


def _polygon_to_rings(poly: Polygon) -> dict:
    def _coords(coords):
        return [[float(x), float(y)] for x, y in coords]

    return {
        "exterior": _coords(poly.exterior.coords),
        "holes": [_coords(ring.coords) for ring in poly.interiors],
    }


def _geometry_to_polygons(geom: Polygon | MultiPolygon) -> list[Polygon]:
    if isinstance(geom, Polygon):
        return [geom]
    if isinstance(geom, MultiPolygon):
        return list(geom.geoms)
    return []


def run_pipeline(
    cfg: Dict[str, Any],
    run_id: Optional[str] = None,
    progress_callback: Optional[Callable[[int, str], None]] = None,
) -> str:
    """Execute the Elevation Relief pipeline."""
    configure_geospatial_runtime_env(force=True)
    from elevation_relief.dataio.dem import fetch_dem
    from elevation_relief.dataio.imagery import fetch_imagery_stac

    timings: Dict[str, float] = {}

    def report(pct: int, msg: str) -> None:
        if progress_callback:
            progress_callback(pct, msg)
        print(f"[{pct}%] {msg}")

    def timed_step(step_name: str, fn):
        start = time.perf_counter()
        result = fn()
        elapsed = time.perf_counter() - start
        timings[step_name] = elapsed
        return result, elapsed

    report(0, f"Starting Experiment: {cfg['experiment']['name']}")
    machine_id = str((cfg.get("profiles") or {}).get("machine_id") or "").strip().lower()
    is_cricut_machine = machine_id == "cricut-maker-3"

    if run_id:
        # The API already bakes run_id into experiment name.
        pass

    res_dir = Path(cfg["experiment"]["output_dir"]) / cfg["experiment"]["name"]
    res_dir.mkdir(parents=True, exist_ok=True)
    (res_dir / "vectors").mkdir(exist_ok=True)
    (res_dir / "textures").mkdir(exist_ok=True)

    report(5, "Defining Region of Interest...")
    lat = cfg["region"]["center_lat"]
    lon = cfg["region"]["center_lon"]
    rad = cfg["region"]["radius_m"]
    bounds = feature_bounds_from_center(lat, lon, rad)
    print(f"ROI Bounds: {bounds}")

    report(10, "Fetching Digital Elevation Model (DEM)...")
    (dem_arr, dem_prof), dem_time = timed_step(
        "fetch_dem",
        lambda: fetch_dem(bounds, dem_name=cfg["data"]["dem_source"]),
    )
    report(12, f"DEM fetched in {dem_time:.2f}s")

    if len(dem_arr.shape) == 2:
        dem_arr = dem_arr[np.newaxis, :, :]

    with rasterio.open(res_dir / "raw_dem.tif", "w", **dem_prof) as dst:
        dst.write(dem_arr)

    report(20, "Fetching Satellite Imagery...")
    imagery_resolution = cfg["data"].get("imagery_resolution", "5m")
    (img_arr, img_prof), img_time = timed_step(
        "fetch_imagery",
        lambda: fetch_imagery_stac(
            bounds,
            collection=cfg["data"]["imagery_source"],
            resolution=imagery_resolution,
        ),
    )
    report(22, f"Imagery fetched in {img_time:.2f}s")

    dst_crs = "EPSG:3857"
    report(30, f"Reprojecting Data to {dst_crs}...")

    (dem_reproj, dem_trans), dem_reproj_time = timed_step(
        "reproject_dem",
        lambda: _reproject_raster(dem_arr, dem_prof, dst_crs),
    )
    report(32, f"DEM reprojection in {dem_reproj_time:.2f}s")

    (img_reproj, img_trans), img_reproj_time = timed_step(
        "reproject_imagery",
        lambda: _reproject_raster(img_arr, img_prof, dst_crs),
    )
    report(34, f"Imagery reprojection in {img_reproj_time:.2f}s")

    img_prof_reproj = img_prof.copy()
    img_prof_reproj.update(
        {
            "crs": dst_crs,
            "transform": img_trans,
            "width": img_reproj.shape[2],
            "height": img_reproj.shape[1],
        }
    )

    texture_normalize_bounds = None
    if cfg["processing"].get("texture_normalize", True):
        cutoff = cfg["processing"].get("texture_normalize_cutoff", 1.0)
        try:
            nodata = img_prof_reproj.get("nodata")
            if img_reproj.shape[0] >= 3:
                r = img_reproj[0].astype(np.float32)
                g = img_reproj[1].astype(np.float32)
                b = img_reproj[2].astype(np.float32)
                gray_full = r * 0.2989 + g * 0.5870 + b * 0.1140
                if nodata is not None:
                    valid_mask = np.any(img_reproj[:3] != nodata, axis=0)
                else:
                    valid_mask = np.ones(gray_full.shape, dtype=bool)
            else:
                gray_full = img_reproj[0].astype(np.float32)
                if nodata is not None:
                    valid_mask = img_reproj[0] != nodata
                else:
                    valid_mask = np.ones(gray_full.shape, dtype=bool)
            valid = gray_full[valid_mask]
            if valid.size > 0:
                low = np.percentile(valid, cutoff)
                high = np.percentile(valid, 100 - cutoff)
                if high > low:
                    texture_normalize_bounds = (float(low), float(high))
        except Exception:
            texture_normalize_bounds = None

    del dem_arr
    del img_arr
    del dem_prof
    del img_prof
    gc.collect()

    interval = cfg["model"]["contour_interval_m"]
    report(40, f"Slicing Terrain at {interval}m intervals...")

    slices, slice_time = timed_step(
        "slice_terrain",
        lambda: slice_terrain(
            dem_reproj[0],
            dem_trans,
            interval_m=interval,
            smoothing_sigma=cfg["processing"].get("smoothing_sigma", 0.0),
            geometric_smoothing=cfg["processing"].get("geometric_smoothing", False),
        ),
    )
    report(50, f"Generated {len(slices)} elevation layers in {slice_time:.2f}s")

    target_width_mm = cfg["model"]["width_inches"] * 25.4
    height_px, width_px = dem_reproj.shape[1], dem_reproj.shape[2]
    real_width_m = width_px * dem_trans.a
    scale_factor = target_width_mm / real_width_m
    print(f"Scale Factor: {scale_factor:.4f} (1m = {scale_factor}mm on table)")

    min_part_area_sq_in = float(cfg["processing"].get("min_part_area_sq_in", 0.015))
    filtered_layers, filter_stats = filter_slices_by_physical_area(
        slices,
        scale_factor_mm_per_m=scale_factor,
        min_part_area_sq_in=min_part_area_sq_in,
    )
    filtered_total = int(filter_stats["filtered_polygons"])
    if filtered_total > 0:
        print(
            "Small-part filter: removed "
            f"{filtered_total}/{filter_stats['total_polygons']} polygons below "
            f"{filter_stats['threshold_sq_in']:.3f} sq in "
            f"({filter_stats['threshold_sq_mm']:.2f} mm^2), "
            f"skipped layers={filter_stats['skipped_layers']}."
        )
        if filter_stats["filtered_by_layer"]:
            print(f"Filtered-by-layer (elev_m -> count): {filter_stats['filtered_by_layer']}")

    center_x = dem_trans.c + (width_px * dem_trans.a) / 2
    center_y = dem_trans.f + (height_px * dem_trans.e) / 2

    del dem_reproj
    gc.collect()

    all_layer_geometries = []
    all_layer_geometries_world = []
    all_layer_ids = []

    total_layers_to_export = len(filtered_layers)
    processed_layers = 0

    with MemoryFile() as memfile:
        with memfile.open(**img_prof_reproj) as dataset:
            dataset.write(img_reproj)

            layer_loop_start = time.perf_counter()
            for generated_layer_idx, (elev, polys) in enumerate(filtered_layers):
                layer_id = f"layer_{generated_layer_idx:03d}_elev_{int(elev)}"
                pct = 50 + int((processed_layers / max(1, total_layers_to_export)) * 30)
                report(pct, f"Processing {layer_id}...")

                texture_img = generate_layer_texture(
                    dataset,
                    polys,
                    normalize_contrast=cfg["processing"].get("texture_normalize", True),
                    normalize_cutoff=cfg["processing"].get("texture_normalize_cutoff", 1.0),
                    normalize_bounds=texture_normalize_bounds,
                    gamma=cfg["processing"].get("texture_gamma", 1.0),
                )
                texture_img.save(res_dir / "textures" / f"{layer_id}.png")

                scaled_polys = []
                for poly in polys:
                    scaled_polys.append(
                        scale(poly, xfact=scale_factor, yfact=scale_factor, origin=(center_x, center_y))
                    )

                for world_poly, scaled_poly in zip(polys, scaled_polys):
                    all_layer_geometries.append(scaled_poly)
                    all_layer_geometries_world.append(world_poly)
                    all_layer_ids.append(layer_id)

                save_to_dxf(scaled_polys, str(res_dir / "vectors" / f"{layer_id}.dxf"))
                processed_layers += 1

            layer_loop_time = time.perf_counter() - layer_loop_start
            timings["per_layer_processing_total"] = layer_loop_time
            if total_layers_to_export > 0:
                timings["per_layer_avg"] = layer_loop_time / total_layers_to_export

    nesting_cfg = cfg["processing"].get("nesting", {})
    if nesting_cfg.get("enabled", False):
        report(85, "Optimizing Nesting Layout...")

        geometry = resolve_bed_geometry(nesting_cfg)
        sheet_w = geometry["sheet_width_mm"]
        sheet_h = geometry["sheet_height_mm"]
        bed_w = geometry["bed_width_mm"]
        bed_h = geometry["bed_height_mm"]
        sheet_margin = geometry["sheet_margin_mm"]
        part_gap_mm = geometry["sheet_gap_mm"]

        kerf_mm = cfg["processing"].get("kerf_width_mm", 0.15)
        margin = kerf_mm + part_gap_mm

        packed_sheets, nest_time = timed_step(
            "nesting",
            lambda: pack_polygons(
                all_layer_geometries,
                max(1.0, sheet_w - 2 * sheet_margin),
                max(1.0, sheet_h - 2 * sheet_margin),
                spacing=margin,
            ),
        )
        report(88, f"Nesting completed in {nest_time:.2f}s")

        sheets: Dict[int, list[Dict[str, Any]]] = {}
        for item in packed_sheets:
            s_idx = item["sheet_idx"]
            if s_idx not in sheets:
                sheets[s_idx] = []

            idx = item["original_idx"]
            layer_id = all_layer_ids[idx]
            packed_poly = translate(item["polygon"], xoff=sheet_margin, yoff=sheet_margin)
            sheets[s_idx].append(
                {
                    "polygon": packed_poly,
                    "layer_id": layer_id,
                    "world_polygon": all_layer_geometries_world[idx],
                    "scaled_polygon": all_layer_geometries[idx],
                    "is_rotated": item.get("is_rotated", False),
                    "final_x": item.get("final_x", 0.0) + sheet_margin,
                    "final_y": item.get("final_y", 0.0) + sheet_margin,
                }
            )

        (res_dir / "nested").mkdir(exist_ok=True)

        calibration_cfg = resolve_calibration_config(cfg)
        calibration_definition = None
        calibration_manifest = None
        calibration_placements_by_sheet: Dict[int, Dict[str, Any]] = {}

        if calibration_cfg.get("enabled", True):
            calibration_definition = build_gamma_ladder_definition(calibration_cfg)
            placement = place_calibration_strip(
                sheets=sheets,
                sheet_width_mm=sheet_w,
                sheet_height_mm=sheet_h,
                sheet_margin_mm=sheet_margin,
                sheet_gap_mm=part_gap_mm,
                strip_width_mm=calibration_definition["strip"]["width_mm"],
                strip_height_mm=calibration_definition["strip"]["height_mm"],
                padding_mm=calibration_definition["strip"]["padding_mm"],
            )

            placement_record = {
                "sheet_id": f"sheet_{placement['sheet_index']:02d}",
                "sheet_index": int(placement["sheet_index"]),
                "x_mm": placement["x_mm"],
                "y_mm": placement["y_mm"],
                "w_mm": placement["w_mm"],
                "h_mm": placement["h_mm"],
                "gamma_values": calibration_definition["gamma_values"],
            }
            calibration_placements_by_sheet[placement_record["sheet_index"]] = placement_record

            if placement_record["sheet_index"] not in sheets:
                sheets[placement_record["sheet_index"]] = []

            calibration_manifest = {
                "pattern": calibration_definition["pattern"],
                "legend": calibration_definition["legend"],
                "strip": calibration_definition["strip"],
                "gamma_values": calibration_definition["gamma_values"],
                "reference_grayscale": calibration_definition["reference_grayscale"],
                "cells": calibration_definition["cells"],
                "placements": [placement_record],
                "profiles": cfg.get("profiles", {}),
            }

        report(90, "Exporting Nested Sheets...")
        sheet_exports: Dict[int, Dict[str, Any]] = {}
        for s_idx in sorted(sheets.keys()):
            polys_with_layer = sheets[s_idx]
            sheet_id = f"sheet_{s_idx:02d}"
            sheet_polys = []
            for item in polys_with_layer:
                sheet_polys.extend(_geometry_to_polygons(item["polygon"]))

            out_dxf = res_dir / "nested" / f"{sheet_id}.dxf"
            save_to_dxf(sheet_polys, str(out_dxf))

            out_svg = res_dir / "nested" / f"{sheet_id}.svg"
            save_polygons_plot(sheet_polys, str(out_svg), sheet_w, sheet_h)

            out_composite = res_dir / "nested" / f"{sheet_id}_composite.png"
            label_layouts = save_composite_sheet(
                polys_with_layer,
                res_dir / "textures",
                sheet_w,
                sheet_h,
                str(out_composite),
                img_trans,
                calibration_definition=calibration_definition,
                calibration_placement=calibration_placements_by_sheet.get(s_idx),
            )

            cricut_png: Optional[Path] = None
            if is_cricut_machine and polys_with_layer:
                cricut_png = res_dir / "nested" / f"{sheet_id}_cricut_print.png"
                save_composite_sheet(
                    polys_with_layer,
                    res_dir / "textures",
                    sheet_w,
                    sheet_h,
                    str(cricut_png),
                    img_trans,
                    dpi=300,
                    calibration_definition=None,
                    calibration_placement=None,
                )
                save_cricut_print_png(
                    polys_with_layer,
                    cricut_png,
                    sheet_w,
                    sheet_h,
                    cricut_png,
                    source_dpi=300,
                )

            out_bundle_svg = res_dir / "nested" / f"{sheet_id}_bundle.svg"
            save_composite_bundle_svg(
                polys_with_layer,
                sheet_w,
                sheet_h,
                out_composite,
                str(out_bundle_svg),
            )

            layer_counts: Dict[str, int] = {}
            cutouts = []
            for cutout_idx, item in enumerate(polys_with_layer):
                layer_id = item.get("layer_id", "")
                layer_index, elevation_m = _parse_layer_id(layer_id)
                layer_counts[layer_id] = layer_counts.get(layer_id, 0) + 1
                cutout_id = f"{layer_id}_{layer_counts[layer_id]:02d}"
                geom = item.get("polygon")
                if geom is None:
                    continue

                polygons = [_polygon_to_rings(poly) for poly in _geometry_to_polygons(geom)]
                label_layout = label_layouts.get(cutout_idx, {})
                default_label_point = geom.representative_point()
                label_point = label_layout.get(
                    "label_point",
                    [float(default_label_point.x), float(default_label_point.y)],
                )
                rotation_deg = 90 if item.get("is_rotated") else 0

                cutout_payload: Dict[str, Any] = {
                    "id": cutout_id,
                    "layer_id": layer_id,
                    "layer_index": layer_index,
                    "elevation_m": elevation_m,
                    "label": f"L{layer_index + 1:02d}",
                    "polygons": polygons,
                    "label_point": [float(label_point[0]), float(label_point[1])],
                    "is_rotated": bool(item.get("is_rotated")),
                    "rotation_deg": rotation_deg,
                    "sheet_index": s_idx,
                    "cutout_index": cutout_idx,
                }
                label_mode = label_layout.get("label_mode")
                if label_mode:
                    cutout_payload["label_mode"] = str(label_mode)
                leader_start = label_layout.get("leader_start_point")
                if leader_start:
                    cutout_payload["leader_start_point"] = [
                        float(leader_start[0]),
                        float(leader_start[1]),
                    ]
                leader_end = label_layout.get("leader_end_point")
                if leader_end:
                    cutout_payload["leader_end_point"] = [
                        float(leader_end[0]),
                        float(leader_end[1]),
                    ]
                if "label_font_cap_height_mm" in label_layout:
                    cutout_payload["label_font_cap_height_mm"] = float(
                        label_layout["label_font_cap_height_mm"]
                    )

                cutouts.append(cutout_payload)

            manifest = {
                "sheet_id": sheet_id,
                "sheet_index": s_idx,
                "sheet_width_mm": sheet_w,
                "sheet_height_mm": sheet_h,
                "cutouts": cutouts,
            }
            manifest_path = res_dir / "nested" / f"{sheet_id}.json"
            with open(manifest_path, "w", encoding="utf-8") as handle:
                json.dump(manifest, handle)

            sheet_exports[s_idx] = {
                "sheet_id": sheet_id,
                "sheet_index": s_idx,
                "dxf_file": out_dxf.name,
                "svg_file": out_svg.name,
                "composite_file": out_composite.name,
                "cricut_print_file": cricut_png.name if cricut_png else None,
                "manifest_file": manifest_path.name,
                "composite_path": str(out_composite),
            }
            print(f"Exported Nested Sheet {s_idx}: {out_dxf} & {out_svg}")

        if calibration_manifest is not None:
            calibration_path = res_dir / "nested" / "calibration_manifest.json"
            with open(calibration_path, "w", encoding="utf-8") as handle:
                json.dump(calibration_manifest, handle)

        bed_layout = build_bed_layout(
            sheets.keys(),
            bed_width_mm=bed_w,
            bed_height_mm=bed_h,
            sheet_width_mm=sheet_w,
            sheet_height_mm=sheet_h,
            sheet_margin_mm=sheet_margin,
            sheet_gap_mm=part_gap_mm,
        )

        bed_records = []
        for bed in bed_layout["beds"]:
            bed_idx = bed["bed_index"]
            bed_id = bed["bed_id"]
            bed_polys = []
            bed_sheets_for_composite = []
            bed_sheet_entries = []

            for placement in bed["sheets"]:
                sheet_idx = int(placement["sheet_index"])
                sheet_items = sheets.get(sheet_idx, [])
                for item in sheet_items:
                    geom = item.get("polygon")
                    if geom is None:
                        continue
                    shifted = translate(
                        geom,
                        xoff=float(placement["x_mm"]),
                        yoff=float(placement["y_mm"]),
                    )
                    bed_polys.extend(_geometry_to_polygons(shifted))

                export_info = sheet_exports.get(sheet_idx, {})
                bed_sheets_for_composite.append(
                    {
                        **placement,
                        "composite_path": export_info.get("composite_path"),
                    }
                )
                bed_sheet_entries.append(
                    {
                        **placement,
                        "sheet_dxf": export_info.get("dxf_file"),
                        "sheet_svg": export_info.get("svg_file"),
                        "sheet_composite": export_info.get("composite_file"),
                        "sheet_manifest": export_info.get("manifest_file"),
                    }
                )

            out_bed_dxf = res_dir / "nested" / f"{bed_id}.dxf"
            out_bed_svg = res_dir / "nested" / f"{bed_id}.svg"
            out_bed_composite = res_dir / "nested" / f"{bed_id}_composite.png"
            save_to_dxf(bed_polys, str(out_bed_dxf))
            save_polygons_plot(bed_polys, str(out_bed_svg), bed_w, bed_h)
            save_bed_composite(
                bed_sheets_for_composite,
                bed_w,
                bed_h,
                str(out_bed_composite),
            )

            bed_json = {
                "bed_id": bed_id,
                "bed_index": bed_idx,
                "bed_width_mm": bed_w,
                "bed_height_mm": bed_h,
                "profiles": cfg.get("profiles", {}),
                "sheets": bed_sheet_entries,
            }
            with open(res_dir / "nested" / f"{bed_id}.json", "w", encoding="utf-8") as handle:
                json.dump(bed_json, handle)

            bed_records.append(
                {
                    "bed_id": bed_id,
                    "bed_index": bed_idx,
                    "dxf_file": out_bed_dxf.name,
                    "svg_file": out_bed_svg.name,
                    "composite_file": out_bed_composite.name,
                    "json_file": f"{bed_id}.json",
                    "sheets": bed_sheet_entries,
                }
            )

        bed_manifest = {
            "profiles": cfg.get("profiles", {}),
            "bed_width_mm": bed_w,
            "bed_height_mm": bed_h,
            "sheet_width_mm": sheet_w,
            "sheet_height_mm": sheet_h,
            "sheet_margin_mm": sheet_margin,
            "sheet_gap_mm": part_gap_mm,
            "cols": bed_layout["cols"],
            "rows": bed_layout["rows"],
            "capacity": bed_layout["capacity"],
            "beds": bed_records,
        }
        with open(res_dir / "nested" / "bed_manifest.json", "w", encoding="utf-8") as handle:
            json.dump(bed_manifest, handle)

    if timings:
        summary = ", ".join([f"{name}={elapsed:.2f}s" for name, elapsed in timings.items()])
        report(99, f"Timing summary: {summary}")

    report(100, "Processing Complete!")
    return str(res_dir.resolve())


@click.command()
@click.option("--config", default="config/default_config.yaml", help="Path to config file")
def main(config):
    """Run the Elevation Relief pipeline."""
    with open(config, "r", encoding="utf-8") as handle:
        cfg = yaml.safe_load(handle)

    run_pipeline(cfg)


if __name__ == "__main__":
    main()  # type: ignore
