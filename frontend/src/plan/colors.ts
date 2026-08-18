/**
 * Colour scales for the plan tree.
 *
 * Two modes matter (spec F2):
 *
 *  - **self time** -- classic flame colouring. Shows where the wall clock went.
 *  - **estimate error** -- log-scale on max(actual/est, est/actual). This is the
 *    view worth learning from and the one most tools do not have: a node can be
 *    fast and still be the reason the plan above it is wrong.
 *
 * Buffers is included as a third because it is the machine-independent metric,
 * so it is the one that stays true when you re-run on a different laptop.
 */

import type { PlanNode } from "./types";
import { totalBlocks } from "./types";

export type ColorMode = "self_time" | "estimate_error" | "buffers";

export const COLOR_MODES: { id: ColorMode; label: string; hint: string }[] = [
  {
    id: "self_time",
    label: "Self time",
    hint: "Share of wall clock spent in this node alone, excluding children.",
  },
  {
    id: "estimate_error",
    label: "Estimate error",
    hint: "How far the planner's row estimate was from reality, on a log scale.",
  },
  {
    id: "buffers",
    label: "Buffers",
    hint: "Share of blocks touched by this node alone. Machine-independent.",
  },
];

// Slate -> cyan -> yellow -> orange -> red. Reads as a flame in a dark UI.
const RAMP: [number, [number, number, number]][] = [
  [0.0, [30, 41, 59]],
  [0.2, [14, 116, 144]],
  [0.45, [101, 163, 13]],
  [0.65, [202, 138, 4]],
  [0.85, [234, 88, 12]],
  [1.0, [220, 38, 38]],
];

function lerp(a: number, b: number, t: number): number {
  return a + (b - a) * t;
}

/** Sample the ramp at t in [0,1]. */
export function heat(t: number): string {
  const x = Math.max(0, Math.min(1, t));
  for (let i = 1; i < RAMP.length; i++) {
    const lo = RAMP[i - 1]!;
    const hi = RAMP[i]!;
    if (x <= hi[0]) {
      const span = hi[0] - lo[0];
      const local = span === 0 ? 0 : (x - lo[0]) / span;
      const [r, g, b] = [0, 1, 2].map((c) => Math.round(lerp(lo[1][c]!, hi[1][c]!, local)));
      return `rgb(${r} ${g} ${b})`;
    }
  }
  return "rgb(220 38 38)";
}

/** Text that stays readable on top of the ramp. */
export function heatText(t: number): string {
  return t > 0.42 ? "rgb(15 23 42)" : "rgb(226 232 240)";
}

// 1x -> 0, 10x -> 1/3, 100x -> 2/3, 1000x and beyond -> 1.
const ERROR_DECADES = 3;

export function errorIntensity(ratio: number | null | undefined): number {
  if (ratio == null || ratio <= 1) return 0;
  return Math.min(1, Math.log10(ratio) / ERROR_DECADES);
}

export interface Scale {
  /** 0..1 heat position for this node. */
  intensity: (node: PlanNode) => number;
  /** Short value shown on the node face. */
  format: (node: PlanNode) => string;
  /** Legend tick labels, low to high. */
  legend: string[];
  /** Why the whole mode has nothing to show, if so. */
  unavailable?: string;
}

export function buildScale(mode: ColorMode, nodes: PlanNode[], analyzed: boolean): Scale {
  if (mode === "estimate_error") {
    return {
      intensity: (n) => errorIntensity(n.rows.error_ratio),
      format: (n) =>
        n.rows.error_ratio == null || n.rows.error_ratio < 1.05
          ? "on target"
          : `${formatRatio(n.rows.error_ratio)} ${n.rows.direction ?? ""}`.trim(),
      legend: ["1x", "10x", "100x", "1000x+"],
      unavailable: analyzed
        ? undefined
        : "Estimate error needs actual row counts. Run in Analyze mode.",
    };
  }

  if (mode === "buffers") {
    // Relative to the busiest node rather than the total: one node usually
    // dominates, and scaling to the total would leave everything else black.
    const peak = Math.max(1, ...nodes.map((n) => totalBlocks(n.self_buffers)));
    return {
      intensity: (n) => totalBlocks(n.self_buffers) / peak,
      format: (n) => `${formatCount(totalBlocks(n.self_buffers))} blk`,
      legend: ["0", "", "", `${formatCount(peak)} blk`],
    };
  }

  return {
    intensity: (n) => n.timing?.self_fraction ?? 0,
    format: (n) =>
      n.timing?.self_ms == null ? "-" : `${formatMs(n.timing.self_ms)} self`,
    legend: ["0%", "33%", "66%", "100%"],
    unavailable: analyzed ? undefined : "Timing needs a run. Use Analyze mode.",
  };
}

export function formatMs(ms: number): string {
  if (ms >= 1000) return `${(ms / 1000).toFixed(2)} s`;
  if (ms >= 10) return `${ms.toFixed(0)} ms`;
  if (ms >= 1) return `${ms.toFixed(1)} ms`;
  return `${ms.toFixed(2)} ms`;
}

export function formatCount(n: number | null | undefined): string {
  if (n == null) return "-";
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1_000) return `${(n / 1_000).toFixed(1)}k`;
  return String(n);
}

export function formatRatio(r: number | null | undefined): string {
  if (r == null) return "-";
  if (r >= 100) return `${Math.round(r).toLocaleString()}x`;
  if (r >= 10) return `${r.toFixed(0)}x`;
  return `${r.toFixed(1)}x`;
}

export const SEVERITY_STYLE: Record<string, string> = {
  critical: "border-red-500/60 bg-red-500/15 text-red-200",
  warn: "border-amber-500/50 bg-amber-500/15 text-amber-200",
  info: "border-sky-500/40 bg-sky-500/10 text-sky-200",
};
