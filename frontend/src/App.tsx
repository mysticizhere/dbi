import { useCallback, useState } from "react";
import { postDiscard, postPrewarm, postRun, type RunMode, type RunResponse } from "./api";
import SqlEditor from "./components/SqlEditor";
import OutputPanel from "./components/OutputPanel";
import MetricsBar from "./components/MetricsBar";
import HealthBar from "./components/HealthBar";

const STARTING_SQL = `-- city and pincode are 1:1 in this dataset, but the planner
-- assumes they are independent and multiplies the selectivities.
-- Switch the plan view to "Estimate error" to see it.

SELECT count(*) FROM events
WHERE city = 'Mumbai North' AND pincode = 400038;

-- Then try this instead: sandbox mode rolls the index back afterwards,
-- so the experiment is free.
--
--   CREATE INDEX idx_events_score ON events (score);
--   SELECT count(*) FROM events WHERE score < 5000;
`;

// Offered to the SQL editor for completion. Hand-maintained to match seed.py.
const SCHEMA: Record<string, string[]> = {
  events: [
    "id",
    "user_id",
    "score",
    "status",
    "city",
    "pincode",
    "email",
    "sku",
    "payload",
    "created_at",
  ],
};

const MODES: { id: RunMode; label: string; hint: string }[] = [
  { id: "execute", label: "Execute", hint: "Run it and show rows (capped)." },
  { id: "explain", label: "Explain", hint: "Plan only. Nothing is executed." },
  {
    id: "analyze",
    label: "Analyze",
    hint: "EXPLAIN (ANALYZE, BUFFERS, VERBOSE, SETTINGS). Actually runs the query.",
  },
];

export default function App() {
  const [sql, setSql] = useState(STARTING_SQL);
  const [mode, setMode] = useState<RunMode>("analyze");
  const [sandbox, setSandbox] = useState(true);
  const [repeat, setRepeat] = useState(5);
  const [timeoutMs, setTimeoutMs] = useState(30_000);
  const [response, setResponse] = useState<RunResponse | null>(null);
  const [pending, setPending] = useState(false);
  const [toast, setToast] = useState<string | null>(null);

  const run = useCallback(async () => {
    setPending(true);
    try {
      const r = await postRun({
        sql,
        mode,
        sandbox,
        statement_timeout_ms: timeoutMs,
        repeat,
        row_cap: 200,
        settings_overrides: {},
      });
      setResponse(r);
    } catch (e) {
      setToast(e instanceof Error ? e.message : String(e));
    } finally {
      setPending(false);
    }
  }, [sql, mode, sandbox, repeat, timeoutMs]);

  const maintenance = useCallback(async (action: "prewarm" | "discard") => {
    try {
      const r =
        action === "prewarm" ? await postPrewarm("events") : await postDiscard();
      setToast("blocks" in r ? `prewarmed ${r.blocks} blocks of events` : r.note);
    } catch (e) {
      setToast(e instanceof Error ? e.message : String(e));
    }
  }, []);

  return (
    <div className="flex h-full flex-col gap-3 p-4">
      <header className="flex shrink-0 flex-wrap items-center justify-between gap-4">
        <div className="flex items-baseline gap-3">
          <h1 className="text-sm font-semibold tracking-tight text-slate-200">
            Postgres Performance Lab
          </h1>
          <span className="text-xs text-slate-600">workbench</span>
        </div>
        <HealthBar />
      </header>

      <div className="flex shrink-0 flex-wrap items-center gap-3 rounded-lg border border-slate-800 bg-slate-900/50 px-3 py-2">
        <div className="flex overflow-hidden rounded border border-slate-700">
          {MODES.map((m) => (
            <button
              key={m.id}
              title={m.hint}
              onClick={() => setMode(m.id)}
              className={`px-3 py-1.5 text-xs font-medium transition-colors ${
                mode === m.id
                  ? "bg-sky-600 text-white"
                  : "bg-slate-900 text-slate-400 hover:text-slate-200"
              }`}
            >
              {m.label}
            </button>
          ))}
        </div>

        <label
          className="flex cursor-pointer items-center gap-2 text-xs text-slate-400"
          title="Wrap the run in BEGIN..ROLLBACK. Indexes created here vanish afterwards."
        >
          <input
            type="checkbox"
            checked={sandbox}
            onChange={(e) => setSandbox(e.target.checked)}
            className="accent-sky-500"
          />
          Sandbox
          {!sandbox && <span className="font-medium text-amber-400">changes persist</span>}
        </label>

        <label className="flex items-center gap-1.5 text-xs text-slate-400" title="Repetitions. The first is discarded and the median of the rest reported.">
          repeat
          <input
            type="number"
            min={1}
            max={50}
            value={repeat}
            onChange={(e) => setRepeat(Number(e.target.value))}
            className="w-14 rounded border border-slate-700 bg-slate-950 px-2 py-1 font-mono text-slate-200"
          />
        </label>

        <label className="flex items-center gap-1.5 text-xs text-slate-400">
          timeout
          <input
            type="number"
            min={100}
            step={1000}
            value={timeoutMs}
            onChange={(e) => setTimeoutMs(Number(e.target.value))}
            className="w-20 rounded border border-slate-700 bg-slate-950 px-2 py-1 font-mono text-slate-200"
          />
          <span className="text-slate-600">ms</span>
        </label>

        <div className="ml-auto flex items-center gap-2">
          <button
            onClick={() => void maintenance("prewarm")}
            title="pg_prewarm(events) -- pull the table into shared_buffers for a warm run."
            className="rounded border border-slate-700 px-2.5 py-1.5 text-xs text-slate-400 hover:text-slate-200"
          >
            Prewarm
          </button>
          <button
            onClick={() => void maintenance("discard")}
            title="DISCARD ALL. Clears session state only -- it cannot evict shared_buffers or the OS cache."
            className="rounded border border-slate-700 px-2.5 py-1.5 text-xs text-slate-400 hover:text-slate-200"
          >
            Discard
          </button>
          <button
            onClick={() => void run()}
            disabled={pending}
            className="rounded bg-sky-600 px-4 py-1.5 text-xs font-semibold text-white hover:bg-sky-500 disabled:opacity-50"
          >
            {pending ? "Running..." : "Run  ^Enter"}
          </button>
        </div>
      </div>

      <MetricsBar timings={response?.timings ?? null} buffers={response?.buffers ?? null} />

      {/* The plan tree needs the room more than the editor does. */}
      <main className="grid min-h-0 flex-1 grid-cols-[minmax(18.75rem,2fr)_3fr] gap-3">
        <SqlEditor value={sql} onChange={setSql} onRun={() => void run()} schema={SCHEMA} />
        <OutputPanel response={response} pending={pending} />
      </main>

      {toast && (
        <button
          onClick={() => setToast(null)}
          className="fixed bottom-4 right-4 max-w-md rounded border border-slate-700 bg-slate-900 px-4 py-2 text-left text-xs text-slate-300 shadow-lg"
        >
          {toast}
          <span className="ml-2 text-slate-600">(click to dismiss)</span>
        </button>
      )}
    </div>
  );
}
