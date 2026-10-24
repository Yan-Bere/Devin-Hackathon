// Types for the coldplate results document (docs/API_CONTRACT.md).

export interface FileRef {
  url?: string;
  path: string;
  bytes: number;
  sha256: string;
  convention?: string;
}

export interface ComponentMetrics {
  type: string;
  max_C: number;
  mean_C: number;
  R_th_K_per_W: number | null;
  power_W: number;
}

export interface CandidateMetrics {
  critical_temperature_C: number;
  hbm_max_C: number | null;
  hbm_hottest: string | null;
  gpu_max_C: number | null;
  gpu_hottest: string | null;
  pressure_drop_kPa: number;
  pumping_power_W: number;
  coolant_outlet_C: number;
  coolant_rise_K: number;
  worst_margin_K: number | null;
  worst_margin_component: string | null;
  components: Record<string, ComponentMetrics>;
  energy_residual: number;
  [k: string]: unknown;
}

export interface Violation {
  constraint: string;
  component: string | null;
  value: number;
  limit: number;
}

export interface CandidateParams {
  arrangement: string;
  flow_axis: string;
  fin_height_mm: number;
  fin_thickness_mm: number;
  channel_width_by_zone_mm: Record<string, number>;
  zones: { label: string; v_start_mm: number; v_end_mm: number;
           channel_width_mm: number; actual_channel_width_mm: number | null;
           fin_thickness_mm: number; n_channels: number }[];
  n_channels: number;
  n_fins: number;
  inlet_opening_mm: number;
  outlet_opening_mm: number;
  [k: string]: unknown;
}

export interface Candidate {
  candidate_id: string;
  design_id: string;
  is_baseline: boolean;
  params: CandidateParams;
  metrics: CandidateMetrics;
  feasible: boolean;
  violations: Violation[];
  targets_met: Record<string, boolean>;
  worst_case: Record<string, unknown>;
  pareto: { nondominated: boolean; rank: number };
  selected: boolean;
  role: string | null;
  status_label: "nondominated" | "dominated" | "infeasible";
}

export interface SelectedDesign extends Candidate {
  role_label?: string;
  sweep?: {
    flows_Lpm: number[];
    inlet_temperatures_C: number[];
    points: unknown[];
  } | null;
  acceptance?: {
    worst_point: Record<string, unknown>;
    pressure_at_highest_flow: Record<string, unknown>;
    outlet_rise: Record<string, unknown>;
    accepted: boolean;
    summary: string;
  } | null;
  files?: Record<string, FileRef>;
  cad_check?: Record<string, unknown>;
}

export interface Constraint {
  key: string;
  label: string;
  unit: string;
  limit: number | null;
  target?: number | null;
  stretch?: number | null;
  acceptance?: number | null;
  kind: string;
}

export interface ResultsDoc {
  schema_version: string;
  job_id: string;
  engine_version: string;
  created_at: string;
  completed_at: string | null;
  status: string;
  label: string;
  inputs: Record<string, unknown>;
  interpretation: {
    provider: string;
    provider_label: string;
    api_version?: string | null;
    prompt_version: string;
    cached: boolean;
    devin_calls: number;
    sessions: { session_id?: string; url?: string }[];
    warnings: string[];
    missing_essential: string[];
    [k: string]: unknown;
  };
  normalized_inputs: Record<string, unknown> | null;
  assumptions: { field: string; statement: string; origin: string }[];
  requirement_conflicts: string[];
  simulation: Record<string, unknown>;
  objectives: {
    x: { key: string; label: string; direction: string };
    y: { key: string; label: string; component_type: string | null };
    alternatives: { key: string; label: string }[];
  } | null;
  constraints: Constraint[];
  candidates: Candidate[];
  rejected_candidates: { candidate_id: string; params: unknown; reason: string }[];
  pareto: {
    front_candidate_ids: string[];
    n_evaluated: number;
    n_feasible: number;
    n_nondominated: number;
    all_infeasible: boolean;
  };
  selected_designs: SelectedDesign[];
  warnings: string[];
  links: Record<string, string>;
}
