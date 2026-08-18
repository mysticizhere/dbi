import { useState } from "react";
import type { RunResponse } from "../api";
import PlanView from "../plan/PlanView";

type Tab = "plan" | "json" | "rows" | "messages";

function ResultTable({ result }: { result: NonNullable<RunResponse["result"]> }) {
  if (result.columns.length === 0) {
    return (
      <div className="p-4 text-sm text-slate-400">
        No result set. {result.row_count > 0 && `${result.row_count} row(s) affected.`}
      </div>
    );
  }
  return (
    <div className="overflow-auto">
      <table className="w-full border-collapse text-left font-mono text-xs">
        <thead className="sticky top-0 bg-slate-900">
          <tr>
            {result.columns.map((c) => (
              <th
                key={c}
                className="border-b border-slate-700 px-3 py-2 font-semibold text-slate-300"
              >
                {c}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {result.rows.map((row, i) => (
            <tr key={i} className="odd:bg-slate-900/40">
              {row.map((cell, j) => (
                <td key={j} className="border-b border-slate-800/60 px-3 py-1.5 text-slate-300">
                  {cell === null ? <span className="italic text-slate-600">null</span> : String(cell)}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
      {result.truncated && (
        <div className="px-3 py-2 text-xs text-amber-400/80">
          Truncated at {result.row_count} rows. The workbench caps results on purpose -- it is
          for experiments, not for browsing data.
        </div>
      )}
    </div>
  );
}

export default function OutputPanel({
  response,
  pending,
}: {
  response: RunResponse | null;
  pending: boolean;
}) {
  const [tab, setTab] = useState<Tab>("plan");

  if (pending) {
    return (
      <div className="flex h-full items-center justify-center text-sm text-slate-500">
        Running...
      </div>
    );
  }
  if (!response) {
    return (
      <div className="flex h-full items-center justify-center px-8 text-center text-sm text-slate-600">
        Write a query and press <kbd className="mx-1 rounded bg-slate-800 px-1.5 py-0.5">Ctrl</kbd>
        +<kbd className="mx-1 rounded bg-slate-800 px-1.5 py-0.5">Enter</kbd>.
      </div>
    );
  }

  const messageCount =
    response.notices.length + response.warnings.length + (response.error ? 1 : 0);

  const tabs: { id: Tab; label: string; badge?: number }[] = [
    { id: "plan", label: "Plan", badge: response.analyzed_plan?.warnings.length || undefined },
    { id: "json", label: "JSON" },
    { id: "rows", label: "Rows", badge: response.result?.row_count },
    { id: "messages", label: "Messages", badge: messageCount || undefined },
  ];

  return (
    <div className="flex h-full flex-col overflow-hidden rounded-lg border border-slate-800">
      <div className="flex shrink-0 gap-1 border-b border-slate-800 bg-slate-900/60 px-2">
        {tabs.map((t) => (
          <button
            key={t.id}
            onClick={() => setTab(t.id)}
            className={`px-3 py-2 text-xs font-medium transition-colors ${
              tab === t.id
                ? "border-b-2 border-sky-400 text-sky-300"
                : "border-b-2 border-transparent text-slate-500 hover:text-slate-300"
            }`}
          >
            {t.label}
            {t.badge != null && (
              <span className="ml-1.5 rounded bg-slate-800 px-1.5 py-0.5 text-[0.625rem] text-slate-400">
                {t.badge}
              </span>
            )}
          </button>
        ))}
      </div>

      <div className={`min-h-0 flex-1 ${tab === "plan" ? "overflow-hidden" : "overflow-auto"}`}>
        {tab === "plan" &&
          (response.analyzed_plan ? (
            <PlanView plan={response.analyzed_plan} />
          ) : (
            <div className="p-4 text-sm text-slate-500">
              No plan. Run in Explain or Analyze mode to get one.
            </div>
          ))}

        {tab === "json" &&
          (response.plan ? (
            <pre className="p-4 font-mono text-xs leading-relaxed text-slate-300">
              {JSON.stringify(response.plan, null, 2)}
            </pre>
          ) : (
            <div className="p-4 text-sm text-slate-500">
              No plan. Run in Explain or Analyze mode to get one.
            </div>
          ))}

        {tab === "rows" &&
          (response.result ? (
            <ResultTable result={response.result} />
          ) : (
            <div className="p-4 text-sm text-slate-500">
              No rows. Explain and Analyze modes return a plan, not a result set.
            </div>
          ))}

        {tab === "messages" && (
          <div className="space-y-3 p-4 text-xs">
            {response.error && (
              <div className="rounded border border-red-900/60 bg-red-950/40 p-3">
                <div className="font-mono font-semibold text-red-300">
                  {response.error.sqlstate && `[${response.error.sqlstate}] `}
                  {response.error.message}
                </div>
                {response.error.detail && (
                  <div className="mt-1 text-red-200/70">{response.error.detail}</div>
                )}
                {response.error.hint && (
                  <div className="mt-1 text-red-200/70">Hint: {response.error.hint}</div>
                )}
                {response.error.position != null && (
                  <div className="mt-1 text-red-200/50">
                    at character {response.error.position}
                    {response.error.statement_index != null &&
                      ` of statement ${response.error.statement_index + 1}`}
                  </div>
                )}
              </div>
            )}
            {response.warnings.map((w, i) => (
              <div
                key={i}
                className="rounded border border-amber-900/50 bg-amber-950/20 p-3 text-amber-200/80"
              >
                {w}
              </div>
            ))}
            {response.notices.map((n, i) => (
              <div key={i} className="rounded border border-slate-800 p-3 font-mono text-slate-400">
                {n}
              </div>
            ))}
            {response.statements.length > 1 && (
              <div className="rounded border border-slate-800 p-3">
                <div className="mb-2 font-semibold text-slate-400">Statements</div>
                {response.statements.map((s) => (
                  <div key={s.index} className="flex gap-3 py-0.5 font-mono text-slate-500">
                    <span className={s.is_target ? "text-sky-400" : ""}>
                      {s.is_target ? "target" : `setup `}
                    </span>
                    <span className="flex-1 truncate">{s.sql}</span>
                    <span>{s.duration_ms == null ? "" : `${s.duration_ms.toFixed(1)} ms`}</span>
                  </div>
                ))}
              </div>
            )}
            {messageCount === 0 && response.statements.length <= 1 && (
              <div className="text-slate-600">Nothing to report.</div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
