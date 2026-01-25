import os
import yaml
import click
import numpy as np
import time
from pathlib import Path
from typing import Dict, Any, Optional, Tuple
from shapely.geometry import Polygon
from shapely.affinity import scale, translate
from rasterio.warp import calculate_default_transform, reproject, Resampling
from rasterio.crs import CRS
from rasterio.transform import Affine
from rasterio import MemoryFile
import rasterio

from elevation_relief.dataio.dem import fetch_dem
from elevation_relief.dataio.imagery import fetch_imagery_stac
from elevation_relief.dataio.utils import feature_bounds_from_center
from elevation_relief.geometry.slicer import slice_terrain
from elevation_relief.geometry.smoothing import smooth_geometry
from elevation_relief.nesting.packer import pack_polygons
from elevation_relief.imagery.texture import generate_layer_texture
from elevation_relief.export.dxf import save_to_dxf
from elevation_relief.export.plot import save_polygons_plot, save_composite_sheet

def _reproject_raster(src_arr: np.ndarray, src_prof: Dict[str, Any], dst_crs: str) -> Tuple[np.ndarray, Affine]:
    """
    Reproject raster array to destination CRS.
    """
    dst_crs_obj = CRS.from_string(dst_crs)
    src_crs = src_prof['crs']
    width = src_prof['width']
    height = src_prof['height']
    left = src_prof['transform'].c
    bottom = src_prof['transform'].f + src_prof['transform'].e * height
    right = src_prof['transform'].c + src_prof['transform'].a * width
    top = src_prof['transform'].f
    
    transform, dst_width, dst_height = calculate_default_transform(
        src_crs, dst_crs_obj, width, height, left, bottom, right, top
    )

    if dst_width is None or dst_height is None:
        raise ValueError("Failed to calculate destination dimensions during reprojection.")
    
    # Ensure dimensions are ints for numpy
    width, height = int(dst_width), int(dst_height)
    
    # kwargs = src_prof.copy() # Unused
    
    dst_arr = np.zeros((src_arr.shape[0], height, width), dtype=src_arr.dtype)
    
    for i in range(src_arr.shape[0]):
        reproject(
            source=src_arr[i],
            destination=dst_arr[i],
            src_transform=src_prof['transform'],
            src_crs=src_crs,
            dst_transform=transform,
            dst_crs=dst_crs_obj,
            resampling=Resampling.bilinear
        )
        
    return dst_arr, transform

def run_pipeline(cfg: Dict[str, Any], run_id: Optional[str] = None) -> str:
    """
    Execute the Elevation Relief Pipeline with the given configuration dictionary.
    Parameters:
        cfg (dict): The configuration dictionary.
        run_id (str): Optional identifier for the run.
    Returns:
        str: Absolute path to the results directory.
    """
    print(f"Starting Experiment: {cfg['experiment']['name']}")
    
    # Setup Paths
    if run_id:
        # If web triggered, maybe subfolder by ID?
        # For now, stick to config name unless overridden
        pass

    res_dir = Path(cfg['experiment']['output_dir']) / cfg['experiment']['name']
    
    # If run_id provided, maybe ensure uniqueness? 
    # The existing logic uses cfg['experiment']['name'].
    # We'll stick to that for now to keep it simple.
    
    res_dir.mkdir(parents=True, exist_ok=True)
    (res_dir / 'vectors').mkdir(exist_ok=True)
    (res_dir / 'textures').mkdir(exist_ok=True)
    
    # 1. Define ROI
    lat = cfg['region']['center_lat']
    lon = cfg['region']['center_lon']
    rad = cfg['region']['radius_m']
    bounds = feature_bounds_from_center(lat, lon, rad)
    print(f"ROI Bounds: {bounds}")
    
    # 2. Fetch Data
from typing import Dict, Any, Optional, Tuple, Callable

# ... imports ...

def run_pipeline(cfg: Dict[str, Any], run_id: Optional[str] = None, progress_callback: Optional[Callable[[int, str], None]] = None) -> str:
    """
    Execute the Elevation Relief Pipeline with the given configuration dictionary.
    Parameters:
        cfg (dict): The configuration dictionary.
        run_id (str): Optional identifier for the run.
        progress_callback (func): Optional function(percent, message) to report progress.
    Returns:
        str: Absolute path to the results directory.
    """
    timings: Dict[str, float] = {}

    def report(p, msg):
        if progress_callback:
            progress_callback(p, msg)
        print(f"[{p}%] {msg}")

    def timed_step(step_name: str, fn):
        start = time.perf_counter()
        result = fn()
        elapsed = time.perf_counter() - start
        timings[step_name] = elapsed
        return result, elapsed

    report(0, f"Starting Experiment: {cfg['experiment']['name']}")
    
    # Setup Paths
    if run_id:
        # If web triggered, maybe subfolder by ID?
        # For now, stick to config name unless overridden
        pass

    res_dir = Path(cfg['experiment']['output_dir']) / cfg['experiment']['name']
    
    # If run_id provided, maybe ensure uniqueness? 
    # The existing logic uses cfg['experiment']['name'].
    # We'll stick to that for now to keep it simple.
    
    res_dir.mkdir(parents=True, exist_ok=True)
    (res_dir / 'vectors').mkdir(exist_ok=True)
    (res_dir / 'textures').mkdir(exist_ok=True)
    
    # 1. Define ROI
    report(5, "Defining Region of Interest...")
    lat = cfg['region']['center_lat']
    lon = cfg['region']['center_lon']
    rad = cfg['region']['radius_m']
    bounds = feature_bounds_from_center(lat, lon, rad)
    print(f"ROI Bounds: {bounds}")
    
    # 2. Fetch Data
    report(10, "Fetching Digital Elevation Model (DEM)...")
    (dem_arr, dem_prof), dem_time = timed_step(
        "fetch_dem",
        lambda: fetch_dem(bounds, dem_name=cfg['data']['dem_source'])
    )
    report(12, f"DEM fetched in {dem_time:.2f}s")
    
    # Ensure DEM is 3D (Bands, Height, Width)
    if len(dem_arr.shape) == 2:
        dem_arr = dem_arr[np.newaxis, :, :]

    # Save raw DEM for debugging
    with rasterio.open(res_dir / 'raw_dem.tif', 'w', **dem_prof) as dst:
        dst.write(dem_arr) # Write all bands
        
    report(20, "Fetching Satellite Imagery...")
    # Handle temporal range or just default
    imagery_resolution = cfg['data'].get('imagery_resolution', '5m')
    (img_arr, img_prof), img_time = timed_step(
        "fetch_imagery",
        lambda: fetch_imagery_stac(
            bounds, 
            collection=cfg['data']['imagery_source'],
            resolution=imagery_resolution
        )
    )
    report(22, f"Imagery fetched in {img_time:.2f}s")
    
    # Step 2.5: Reproject to local UTM / EPSG:3857
    dst_crs = 'EPSG:3857' # Web Mercator (Meters-ish)
    report(30, f"Reprojecting Data to {dst_crs}...")
    
    # Reproject DEM
    (dem_reproj, dem_trans), dem_reproj_time = timed_step(
        "reproject_dem",
        lambda: _reproject_raster(dem_arr, dem_prof, dst_crs)
    )
    report(32, f"DEM reprojection in {dem_reproj_time:.2f}s")
    
    # Reproject Imagery
    (img_reproj, img_trans), img_reproj_time = timed_step(
        "reproject_imagery",
        lambda: _reproject_raster(img_arr, img_prof, dst_crs)
    )
    report(34, f"Imagery reprojection in {img_reproj_time:.2f}s")
    img_prof_reproj = img_prof.copy()
    img_prof_reproj.update({
        'crs': dst_crs,
        'transform': img_trans,
        'width': img_reproj.shape[2],
        'height': img_reproj.shape[1]
    })
    
    # 3. Slice Terrain
    interval = cfg['model']['contour_interval_m']
    report(40, f"Slicing Terrain at {interval}m intervals...")
    
    slices, slice_time = timed_step(
        "slice_terrain",
        lambda: slice_terrain(
            dem_reproj[0], # band 1
            dem_trans, 
            interval_m=interval,
            smoothing_sigma=cfg['processing'].get('smoothing_sigma', 0.5),
            geometric_smoothing=cfg['processing'].get('geometric_smoothing', True)
        )
    )
    
    report(50, f"Generated {len(slices)} elevation layers in {slice_time:.2f}s")
    
    # 4. Process & Export
    # Calculate Scale Factor
    target_width_mm = cfg['model']['width_inches'] * 25.4
    
    # Real Width (m)
    height_px, width_px = dem_reproj.shape[1], dem_reproj.shape[2]
    real_width_m = width_px * dem_trans.a # pixel width
    
    scale_factor = target_width_mm / real_width_m
    print(f"Scale Factor: {scale_factor:.4f} (1m = {scale_factor}mm on table)")
    
    # Center params for Scaling
    center_x = dem_trans.c + (width_px * dem_trans.a) / 2
    center_y = dem_trans.f + (height_px * dem_trans.e) / 2
    
    # Store all polygons for Nesting
    all_layer_geometries = []
    all_layer_geometries_world = []
    all_layer_ids = []

    total_layers = len(slices)
    current_layer = 0

    with MemoryFile() as memfile:
        with memfile.open(**img_prof_reproj) as dataset:
            dataset.write(img_reproj)
            
            layer_loop_start = time.perf_counter()
            for i, (elev, polys) in enumerate(sorted(slices.items())):
                layer_id = f"layer_{i:03d}_elev_{int(elev)}"
                # Calculate progress between 50 and 80 based on layers
                pct = 50 + int((current_layer / max(1, total_layers)) * 30)
                report(pct, f"Processing {layer_id}...")
                
                # A. Texture (Masking using Original Coordinates in Meters)
                texture_img = generate_layer_texture(dataset, polys)
                
                # Save Texture
                tex_path = res_dir / 'textures' / f"{layer_id}.png"
                texture_img.save(tex_path)
                
                # B. Geometry (Scale to model size)
                scaled_polys = []
                for p in polys:
                    # Scale (origin=center)
                    sp = scale(p, xfact=scale_factor, yfact=scale_factor, origin=(center_x, center_y))
                    scaled_polys.append(sp)
                
                # Collect for nesting
                for p, sp in zip(polys, scaled_polys):
                    # Keep layer_id aligned with polygon index for nesting metadata
                    all_layer_geometries.append(sp)
                    all_layer_geometries_world.append(p)
                    all_layer_ids.append(layer_id)

                # Save Vector (Individual)
                vec_path = res_dir / 'vectors' / f"{layer_id}.dxf"
                save_to_dxf(scaled_polys, str(vec_path))
                
                current_layer += 1

            layer_loop_time = time.perf_counter() - layer_loop_start
            timings["per_layer_processing_total"] = layer_loop_time
            if total_layers > 0:
                timings["per_layer_avg"] = layer_loop_time / total_layers

    # 5. Nesting Logic
    nesting_cfg = cfg['processing'].get('nesting', {})
    if nesting_cfg.get('enabled', False):
        report(85, "Optimizing Nesting Layout...")
        sheet_w = nesting_cfg.get('sheet_width_in', 24.0) * 25.4 # inches to mm
        sheet_h = nesting_cfg.get('sheet_height_in', 12.0) * 25.4
        sheet_margin = nesting_cfg.get('sheet_margin_in', 0.125) * 25.4
        
        # Pack
        # Spacing: kerf + user-defined gap
        kerf_mm = cfg['processing'].get('kerf_width_mm', 0.15)
        part_gap_mm = nesting_cfg.get('sheet_gap_in', 0.0625) * 25.4
        margin = kerf_mm + part_gap_mm
        
        packed_sheets, nest_time = timed_step(
            "nesting",
            lambda: pack_polygons(
                all_layer_geometries,
                max(1.0, sheet_w - 2 * sheet_margin),
                max(1.0, sheet_h - 2 * sheet_margin),
                spacing=margin
            )
        )
        report(88, f"Nesting completed in {nest_time:.2f}s")
        
        # Group by sheet
        sheets = {}
        for item in packed_sheets:
            s_idx = item['sheet_idx']
            if s_idx not in sheets:
                sheets[s_idx] = []
            idx = item['original_idx']
            layer_id = all_layer_ids[idx]
            packed_poly = translate(item['polygon'], xoff=sheet_margin, yoff=sheet_margin)
            sheets[s_idx].append({
                "polygon": packed_poly,
                "layer_id": layer_id,
                "world_polygon": all_layer_geometries_world[idx],
                "scaled_polygon": all_layer_geometries[idx],
                "is_rotated": item.get("is_rotated", False),
                "final_x": item.get("final_x", 0.0) + sheet_margin,
                "final_y": item.get("final_y", 0.0) + sheet_margin
            })
            
        # Export Sheets
        (res_dir / 'nested').mkdir(exist_ok=True)
        report(90, "Exporting Nested Sheets...")
        for s_idx, polys_with_layer in sheets.items():
            sheet_polys = [p["polygon"] for p in polys_with_layer]
            # Export DXF
            out_name = res_dir / 'nested' / f"sheet_{s_idx:02d}.dxf"
            save_to_dxf(sheet_polys, str(out_name))
            
            # Export SVG Preview
            out_img = res_dir / 'nested' / f"sheet_{s_idx:02d}.svg"
            save_polygons_plot(sheet_polys, str(out_img), sheet_w, sheet_h)

            # Export Composite Preview (Texture + Vector)
            out_composite = res_dir / 'nested' / f"sheet_{s_idx:02d}_composite.png"
            save_composite_sheet(
                polys_with_layer,
                res_dir / 'textures',
                sheet_w,
                sheet_h,
                str(out_composite),
                img_trans
            )
            
            print(f"Exported Nested Sheet {s_idx}: {out_name} & {out_img}")
                
    # Final timing summary
    if timings:
        summary = ", ".join([f"{k}={v:.2f}s" for k, v in timings.items()])
        report(99, f"Timing summary: {summary}")

    report(100, "Processing Complete!")
    return str(res_dir.resolve())

@click.command()
@click.option('--config', default='config/default_config.yaml', help='Path to config file')
def main(config):
    """
    Run the Elevation Relief Pipeline.
    """
    # Load Config
    with open(config, 'r') as f:
        cfg = yaml.safe_load(f)
    
    run_pipeline(cfg)

if __name__ == '__main__':
    main() # type: ignore
