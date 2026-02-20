from __future__ import annotations

from math import floor
from typing import Any, Dict, Iterable, List


def resolve_bed_geometry(nesting_cfg: Dict[str, Any]) -> Dict[str, float]:
    sheet_width_mm = float(nesting_cfg.get("sheet_width_in", 24.0)) * 25.4
    sheet_height_mm = float(nesting_cfg.get("sheet_height_in", 12.0)) * 25.4
    bed_width_mm = float(nesting_cfg.get("bed_width_in", nesting_cfg.get("sheet_width_in", 24.0))) * 25.4
    bed_height_mm = float(nesting_cfg.get("bed_height_in", nesting_cfg.get("sheet_height_in", 12.0))) * 25.4
    sheet_margin_mm = float(nesting_cfg.get("sheet_margin_in", 0.125)) * 25.4
    sheet_gap_mm = float(nesting_cfg.get("sheet_gap_in", 0.0625)) * 25.4

    if sheet_width_mm <= 0 or sheet_height_mm <= 0:
        raise ValueError("Sheet dimensions must be positive.")
    if bed_width_mm <= 0 or bed_height_mm <= 0:
        raise ValueError("Bed dimensions must be positive.")
    if sheet_margin_mm < 0:
        raise ValueError("Sheet margin cannot be negative.")
    if sheet_gap_mm < 0:
        raise ValueError("Part gap cannot be negative.")

    usable_width_mm = bed_width_mm - (2.0 * sheet_margin_mm)
    usable_height_mm = bed_height_mm - (2.0 * sheet_margin_mm)
    if usable_width_mm <= 0 or usable_height_mm <= 0:
        raise ValueError("Machine bed is fully consumed by edge margins.")
    if sheet_width_mm > usable_width_mm or sheet_height_mm > usable_height_mm:
        raise ValueError(
            "Material sheet does not fit within machine bed after applying edge margins."
        )

    cols = int(floor((usable_width_mm + sheet_gap_mm) / (sheet_width_mm + sheet_gap_mm)))
    rows = int(floor((usable_height_mm + sheet_gap_mm) / (sheet_height_mm + sheet_gap_mm)))
    if cols < 1 or rows < 1:
        raise ValueError("Unable to place any sheets on the selected bed geometry.")

    return {
        "sheet_width_mm": sheet_width_mm,
        "sheet_height_mm": sheet_height_mm,
        "bed_width_mm": bed_width_mm,
        "bed_height_mm": bed_height_mm,
        "sheet_margin_mm": sheet_margin_mm,
        "sheet_gap_mm": sheet_gap_mm,
        "usable_width_mm": usable_width_mm,
        "usable_height_mm": usable_height_mm,
        "cols": cols,
        "rows": rows,
        "capacity": cols * rows,
    }


def build_bed_layout(
    sheet_indices: Iterable[int],
    *,
    bed_width_mm: float,
    bed_height_mm: float,
    sheet_width_mm: float,
    sheet_height_mm: float,
    sheet_margin_mm: float,
    sheet_gap_mm: float,
) -> Dict[str, Any]:
    usable_width_mm = bed_width_mm - (2.0 * sheet_margin_mm)
    usable_height_mm = bed_height_mm - (2.0 * sheet_margin_mm)
    cols = int(floor((usable_width_mm + sheet_gap_mm) / (sheet_width_mm + sheet_gap_mm)))
    rows = int(floor((usable_height_mm + sheet_gap_mm) / (sheet_height_mm + sheet_gap_mm)))
    if cols < 1 or rows < 1:
        raise ValueError("Unable to place any sheets on the selected bed geometry.")
    capacity = cols * rows

    ordered_sheet_indices: List[int] = sorted(int(idx) for idx in sheet_indices)
    beds: Dict[int, List[Dict[str, Any]]] = {}

    for order, sheet_index in enumerate(ordered_sheet_indices):
        bed_index = order // capacity
        slot_index = order % capacity
        row = slot_index // cols
        col = slot_index % cols

        x_mm = sheet_margin_mm + col * (sheet_width_mm + sheet_gap_mm)
        y_top = bed_height_mm - sheet_margin_mm - sheet_height_mm
        y_mm = y_top - row * (sheet_height_mm + sheet_gap_mm)

        if bed_index not in beds:
            beds[bed_index] = []
        beds[bed_index].append(
            {
                "sheet_index": sheet_index,
                "sheet_id": f"sheet_{sheet_index:02d}",
                "x_mm": round(x_mm, 3),
                "y_mm": round(y_mm, 3),
                "w_mm": round(sheet_width_mm, 3),
                "h_mm": round(sheet_height_mm, 3),
                "row": row,
                "col": col,
            }
        )

    bed_list = []
    for bed_index in sorted(beds.keys()):
        bed_list.append(
            {
                "bed_index": bed_index,
                "bed_id": f"bed_{bed_index:02d}",
                "sheets": beds[bed_index],
            }
        )

    return {
        "bed_width_mm": bed_width_mm,
        "bed_height_mm": bed_height_mm,
        "sheet_width_mm": sheet_width_mm,
        "sheet_height_mm": sheet_height_mm,
        "sheet_margin_mm": sheet_margin_mm,
        "sheet_gap_mm": sheet_gap_mm,
        "cols": cols,
        "rows": rows,
        "capacity": capacity,
        "beds": bed_list,
    }
