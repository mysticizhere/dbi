import type { GradeResult } from "./api";

/**
 * Per-assertion grading results.
 *
 * Every row shows expected *and* observed. A red cross alone tells you nothing;
 * "expected <= 30,000 blocks | observed 199,803" tells you how far off you are
 * and in which direction.
 */
export default function GradePanel({
  grade,
  onHighlight,
}: {
  grade: GradeResult;
  onHighlight?: (nodeId: number) => void;
}) {
  if (grade.error) {
    return (
      <div className="p-4">
        <div className="rounded border border-red-900/60 bg-red-950/40 p-3 text-sm text-red-200">
          <div className="font-semibold">Could not grade this run</div>
          <div className="mt-1 text-red-200/80">{grade.error}</div>
        </div>
      </div>
    );
  }

  const passedCount = grade.results.filter((r) => r.passed).length;

  return (
    <div className="p-4">
      <div
        className={`mb-4 rounded border px-4 py-3 ${
          grade.passed
            ? "border-emerald-700/60 bg-emerald-950/30"
            : "border-slate-700 bg-slate-900/60"
        }`}
      >
        <div
          className={`text-sm font-semibold ${
            grade.passed ? "text-emerald-300" : "text-slate-300"
          }`}
        >
          {grade.passed ? "Passed" : "Not there yet"}
        </div>
        <div className="mt-0.5 text-xs text-slate-500">
          {passedCount} of {grade.results.length} assertions met
        </div>
      </div>

      <div className="space-y-2">
        {grade.results.map((r, i) => (
          <div
            key={i}
            className={`rounded border p-3 ${
              r.passed
                ? "border-emerald-900/50 bg-emerald-950/15"
                : "border-red-900/50 bg-red-950/15"
            }`}
          >
            <div className="flex items-start gap-2">
              <span
                className={`mt-0.5 shrink-0 font-mono text-xs font-bold ${
                  r.passed ? "text-emerald-400" : "text-red-400"
                }`}
              >
                {r.passed ? "PASS" : "FAIL"}
              </span>
              <div className="min-w-0 flex-1">
                <div className="text-xs font-medium text-slate-200">{r.description}</div>

                <div className="mt-1.5 grid grid-cols-[auto_1fr] gap-x-3 gap-y-0.5 text-[0.6875rem]">
                  <span className="text-slate-500">expected</span>
                  <span className="font-mono text-slate-300">{r.expected}</span>
                  <span className="text-slate-500">observed</span>
                  <span
                    className={`font-mono ${r.passed ? "text-emerald-300" : "text-red-300"}`}
                  >
                    {r.observed}
                  </span>
                </div>

                {r.because && (
                  <div className="mt-2 text-[0.6875rem] italic text-slate-500">{r.because}</div>
                )}
                {!r.passed && r.detail && (
                  <div className="mt-1.5 text-[0.6875rem] text-slate-400">{r.detail}</div>
                )}

                {r.node_ids.length > 0 && onHighlight && (
                  <div className="mt-2 flex flex-wrap gap-1">
                    {r.node_ids.slice(0, 6).map((id) => (
                      <button
                        key={id}
                        onClick={() => onHighlight(id)}
                        className="rounded border border-slate-700 px-1.5 py-0.5 text-[0.625rem] text-slate-400 hover:border-slate-500 hover:text-slate-200"
                        title="Show this node in the plan"
                      >
                        node {id}
                      </button>
                    ))}
                  </div>
                )}
              </div>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
