from pathlib import Path

from PIL import Image
from rasterio.transform import Affine
from shapely.geometry import Point, Polygon

from elevation_relief.export.plot import save_composite_sheet


def _write_texture(path: Path, width: int = 20, height: int = 20, value: int = 140) -> None:
    image = Image.new("L", (width, height), color=value)
    image.save(path)


def test_label_uses_inside_white_zone_when_available(tmp_path: Path) -> None:
    textures_dir = tmp_path / "textures"
    textures_dir.mkdir(parents=True, exist_ok=True)
    _write_texture(textures_dir / "layer_000_elev_100.png")
    _write_texture(textures_dir / "layer_001_elev_200.png")

    lower_poly = Polygon([(2, 2), (18, 2), (18, 18), (2, 18)])
    upper_poly = Polygon([(7, 7), (13, 7), (13, 13), (7, 13)])

    items = [
        {
            "layer_id": "layer_000_elev_100",
            "polygon": lower_poly,
            "scaled_polygon": lower_poly,
            "world_polygon": lower_poly,
            "is_rotated": False,
        },
        {
            "layer_id": "layer_001_elev_200",
            "polygon": upper_poly,
            "scaled_polygon": upper_poly,
            "world_polygon": upper_poly,
            "is_rotated": False,
        },
    ]

    output_path = tmp_path / "sheet.png"
    placements = save_composite_sheet(
        items=items,
        textures_dir=textures_dir,
        sheet_width_mm=20.0,
        sheet_height_mm=20.0,
        filename=str(output_path),
        img_transform=Affine(1, 0, 0, 0, -1, 20),
    )

    assert output_path.exists()
    assert placements[0]["label_mode"] == "inside_white"
    assert "leader_start_point" not in placements[0]
    assert "leader_end_point" not in placements[0]


def test_label_falls_back_outside_with_leader(tmp_path: Path) -> None:
    textures_dir = tmp_path / "textures"
    textures_dir.mkdir(parents=True, exist_ok=True)
    _write_texture(textures_dir / "layer_000_elev_100.png")

    poly = Polygon([(2, 2), (18, 2), (18, 18), (2, 18)])
    items = [
        {
            "layer_id": "layer_000_elev_100",
            "polygon": poly,
            "scaled_polygon": poly,
            "world_polygon": poly,
            "is_rotated": False,
        }
    ]

    output_path = tmp_path / "sheet.png"
    placements = save_composite_sheet(
        items=items,
        textures_dir=textures_dir,
        sheet_width_mm=20.0,
        sheet_height_mm=20.0,
        filename=str(output_path),
        img_transform=Affine(1, 0, 0, 0, -1, 20),
    )

    placement = placements[0]
    assert placement["label_mode"] in {"outside_leader", "fallback"}
    assert "leader_start_point" in placement
    assert "leader_end_point" in placement

    label_pt = Point(*placement["label_point"])
    assert not poly.contains(label_pt)

    end_pt = Point(*placement["leader_end_point"])
    end_dist = poly.boundary.distance(end_pt)
    assert end_dist >= 0.45
    assert end_dist <= 1.2


def test_label_metadata_shape_is_stable(tmp_path: Path) -> None:
    textures_dir = tmp_path / "textures"
    textures_dir.mkdir(parents=True, exist_ok=True)
    _write_texture(textures_dir / "layer_000_elev_100.png")

    poly = Polygon([(3, 3), (17, 3), (17, 17), (3, 17)])
    items = [
        {
            "layer_id": "layer_000_elev_100",
            "polygon": poly,
            "scaled_polygon": poly,
            "world_polygon": poly,
            "is_rotated": False,
        }
    ]

    placements = save_composite_sheet(
        items=items,
        textures_dir=textures_dir,
        sheet_width_mm=20.0,
        sheet_height_mm=20.0,
        filename=str(tmp_path / "sheet.png"),
        img_transform=Affine(1, 0, 0, 0, -1, 20),
    )

    placement = placements[0]
    assert placement["label_mode"] in {"inside_white", "outside_leader", "fallback"}
    assert isinstance(placement["label_point"], list)
    assert len(placement["label_point"]) == 2
    assert placement["label_font_cap_height_mm"] == 1.8


def test_outside_labels_avoid_other_parts(tmp_path: Path) -> None:
    textures_dir = tmp_path / "textures"
    textures_dir.mkdir(parents=True, exist_ok=True)
    _write_texture(textures_dir / "layer_000_elev_100.png", width=40, height=20)
    _write_texture(textures_dir / "layer_001_elev_200.png", width=40, height=20)

    left_poly = Polygon([(2, 2), (18, 2), (18, 18), (2, 18)])
    right_poly = Polygon([(22, 2), (38, 2), (38, 18), (22, 18)])
    items = [
        {
            "layer_id": "layer_000_elev_100",
            "polygon": left_poly,
            "scaled_polygon": left_poly,
            "world_polygon": left_poly,
            "is_rotated": False,
        },
        {
            "layer_id": "layer_001_elev_200",
            "polygon": right_poly,
            "scaled_polygon": right_poly,
            "world_polygon": right_poly,
            "is_rotated": False,
        },
    ]

    placements = save_composite_sheet(
        items=items,
        textures_dir=textures_dir,
        sheet_width_mm=40.0,
        sheet_height_mm=20.0,
        filename=str(tmp_path / "sheet.png"),
        img_transform=Affine(1, 0, 0, 0, -1, 20),
    )

    left_label = Point(*placements[0]["label_point"])
    right_label = Point(*placements[1]["label_point"])

    assert not right_poly.contains(left_label)
    assert not left_poly.contains(right_label)
