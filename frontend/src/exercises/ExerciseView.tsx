import { useCallback, useEffect, useState } from "react";
import SqlEditor from "../components/SqlEditor";
import OutputPanel from "../components/OutputPanel";
import MetricsBar from "../components/MetricsBar";
import PromptPanel from "./PromptPanel";
import { LAB_SCHEMA } from "../schema";
import {
  getExercise,
  listExercises,
  runSetup,
  submitExercise,
  type Exercise,
  type ExerciseSummary,
  type SubmitResponse,
} from "./api";


export default function ExerciseView() {
  const [list, setList] = useState<ExerciseSummary[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [exercise, setExercise] = useState<Exercise | null>(null);
  const [sql, setSql] = useState("");
  const [sandbox, setSandbox] = useState(true);
  const [result, setResult] = useState<SubmitResponse | null>(null);
  const [busy, setBusy] = useState<null | "setup" | "submit">(null);
  const [toast, setToast] = useState<string | null>(null);
  const [showPrompt, setShowPrompt] = useState(true);

  const refreshList = useCallback(() => {
    listExercises()
      .then((found) => {
        setList(found);
        setSelectedId((current) => current ?? found[0]?.id ?? null);
      })
      .catch((e: unknown) => setToast(e instanceof Error ? e.message : String(e)));
  }, []);

  useEffect(refreshList, [refreshList]);

  useEffect(() => {
    if (!selectedId) return;
    getExercise(selectedId)
      .then((e) => {
        setExercise(e);
        setSql(e.starting_query);
        // Exercises whose fix needs VACUUM cannot run inside BEGIN..ROLLBACK.
        setSandbox(!e.requires_persist);
        setResult(null);
      })
      .catch((err: unknown) => setToast(err instanceof Error ? err.message : String(err)));
  }, [selectedId]);

  const doSetup = useCallback(async () => {
    if (!exercise) return;
    setBusy("setup");
    try {
      const r = await runSetup(exercise.id);
      setToast(
        r.ok
          ? `Playground prepared for "${exercise.title}" (${r.statements} statements).`
          : `Setup failed: ${r.error}`,
      );
    } catch (e) {
      setToast(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(null);
    }
  }, [exercise]);

  const doSubmit = useCallback(async () => {
    if (!exercise) return;
    setBusy("submit");
    try {
      const r = await submitExercise(exercise.id, {
        sql,
        sandbox,
        repeat: 3,
        statement_timeout_ms: 120_000,
      });
      setResult(r);
      refreshList();
    } catch (e) {
      setToast(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(null);
    }
  }, [exercise, sql, sandbox, refreshList]);

  return (
    <div className="flex min-h-0 flex-1 flex-col gap-3">
      {/* Toolbar */}
      <div className="flex shrink-0 flex-wrap items-center gap-3 rounded-lg border border-slate-800 bg-slate-900/50 px-3 py-2">
        <select
          value={selectedId ?? ""}
          onChange={(e) => setSelectedId(e.target.value)}
          className="max-w-md rounded border border-slate-700 bg-slate-950 px-2 py-1.5 text-xs text-slate-200"
        >
          {list.map((e) => (
            <option key={e.id} value={e.id}>
              {e.passed ? "✓ " : e.attempts > 0 ? "· " : "  "}
              {e.slug.split("-")[0]} — {e.title}
            </option>
          ))}
        </select>

        <button
          onClick={() => void doSetup()}
          disabled={busy !== null}
          title="Run this exercise's setup.sql against the playground. Do this before your first attempt, and again to start over."
          className="rounded border border-slate-700 px-2.5 py-1.5 text-xs text-slate-400 hover:text-slate-200 disabled:opacity-50"
        >
          {busy === "setup" ? "Preparing..." : "Prepare playground"}
        </button>

        <button
          onClick={() => exercise && setSql(exercise.starting_query)}
          className="rounded border border-slate-700 px-2.5 py-1.5 text-xs text-slate-400 hover:text-slate-200"
        >
          Reset query
        </button>

        <label
          className="flex cursor-pointer items-center gap-2 text-xs text-slate-400"
          title="Wrap the run in BEGIN..ROLLBACK so indexes vanish afterwards."
        >
          <input
            type="checkbox"
            checked={sandbox}
            onChange={(e) => setSandbox(e.target.checked)}
            className="accent-sky-500"
          />
          Sandbox
        </label>

        {exercise?.requires_persist && sandbox && (
          <span className="rounded border border-amber-800/60 bg-amber-950/40 px-2 py-1 text-[0.6875rem] text-amber-300">
            This one needs sandbox off
          </span>
        )}

        <button
          onClick={() => setShowPrompt((v) => !v)}
          className="rounded border border-slate-700 px-2.5 py-1.5 text-xs text-slate-400 hover:text-slate-200"
        >
          {showPrompt ? "Hide brief" : "Show brief"}
        </button>

        <button
          onClick={() => void doSubmit()}
          disabled={busy !== null || !exercise}
          className="ml-auto rounded bg-emerald-600 px-4 py-1.5 text-xs font-semibold text-white hover:bg-emerald-500 disabled:opacity-50"
        >
          {busy === "submit" ? "Grading..." : "Submit  ^Enter"}
        </button>
      </div>

      <MetricsBar
        timings={result?.run.timings ?? null}
        buffers={result?.run.buffers ?? null}
      />

      <main
        className={`grid min-h-0 flex-1 gap-3 ${
          showPrompt
            ? "grid-cols-[minmax(0,1fr)_minmax(0,1fr)_minmax(0,1.3fr)]"
            : "grid-cols-[minmax(0,1fr)_minmax(0,1.3fr)]"
        }`}
      >
        {showPrompt && exercise && <PromptPanel key={exercise.id} exercise={exercise} />}
        <SqlEditor value={sql} onChange={setSql} onRun={() => void doSubmit()} schema={LAB_SCHEMA} />
        <OutputPanel
          response={result?.run ?? null}
          grade={result?.grade ?? null}
          pending={busy === "submit"}
        />
      </main>

      {toast && (
        <button
          onClick={() => setToast(null)}
          className="fixed bottom-4 right-4 max-w-lg rounded border border-slate-700 bg-slate-900 px-4 py-2 text-left text-xs text-slate-300 shadow-lg"
        >
          {toast}
          <span className="ml-2 text-slate-600">(click to dismiss)</span>
        </button>
      )}
    </div>
  );
}
