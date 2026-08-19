import { useState } from "react";
import Markdown from "./Markdown";
import type { Exercise } from "./api";

type Tab = "prompt" | "hints" | "notes";

/**
 * The exercise brief.
 *
 * Hints reveal one at a time on purpose: the whole point is to sit with the plan
 * for a minute first, and a wall of hints removes that.
 */
export default function PromptPanel({ exercise }: { exercise: Exercise }) {
  const [tab, setTab] = useState<Tab>("prompt");
  const [revealed, setRevealed] = useState(0);

  const tabs: { id: Tab; label: string; badge?: string }[] = [
    { id: "prompt", label: "Brief" },
    { id: "hints", label: "Hints", badge: `${revealed}/${exercise.hints.length}` },
    { id: "notes", label: "Notes" },
  ];

  return (
    <div className="flex h-full flex-col overflow-hidden rounded-lg border border-slate-800 bg-slate-900/30">
      <div className="flex shrink-0 items-center gap-1 border-b border-slate-800 px-2">
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
            {t.badge && <span className="ml-1.5 text-[0.625rem] text-slate-600">{t.badge}</span>}
          </button>
        ))}
        <div className="ml-auto flex items-center gap-2 pr-1 text-[0.625rem] text-slate-600">
          <span>layer {exercise.layer}</span>
          <span>difficulty {exercise.difficulty}/5</span>
          {exercise.requires_persist && (
            <span className="rounded border border-amber-800/60 bg-amber-950/40 px-1.5 py-0.5 text-amber-300">
              sandbox off
            </span>
          )}
        </div>
      </div>

      <div className="min-h-0 flex-1 overflow-auto px-4 py-3">
        {tab === "prompt" && <Markdown source={exercise.prompt} />}

        {tab === "hints" && (
          <div className="space-y-3">
            {exercise.hints.slice(0, revealed).map((h, i) => (
              <div key={i} className="rounded border border-slate-800 bg-slate-900/60 p-3">
                <div className="mb-1 text-[0.625rem] uppercase tracking-wider text-slate-600">
                  hint {i + 1}
                </div>
                <div className="text-sm text-slate-300">{h}</div>
              </div>
            ))}
            {revealed < exercise.hints.length ? (
              <button
                onClick={() => setRevealed((n) => n + 1)}
                className="rounded border border-slate-700 px-3 py-1.5 text-xs text-slate-400 hover:border-slate-500 hover:text-slate-200"
              >
                Reveal hint {revealed + 1} of {exercise.hints.length}
              </button>
            ) : (
              <div className="text-xs text-slate-600">
                {exercise.hints.length === 0 ? "No hints for this one." : "That is all of them."}
              </div>
            )}
          </div>
        )}

        {tab === "notes" && (
          <>
            <div className="mb-3 rounded border border-slate-800 bg-slate-900/60 px-3 py-2 text-[0.6875rem] text-slate-500">
              These notes explain the answer. Worth reading after you have solved it —
              or when you are properly stuck.
            </div>
            <Markdown source={exercise.notes_md} />
          </>
        )}
      </div>
    </div>
  );
}
