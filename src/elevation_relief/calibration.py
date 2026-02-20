from __future__ import annotations

from typing import Any, Dict, Iterable, List, Tuple

import numpy as np
from shapely.geometry import box
from shapely.ops import unary_union

DEFAULT_CALIBRATION_CONFIG: Dict[str, Any] = {
    "enabled": True,
    "mode": "auto_pack",
    "pattern": "gamma_ladder",
    "gamma_min": 0.70,
    "gamma_max": 1.60,
    "gamma_steps": 10,
    "strip_width_mm": 140.0,
    "strip_height_mm": 28.0,
    "padding_mm": 2.0,
}


def resolve_calibration_config(cfg: Dict[str, Any]) -> Dict[str, Any]:
    raw = (cfg.get("processing", {}) or {}).get("calibration", {}) or {}
    merged = {**DEFAULT_CALIBRATION_CONFIG, **raw}

    gamma_min = float(merged.get("gamma_min", DEFAULT_CALIBRATION_CONFIG["gamma_min"]))
    gamma_max = float(merged.get("gamma_max", DEFAULT_CALIBRATION_CONFIG["gamma_max"]))
    if gamma_min > gamma_max:
        gamma_min, gamma_max = gamma_max, gamma_min
    if abs(gamma_max - gamma_min) < 1e-6:
        gamma_max = gamma_min + 0.1

    merged["enabled"] = bool(merged.get("enabled", True))
    merged["mode"] = "auto_pack"
    merged["pattern"] = "gamma_ladder"
    merged["gamma_min"] = max(0.05, gamma_min)
    merged["gamma_max"] = min(5.0, gamma_max)
    merged["gamma_steps"] = max(2, int(merged.get("gamma_steps", 10)))
    merged["strip_width_mm"] = max(40.0, float(merged.get("strip_width_mm", 140.0)))
    merged["strip_height_mm"] = max(16.0, float(merged.get("strip_height_mm", 28.0)))
    merged["padding_mm"] = max(0.5, float(merged.get("padding_mm", 2.0)))
    return merged


def build_gamma_ladder_definition(config: Dict[str, Any]) -> Dict[str, Any]:
    gamma_values = np.linspace(
        config["gamma_min"],
        config["gamma_max"],
        int(config["gamma_steps"]),
    )
    gamma_list = [round(float(g), 3) for g in gamma_values]

    strip_w = float(config["strip_width_mm"])
    strip_h = float(config["strip_height_mm"])
    padding = float(config["padding_mm"])

    step_count = len(gamma_list)
    cell_gap = max(0.6, min(2.0, padding * 0.7))
    label_band_mm = max(3.0, min(5.0, strip_h * 0.18))
    interior_h = max(6.0, strip_h - (2 * padding) - label_band_mm)
    interior_w = max(10.0, strip_w - (2 * padding) - ((step_count - 1) * cell_gap))
    cell_w = max(4.0, interior_w / step_count)

    # If clamping changed width, recenter the ladder inside the strip.
    ladder_w = cell_w * step_count + (step_count - 1) * cell_gap
    x0 = (strip_w - ladder_w) / 2.0
    y0 = padding + label_band_mm

    cells: List[Dict[str, Any]] = []
    for idx, gamma in enumerate(gamma_list):
        cells.append(
            {
                "index": idx,
                "label": f"g={gamma:.2f}",
                "gamma": gamma,
                "x_mm": round(x0 + idx * (cell_w + cell_gap), 3),
                "y_mm": round(y0, 3),
                "width_mm": round(cell_w, 3),
                "height_mm": round(interior_h, 3),
            }
        )

    return {
        "pattern": "gamma_ladder",
        "legend": "Expected gamma row; choose best physical match",
        "strip": {
            "width_mm": strip_w,
            "height_mm": strip_h,
            "padding_mm": padding,
        },
        "gamma_values": gamma_list,
        "reference_grayscale": [int(v) for v in np.linspace(0, 255, 9)],
        "cells": cells,
    }


def place_calibration_strip(
    sheets: Dict[int, List[Dict[str, Any]]],
    sheet_width_mm: float,
    sheet_height_mm: float,
    sheet_margin_mm: float,
    sheet_gap_mm: float,
    strip_width_mm: float,
    strip_height_mm: float,
    padding_mm: float,
) -> Dict[str, Any]:
    usable_min_x = float(sheet_margin_mm)
    usable_min_y = float(sheet_margin_mm)
    usable_max_x = float(sheet_width_mm - sheet_margin_mm)
    usable_max_y = float(sheet_height_mm - sheet_margin_mm)
    usable_rect = box(usable_min_x, usable_min_y, usable_max_x, usable_max_y)

    strip_w = min(float(strip_width_mm), usable_max_x - usable_min_x)
    strip_h = min(float(strip_height_mm), usable_max_y - usable_min_y)
    clearance = max(0.0, (sheet_gap_mm * 0.5) + padding_mm)

    def candidate_points() -> Iterable[Tuple[float, float]]:
        yield usable_min_x, usable_max_y - strip_h
        yield usable_max_x - strip_w, usable_max_y - strip_h
        yield usable_min_x, usable_min_y
        yield usable_max_x - strip_w, usable_min_y

        step = 5.0
        y = usable_max_y - strip_h
        while y >= usable_min_y:
            x = usable_min_x
            while x <= usable_max_x - strip_w:
                yield x, y
                x += step
            y -= step

    for sheet_idx in sorted(sheets.keys()):
        occupied = [item.get("polygon") for item in sheets[sheet_idx] if item.get("polygon") is not None]
        occupied_union = None
        if occupied:
            buffered = [poly.buffer(clearance, join_style=2) for poly in occupied]
            occupied_union = unary_union(buffered)

        for x, y in candidate_points():
            candidate = box(x, y, x + strip_w, y + strip_h)
            if not usable_rect.contains(candidate):
                continue
            if occupied_union is not None and candidate.intersects(occupied_union):
                continue
            return {
                "sheet_index": int(sheet_idx),
                "x_mm": round(x, 3),
                "y_mm": round(y, 3),
                "w_mm": round(strip_w, 3),
                "h_mm": round(strip_h, 3),
                "fallback_sheet": False,
            }

    fallback_idx = max(sheets.keys(), default=-1) + 1
    x = max(usable_min_x, min(usable_max_x - strip_w, usable_min_x + padding_mm))
    y = max(usable_min_y, min(usable_max_y - strip_h, usable_min_y + padding_mm))
    return {
        "sheet_index": int(fallback_idx),
        "x_mm": round(x, 3),
        "y_mm": round(y, 3),
        "w_mm": round(strip_w, 3),
        "h_mm": round(strip_h, 3),
        "fallback_sheet": True,
    }

