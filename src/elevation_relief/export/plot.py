import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from pathlib import Path
from shapely.geometry import Polygon, MultiPolygon
from typing import List, Dict, Any, Iterable
from PIL import Image, ImageDraw
from rasterio.transform import Affine
import numpy as np
import re
from shapely.ops import unary_union

def save_polygons_plot(polygons: List[Polygon], filename: str, sheet_width_mm: float, sheet_height_mm: float):
    """
    Save a plot of the polygons to an image file (SVG/PNG).
    """
    # Create figure with correct aspect ratio
    # Matplotlib figsize is in inches.
    w_in = sheet_width_mm / 25.4
    h_in = sheet_height_mm / 25.4
    
    fig, ax = plt.subplots(figsize=(w_in, h_in))
    ax.set_xlim(0, sheet_width_mm)
    ax.set_ylim(0, sheet_height_mm)
    ax.set_aspect('equal')
    ax.axis('off') # Hide axes
    
    # Add rectangle for sheet border
    rect = plt.Rectangle((0, 0), sheet_width_mm, sheet_height_mm, 
                         linewidth=1, edgecolor='black', facecolor='none', linestyle='--')
    ax.add_patch(rect)
    
    for poly in polygons:
        if poly.is_empty:
            continue
        
        # Plot Polygon
        if isinstance(poly, Polygon):
            x, y = poly.exterior.xy
            ax.fill(x, y, alpha=0.5, fc='steelblue', ec='black')
             # Draw holes
            for interior in poly.interiors:
                xi, yi = interior.xy
                ax.plot(xi, yi, color='black', linewidth=0.5)
        elif isinstance(poly, MultiPolygon):
             for p in poly.geoms:
                x, y = p.exterior.xy
                ax.fill(x, y, alpha=0.5, fc='steelblue', ec='black')

    plt.tight_layout(pad=0)
    plt.savefig(filename, dpi=150, bbox_inches='tight', pad_inches=0.1)
    plt.close(fig)


def _iter_polygons(poly: Polygon | MultiPolygon) -> Iterable[Polygon]:
    if isinstance(poly, Polygon):
        return [poly]
    if isinstance(poly, MultiPolygon):
        return list(poly.geoms)
    return []


def save_composite_sheet(
    items: List[Dict[str, Any]],
    textures_dir: Path,
    sheet_width_mm: float,
    sheet_height_mm: float,
    filename: str,
    img_transform: Affine,
    dpi: int = 150,
):
    """
    Save a composite sheet with texture fills and vector outlines.
    Each item must include:
        - polygon: packed Polygon or MultiPolygon (sheet coords)
        - scaled_polygon: original scaled polygon before nesting
        - world_polygon: original polygon in imagery CRS
        - layer_id: corresponding texture id (e.g. layer_000_elev_620)
        - is_rotated, final_x, final_y
    """
    scale = dpi / 25.4
    width_px = max(1, int(sheet_width_mm * scale))
    height_px = max(1, int(sheet_height_mm * scale))

    base = Image.new("RGBA", (width_px, height_px), (255, 255, 255, 255))
    texture_cache: Dict[str, Image.Image] = {}
    inv_transform = ~img_transform

    # Precompute visibility masks: remove areas covered by higher layers
    def _get_elev(layer_id: str) -> float:
        match = re.search(r"elev_(\d+)", layer_id)
        return float(match.group(1)) if match else 0.0

    items_with_elev = []
    for item in items:
        layer_id = item.get("layer_id")
        world_poly = item.get("world_polygon")
        if not layer_id or world_poly is None:
            continue
        items_with_elev.append((item, _get_elev(layer_id)))

    # Sort ascending (lower elevation first), higher elevations occlude lower
    items_with_elev.sort(key=lambda t: t[1])

    visible_world_polys: Dict[int, Polygon | MultiPolygon] = {}
    for idx, (item, elev) in enumerate(items_with_elev):
        world_poly = item.get("world_polygon")
        if world_poly is None:
            continue
        higher_polys = [it.get("world_polygon") for it, e in items_with_elev if e > elev and it.get("world_polygon") is not None]
        if higher_polys:
            try:
                occluder = unary_union(higher_polys)
                visible = world_poly.difference(occluder)
            except Exception:
                visible = world_poly
        else:
            visible = world_poly

        if hasattr(visible, "is_valid") and not visible.is_valid:
            try:
                visible = visible.buffer(0)
            except Exception:
                pass
        visible_world_polys[id(item)] = visible

    for item in items:
        layer_id = item.get("layer_id")
        world_poly = item.get("world_polygon")
        scaled_poly = item.get("scaled_polygon")
        packed_poly = item.get("polygon")
        is_rotated = bool(item.get("is_rotated", False))

        if not layer_id or world_poly is None or scaled_poly is None or packed_poly is None:
            continue

        if layer_id not in texture_cache:
            texture_path = textures_dir / f"{layer_id}.png"
            if not texture_path.exists():
                continue
            try:
                texture_cache[layer_id] = Image.open(texture_path).convert("L")
            except Exception:
                continue

        tex_full = texture_cache[layer_id]
        tex_w, tex_h = tex_full.size

        # Convert world polygon bounds to texture pixel bounds
        visible_poly = visible_world_polys.get(id(item))
        if visible_poly is None or getattr(visible_poly, "is_empty", False):
            continue

        # Use full layer bounds for texture cropping to keep resolution consistent
        minx, miny, maxx, maxy = world_poly.bounds
        col_min, row_max = inv_transform * (minx, miny)
        col_max, row_min = inv_transform * (maxx, maxy)

        left = max(0, int(np.floor(min(col_min, col_max))))
        right = min(tex_w, int(np.ceil(max(col_min, col_max))))
        top = max(0, int(np.floor(min(row_min, row_max))))
        bottom = min(tex_h, int(np.ceil(max(row_min, row_max))))

        if right <= left or bottom <= top:
            continue

        # Crop texture and build polygon mask in local pixel coords
        tex_crop = tex_full.crop((left, top, right, bottom))
        mask = Image.new("L", (right - left, bottom - top), 0)
        draw = ImageDraw.Draw(mask)

        def to_local(coords):
            pts = []
            for x, y in coords:
                col, row = inv_transform * (x, y)
                pts.append((col - left, row - top))
            return pts

        for p in _iter_polygons(visible_poly):
            draw.polygon(to_local(p.exterior.coords), fill=255)
            for interior in p.interiors:
                draw.polygon(to_local(interior.coords), fill=0)

        # Resize texture crop to packed polygon size in sheet coords
        p_minx, p_miny, p_maxx, p_maxy = packed_poly.bounds
        poly_w_mm = max(1e-6, p_maxx - p_minx)
        poly_h_mm = max(1e-6, p_maxy - p_miny)
        target_w_px = max(1, int(poly_w_mm * scale))
        target_h_px = max(1, int(poly_h_mm * scale))

        if is_rotated:
            tex_resized = tex_crop.resize((target_h_px, target_w_px), Image.Resampling.LANCZOS)
            mask_resized = mask.resize((target_h_px, target_w_px), Image.Resampling.NEAREST)
            tex_resized = tex_resized.rotate(90, expand=True)
            mask_resized = mask_resized.rotate(90, expand=True)
        else:
            tex_resized = tex_crop.resize((target_w_px, target_h_px), Image.Resampling.LANCZOS)
            mask_resized = mask.resize((target_w_px, target_h_px), Image.Resampling.NEAREST)

        # Place in final packed position based on packed polygon bounds
        paste_left = int(p_minx * scale)
        paste_top = int((sheet_height_mm - p_maxy) * scale)

        base.paste(tex_resized.convert("RGB"), (paste_left, paste_top), mask_resized)

    # Draw outlines on top (packed polygons)
    outline_draw = ImageDraw.Draw(base)
    for item in items:
        poly = item.get("polygon")
        if poly is None:
            continue
        for p in _iter_polygons(poly):
            exterior = [
                (x * scale, (sheet_height_mm - y) * scale)
                for x, y in p.exterior.coords
            ]
            outline_draw.line(exterior, fill=(0, 0, 0, 255), width=2)
            for interior in p.interiors:
                hole = [
                    (x * scale, (sheet_height_mm - y) * scale)
                    for x, y in interior.coords
                ]
                outline_draw.line(hole, fill=(0, 0, 0, 255), width=1)

    base.save(filename)
