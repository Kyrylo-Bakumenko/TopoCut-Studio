import numpy as np
from shapely.geometry import shape, Polygon, MultiPolygon, box
from typing import List, Dict, Any, Tuple, Optional
import rasterio
from rasterio import features
from scipy.ndimage import gaussian_filter
from elevation_relief.geometry.smoothing import smooth_geometry

def slice_terrain(
    dem_array: np.ndarray, 
    transform: rasterio.Affine, 
    interval_m: float,
    min_elev: Optional[float] = None,
    max_elev: Optional[float] = None,
    base_pad: bool = True,
    smoothing_sigma: float = 0.5,
    geometric_smoothing: bool = True,
    smoothing_iterations: int = 3
) -> Dict[float, List[Polygon]]:
    """
    Slice the DEM into vertical layers using Robust Masking method.
    
    1. Smooths DEM (Gaussian)
    2. Thresholds at each level
    3. Vectorizes mask (handles topology/holes automatically)
    4. Simplifies geometry (Douglas-Peucker)
    5. Geometrically smooths (Chaikin) - Optional
    
    Args:
        dem_array: 2D numpy array.
        transform: Affine transform.
        interval_m: Step size.
        smoothing_sigma: Smoothing factor (pixels) to reduce stair-stepping.
        geometric_smoothing: Apply Chaikin smoothing to vectors.
        smoothing_iterations: Intensity of Chaikin smoothing.
        
    Returns:
        Dict mapped elevation -> List of Polygons (with holes properly handled).
    """
    
    # Handle NaN
    dem_safe = np.nan_to_num(dem_array, nan=-9999)
    
    if min_elev is None:
        valid_vals = dem_array[~np.isnan(dem_array)]
        if len(valid_vals) == 0:
            return {}
        min_elev = np.min(valid_vals)
    if max_elev is None:
        max_elev = np.nanmax(dem_array)
        
    # Python 3.10+ TypeAssert for Pylance
    assert min_elev is not None
    assert max_elev is not None
        
    # Gaussian Smooth using 'nearest' mode to handle edges better than zero padding if possible
    # But usually DEMs are continuous.
    if smoothing_sigma > 0:
        processed_dem = gaussian_filter(dem_safe, sigma=smoothing_sigma)
    else:
        processed_dem = dem_safe
    
    # Define Scene Bounds (for boundary preservation)
    # dem_array is [height, width]
    h, w = dem_array.shape
    # Left, Bottom, Right, Top from transform
    # transform * (0,0) = Top Left
    # transform * (w, h) = Bottom Right
    # But usually transform.f is top, transform.f + h*e is bottom (if e is negative)
    
    # Rasterio Box:
    bounds_poly = box(*rasterio.transform.array_bounds(h, w, transform))

    start_level = np.floor(min_elev / interval_m) * interval_m
    # Ensure start level is robust
    if start_level < min_elev - interval_m:
         start_level = np.floor(min_elev / interval_m) * interval_m
         
    levels = np.arange(start_level, max_elev + interval_m, interval_m)
    slices = {}
    
    for level in levels:
        # Create Binary Mask
        # We want everything >= level
        # Also ensure we ignore the nodata areas (-9999)
        mask = ((processed_dem >= level) & (processed_dem > -5000)).astype(np.uint8)
        
        if np.sum(mask) == 0:
            continue
            
        # Rasterio Shapes logic
        # extract shapes where mask == 1. 
        shapes_gen = features.shapes(mask, transform=transform, mask=(mask==1))
        
        layer_polys = []
        for geom, val in shapes_gen:
            if val == 1:
                s = shape(geom)
                if not s.is_valid:
                    s = s.buffer(0)
                
                # Simplify
                # Use a small tolerance relative to resolution.
                # If resolution is 10m/px, tolerance 0.2 means nothing.
                # If resolution is 1m/px, tolerance 0.2 is modest smoothing.
                s_smooth = s.simplify(tolerance=transform.a * 0.5 if transform.a > 0 else 0.5, preserve_topology=True)
                
                # Chaikin Smoothing for Laser Cutting (Organic curves)
                if geometric_smoothing and isinstance(s_smooth, Polygon):
                    # Check if this polygon is the Perimeter (e.g. base layer covering the whole ROI)
                    # We check if the area is close to the bounds area (e.g. > 95%)
                    # Or simpler: if the envelope is almost the same.
                    
                    is_perimeter = False
                    if s_smooth.area > 0.95 * bounds_poly.area:
                         is_perimeter = True
                         
                    s_smooth = smooth_geometry(
                        s_smooth, 
                        iterations=smoothing_iterations, 
                        smooth_exterior=not is_perimeter
                    )
                
                if isinstance(s_smooth, Polygon):
                    layer_polys.append(s_smooth)
        
        if layer_polys:
            slices[level] = layer_polys
        
    return slices
