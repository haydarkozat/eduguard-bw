"use client";

import { useEffect, useRef, useState } from "react";
import {
  getNetworkStatus,
  getScan,
  postScan,
  type SubnetStatus,
} from "../../lib/api";

const POLL_MS = 10_000;

// Card theme driven by subnet health / anomalies.
function cardTheme(s: SubnetStatus) {
  const hasHigh = s.anomalies.some((a) => a.severity === "high");
  if (s.health === "critical" || hasHigh) {
    return { ring: "border-red-300 bg-red-50", dot: "bg-red-500", label: "text-red-700" };
  }
  if (s.health === "degraded" || s.alerts > 0) {
    return { ring: "border-amber-300 bg-amber-50", dot: "bg-amber-500", label: "text-amber-700" };
  }
  return { ring: "border-emerald-300 bg-emerald-50", dot: "bg-emerald-500", label: "text-emerald-700" };
}

export default function NetworkPulse() {
  const [subnets, setSubnets] = useState<SubnetStatus[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [updatedAt, setUpdatedAt] = useState<string>("");
  const [scanning, setScanning] = useState(false);
  const mounted = useRef(true);

  async function load() {
    try {
      const data = await getNetworkStatus();
      if (!mounted.current) return;
      setSubnets(data);
      setError(null);
      setUpdatedAt(new Date().toLocaleTimeString());
    } catch (e) {
      if (mounted.current) setError((e as Error).message);
    }
  }

  useEffect(() => {
    mounted.current = true;
    load();
    const id = setInterval(load, POLL_MS);
    return () => {
      mounted.current = false;
      clearInterval(id);
    };
  }, []);

  // Trigger a sweep, poll the job until it finishes, then refresh the cards.
  async function runScan() {
    setScanning(true);
    setError(null);
    try {
      const job = await postScan("all");
      for (let i = 0; i < 20; i++) {
        const current = await getScan(job.scan_id);
        if (current.status !== "running") break;
        await new Promise((r) => setTimeout(r, 1500));
      }
      await load();
    } catch (e) {
      if (mounted.current) setError((e as Error).message);
    } finally {
      if (mounted.current) setScanning(false);
    }
  }

  return (
    <section className="mb-8">
      <div className="mb-3 flex items-center justify-between">
        <h2 className="text-lg font-semibold text-slate-800">Network Pulse</h2>
        <div className="flex items-center gap-3">
          <span className="text-xs text-slate-400">
            {error
              ? `⚠ ${error}`
              : updatedAt
                ? `Updated ${updatedAt} · auto-refresh 10s`
                : "Loading…"}
          </span>
          <button
            onClick={runScan}
            disabled={scanning}
            className="rounded-lg bg-slate-800 px-3 py-1.5 text-xs font-medium text-white transition hover:bg-slate-700 disabled:cursor-not-allowed disabled:opacity-50"
          >
            {scanning ? "Scanning…" : "▶ Run scan"}
          </button>
        </div>
      </div>

      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
        {subnets.map((s) => {
          const t = cardTheme(s);
          return (
            <article key={s.name} className={`rounded-xl border p-5 shadow-sm ${t.ring}`}>
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-2">
                  <span className={`h-2.5 w-2.5 rounded-full ${t.dot}`} />
                  <h3 className="font-semibold text-slate-800">{s.name}</h3>
                </div>
                <span className={`text-xs font-medium uppercase ${t.label}`}>{s.health}</span>
              </div>
              <p className="mt-1 text-xs text-slate-400">{s.cidr}</p>

              <div className="mt-4 flex items-center justify-between text-sm">
                <div>
                  <p className="text-2xl font-bold text-slate-800">{s.devices_online}</p>
                  <p className="text-xs text-slate-400">devices online</p>
                </div>
                <div className="text-right">
                  <p className={`text-2xl font-bold ${s.alerts > 0 ? t.label : "text-slate-800"}`}>
                    {s.alerts}
                  </p>
                  <p className="text-xs text-slate-400">alerts</p>
                </div>
              </div>

              {s.anomalies.length > 0 && (
                <ul className="mt-4 space-y-1 border-t border-white/60 pt-3 text-xs text-slate-600">
                  {s.anomalies.slice(0, 2).map((a, i) => (
                    <li key={i} className="truncate" title={a.detail}>
                      <span className="font-medium">{a.kind}</span> @ {a.host}
                    </li>
                  ))}
                </ul>
              )}
            </article>
          );
        })}

        {subnets.length === 0 && !error && (
          <p className="text-sm text-slate-400">Waiting for subnet data…</p>
        )}
      </div>
    </section>
  );
}
