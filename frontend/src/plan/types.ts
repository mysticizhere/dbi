/** Mirrors backend/app/models/plan.py. The backend derives every number here. */

export type Severity = "info" | "warn" | "critical";

export type WarningCode =
  | "estimate_error"
  | "seq_scan_large"
  | "heap_fetches"
  | "sort_spill"
  | "hash_spill"
  | "nested_loop_loops"
  | "filter_discard"
  | "lossy_bitmap";

export interface PlanWarning {
  code: WarningCode;
  severity: Severity;
  label: string;
  detail: string;
  node_id: number;
}

export interface Buffers {
  shared_hit: number;
  shared_read: number;
  shared_dirtied: number;
  shared_written: number;
  local_hit: number;
  local_read: number;
  temp_read: number;
  temp_written: number;
}

export interface NodeRows {
  planned: number | null;
  actual: number | null;
  total_actual: number | null;
  error_ratio: number | null;
  direction: "over" | "under" | "exact" | null;
}

export interface NodeTiming {
  startup_ms: number | null;
  per_loop_ms: number | null;
  /** ATT x loops -- total work across every loop and worker. */
  total_ms: number | null;
  /** total_ms divided back down by concurrent workers: wall-clock share. */
  elapsed_ms: number | null;
  self_ms: number | null;
  self_fraction: number | null;
  loops: number;
  parallel_divisor: number;
}

export interface NodeCost {
  startup: number | null;
  total: number | null;
  width: number | null;
}

export interface PlanNode {
  id: number;
  node_type: string;
  depth: number;
  parent_relationship: string | null;
  subplan_name: string | null;
  cte_name: string | null;
  relation: string | null;
  alias: string | null;
  index_name: string | null;
  join_type: string | null;
  scan_direction: string | null;
  strategy: string | null;
  parallel_aware: boolean;
  workers_planned: number | null;
  workers_launched: number | null;
  cost: NodeCost;
  rows: NodeRows;
  timing: NodeTiming | null;
  buffers: Buffers;
  self_buffers: Buffers;
  conditions: Record<string, string>;
  metrics: Record<string, unknown>;
  output: string[];
  warnings: PlanWarning[];
  children: PlanNode[];
}

export interface PlanSummary {
  planning_ms: number | null;
  execution_ms: number | null;
  total_ms: number | null;
  node_count: number;
  max_estimate_error: number | null;
  max_estimate_error_node: number | null;
  slowest_node: number | null;
  buffers: Buffers;
  analyzed: boolean;
  parallel: boolean;
  triggers: Record<string, unknown>[];
  settings: Record<string, string>;
  jit: Record<string, unknown> | null;
}

export interface AnalyzedPlan {
  root: PlanNode;
  summary: PlanSummary;
  warnings: PlanWarning[];
}

/** Flatten depth-first, matching the ids the backend assigned. */
export function flatten(node: PlanNode): PlanNode[] {
  return [node, ...node.children.flatMap(flatten)];
}

export function totalBlocks(b: Buffers): number {
  return b.shared_hit + b.shared_read;
}
