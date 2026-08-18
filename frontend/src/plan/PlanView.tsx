import { useMemo, useState } from "react";
import PlanTree from "./PlanTree";
import NodeDetail from "./NodeDetail";
import { COLOR_MODES, formatRatio, heat, SEVERITY_STYLE, type ColorMode } from "./colors";
import { flatten, type AnalyzedPlan } from "./types";

export default function PlanView({ plan }: { plan: AnalyzedPlan }) {
  const [mode, setMode] = useState<ColorMode>("self_time");
  const [selectedId, setSelectedId] = useState<number | null>(null);

  const nodes = useMemo(() => flatten(plan.root), [plan]);
  const byId = useMemo(() => new Map(nodes.map((n) => [n.id, n])), [nodes]);
  const selected = selectedId == null ? null : (byId.get(selectedId) ?? null);
  const s = plan.summary;

  return (
    <div className="flex h-full flex-col">
      {/* Summary strip */}
      <div className="flex shrink-0 flex-wrap items-center gap-x-5 gap-y-2 border-b border-slate-800 px-3 py-2 text-xs">
        <div className="flex overflow-hidden rounded border border-slate-700">
          {COLOR_MODES.map((m) => (
            <button
              key={m.id}
              title={m.hint}
              onClick={() => setMode(m.id)}
              className={`px-2.5 py-1 text-[0.6875rem] font-medium transition-colors ${
                mode === m.id
                  ? "bg-slate-700 text-slate-100"
                  : "bg-slate-900 text-slate-500 hover:text-slate-300"
              }`}
            >
              {m.label}
            </button>
          ))}
        </div>

        <Legend mode={mode} nodes={nodes} analyzed={s.analyzed} />

        {/* Timings and buffer totals live in the metrics bar above -- repeating
            them here cost a whole wrapped row of vertical space that the tree
            needs more. Only what is specific to the plan stays. */}
        <div className="ml-auto flex flex-wrap items-center gap-x-4 gap-y-1 text-slate-500">
          <span>
            {s.node_count} nodes{s.parallel && " · parallel"}
          </span>
          {s.slowest_node != null && (
            <button
              onClick={() => setSelectedId(s.slowest_node)}
              className="rounded border border-slate-700 px-2 py-0.5 hover:border-slate-500 hover:text-slate-300"
              title="Jump to the node with the highest self time."
            >
              slowest node
            </button>
          )}
          {s.max_estimate_error != null && s.max_estimate_error >= 2 && (
            <button
              onClick={() => setSelectedId(s.max_estimate_error_node)}
              className="rounded border border-red-800/60 bg-red-950/40 px-2 py-0.5 font-mono text-red-300 hover:border-red-600"
              title="Jump to the node with the worst row estimate."
            >
              worst estimate {formatRatio(s.max_estimate_error)}
            </button>
          )}
        </div>
      </div>

      {/* Warning strip */}
      {plan.warnings.length > 0 && (
        <div className="flex shrink-0 flex-wrap gap-1.5 border-b border-slate-800 px-3 py-2">
          {plan.warnings.map((w, i) => (
            <button
              key={i}
              onClick={() => setSelectedId(w.node_id)}
              title={w.detail}
              className={`rounded border px-2 py-0.5 text-[0.625rem] font-medium transition-opacity hover:opacity-80 ${SEVERITY_STYLE[w.severity]}`}
            >
              {w.label}
              <span className="ml-1.5 opacity-50">node {w.node_id}</span>
            </button>
          ))}
        </div>
      )}

      <div className="flex min-h-0 flex-1">
        <div className="min-w-0 flex-1">
          <PlanTree
            root={plan.root}
            mode={mode}
            analyzed={s.analyzed}
            selectedId={selectedId}
            onSelect={setSelectedId}
          />
        </div>
        <div className="w-80 shrink-0 border-l border-slate-800 bg-slate-900/40">
          <NodeDetail node={selected} />
        </div>
      </div>
    </div>
  );
}

function Legend({
  mode,
  nodes,
  analyzed,
}: {
  mode: ColorMode;
  nodes: ReturnType<typeof flatten>;
  analyzed: boolean;
}) {
  const labels =
    mode === "estimate_error"
      ? ["1x", "10x", "100x", "1000x+"]
      : mode === "buffers"
        ? ["0", "", "", "peak"]
        : ["0%", "", "", "100%"];

  if (!analyzed && mode !== "estimate_error") {
    return <span className="text-slate-600">no actuals — Analyze mode required</span>;
  }
  void nodes;

  return (
    <div className="flex items-center gap-1.5">
      <div className="flex overflow-hidden rounded">
        {[0, 0.2, 0.4, 0.6, 0.8, 1].map((t) => (
          <div key={t} className="h-3 w-5" style={{ background: heat(t) }} />
        ))}
      </div>
      <div className="flex gap-2 text-[0.625rem] text-slate-600">
        {labels.filter(Boolean).map((l) => (
          <span key={l}>{l}</span>
        ))}
      </div>
    </div>
  );
}
