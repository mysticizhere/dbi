/** Typed client for the exercise engine. Mirrors backend/app/models/exercise.py. */

import type { RunResponse } from "../api";

export type AssertionType =
  | "has_node"
  | "no_node"
  | "heap_fetches_max"
  | "max_estimate_error"
  | "max_shared_read"
  | "max_total_blocks"
  | "max_total_time_ms"
  | "no_sort_spill"
  | "returns_same_rows_as_solution";

export interface Assertion {
  type: AssertionType;
  value: number | null;
  node_type: string | null;
  relation: string | null;
  index_name: string | null;
  because: string | null;
}

export interface ExerciseSummary {
  id: string;
  slug: string;
  title: string;
  layer: number;
  difficulty: number;
  requires_persist: boolean;
  assertion_count: number;
  attempts: number;
  passed: boolean;
}

export interface Exercise extends Omit<ExerciseSummary, "attempts" | "passed" | "assertion_count"> {
  prompt: string;
  starting_query: string;
  hints: string[];
  assertions: Assertion[];
  setup_sql: string;
  solution_sql: string;
  notes_md: string;
}

export interface AssertionResult {
  type: AssertionType;
  description: string;
  passed: boolean;
  expected: string;
  observed: string;
  detail: string | null;
  because: string | null;
  node_ids: number[];
}

export interface GradeResult {
  exercise_id: string;
  passed: boolean;
  results: AssertionResult[];
  error: string | null;
}

export interface SubmitResponse {
  run: RunResponse;
  grade: GradeResult;
  attempt_id: number | null;
}

export interface SetupResponse {
  ok: boolean;
  statements: number;
  notices: string[];
  error: string | null;
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const resp = await fetch(`/api${path}`, {
    headers: { "Content-Type": "application/json" },
    ...init,
  });
  if (!resp.ok) {
    const body = await resp.text();
    throw new Error(`${resp.status}: ${body.slice(0, 400)}`);
  }
  return (await resp.json()) as T;
}

export const listExercises = () => request<ExerciseSummary[]>("/exercises");

export const getExercise = (id: string) => request<Exercise>(`/exercises/${id}`);

export const runSetup = (id: string) =>
  request<SetupResponse>(`/exercises/${id}/setup`, { method: "POST" });

export const submitExercise = (
  id: string,
  body: { sql: string; sandbox: boolean; repeat: number; statement_timeout_ms: number },
) =>
  request<SubmitResponse>(`/exercises/${id}/submit`, {
    method: "POST",
    body: JSON.stringify(body),
  });
