import type { Buffers, Timings } from "../api";

function Stat({
  label,
  value,
  hint,
  tone = "normal",
}: {
  label: string;
  value: string;
  hint?: string;
  tone?: "normal" | "good" | "warn";
}) {
  const toneClass =
    tone === "good" ? "text-emerald-300" : tone === "warn" ? "text-amber-300" : "text-slate-100";
  return (
    <div className="min-w-24" title={hint}>
      <div className="text-[0.625rem] font-medium uppercase tracking-wider text-slate-500">{label}</div>
      <div className={`font-mono text-sm ${toneClass}`}>{value}</div>
    </div>
  );
}

const ms = (v: number | null | undefined) => (v == null ? "-" : `${v.toFixed(2)} ms`);
const num = (v: number | null | undefined) => (v == null ? "-" : v.toLocaleString());

export default function MetricsBar({
  timings,
  buffers,
}: {
  timings: Timings | null;
  buffers: Buffers | null;
}) {
  if (!timings && !buffers) return null;

  // Buffers are the honest metric: they do not move with machine speed or with
  // whatever else the laptop was doing. Wall time is shown, but second.
  const totalBlocks = buffers ? buffers.shared_hit + buffers.shared_read : null;

  return (
    <div className="flex flex-wrap items-start gap-x-6 gap-y-3 rounded-lg border border-slate-800 bg-slate-900/50 px-4 py-3">
      {buffers && (
        <>
          <Stat
            label="shared hit"
            value={num(buffers.shared_hit)}
            hint="Blocks found in shared_buffers -- already cached."
            tone="good"
          />
          <Stat
            label="shared read"
            value={num(buffers.shared_read)}
            hint="Blocks fetched from the OS/disk. The number that matters when comparing plans."
            tone={buffers.shared_read > 0 ? "warn" : "normal"}
          />
          <Stat label="blocks total" value={num(totalBlocks)} hint="hit + read, i.e. work done." />
          {buffers.temp_written > 0 && (
            <Stat
              label="temp written"
              value={num(buffers.temp_written)}
              hint="Spilled to disk -- work_mem is too low for this plan."
              tone="warn"
            />
          )}
        </>
      )}

      {timings && (
        <>
          <div className="h-8 w-px self-center bg-slate-800" />
          <Stat
            label="median"
            value={ms(timings.median_ms)}
            hint={
              timings.discarded_first_ms != null
                ? `First run (${timings.discarded_first_ms.toFixed(2)} ms) discarded as cold.`
                : undefined
            }
          />
          <Stat label="p25 / p75" value={`${ms(timings.p25_ms)} / ${ms(timings.p75_ms)}`} />
          {timings.planning_ms != null && (
            <Stat label="planning" value={ms(timings.planning_ms)} />
          )}
          {timings.execution_ms != null && (
            <Stat label="execution" value={ms(timings.execution_ms)} />
          )}
          {timings.runs_ms.length > 1 && (
            <Stat
              label="runs"
              value={timings.runs_ms.map((r) => r.toFixed(1)).join(", ")}
              hint="Every kept repetition, in order."
            />
          )}
        </>
      )}
    </div>
  );
}
