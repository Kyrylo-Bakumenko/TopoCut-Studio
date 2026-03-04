export interface ExperimentConfig {
  name: string;
  output_dir: string;
}

export interface RegionConfig {
  center_lat: number;
  center_lon: number;
  radius_m: number;
}

export interface ModelConfig {
  width_inches: number;
  height_inches: number;
  layer_thickness_mm: number;
  contour_interval_m: number;
}

export interface DataConfig {
  dem_source: string;
  imagery_source: string;
  imagery_resolution: string;
}

export interface ProfilesConfig {
  machine_id?: string | null;
  machine_name?: string | null;
  material_id?: string | null;
  material_name?: string | null;
}

export interface MachineProfile {
  id: string;
  name: string;
  bed_width_in: number;
  bed_height_in: number;
  sheet_margin_in: number;
  sheet_gap_in: number;
  calibration_enabled_default: boolean;
}

export interface MaterialProfile {
  id: string;
  name: string;
  sheet_width_in: number;
  sheet_height_in: number;
  layer_thickness_mm: number;
}

export interface ProfileDefaultsResponse {
  version: string;
  machine_profiles: MachineProfile[];
  material_profiles: MaterialProfile[];
}

export interface AuthUser {
  id: number;
  email: string;
  created_at: string;
}

export interface AuthResponse {
  token: string;
  user: AuthUser;
}

export interface CustomProfilesResponse {
  machine_profiles: MachineProfile[];
  material_profiles: MaterialProfile[];
}

export interface ProcessingConfig {
  smoothing_sigma: number;
  simplification_tol: number;
  kerf_width_mm: number;
  geometric_smoothing: boolean;
  texture_normalize: boolean;
  texture_normalize_cutoff: number;
  texture_gamma: number;
  min_part_area_sq_in: number;
  calibration: {
    enabled: boolean;
    mode: 'auto_pack';
    pattern: 'gamma_ladder';
    gamma_min: number;
    gamma_max: number;
    gamma_steps: number;
    strip_width_mm: number;
    strip_height_mm: number;
    padding_mm: number;
  };
  nesting: {
    enabled: boolean;
    sheet_width_in: number;
    sheet_height_in: number;
    bed_width_in: number;
    bed_height_in: number;
    sheet_margin_in: number;
    sheet_gap_in: number;
  };
}

export interface ExportConfig {
  format: string;
  layers_per_file: number;
}

export interface PipelineConfig {
  experiment: ExperimentConfig;
  region: RegionConfig;
  model: ModelConfig;
  data: DataConfig;
  profiles: ProfilesConfig;
  processing: ProcessingConfig;
  export: ExportConfig;
}

export interface JobInfo {
  id: string;
  status: 'pending' | 'running' | 'completed' | 'failed' | 'canceled';
  result_path?: string;
  error?: string;
  progress: number;
  message: string;
  created_at: string;
  config_summary: string;
}

export interface JobFile {
  type: string;
  name: string;
  url: string;
  category: string;
}

export interface SheetPolygon {
  exterior: [number, number][];
  holes: [number, number][][];
}

export interface SheetCutout {
  id: string;
  layer_id: string;
  layer_index: number;
  elevation_m: number;
  label: string;
  polygons: SheetPolygon[];
  label_point: [number, number];
  label_mode?: 'inside_white' | 'outside_leader' | 'fallback';
  leader_start_point?: [number, number];
  leader_end_point?: [number, number];
  label_font_cap_height_mm?: number;
  is_rotated: boolean;
  rotation_deg: number;
  sheet_index: number;
  cutout_index: number;
}

export interface SheetManifest {
  sheet_id: string;
  sheet_index: number;
  sheet_width_mm: number;
  sheet_height_mm: number;
  cutouts: SheetCutout[];
}

export interface CalibrationCell {
  index: number;
  label: string;
  gamma: number;
  x_mm: number;
  y_mm: number;
  width_mm: number;
  height_mm: number;
}

export interface CalibrationPlacement {
  sheet_id: string;
  sheet_index: number;
  x_mm: number;
  y_mm: number;
  w_mm: number;
  h_mm: number;
  gamma_values: number[];
}

export interface CalibrationManifest {
  pattern: 'gamma_ladder';
  legend: string;
  strip: {
    width_mm: number;
    height_mm: number;
    padding_mm: number;
  };
  gamma_values: number[];
  reference_grayscale: number[];
  cells: CalibrationCell[];
  placements: CalibrationPlacement[];
}

export interface JobConfigResponse {
  config: PipelineConfig;
}
