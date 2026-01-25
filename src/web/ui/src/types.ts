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

export interface ProcessingConfig {
  smoothing_sigma: number;
  simplification_tol: number;
  kerf_width_mm: number;
  geometric_smoothing: boolean;
  nesting: {
    enabled: boolean;
    sheet_width_in: number;
    sheet_height_in: number;
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
  processing: ProcessingConfig;
  export: ExportConfig;
}

export interface JobInfo {
  id: string;
  status: 'pending' | 'running' | 'completed' | 'failed';
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
