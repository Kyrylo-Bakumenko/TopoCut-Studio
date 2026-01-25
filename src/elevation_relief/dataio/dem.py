import rasterio
from dem_stitcher import stitch_dem
from typing import List, Tuple, Any
import numpy as np

def fetch_dem(bounds: List[float], dem_name: str = 'glo_30') -> Tuple[np.ndarray, dict]:
    """
    Fetch DEM for the given bounds.
    
    Args:
        bounds: [min_lon, min_lat, max_lon, max_lat]
        dem_name: 'glo_30', 'nasadem', '3dep' (if supported by stitcher w/ caveats)
        
    Returns:
        (dem_array, profile)
        dem_array is a numpy array of elevation values.
        profile is the rasterio profile/metadata.
    """
    
    # dem_stitcher handles the geoid correction if dst_ellipsoidal_height=False (default is typically False or explicit)
    # Actually, check dem_stitcher docs or standard usage: 
    # Usually we want orthometric height (Geoid) for "sea level" reference, which is what standard maps use.
    # Satellite DEMs are often Ellipsoidal. stitch_dem can convert.
    
    # ensure bounds are flat list
    
    # Note: 3DEP support in dem_stitcher might require specific keywords or might be better handled directly if dem_stitcher is purely global.
    # checking dem_stitcher common usage: it supports glo_30, nasadem, etc. 
    # For high res US data, we might need a separate path if dem_stitcher doesn't cover 3DEP 1m/10m naturally.
    # But for MVP let's assume glo_30 or nasadem for global, and maybe basic 3DEP if available.
    
    X, profile = stitch_dem(
        bounds, 
        dem_name=dem_name, 
        dst_ellipsoidal_height=False,
        dst_area_or_point='Area'
    )
    
    return X, profile

def save_dem(X: np.ndarray, profile: dict, output_path: str):
    """Save DEM to disk"""
    with rasterio.open(output_path, 'w', **profile) as dst:
        dst.write(X, 1)
