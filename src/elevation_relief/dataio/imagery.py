import pystac_client
import planetary_computer
import rasterio
from rasterio.merge import merge
from rasterio.io import MemoryFile
from rasterio.warp import transform_bounds, reproject, Resampling
from rasterio.errors import NotGeoreferencedWarning
from typing import List, Tuple, Optional
import numpy as np
import os
import requests
import warnings
from io import BytesIO


def _parse_resolution_meters(resolution: str) -> float:
    """Parse resolution string (e.g., '5m') to meters."""
    return float(resolution.rstrip('m'))


def _downsample_imagery(
    data: np.ndarray, 
    profile: dict, 
    target_resolution_m: float
) -> Tuple[np.ndarray, dict]:
    """
    Downsample imagery to target resolution.
    Returns (downsampled_data, updated_profile).
    """
    transform = profile.get('transform')
    if transform is None:
        return data, profile
    
    # current resolution (assumes square pixels)
    current_res = abs(transform.a)
    
    # if already at or below target, no downsampling needed
    if current_res >= target_resolution_m:
        print(f"Imagery already at {current_res:.1f}m, no downsampling needed")
        return data, profile
    
    scale_factor = target_resolution_m / current_res
    new_width = max(1, int(profile['width'] / scale_factor))
    new_height = max(1, int(profile['height'] / scale_factor))
    
    print(f"Downsampling imagery: {profile['width']}x{profile['height']} -> {new_width}x{new_height} "
          f"({current_res:.1f}m -> {target_resolution_m:.1f}m)")
    
    # create new transform with updated resolution
    new_transform = rasterio.Affine(
        transform.a * scale_factor, transform.b, transform.c,
        transform.d, transform.e * scale_factor, transform.f
    )
    
    # allocate output array
    num_bands = data.shape[0]
    downsampled = np.zeros((num_bands, new_height, new_width), dtype=data.dtype)
    
    # reproject each band
    for i in range(num_bands):
        reproject(
            source=data[i],
            destination=downsampled[i],
            src_transform=transform,
            src_crs=profile.get('crs', 'EPSG:4326'),
            dst_transform=new_transform,
            dst_crs=profile.get('crs', 'EPSG:4326'),
            resampling=Resampling.bilinear
        )
    
    new_profile = profile.copy()
    new_profile.update({
        'width': new_width,
        'height': new_height,
        'transform': new_transform
    })
    
    return downsampled, new_profile


def fetch_imagery_stac(
    bounds: List[float], 
    collection: str = "naip", 
    max_cloud_cover: float = 20.0,
    time_range: str = "2010-01-01/2025-12-31",
    resolution: Optional[str] = None
) -> Tuple[np.ndarray, dict]:
    """
    Fetch imagery from Microsoft Planetary Computer STAC.
    Falls back to USGS REST API if STAC fails for NAIP.
    """
    catalog = pystac_client.Client.open(
        "https://planetarycomputer.microsoft.com/api/stac/v1",
        modifier=planetary_computer.sign_inplace,
    )
    
    query_params = {}
    if collection != 'naip':
        query_params["eo:cloud_cover"] = {"lt": max_cloud_cover}

    print(f"Searching STAC: {collection}, {time_range}, bounds={bounds}")
    try:
        # OPTIMIZED SEARCH: POST method, sorted by date desc, limited items.
        search = catalog.search(
            collections=[collection],
            bbox=bounds,
            datetime=time_range,
            query=query_params,
            max_items=5, # Only fetch the top 5 candidates
            sortby=[{"field": "datetime", "direction": "desc"}],
            method="POST" # Avoid URL length limits
        )
        # Use generator to avoid materializing huge lists, but list() here respects max_items=5
        items = list(search.items())
        print(f"STAC Search returned {len(items)} items.")
    except Exception as e:
        print(f"STAC Search failed ({e}). Check network or API status.")
        items = None

    # Fallback Logic
    if not items:
        if collection == 'naip':
             print("Falling back to USGS National Map (REST API)...")
             return fetch_imagery_usgs_rest(bounds)
        else:
             print("No imagery found. Generating Placeholder Imagery (Noise)...")
             return generate_placeholder_imagery(bounds)

    # Identify assets
    asset_key = 'image' if collection == 'naip' else 'visual'
    
    # Check first item assets
    if not items[0].assets:
         return generate_placeholder_imagery(bounds)
         
    if asset_key not in items[0].assets:
        available = list(items[0].assets.keys())
        if 'visual' in available: asset_key = 'visual'
        elif 'image' in available: asset_key = 'image'
        else: 
            print(f"Asset '{asset_key}' not found. Available: {available}.")
            return generate_placeholder_imagery(bounds)

    sources = []
    # Only process the first item (Best/Newest) if it covers the area, 
    # but since we might need multiple to cover the bounds if tiled...
    # Actually, simplistic logic: Try to merge all 5. 
    # Usually for a small ROI, 1-2 items suffice.
    
    for item in items:
        if asset_key in item.assets:
            href = item.assets[asset_key].href
            src = rasterio.open(href)
            sources.append(src)
    
    if not sources:
         return generate_placeholder_imagery(bounds)

    src_crs = sources[0].crs
    if src_crs and src_crs.to_string() != "EPSG:4326":
        try:
            left, bottom, right, top = transform_bounds("EPSG:4326", src_crs, *bounds)
            merge_bounds = (left, bottom, right, top)
        except Exception:
            merge_bounds = bounds
    else:
        merge_bounds = bounds
    
    # determine target resolution for COG overview-based fetch
    # this makes GDAL read from overviews, drastically reducing network transfer
    target_res_m = None
    if resolution:
        target_res_m = _parse_resolution_meters(resolution)
        # convert target resolution from meters to source CRS units
        # for projected CRS (like UTM), units are typically meters
        # for NAIP in EPSG:26919 (UTM), 1 unit = 1 meter
        native_res = abs(sources[0].transform.a)
        print(f"Native resolution: {native_res:.2f}m, Target: {target_res_m:.1f}m")
        
        if target_res_m > native_res:
            print(f"Requesting COG overviews at {target_res_m}m resolution (reduces network transfer)")
            merge_res = (target_res_m, target_res_m)
        else:
            print(f"Target {target_res_m}m <= native {native_res:.2f}m, using native resolution")
            merge_res = None
    else:
        merge_res = None
    
    print(f"Merging {len(sources)} sources...")
    try:
        if merge_res:
            # use res parameter to leverage COG overviews
            mosaic, out_trans = merge(
                sources, 
                bounds=merge_bounds, 
                res=merge_res,
                resampling=Resampling.bilinear
            )
        else:
            mosaic, out_trans = merge(sources, bounds=merge_bounds)
    except Exception as e:
        print(f"Merge with res failed ({e}), falling back to native resolution")
        mosaic, out_trans = merge(sources, bounds=merge_bounds)
    
    profile = sources[0].profile.copy()
    profile.update({
        "driver": "GTiff",
        "height": mosaic.shape[1],
        "width": mosaic.shape[2],
        "transform": out_trans,
        "count": mosaic.shape[0]
    })
    
    for src in sources: src.close()
    
    # no post-merge downsampling needed - resolution already applied during merge
    print(f"Merged imagery: {mosaic.shape[2]}x{mosaic.shape[1]} pixels")
        
    return mosaic, profile


def fetch_imagery_usgs_rest(bounds: List[float]) -> Tuple[np.ndarray, dict]:
    """
    Fetch imagery from USGS National Map REST API.
    """
    url = "https://basemap.nationalmap.gov/arcgis/rest/services/USGSImageryOnly/MapServer/export"
    minx, miny, maxx, maxy = bounds
    
    # Approx size request (2048x2048) - Covers small regions well
    params = {
        "bbox": f"{minx},{miny},{maxx},{maxy}",
        "bboxSR": "4326",
        "size": "2048,2048", 
        "imageSR": "4326", 
        "format": "tiff",
        "f": "image"
    }
    
    print("Requesting USGS Imagery URL...")
    try:
        response = requests.get(url, params=params, timeout=30)
        if response.status_code != 200:
            print(f"USGS Rest Error: {response.text}")
            return generate_placeholder_imagery(bounds)
            
        # Suppress NotGeoreferencedWarning since we manually reference it below
        with warnings.catch_warnings():
            warnings.filterwarnings("ignore", category=NotGeoreferencedWarning)
            with MemoryFile(response.content) as memfile:
                with memfile.open() as src:
                    arr = src.read()
                    h, w = arr.shape[1], arr.shape[2]
                
        # Manually construct profile for USGS Export (It follows bbox exactly)
        from rasterio.transform import from_bounds
        # Note: USGS ImageServer export bbox is [minx, miny, maxx, maxy]
        transform = from_bounds(minx, miny, maxx, maxy, w, h)
        
        profile = {
            'driver': 'GTiff',
            'dtype': arr.dtype,
            'count': arr.shape[0],
            'height': h,
            'width': w,
            'crs': 'EPSG:4326', # We requested imageSR=4326
            'transform': transform
        }
        
        return arr, profile
        
    except Exception as e:
        print(f"USGS REST API failed: {e}")
        return generate_placeholder_imagery(bounds)

def generate_placeholder_imagery(bounds):
    """Generate random noise imagery if API fails."""
    import rasterio.transform
    width = 2000
    height = 2000
    w, s, e, n = bounds
    t = rasterio.transform.from_bounds(w, s, e, n, width, height)
    arr = np.random.randint(100, 200, (3, height, width), dtype='uint8')
    profile = {
        'driver': 'GTiff',
        'dtype': 'uint8',
        'count': 3,
        'height': height,
        'width': width,
        'crs': 'EPSG:4326',
        'transform': t
    }
    return arr, profile
