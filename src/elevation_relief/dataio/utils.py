import math
from typing import Tuple, List

def feature_bounds_from_center(lat: float, lon: float, radius_m: float) -> List[float]:
    """
    Calculate bounding box [min_lon, min_lat, max_lon, max_lat] 
    given a center point and radius in meters.
    Approximation for small areas.
    """
    # Earth radius approximation
    R = 6378137.0
    
    # Delta degrees
    dn = radius_m
    de = radius_m
    
    dLat = dn / R
    dLon = de / (R * math.cos(math.pi * lat / 180))
    
    dLat_deg = dLat * 180 / math.pi
    dLon_deg = dLon * 180 / math.pi
    
    return [lon - dLon_deg, lat - dLat_deg, lon + dLon_deg, lat + dLat_deg]
