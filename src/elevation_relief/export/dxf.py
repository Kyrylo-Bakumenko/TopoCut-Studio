import ezdxf
from shapely.geometry import Polygon
from typing import List

def save_to_dxf(
    polygons: List[Polygon], 
    output_path: str,
    units: str = "mm"
):
    """
    Save polygons to DXF R2000 (standard compatibility).
    
    Args:
        polygons: List of Shapely polygons.
        output_path: .dxf file path.
        units: 'mm', 'in'. 
    """
    
    doc = ezdxf.new('R2000') # Upgrade to R2000 for LWPOLYLINE and units support
    msp = doc.modelspace()
    
    # Set units (4 = mm, 1 = inches)
    doc.header['$INSUNITS'] = 4 if units == 'mm' else 1
    
    for poly in polygons:
        # Exterior
        if poly.exterior:
            coords = list(poly.exterior.coords)
            msp.add_lwpolyline(coords, close=True)
            
        # Interiors (Holes)
        for interior in poly.interiors:
            coords = list(interior.coords)
            msp.add_lwpolyline(coords, close=True)
            
    doc.saveas(output_path)
    # Optimization (linesort) removed due to dependency issues with vpype in this env.
