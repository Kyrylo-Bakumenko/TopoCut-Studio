import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from pathlib import Path
from shapely.geometry import Polygon, MultiPolygon, Point
from typing import List, Dict, Any, Iterable, Optional
from PIL import Image, ImageDraw, ImageFont
from rasterio.transform import Affine
import numpy as np
import re
import base64
from shapely.ops import unary_union, nearest_points

LABEL_FONT_CAP_HEIGHT_MM = 1.8
LABEL_PADDING_MM = 0.6
LABEL_OUTSIDE_OFFSET_MM = 1.2
LABEL_ARROW_HEAD_MM = 1.2
LABEL_ARROW_END_GAP_MM = 0.7
LABEL_TEXT_COLOR = (0, 0, 0, 255)
LABEL_TEXT_STROKE_COLOR = (255, 255, 255, 255)

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
    ax.margins(0)
    ax.set_position([0, 0, 1, 1])
    fig.subplots_adjust(left=0, right=1, top=1, bottom=0)
    
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

    plt.savefig(filename, dpi=150, bbox_inches=None, pad_inches=0)
    plt.close(fig)


def _iter_polygons(poly: Polygon | MultiPolygon) -> Iterable[Polygon]:
    if isinstance(poly, Polygon):
        return [poly]
    if isinstance(poly, MultiPolygon):
        return list(poly.geoms)
    return []


def _parse_layer_index(layer_id: str) -> int:
    match = re.search(r"layer_(\d+)", layer_id)
    if not match:
        return 0
    return int(match.group(1))


def _load_label_font(target_cap_height_px: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    size_guess = max(8, int(round(target_cap_height_px * 1.55)))
    try:
        return ImageFont.truetype("DejaVuSans.ttf", size_guess)
    except Exception:
        return ImageFont.load_default()


def _measure_text(
    draw: ImageDraw.ImageDraw,
    text: str,
    font: ImageFont.FreeTypeFont | ImageFont.ImageFont,
    stroke_width: int,
) -> tuple[int, int]:
    try:
        left, top, right, bottom = draw.textbbox(
            (0, 0),
            text,
            font=font,
            stroke_width=stroke_width,
        )
        return max(1, right - left), max(1, bottom - top)
    except Exception:
        width, height = draw.textsize(text, font=font)
        return max(1, width), max(1, height)


def _build_part_mask_local(
    packed_poly: Polygon | MultiPolygon,
    p_minx: float,
    p_maxy: float,
    scale: float,
    width_px: int,
    height_px: int,
) -> Image.Image:
    mask = Image.new("L", (width_px, height_px), 0)
    draw = ImageDraw.Draw(mask)

    for poly in _iter_polygons(packed_poly):
        exterior = [
            ((x - p_minx) * scale, (p_maxy - y) * scale)
            for x, y in poly.exterior.coords
        ]
        draw.polygon(exterior, fill=255)
        for interior in poly.interiors:
            hole = [
                ((x - p_minx) * scale, (p_maxy - y) * scale)
                for x, y in interior.coords
            ]
            draw.polygon(hole, fill=0)
    return mask


def _find_inside_slot(
    white_zone_mask: np.ndarray,
    text_w_px: int,
    text_h_px: int,
    padding_px: int,
) -> Optional[tuple[int, int]]:
    required_w = text_w_px + 2 * padding_px
    required_h = text_h_px + 2 * padding_px
    h, w = white_zone_mask.shape[:2]

    if required_w <= 0 or required_h <= 0 or required_w > w or required_h > h:
        return None

    binary = (white_zone_mask > 0).astype(np.uint8)
    if np.count_nonzero(binary) == 0:
        return None

    integral = np.pad(binary, ((1, 0), (1, 0)), mode="constant").cumsum(0).cumsum(1)
    target_sum = required_w * required_h

    coords = np.argwhere(binary > 0)
    center_yx = coords.mean(axis=0) if len(coords) > 0 else np.array([h / 2, w / 2], dtype=np.float32)

    best_slot: Optional[tuple[int, int]] = None
    best_dist_sq: Optional[float] = None

    for y in range(0, h - required_h + 1):
        y2 = y + required_h
        row_sums = (
            integral[y2, required_w:]
            - integral[y, required_w:]
            - integral[y2, :-required_w]
            + integral[y, :-required_w]
        )
        valid_x = np.where(row_sums == target_sum)[0]
        for x in valid_x:
            cx = x + required_w / 2.0
            cy = y + required_h / 2.0
            dx = cx - center_yx[1]
            dy = cy - center_yx[0]
            dist_sq = dx * dx + dy * dy
            if best_dist_sq is None or dist_sq < best_dist_sq:
                best_dist_sq = dist_sq
                best_slot = (int(x + padding_px), int(y + padding_px))

    return best_slot


def _rect_overlaps_mask(
    left_px: int,
    top_px: int,
    width_px: int,
    height_px: int,
    mask: np.ndarray,
) -> bool:
    right_px = left_px + width_px
    bottom_px = top_px + height_px
    if left_px < 0 or top_px < 0 or right_px > mask.shape[1] or bottom_px > mask.shape[0]:
        return True
    region = mask[top_px:bottom_px, left_px:right_px]
    return bool(np.any(region > 0))


def _find_outside_slot(
    sheet_width_px: int,
    sheet_height_px: int,
    part_left_px: int,
    part_top_px: int,
    part_w_px: int,
    part_h_px: int,
    text_w_px: int,
    text_h_px: int,
    offset_px: int,
    blocked_parts_mask: np.ndarray,
    blocked_labels_mask: np.ndarray,
) -> tuple[int, int, str]:
    center_x = part_left_px + part_w_px / 2.0
    center_y = part_top_px + part_h_px / 2.0

    def _is_slot_free(candidate_left: int, candidate_top: int) -> bool:
        if candidate_left < 0 or candidate_top < 0:
            return False
        if candidate_left + text_w_px > sheet_width_px or candidate_top + text_h_px > sheet_height_px:
            return False
        if _rect_overlaps_mask(candidate_left, candidate_top, text_w_px, text_h_px, blocked_parts_mask):
            return False
        if _rect_overlaps_mask(candidate_left, candidate_top, text_w_px, text_h_px, blocked_labels_mask):
            return False
        return True

    search_step = max(3, int(round(min(text_w_px, text_h_px) * 0.45)))
    max_ring = 28
    for ring in range(0, max_ring):
        gap = offset_px + ring * search_step
        mid_x = int(round(center_x - text_w_px / 2.0))
        mid_y = int(round(center_y - text_h_px / 2.0))
        left_x = int(round(part_left_px - gap - text_w_px))
        right_x = int(round(part_left_px + part_w_px + gap))
        top_y = int(round(part_top_px - gap - text_h_px))
        bottom_y = int(round(part_top_px + part_h_px + gap))

        quarter_shift = max(1, int(round(part_w_px * 0.25)))
        vertical_shift = max(1, int(round(part_h_px * 0.25)))

        candidates = [
            (mid_x, top_y),  # top
            (mid_x, bottom_y),  # bottom
            (left_x, mid_y),  # left
            (right_x, mid_y),  # right
            (left_x, top_y),  # top-left
            (right_x, top_y),  # top-right
            (left_x, bottom_y),  # bottom-left
            (right_x, bottom_y),  # bottom-right
            (mid_x - quarter_shift, top_y),
            (mid_x + quarter_shift, top_y),
            (mid_x - quarter_shift, bottom_y),
            (mid_x + quarter_shift, bottom_y),
            (left_x, mid_y - vertical_shift),
            (left_x, mid_y + vertical_shift),
            (right_x, mid_y - vertical_shift),
            (right_x, mid_y + vertical_shift),
        ]

        for text_left, text_top in candidates:
            if _is_slot_free(text_left, text_top):
                return text_left, text_top, "outside_leader"

    # Global nearest-free fallback search.
    sample_step = max(4, int(round(min(text_w_px, text_h_px) * 0.55)))
    best_slot: Optional[tuple[int, int]] = None
    best_dist_sq: Optional[float] = None
    for y in range(0, max(1, sheet_height_px - text_h_px + 1), sample_step):
        for x in range(0, max(1, sheet_width_px - text_w_px + 1), sample_step):
            if not _is_slot_free(x, y):
                continue
            cx = x + text_w_px / 2.0
            cy = y + text_h_px / 2.0
            dx = cx - center_x
            dy = cy - center_y
            dist_sq = dx * dx + dy * dy
            if best_dist_sq is None or dist_sq < best_dist_sq:
                best_dist_sq = dist_sq
                best_slot = (x, y)

    if best_slot is not None:
        return best_slot[0], best_slot[1], "fallback"

    # Absolute fallback when sheet is very crowded.
    fallback_left = int(round(min(max(0, part_left_px + part_w_px + offset_px), sheet_width_px - text_w_px)))
    fallback_top = int(round(min(max(0, part_top_px - text_h_px - offset_px), sheet_height_px - text_h_px)))
    return fallback_left, fallback_top, "fallback"


def _px_to_sheet_mm(
    x_px: float,
    y_px: float,
    scale: float,
    sheet_height_mm: float,
) -> tuple[float, float]:
    return float(x_px / scale), float(sheet_height_mm - (y_px / scale))


def _sheet_mm_to_px(
    x_mm: float,
    y_mm: float,
    scale: float,
    sheet_height_mm: float,
) -> tuple[float, float]:
    return float(x_mm * scale), float((sheet_height_mm - y_mm) * scale)


def _label_edge_point(
    label_center_mm: tuple[float, float],
    target_mm: tuple[float, float],
    label_w_mm: float,
    label_h_mm: float,
) -> tuple[float, float]:
    cx, cy = label_center_mm
    tx, ty = target_mm
    dx = tx - cx
    dy = ty - cy
    if abs(dx) < 1e-9 and abs(dy) < 1e-9:
        return label_center_mm

    half_w = max(1e-6, label_w_mm / 2.0)
    half_h = max(1e-6, label_h_mm / 2.0)
    t_x = half_w / abs(dx) if abs(dx) > 1e-9 else float("inf")
    t_y = half_h / abs(dy) if abs(dy) > 1e-9 else float("inf")
    t = min(t_x, t_y)
    return cx + dx * t, cy + dy * t


def _draw_leader_arrow(
    draw: ImageDraw.ImageDraw,
    start_px: tuple[float, float],
    end_px: tuple[float, float],
    arrow_head_px: float,
) -> None:
    sx, sy = start_px
    ex, ey = end_px
    dx = ex - sx
    dy = ey - sy
    norm = float(np.hypot(dx, dy))
    if norm < 1e-6:
        return

    ux = dx / norm
    uy = dy / norm
    px = -uy
    py = ux
    head = max(2.0, min(arrow_head_px, norm * 0.5))
    spread = head * 0.45

    left = (ex - ux * head + px * spread, ey - uy * head + py * spread)
    right = (ex - ux * head - px * spread, ey - uy * head - py * spread)

    draw.line([start_px, end_px], fill=LABEL_TEXT_COLOR, width=1)
    draw.polygon([end_px, left, right], fill=LABEL_TEXT_COLOR)


def _apply_endpoint_gap_mm(
    start_mm: tuple[float, float],
    end_mm: tuple[float, float],
    gap_mm: float,
) -> tuple[float, float]:
    sx, sy = start_mm
    ex, ey = end_mm
    dx = ex - sx
    dy = ey - sy
    dist = float(np.hypot(dx, dy))
    if dist <= 1e-9:
        return end_mm

    max_gap_allowed = max(0.0, dist - 0.15)
    if max_gap_allowed <= 1e-9:
        return end_mm
    target_gap = min(float(gap_mm), max_gap_allowed)
    min_visual_gap = min(0.35, max_gap_allowed)
    gap = max(target_gap, min_visual_gap)
    ux = dx / dist
    uy = dy / dist
    return ex - ux * gap, ey - uy * gap


def _draw_part_labels(
    canvas: Image.Image,
    label_items: List[Dict[str, Any]],
    sheet_width_mm: float,
    sheet_height_mm: float,
    dpi: int,
) -> Dict[int, Dict[str, Any]]:
    scale = dpi / 25.4
    font_cap_height_px = max(6, int(round(LABEL_FONT_CAP_HEIGHT_MM * scale)))
    font = _load_label_font(font_cap_height_px)
    draw = ImageDraw.Draw(canvas)
    stroke_width = max(1, int(round(font_cap_height_px * 0.2)))
    padding_px = max(1, int(round(LABEL_PADDING_MM * scale)))
    outside_offset_px = max(2, int(round(LABEL_OUTSIDE_OFFSET_MM * scale)))
    arrow_head_px = max(2.0, LABEL_ARROW_HEAD_MM * scale)

    placements: Dict[int, Dict[str, Any]] = {}
    blocked_parts_mask = np.zeros((canvas.size[1], canvas.size[0]), dtype=np.uint8)
    blocked_labels_mask = np.zeros_like(blocked_parts_mask)

    for entry in label_items:
        part_mask = np.array(entry["part_mask"], dtype=np.uint8)
        left = int(entry["left_px"])
        top = int(entry["top_px"])
        right = min(blocked_parts_mask.shape[1], left + part_mask.shape[1])
        bottom = min(blocked_parts_mask.shape[0], top + part_mask.shape[0])
        if right <= left or bottom <= top:
            continue
        blocked_slice = blocked_parts_mask[top:bottom, left:right]
        part_slice = part_mask[: bottom - top, : right - left]
        np.maximum(blocked_slice, part_slice, out=blocked_slice)

    for entry in label_items:
        item_index = int(entry["item_index"])
        part_mask = np.array(entry["part_mask"], dtype=np.uint8)
        visible_mask = np.array(entry["visible_mask"], dtype=np.uint8)
        white_zone_mask = np.where((part_mask > 0) & (visible_mask == 0), 255, 0).astype(np.uint8)

        label_text = str(entry["label"])
        text_w_px, text_h_px = _measure_text(draw, label_text, font, stroke_width)

        inside_slot = _find_inside_slot(white_zone_mask, text_w_px, text_h_px, padding_px)
        if inside_slot is not None:
            local_left_px, local_top_px = inside_slot
            text_left_px = int(entry["left_px"] + local_left_px)
            text_top_px = int(entry["top_px"] + local_top_px)
            if _rect_overlaps_mask(
                text_left_px,
                text_top_px,
                text_w_px,
                text_h_px,
                blocked_labels_mask,
            ):
                inside_slot = None
            else:
                label_mode = "inside_white"
                leader_start_mm = None
                leader_end_mm = None

        if inside_slot is None:
            text_left_px, text_top_px, label_mode = _find_outside_slot(
                sheet_width_px=canvas.size[0],
                sheet_height_px=canvas.size[1],
                part_left_px=int(entry["left_px"]),
                part_top_px=int(entry["top_px"]),
                part_w_px=int(entry["width_px"]),
                part_h_px=int(entry["height_px"]),
                text_w_px=text_w_px,
                text_h_px=text_h_px,
                offset_px=outside_offset_px,
                blocked_parts_mask=blocked_parts_mask,
                blocked_labels_mask=blocked_labels_mask,
            )

            center_x_px = text_left_px + text_w_px / 2.0
            center_y_px = text_top_px + text_h_px / 2.0
            center_mm = _px_to_sheet_mm(center_x_px, center_y_px, scale, sheet_height_mm)

            try:
                _, nearest_boundary_pt = nearest_points(
                    Point(center_mm[0], center_mm[1]),
                    entry["packed_poly"].boundary,
                )
                end_mm = (float(nearest_boundary_pt.x), float(nearest_boundary_pt.y))
            except Exception:
                fallback_pt = entry["packed_poly"].representative_point()
                end_mm = (float(fallback_pt.x), float(fallback_pt.y))

            text_w_mm = text_w_px / scale
            text_h_mm = text_h_px / scale
            edge_start_mm = _label_edge_point(center_mm, end_mm, text_w_mm, text_h_mm)
            edge_dist = float(np.hypot(end_mm[0] - edge_start_mm[0], end_mm[1] - edge_start_mm[1]))
            if edge_dist < (LABEL_ARROW_END_GAP_MM + 0.35):
                start_mm = center_mm
            else:
                start_mm = edge_start_mm
            leader_start_mm = (float(start_mm[0]), float(start_mm[1]))
            end_with_gap = _apply_endpoint_gap_mm(
                leader_start_mm,
                (float(end_mm[0]), float(end_mm[1])),
                LABEL_ARROW_END_GAP_MM,
            )
            leader_end_mm = (float(end_with_gap[0]), float(end_with_gap[1]))

            start_px = _sheet_mm_to_px(
                leader_start_mm[0],
                leader_start_mm[1],
                scale,
                sheet_height_mm,
            )
            end_px = _sheet_mm_to_px(
                leader_end_mm[0],
                leader_end_mm[1],
                scale,
                sheet_height_mm,
            )
            _draw_leader_arrow(draw, start_px, end_px, arrow_head_px)
        else:
            label_mode = "inside_white"
            leader_start_mm = None
            leader_end_mm = None

        try:
            draw.text(
                (text_left_px, text_top_px),
                label_text,
                fill=LABEL_TEXT_COLOR,
                font=font,
                stroke_width=stroke_width,
                stroke_fill=LABEL_TEXT_STROKE_COLOR,
            )
        except TypeError:
            draw.text((text_left_px, text_top_px), label_text, fill=LABEL_TEXT_COLOR, font=font)

        label_center_x_px = text_left_px + text_w_px / 2.0
        label_center_y_px = text_top_px + text_h_px / 2.0
        label_center_mm = _px_to_sheet_mm(
            label_center_x_px,
            label_center_y_px,
            scale,
            sheet_height_mm,
        )

        placement: Dict[str, Any] = {
            "label_mode": label_mode,
            "label_point": [float(label_center_mm[0]), float(label_center_mm[1])],
            "label_font_cap_height_mm": float(LABEL_FONT_CAP_HEIGHT_MM),
        }
        if leader_start_mm is not None and leader_end_mm is not None:
            placement["leader_start_point"] = [leader_start_mm[0], leader_start_mm[1]]
            placement["leader_end_point"] = [leader_end_mm[0], leader_end_mm[1]]
        placements[item_index] = placement

        blocked_labels_mask[
            text_top_px : text_top_px + text_h_px,
            text_left_px : text_left_px + text_w_px,
        ] = 255

    return placements


def save_composite_sheet(
    items: List[Dict[str, Any]],
    textures_dir: Path,
    sheet_width_mm: float,
    sheet_height_mm: float,
    filename: str,
    img_transform: Affine,
    dpi: int = 150,
    calibration_definition: Optional[Dict[str, Any]] = None,
    calibration_placement: Optional[Dict[str, Any]] = None,
) -> Dict[int, Dict[str, Any]]:
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
    label_items: List[Dict[str, Any]] = []

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

    for item_index, item in enumerate(items):
        layer_id = item.get("layer_id")
        world_poly = item.get("world_polygon")
        scaled_poly = item.get("scaled_polygon")
        packed_poly = item.get("polygon")
        is_rotated = bool(item.get("is_rotated", False))

        if packed_poly is None:
            continue

        p_minx, p_miny, p_maxx, p_maxy = packed_poly.bounds
        poly_w_mm = max(1e-6, p_maxx - p_minx)
        poly_h_mm = max(1e-6, p_maxy - p_miny)
        target_w_px = max(1, int(poly_w_mm * scale))
        target_h_px = max(1, int(poly_h_mm * scale))
        paste_left = int(p_minx * scale)
        paste_top = int((sheet_height_mm - p_maxy) * scale)

        part_mask_local = _build_part_mask_local(
            packed_poly,
            p_minx,
            p_maxy,
            scale,
            target_w_px,
            target_h_px,
        )
        visible_mask_local = Image.new("L", (target_w_px, target_h_px), 0)

        if not layer_id or world_poly is None or scaled_poly is None:
            label_items.append(
                {
                    "item_index": item_index,
                    "label": f"L{_parse_layer_index(str(layer_id or '')) + 1:02d}",
                    "left_px": paste_left,
                    "top_px": paste_top,
                    "width_px": target_w_px,
                    "height_px": target_h_px,
                    "part_mask": part_mask_local,
                    "visible_mask": visible_mask_local,
                    "packed_poly": packed_poly,
                }
            )
            continue

        if layer_id not in texture_cache:
            texture_path = textures_dir / f"{layer_id}.png"
            if not texture_path.exists():
                label_items.append(
                    {
                        "item_index": item_index,
                        "label": f"L{_parse_layer_index(layer_id) + 1:02d}",
                        "left_px": paste_left,
                        "top_px": paste_top,
                        "width_px": target_w_px,
                        "height_px": target_h_px,
                        "part_mask": part_mask_local,
                        "visible_mask": visible_mask_local,
                        "packed_poly": packed_poly,
                    }
                )
                continue
            try:
                texture_cache[layer_id] = Image.open(texture_path).convert("L")
            except Exception:
                label_items.append(
                    {
                        "item_index": item_index,
                        "label": f"L{_parse_layer_index(layer_id) + 1:02d}",
                        "left_px": paste_left,
                        "top_px": paste_top,
                        "width_px": target_w_px,
                        "height_px": target_h_px,
                        "part_mask": part_mask_local,
                        "visible_mask": visible_mask_local,
                        "packed_poly": packed_poly,
                    }
                )
                continue

        tex_full = texture_cache[layer_id]
        tex_w, tex_h = tex_full.size

        # Convert world polygon bounds to texture pixel bounds
        visible_poly = visible_world_polys.get(id(item))
        if visible_poly is not None and not getattr(visible_poly, "is_empty", False):
            # Use full layer bounds for texture cropping to keep resolution consistent
            minx, miny, maxx, maxy = world_poly.bounds
            col_min, row_max = inv_transform * (minx, miny)
            col_max, row_min = inv_transform * (maxx, maxy)

            left = max(0, int(np.floor(min(col_min, col_max))))
            right = min(tex_w, int(np.ceil(max(col_min, col_max))))
            top = max(0, int(np.floor(min(row_min, row_max))))
            bottom = min(tex_h, int(np.ceil(max(row_min, row_max))))

            if right > left and bottom > top:
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

                if is_rotated:
                    tex_resized = tex_crop.resize((target_h_px, target_w_px), Image.Resampling.LANCZOS)
                    mask_resized = mask.resize((target_h_px, target_w_px), Image.Resampling.NEAREST)
                    tex_resized = tex_resized.rotate(90, expand=True)
                    mask_resized = mask_resized.rotate(90, expand=True)
                else:
                    tex_resized = tex_crop.resize((target_w_px, target_h_px), Image.Resampling.LANCZOS)
                    mask_resized = mask.resize((target_w_px, target_h_px), Image.Resampling.NEAREST)

                if tex_resized.size != (target_w_px, target_h_px):
                    tex_resized = tex_resized.resize((target_w_px, target_h_px), Image.Resampling.LANCZOS)
                if mask_resized.size != (target_w_px, target_h_px):
                    mask_resized = mask_resized.resize((target_w_px, target_h_px), Image.Resampling.NEAREST)

                base.paste(tex_resized.convert("RGB"), (paste_left, paste_top), mask_resized)
                visible_mask_local = mask_resized

        label_items.append(
            {
                "item_index": item_index,
                "label": f"L{_parse_layer_index(layer_id) + 1:02d}",
                "left_px": paste_left,
                "top_px": paste_top,
                "width_px": target_w_px,
                "height_px": target_h_px,
                "part_mask": part_mask_local,
                "visible_mask": visible_mask_local,
                "packed_poly": packed_poly,
            }
        )

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

    label_placements = _draw_part_labels(
        base,
        label_items=label_items,
        sheet_width_mm=sheet_width_mm,
        sheet_height_mm=sheet_height_mm,
        dpi=dpi,
    )

    if calibration_definition and calibration_placement:
        _draw_calibration_overlay(
            base,
            sheet_width_mm=sheet_width_mm,
            sheet_height_mm=sheet_height_mm,
            dpi=dpi,
            definition=calibration_definition,
            placement=calibration_placement,
        )

    base.save(filename)
    return label_placements


def save_cricut_print_png(
    items: List[Dict[str, Any]],
    source_png: str | Path,
    sheet_width_mm: float,
    sheet_height_mm: float,
    output_png: str | Path,
    *,
    source_dpi: int = 300,
    max_width_in: float = 8.76,
    max_height_in: float = 6.76,
    crop_padding_mm: float = 1.6,
):
    """
    Create a Cricut-friendly transparent PNG:
    - transparent background outside cut geometries
    - tightly cropped to content with small padding
    - scaled to Cricut print-then-cut bounds
    """
    src_path = Path(source_png)
    out_path = Path(output_png)
    if not src_path.exists():
        return

    image = Image.open(src_path).convert("RGBA")
    scale = source_dpi / 25.4
    alpha = Image.new("L", image.size, 0)
    draw = ImageDraw.Draw(alpha)

    for item in items:
        poly = item.get("polygon")
        if poly is None:
            continue
        for polygon in _iter_polygons(poly):
            exterior = [
                (x * scale, (sheet_height_mm - y) * scale)
                for x, y in polygon.exterior.coords
            ]
            draw.polygon(exterior, fill=255)
            for interior in polygon.interiors:
                hole = [
                    (x * scale, (sheet_height_mm - y) * scale)
                    for x, y in interior.coords
                ]
                draw.polygon(hole, fill=0)

    bbox = alpha.getbbox()
    if bbox is None:
        image.save(out_path, dpi=(source_dpi, source_dpi))
        return

    pad = max(0, int(round(crop_padding_mm * scale)))
    left = max(0, bbox[0] - pad)
    top = max(0, bbox[1] - pad)
    right = min(image.width, bbox[2] + pad)
    bottom = min(image.height, bbox[3] + pad)

    image.putalpha(alpha)
    image = image.crop((left, top, right, bottom))

    max_w_px = max(1, int(round(max_width_in * source_dpi)))
    max_h_px = max(1, int(round(max_height_in * source_dpi)))
    fit_ratio = min(max_w_px / image.width, max_h_px / image.height, 1.0)
    if fit_ratio < 1.0:
        new_w = max(1, int(round(image.width * fit_ratio)))
        new_h = max(1, int(round(image.height * fit_ratio)))
        image = image.resize((new_w, new_h), Image.Resampling.LANCZOS)

    image.save(out_path, dpi=(source_dpi, source_dpi))


def _mm_to_px(mm: float, scale: float) -> int:
    return int(round(mm * scale))


def _draw_calibration_overlay(
    canvas: Image.Image,
    sheet_width_mm: float,
    sheet_height_mm: float,
    dpi: int,
    definition: Dict[str, Any],
    placement: Dict[str, Any],
) -> None:
    scale = dpi / 25.4
    draw = ImageDraw.Draw(canvas)
    font = ImageFont.load_default()

    x0_mm = float(placement["x_mm"])
    y0_mm = float(placement["y_mm"])
    strip_w_mm = float(placement["w_mm"])
    strip_h_mm = float(placement["h_mm"])

    strip_left_px = _mm_to_px(x0_mm, scale)
    strip_top_px = _mm_to_px(sheet_height_mm - (y0_mm + strip_h_mm), scale)
    strip_right_px = _mm_to_px(x0_mm + strip_w_mm, scale)
    strip_bottom_px = _mm_to_px(sheet_height_mm - y0_mm, scale)

    draw.rectangle(
        [(strip_left_px, strip_top_px), (strip_right_px, strip_bottom_px)],
        fill=(255, 255, 255, 255),
        outline=(0, 0, 0, 255),
        width=1,
    )

    for cell in definition.get("cells", []):
        cx_mm = x0_mm + float(cell["x_mm"])
        cy_mm = y0_mm + float(cell["y_mm"])
        cw_mm = float(cell["width_mm"])
        ch_mm = float(cell["height_mm"])
        gamma = float(cell["gamma"])

        left = _mm_to_px(cx_mm, scale)
        top = _mm_to_px(sheet_height_mm - (cy_mm + ch_mm), scale)
        right = max(left + 1, _mm_to_px(cx_mm + cw_mm, scale))
        bottom = max(top + 1, _mm_to_px(sheet_height_mm - cy_mm, scale))

        grad_w = max(2, right - left)
        grad_h = max(2, bottom - top)
        gradient = np.linspace(0, 1, grad_w, dtype=np.float32)
        values = np.clip(np.power(gradient, gamma) * 255.0, 0, 255).astype(np.uint8)
        strip = np.repeat(values[np.newaxis, :], grad_h, axis=0)
        strip_rgb = np.stack([strip, strip, strip], axis=2)
        strip_img = Image.fromarray(strip_rgb, mode="RGB")
        canvas.paste(strip_img, (left, top))
        draw.rectangle([(left, top), (right, bottom)], outline=(0, 0, 0, 255), width=1)

        label_y = bottom + 2
        draw.text((left + 1, label_y), str(cell["label"]), fill=(0, 0, 0, 255), font=font)

    legend = definition.get("legend")
    if legend:
        draw.text((strip_left_px + 2, max(0, strip_top_px - 12)), str(legend), fill=(0, 0, 0, 255), font=font)


def save_composite_bundle_svg(
    items: List[Dict[str, Any]],
    sheet_width_mm: float,
    sheet_height_mm: float,
    composite_png: Path,
    filename: str,
    stroke_width_mm: float = 0.2,
):
    """
    Save an SVG that embeds the composite PNG and overlays vector outlines.
    """
    if not composite_png.exists():
        return

    png_data = base64.b64encode(composite_png.read_bytes()).decode("ascii")
    svg_lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        f'<svg xmlns="http://www.w3.org/2000/svg" '
        f'width="{sheet_width_mm}mm" height="{sheet_height_mm}mm" '
        f'viewBox="0 0 {sheet_width_mm} {sheet_height_mm}">',
        (
            f'<image href="data:image/png;base64,{png_data}" '
            f'x="0" y="0" width="{sheet_width_mm}" height="{sheet_height_mm}" '
            f'preserveAspectRatio="none" />'
        ),
        f'<g fill="none" stroke="#000000" stroke-width="{stroke_width_mm}">',
    ]

    def _path_for_coords(coords):
        pts = [f"{x:.3f},{(sheet_height_mm - y):.3f}" for x, y in coords]
        if not pts:
            return ""
        return "M " + " L ".join(pts) + " Z"

    for item in items:
        poly = item.get("polygon")
        if poly is None:
            continue
        for p in _iter_polygons(poly):
            path = _path_for_coords(p.exterior.coords)
            if path:
                svg_lines.append(f'<path d="{path}" />')
            for interior in p.interiors:
                hole_path = _path_for_coords(interior.coords)
                if hole_path:
                    svg_lines.append(f'<path d="{hole_path}" />')

    svg_lines.append("</g></svg>")
    Path(filename).write_text("\n".join(svg_lines), encoding="utf-8")


def save_bed_composite(
    bed_sheets: List[Dict[str, Any]],
    bed_width_mm: float,
    bed_height_mm: float,
    filename: str,
    dpi: int = 150,
):
    """Render a bed-level composite by placing sheet composites on the machine bed."""
    scale = dpi / 25.4
    width_px = max(1, int(round(bed_width_mm * scale)))
    height_px = max(1, int(round(bed_height_mm * scale)))
    canvas = Image.new("RGBA", (width_px, height_px), (255, 255, 255, 255))
    draw = ImageDraw.Draw(canvas)

    for sheet in bed_sheets:
        composite_path = sheet.get("composite_path")
        if not composite_path:
            continue
        src = Path(composite_path)
        if not src.exists():
            continue

        x_mm = float(sheet.get("x_mm", 0.0))
        y_mm = float(sheet.get("y_mm", 0.0))
        w_mm = float(sheet.get("w_mm", 0.0))
        h_mm = float(sheet.get("h_mm", 0.0))

        target_w = max(1, int(round(w_mm * scale)))
        target_h = max(1, int(round(h_mm * scale)))
        left = int(round(x_mm * scale))
        top = int(round((bed_height_mm - (y_mm + h_mm)) * scale))

        try:
            img = Image.open(src).convert("RGBA")
        except Exception:
            continue
        if img.size != (target_w, target_h):
            img = img.resize((target_w, target_h), Image.Resampling.LANCZOS)

        canvas.paste(img, (left, top))
        draw.rectangle(
            [(left, top), (left + target_w, top + target_h)],
            outline=(0, 0, 0, 180),
            width=1,
        )

    canvas.save(filename)
