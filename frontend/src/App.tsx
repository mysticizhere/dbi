import { useState } from "react";
import HealthBar from "./components/HealthBar";
import WorkbenchView from "./components/WorkbenchView";
import ExerciseView from "./exercises/ExerciseView";

type Mode = "workbench" | "exercises";

const MODES: { id: Mode; label: string; hint: string }[] = [
  { id: "workbench", label: "Workbench", hint: "Run anything and read the plan." },
  { id: "exercises", label: "Exercises", hint: "Graded drills against the plan you produce." },
];

export default function App() {
  const [mode, setMode] = useState<Mode>("workbench");

  return (
    <div className="flex h-full flex-col gap-3 p-4">
      <header className="flex shrink-0 flex-wrap items-center justify-between gap-4">
        <div className="flex items-baseline gap-4">
          <h1 className="text-sm font-semibold tracking-tight text-slate-200">
            Postgres Performance Lab
          </h1>
          <div className="flex overflow-hidden rounded border border-slate-700">
            {MODES.map((m) => (
              <button
                key={m.id}
                title={m.hint}
                onClick={() => setMode(m.id)}
                className={`px-3 py-1 text-xs font-medium transition-colors ${
                  mode === m.id
                    ? "bg-slate-700 text-slate-100"
                    : "bg-slate-900 text-slate-500 hover:text-slate-300"
                }`}
              >
                {m.label}
              </button>
            ))}
          </div>
        </div>
        <HealthBar />
      </header>

      {/* Both views are mounted lazily rather than hidden, so switching modes
          does not keep a stale plan tree laying itself out off-screen. */}
      {mode === "workbench" ? <WorkbenchView /> : <ExerciseView />}
    </div>
  );
}
