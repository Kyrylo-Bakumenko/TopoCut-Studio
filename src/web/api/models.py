from typing import Optional

from pydantic import BaseModel, Field

class ExperimentConfig(BaseModel):
    name: str = Field(..., description="Name of the experiment/folder")
    output_dir: str = Field("results", description="Root output directory")

class RegionConfig(BaseModel):
    center_lat: float = Field(..., description="Latitude of center point")
    center_lon: float = Field(..., description="Longitude of center point")
    radius_m: float = Field(2000.0, description="Radius of interest in meters")

class ModelConfig(BaseModel):
    width_inches: float = Field(5.0, description="Target physical width in inches")
    height_inches: float = Field(5.0, description="Target physical height in inches")
    layer_thickness_mm: float = Field(1.5875, description="Thickness of material in mm")
    contour_interval_m: float = Field(50.0, description="Vertical interval in meters")

class DataConfig(BaseModel):
    dem_source: str = Field("glo_30", description="DEM Source (glo_30, 3dep)")
    imagery_source: str = Field("naip", description="Imagery Source (naip, sentinel-2-l2a)")
    imagery_resolution: str = Field("5m", description="Imagery resolution (1m=native, 5m=preview, 10m=fast)")

class NestingConfig(BaseModel):
    enabled: bool = Field(True, description="Whether to nest parts onto sheets")
    sheet_width_in: float = Field(24.0, description="Sheet width in inches")
    sheet_height_in: float = Field(12.0, description="Sheet height in inches")
    bed_width_in: float = Field(24.0, description="Machine bed width in inches")
    bed_height_in: float = Field(12.0, description="Machine bed height in inches")
    sheet_margin_in: float = Field(0.125, description="Edge margin in inches")
    sheet_gap_in: float = Field(0.0625, description="Minimum gap between parts in inches")


class CalibrationConfig(BaseModel):
    enabled: bool = Field(True, description="Enable calibration strip generation")
    mode: str = Field("auto_pack", description="Calibration placement mode")
    pattern: str = Field("gamma_ladder", description="Calibration pattern type")
    gamma_min: float = Field(0.70, description="Minimum gamma in calibration sweep")
    gamma_max: float = Field(1.60, description="Maximum gamma in calibration sweep")
    gamma_steps: int = Field(10, description="Number of gamma steps in calibration sweep")
    strip_width_mm: float = Field(140.0, description="Calibration strip width in mm")
    strip_height_mm: float = Field(28.0, description="Calibration strip height in mm")
    padding_mm: float = Field(2.0, description="Padding around calibration strip in mm")


def _default_calibration() -> "CalibrationConfig":
    return CalibrationConfig()


def _default_nesting() -> "NestingConfig":
    # explicit defaults avoid pylance false positives for BaseModel init
    return NestingConfig(
        enabled=True,
        sheet_width_in=24.0,
        sheet_height_in=12.0,
        bed_width_in=24.0,
        bed_height_in=12.0,
        sheet_margin_in=0.125,
        sheet_gap_in=0.0625,
    )


class ProfilesConfig(BaseModel):
    machine_id: Optional[str] = Field(None, description="Selected machine profile id")
    machine_name: Optional[str] = Field(None, description="Selected machine profile name")
    material_id: Optional[str] = Field(None, description="Selected material profile id")
    material_name: Optional[str] = Field(None, description="Selected material profile name")

class ProcessingConfig(BaseModel):
    smoothing_sigma: float = Field(0.0, description="Gaussian smoothing sigma")
    simplification_tol: float = Field(0.5, description="Shapely simplification tolerance")
    kerf_width_mm: float = Field(0.15, description="Laser kerf compensation")
    geometric_smoothing: bool = Field(False, description="Apply geometric smoothing to borders")
    texture_normalize: bool = Field(True, description="Normalize texture contrast before dithering")
    texture_normalize_cutoff: float = Field(1.0, description="Autocontrast cutoff percentage")
    texture_gamma: float = Field(1.1, description="Gamma curve for texture contrast (1 = neutral)")
    min_part_area_sq_in: float = Field(
        0.015,
        ge=0.0,
        description="Minimum physical island area (sq in) to keep; smaller islands are removed",
    )
    calibration: Optional[CalibrationConfig] = Field(
        default_factory=_default_calibration,
        description="Calibration strip configuration",
    )
    nesting: Optional[NestingConfig] = Field(
        default_factory=_default_nesting,
        description="Nesting configuration",
    )

class ExportConfig(BaseModel):
    format: str = Field("dxf", description="Export format")
    layers_per_file: int = Field(1, description="1 = separate files, 0 = single file")

class PipelineConfig(BaseModel):
    experiment: ExperimentConfig
    region: RegionConfig
    model: ModelConfig
    data: DataConfig
    profiles: ProfilesConfig = Field(default_factory=ProfilesConfig)
    processing: ProcessingConfig
    export: ExportConfig
