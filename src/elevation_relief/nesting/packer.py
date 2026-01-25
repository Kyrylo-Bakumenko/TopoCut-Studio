import rectpack
from shapely import affinity
from shapely.geometry import Polygon
from typing import List, Dict, Any

def pack_polygons(polygons: List[Polygon], sheet_width: float, sheet_height: float, spacing: float = 0.0) -> List[Dict[str, Any]]:
    """
    Packs a list of Shapely polygons onto sheets of defined size using bounding box packing.
    
    Args:
        polygons: List of source shapely Polygons.
        sheet_width: Width of the material sheet.
        sheet_height: Height of the material sheet.
        spacing: Minimum distance between parts (kerf/margin).
        
    Returns:
        List of dictionaries with keys: 'sheet_idx', 'polygon', 'original_idx'
    """
    
    if not polygons:
        return []

    # rectpack works best with integers, so we scale up float dimensions
    SCALE_FACTOR = 1000 
    
    # Initialize the packer
    # rotation=True allows rotating the bounding box by 90 degrees to fit better
    packer = rectpack.newPacker(rotation=True)
    
    # 1. Add arbitrary number of bins (sheets)
    # We add enough potential sheets to cover worst-case scenarios
    # (e.g., 200 sheets). rectpack will only use what it needs.
    scaled_w = int(sheet_width * SCALE_FACTOR)
    scaled_h = int(sheet_height * SCALE_FACTOR)
    
    for _ in range(200):
        packer.add_bin(scaled_w, scaled_h)

    # 2. Add shapes
    # We pack the bounding box + spacing
    for i, poly in enumerate(polygons):
        minx, miny, maxx, maxy = poly.bounds
        w = (maxx - minx) + spacing
        h = (maxy - miny) + spacing
        
        # We pass the index 'i' as the rectangle ID (rid) to track it
        packer.add_rect(int(w * SCALE_FACTOR), int(h * SCALE_FACTOR), rid=i)

    # 3. Execute Packing
    packer.pack() # type: ignore

    # 4. Extract results and transform Polygons
    packed_results = []
    
    # rectpack returns a list of bins (sheets)
    for sheet_idx, bin_packed in enumerate(packer):
        for rect in bin_packed:
            # rect object attributes: x, y, width, height, rid
            x, y, w, h, rid = rect.x, rect.y, rect.width, rect.height, rect.rid
            
            # Retrieve original polygon
            original_poly = polygons[rid]
            orig_minx, orig_miny, orig_maxx, orig_maxy = original_poly.bounds
            
            # --- Coordinate Transformation ---
            
            # 1. Bring polygon to local (0,0) based on its bottom-left bound
            poly_centered = affinity.translate(original_poly, -orig_minx, -orig_miny)
            
            # 2. Check for Rotation
            # We compare the packed width with the original width
            # (Comparing integers to avoid float precision issues)
            orig_w_int = int(((orig_maxx - orig_minx) + spacing) * SCALE_FACTOR)
            # packed_w_int = int(w)
            
            # Depending on rectpack version/algo, 'w' might be the rotated dimension or bin dimension.
            # Usually rect.width is the dimension *on the bin*.
            # If original width (plus spacing) doesn't equal packed width, it's rotated.
            # Using a tolerance for integer inaccuracies
            is_rotated = abs(int(w) - orig_w_int) > 5
            
            if is_rotated:
                poly_centered = affinity.rotate(poly_centered, 90, origin=(0,0))
                # After rotation, re-align the bottom-left to (0,0) as rotation might shift it
                minx_r, miny_r, _, _ = poly_centered.bounds
                poly_centered = affinity.translate(poly_centered, -minx_r, -miny_r)
            
            # 3. Move to final position on sheet
            # Convert back to float units
            final_x = x / SCALE_FACTOR
            final_y = y / SCALE_FACTOR
            
            # Account for spacing: The packer reserved `size + spacing`. 
            # We place it + half spacing margin.
            final_poly = affinity.translate(poly_centered, final_x + spacing/2, final_y + spacing/2)
            
            packed_results.append({
                "sheet_idx": sheet_idx,
                "polygon": final_poly,
                "original_idx": rid,
                "is_rotated": is_rotated,
                "final_x": final_x,
                "final_y": final_y
            })
            
    return packed_results
