import { useEffect, useState } from "react";
import { getHealth, type HealthResponse } from "../api";

/**
 * A compact readout of the server the numbers came from.
 *
 * Every measurement in this app is relative to shared_buffers, work_mem and
 * random_page_cost, so they are on screen permanently rather than buried in a
 * settings page.
 */
export default function HealthBar() {
  const [health, setHealth] = useState<HealthResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    getHealth()
      .then(setHealth)
      .catch((e: unknown) => setError(e instanceof Error ? e.message : String(e)));
  }, []);

  if (error) {
    return (
      <div className="rounded border border-red-900/60 bg-red-950/40 px-3 py-1.5 text-xs text-red-300">
        Backend unreachable: {error}
      </div>
    );
  }
  if (!health) return <div className="text-xs text-slate-600">checking...</div>;

  const version = health.server_version?.split(" ")[0] ?? "?";
  const keys = ["shared_buffers", "work_mem", "random_page_cost", "default_statistics_target"];

  return (
    <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-slate-500">
      <span className="font-medium text-emerald-400">PostgreSQL {version}</span>
      {keys.map((k) => (
        <span key={k} className="font-mono">
          {k}=<span className="text-slate-300">{health.settings[k] ?? "?"}</span>
        </span>
      ))}
      {health.missing_extensions.length > 0 && (
        <span className="text-amber-400">missing: {health.missing_extensions.join(", ")}</span>
      )}
    </div>
  );
}
