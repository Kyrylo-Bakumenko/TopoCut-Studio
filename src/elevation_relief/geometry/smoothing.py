import numpy as np
from shapely.geometry import Polygon, MultiPolygon
from shapely.validation import make_valid
from typing import List, Union

def smooth_geometry(geom: Polygon, iterations: int = 3, simplify_tol: float = 0.0, smooth_exterior: bool = True) -> Polygon:
    """
    Smooths a Shapely Polygon (and its holes) using Chaikin's Corner Cutting Algorithm.
    
    This technique is ideal for removing "stair-stepping" from raster-derived contours
    and sharp corners from laser-cutting paths. It prioritizes smooth organic curves
    over exact vertex fidelity.

    Args:
        geom (Polygon): The input Shapely Polygon.
        iterations (int): Number of smoothing passes. Higher = smoother.
                          Usually 3-5 is sufficient.
        simplify_tol (float): If > 0, simplifes the geometry before smoothing using
                             Douglas-Peucker (geom.simplify). Useful to remove 
                             collinear pixels from raster traces before smoothing.
        smooth_exterior (bool): If False, the exterior ring is kept original (useful for base layers).

    Returns:
        Polygon: A valid, smoothed Polygon. 
                 Returns the largest polygon by area if smoothing creates self-intersections
                 resulting in a MultiPolygon.
    """
    if not isinstance(geom, Polygon):
        return geom
        
    if geom.is_empty:
        return geom

    # Optional: Simplify first to remove pixel-grid noise (stair-steps of 1-3 pixels)
    if simplify_tol > 0:
        geom = geom.simplify(simplify_tol, preserve_topology=True) # type: ignore
    
    if not isinstance(geom, Polygon):
        return geom

    def _chaikin_ring(coords):
        if len(coords) < 4:
            return coords
            
        points = np.array(coords[:-1]) # Drop the duplicated last point
        
        for _ in range(iterations):
            p0 = points 
            p1 = np.roll(points, -1, axis=0) # P_{i+1}
            
            Q = 0.75 * p0 + 0.25 * p1
            R = 0.25 * p0 + 0.75 * p1
            
            new_points = np.empty((points.shape[0] * 2, 2))
            new_points[0::2] = Q
            new_points[1::2] = R
            points = new_points
            
        final_coords = np.vstack([points, points[0]])
        return final_coords

    # 1. Smooth Exterior
    if smooth_exterior:
        new_exterior = _chaikin_ring(geom.exterior.coords)
    else:
        new_exterior = geom.exterior.coords
    
    # 2. Smooth Interiors
    new_interiors = []
    for interior in geom.interiors:
        new_interiors.append(_chaikin_ring(interior.coords))
        
    # 3. Reconstruct
    smoothed_poly = Polygon(new_exterior, new_interiors)
    
    # 4. robust validation
    if not smoothed_poly.is_valid:
        smoothed_poly = make_valid(smoothed_poly)
        
    if isinstance(smoothed_poly, MultiPolygon):
        smoothed_poly = max(smoothed_poly.geoms, key=lambda g: g.area)
        
    if not isinstance(smoothed_poly, Polygon):
        if hasattr(smoothed_poly, 'geoms'):
             polys = [g for g in smoothed_poly.geoms if isinstance(g, Polygon)] # type: ignore
             if polys:
                 smoothed_poly = max(polys, key=lambda g: g.area)
             else:
                 return geom 
        else:
             return geom

    return smoothed_poly
