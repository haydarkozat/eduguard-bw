"use client";

import { useEffect, useRef, useState } from "react";
import { getSecurityEvents, type SecurityEvent } from "../../lib/api";

const POLL_MS = 10_000;

const severityBadge: Record<string, string> = {
  high: "bg-red-100 text-red-700 ring-red-200",
  medium: "bg-amber-100 text-amber-700 ring-amber-200",
  low: "bg-slate-100 text-slate-600 ring-slate-200",
};

function fmtTime(ts: string | null) {
  if (!ts) return "";
  try {
    return new Date(ts).toLocaleString();
  } catch {
    return ts;
  }
}

export default function SecurityEvents() {
  const [events, setEvents] = useState<SecurityEvent[]>([]);
  const [error, setError] = useState<string | null>(null);
  const mounted = useRef(true);

  useEffect(() => {
    mounted.current = true;

    async function load() {
      try {
        const data = await getSecurityEvents(50);
        if (!mounted.current) return;
        setEvents(data);
        setError(null);
      } catch (e) {
        if (mounted.current) setError((e as Error).message);
      }
    }

    load();
    const id = setInterval(load, POLL_MS);
    return () => {
      mounted.current = false;
      clearInterval(id);
    };
  }, []);

  const highCount = events.filter((e) => e.severity === "high").length;

  return (
    <section className="mt-8">
      <div className="mb-3 flex items-center justify-between">
        <h2 className="text-lg font-semibold text-slate-800">Security Events</h2>
        <span className="text-xs text-slate-400">
          {error
            ? `⚠ ${error}`
            : `${events.length} event${events.length === 1 ? "" : "s"}${
                highCount ? ` · ${highCount} high` : ""
              } · auto-refresh 10s`}
        </span>
      </div>

      <div className="overflow-hidden rounded-xl border border-slate-200 bg-white shadow-sm">
        {events.length === 0 ? (
          <p className="px-5 py-8 text-center text-sm text-slate-400">
            No security events yet — run a scan in Network Pulse to populate.
          </p>
        ) : (
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-slate-100 text-left text-xs uppercase text-slate-400">
                <th className="px-4 py-2.5 font-medium">Severity</th>
                <th className="px-4 py-2.5 font-medium">Subnet</th>
                <th className="px-4 py-2.5 font-medium">Host</th>
                <th className="px-4 py-2.5 font-medium">Kind</th>
                <th className="px-4 py-2.5 font-medium">Detail</th>
                <th className="px-4 py-2.5 font-medium">Time</th>
              </tr>
            </thead>
            <tbody>
              {events.map((e) => (
                <tr key={e.id} className="border-b border-slate-50 last:border-0">
                  <td className="px-4 py-2.5">
                    <span
                      className={`rounded-full px-2 py-0.5 text-xs font-semibold uppercase ring-1 ${
                        severityBadge[e.severity ?? "low"] ?? severityBadge.low
                      }`}
                    >
                      {e.severity}
                    </span>
                  </td>
                  <td className="px-4 py-2.5 font-medium text-slate-700">{e.subnet}</td>
                  <td className="px-4 py-2.5 font-mono text-xs text-slate-500">{e.host}</td>
                  <td className="px-4 py-2.5 text-slate-600">{e.kind}</td>
                  <td className="px-4 py-2.5 text-slate-500">{e.detail}</td>
                  <td className="whitespace-nowrap px-4 py-2.5 text-xs text-slate-400">
                    {fmtTime(e.timestamp)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </section>
  );
}
