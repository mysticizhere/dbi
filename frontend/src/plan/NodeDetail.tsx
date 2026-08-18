import type { PlanNode } from "./types";
import { totalBlocks } from "./types";
import { formatCount, formatMs, formatRatio, SEVERITY_STYLE } from "./colors";

function Row({ label, value, hint }: { label: string; value: React.ReactNode; hint?: string }) {
  return (
    <div className="flex items-baseline justify-between gap-3 py-1" title={hint}>
      <span className="shrink-0 text-[0.6875rem] text-slate-500">{label}</span>
      <span className="text-right font-mono text-xs text-slate-200">{value}</span>
    </div>
  );
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="border-t border-slate-800 px-4 py-3 first:border-t-0">
      <div className="mb-1.5 text-[0.625rem] font-semibold uppercase tracking-wider text-slate-600">
        {title}
      </div>
      {children}
    </div>
  );
}

export default function NodeDetail({ node }: { node: PlanNode | null }) {
  if (!node) {
    return (
      <div className="flex h-full items-center justify-center px-6 text-center text-xs text-slate-600">
        Select a node to inspect it.
      </div>
    );
  }

  const t = node.timing;
  const m = node.metrics;
  const selfBlocks = totalBlocks(node.self_buffers);

  return (
    <div className="h-full overflow-auto">
      <div className="px-4 py-3">
        <div className="text-sm font-semibold text-slate-100">{node.node_type}</div>
        <div className="mt-0.5 font-mono text-[0.6875rem] text-slate-500">
          {node.index_name
            ? `using ${node.index_name}${node.relation ? ` on ${node.relation}` : ""}`
            : (node.relation ?? node.subplan_name ?? node.cte_name ?? "")}
          {node.alias && node.alias !== node.relation && ` (${node.alias})`}
        </div>
        {node.parent_relationship && (
          <div className="mt-1 text-[0.625rem] text-slate-600">
            {node.parent_relationship}
            {node.join_type && ` · ${node.join_type} join`}
            {node.parallel_aware && " · parallel aware"}
          </div>
        )}
      </div>

      {node.warnings.length > 0 && (
        <Section title="Warnings">
          <div className="space-y-2">
            {node.warnings.map((w, i) => (
              <div
                key={i}
                className={`rounded border px-2.5 py-2 text-[0.6875rem] ${SEVERITY_STYLE[w.severity]}`}
              >
                <div className="font-semibold">{w.label}</div>
                <div className="mt-0.5 opacity-80">{w.detail}</div>
              </div>
            ))}
          </div>
        </Section>
      )}

      <Section title="Rows">
        <Row label="estimated" value={formatCount(node.rows.planned)} />
        <Row label="actual (per loop)" value={formatCount(node.rows.actual)} />
        {t && t.loops > 1 && (
          <Row
            label="actual (total)"
            value={formatCount(node.rows.total_actual)}
            hint="actual x loops"
          />
        )}
        <Row
          label="estimate error"
          value={
            <span
              className={
                (node.rows.error_ratio ?? 1) >= 10 ? "text-red-300" : "text-slate-200"
              }
            >
              {formatRatio(node.rows.error_ratio)} {node.rows.direction ?? ""}
            </span>
          }
          hint="max(actual/estimated, estimated/actual)"
        />
      </Section>

      {t && (
        <Section title="Timing">
          <Row
            label="self"
            value={`${t.self_ms == null ? "-" : formatMs(t.self_ms)}${
              t.self_fraction == null ? "" : `  (${(t.self_fraction * 100).toFixed(1)}%)`
            }`}
            hint="This node alone, children excluded."
          />
          <Row label="per loop" value={t.per_loop_ms == null ? "-" : formatMs(t.per_loop_ms)} />
          <Row label="loops" value={t.loops.toLocaleString()} />
          <Row
            label="total (work)"
            value={t.total_ms == null ? "-" : formatMs(t.total_ms)}
            hint="per-loop time x loops -- CPU work across all loops and workers"
          />
          {t.parallel_divisor > 1 && (
            <Row
              label="elapsed (wall)"
              value={t.elapsed_ms == null ? "-" : formatMs(t.elapsed_ms)}
              hint={`${t.parallel_divisor} processes ran this concurrently, so wall time is total/${t.parallel_divisor}.`}
            />
          )}
          <Row label="startup" value={t.startup_ms == null ? "-" : formatMs(t.startup_ms)} />
        </Section>
      )}

      <Section title="Buffers">
        <Row
          label="self hit / read"
          value={`${formatCount(node.self_buffers.shared_hit)} / ${formatCount(node.self_buffers.shared_read)}`}
          hint="Blocks touched by this node alone -- children subtracted out."
        />
        <Row label="self total" value={`${formatCount(selfBlocks)} blk`} />
        <Row
          label="cumulative"
          value={`${formatCount(node.buffers.shared_hit)} / ${formatCount(node.buffers.shared_read)}`}
          hint="Including every child, as Postgres reports it."
        />
        {node.self_buffers.temp_written > 0 && (
          <Row
            label="temp written"
            value={formatCount(node.self_buffers.temp_written)}
            hint="Spilled to disk."
          />
        )}
      </Section>

      {Object.keys(node.conditions).length > 0 && (
        <Section title="Conditions">
          <div className="space-y-1.5">
            {Object.entries(node.conditions).map(([k, v]) => (
              <div key={k}>
                <div className="text-[0.625rem] text-slate-500">{k}</div>
                <div className="break-all font-mono text-[0.6875rem] text-slate-300">{v}</div>
              </div>
            ))}
          </div>
        </Section>
      )}

      {Object.keys(m).length > 0 && (
        <Section title="Metrics">
          {Object.entries(m).map(([k, v]) => (
            <Row key={k} label={k.replace(/_/g, " ")} value={String(v)} />
          ))}
        </Section>
      )}

      <Section title="Cost (planner estimate)">
        <Row label="startup .. total" value={`${node.cost.startup ?? "-"} .. ${node.cost.total ?? "-"}`} />
        <Row label="width" value={node.cost.width == null ? "-" : `${node.cost.width} bytes`} />
        {node.workers_launched != null && (
          <Row
            label="workers"
            value={`${node.workers_launched} launched / ${node.workers_planned ?? "?"} planned`}
          />
        )}
      </Section>

      {node.output.length > 0 && (
        <Section title="Output">
          <div className="break-all font-mono text-[0.6875rem] text-slate-400">
            {node.output.join(", ")}
          </div>
        </Section>
      )}
    </div>
  );
}
