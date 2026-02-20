from __future__ import annotations

from typing import TYPE_CHECKING, Any, Dict, List, Tuple

if TYPE_CHECKING:
    from shapely.geometry import Polygon
else:
    Polygon = Any

SQ_IN_TO_SQ_MM = 645.16


def min_part_area_sq_in_to_sq_mm(min_part_area_sq_in: float) -> float:
    return max(0.0, float(min_part_area_sq_in)) * SQ_IN_TO_SQ_MM


def filter_slices_by_physical_area(
    slices: Dict[float, List[Polygon]],
    *,
    scale_factor_mm_per_m: float,
    min_part_area_sq_in: float,
) -> Tuple[List[Tuple[float, List[Polygon]]], Dict[str, Any]]:
    """
    Remove small disconnected islands based on final physical cut area.

    Returns:
      - kept layers as sorted (elevation, polygons) tuples, excluding empty layers
      - stats dictionary for logging/diagnostics
    """
    threshold_sq_mm = min_part_area_sq_in_to_sq_mm(min_part_area_sq_in)
    sorted_layers = sorted(slices.items())
    scale_sq = abs(float(scale_factor_mm_per_m)) ** 2

    kept_layers: List[Tuple[float, List[Polygon]]] = []
    total_polygons = 0
    total_filtered = 0
    skipped_layers = 0
    filtered_by_layer: Dict[str, int] = {}

    for elevation, polygons in sorted_layers:
        total_polygons += len(polygons)
        if threshold_sq_mm <= 0:
            kept_layers.append((elevation, polygons))
            continue

        kept_polygons: List[Polygon] = []
        filtered_count = 0
        for poly in polygons:
            scaled_area_sq_mm = float(poly.area) * scale_sq
            if scaled_area_sq_mm >= threshold_sq_mm:
                kept_polygons.append(poly)
            else:
                filtered_count += 1

        total_filtered += filtered_count
        if filtered_count > 0:
            filtered_by_layer[str(int(elevation))] = filtered_count

        if kept_polygons:
            kept_layers.append((elevation, kept_polygons))
        else:
            skipped_layers += 1

    if threshold_sq_mm > 0 and total_polygons > 0 and not kept_layers:
        raise ValueError(
            f"All parts were below min_part_area_sq_in={min_part_area_sq_in:.3f}. "
            "Lower threshold or increase model size."
        )

    stats = {
        "threshold_sq_mm": threshold_sq_mm,
        "threshold_sq_in": max(0.0, float(min_part_area_sq_in)),
        "total_layers": len(sorted_layers),
        "kept_layers": len(kept_layers),
        "skipped_layers": skipped_layers,
        "total_polygons": total_polygons,
        "filtered_polygons": total_filtered,
        "filtered_by_layer": filtered_by_layer,
    }
    return kept_layers, stats
