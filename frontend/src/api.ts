/**
 * Typed client for the lab backend.
 *
 * These types mirror backend/app/models/run.py. They are hand-maintained on
 * purpose -- the backend is the source of truth, and a codegen step is not
 * worth it at this size.
 */

import type { AnalyzedPlan, Buffers } from "./plan/types";

export type { AnalyzedPlan, Buffers };

export type RunMode = "execute" | "explain" | "analyze";

export interface Timings {
  runs_ms: number[];
  discarded_first_ms: number | null;
  median_ms: number | null;
  p25_ms: number | null;
  p75_ms: number | null;
  min_ms: number | null;
  max_ms: number | null;
  planning_ms: number | null;
  execution_ms: number | null;
}

export interface ResultSet {
  columns: string[];
  rows: unknown[][];
  row_count: number;
  truncated: boolean;
}

export interface RunError {
  message: string;
  sqlstate: string | null;
  detail: string | null;
  hint: string | null;
  position: number | null;
  statement_index: number | null;
}

export interface StatementInfo {
  index: number;
  sql: string;
  is_target: boolean;
  duration_ms: number | null;
}

/** Raw EXPLAIN FORMAT JSON, kept verbatim for the JSON tab. */
export type ExplainEnvelope = Record<string, unknown>;

export interface RunResponse {
  ok: boolean;
  mode: RunMode;
  sandbox: boolean;
  statements: StatementInfo[];
  plan: ExplainEnvelope | null;
  analyzed_plan: AnalyzedPlan | null;
  result: ResultSet | null;
  timings: Timings | null;
  buffers: Buffers | null;
  notices: string[];
  warnings: string[];
  error: RunError | null;
}

export interface RunRequest {
  sql: string;
  mode: RunMode;
  sandbox: boolean;
  statement_timeout_ms: number;
  repeat: number;
  row_cap: number;
  settings_overrides: Record<string, string>;
}

export interface HealthResponse {
  ok: boolean;
  server_version: string | null;
  databases: Record<string, boolean>;
  extensions: Record<string, string>;
  missing_extensions: string[];
  settings: Record<string, string>;
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const resp = await fetch(`/api${path}`, {
    headers: { "Content-Type": "application/json" },
    ...init,
  });
  if (!resp.ok) {
    const body = await resp.text();
    throw new Error(`${resp.status} ${resp.statusText}: ${body.slice(0, 400)}`);
  }
  return (await resp.json()) as T;
}

export function getHealth(): Promise<HealthResponse> {
  return request<HealthResponse>("/health");
}

export function postRun(req: RunRequest): Promise<RunResponse> {
  return request<RunResponse>("/run", {
    method: "POST",
    body: JSON.stringify(req),
  });
}

export function postPrewarm(relation: string): Promise<{ blocks: number | null }> {
  return request("/maintenance/prewarm", {
    method: "POST",
    body: JSON.stringify({ relation }),
  });
}

export function postDiscard(): Promise<{ note: string }> {
  return request("/maintenance/discard", { method: "POST" });
}
