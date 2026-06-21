"use client";

import { useEffect, useRef, useState } from "react";
import {
  Area,
  AreaChart,
  CartesianGrid,
  Legend,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { getNetworkHistory, type NetworkHistoryPoint } from "../../lib/api";

const POLL_MS = 15_000;

type Row = NetworkHistoryPoint & { label: string };

function toLabel(ts: string): string {
  try {
    return new Date(ts).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
  } catch {
    return ts;
  }
}

export default function NetworkTrendChart() {
  const [data, setData] = useState<Row[]>([]);
  const [error, setError] = useState<string | null>(null);
  const mounted = useRef(true);

  useEffect(() => {
    mounted.current = true;

    async function load() {
      try {
        const points = await getNetworkHistory(24);
        if (!mounted.current) return;
        setData(points.map((p) => ({ ...p, label: toLabel(p.timestamp) })));
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

  return (
    <section className="mb-8">
      <div className="mb-3 flex items-center justify-between">
        <div>
          <h2 className="text-lg font-semibold text-slate-800">Anomaly Trend (24h)</h2>
          <p className="text-xs text-slate-400">
            Subnet health per sweep, from network_logs · auto-refresh 15s
          </p>
        </div>
        {error && <span className="text-xs text-red-500">⚠ {error}</span>}
      </div>

      <div className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
        {data.length === 0 ? (
          <p className="py-16 text-center text-sm text-slate-400">
            No scan history yet — run a scan in Network Pulse to build the timeline.
          </p>
        ) : (
          <div className="h-72 w-full">
            <ResponsiveContainer width="100%" height="100%">
              <AreaChart data={data} margin={{ top: 10, right: 12, left: -12, bottom: 0 }}>
                <defs>
                  <linearGradient id="gOk" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="5%" stopColor="#10b981" stopOpacity={0.7} />
                    <stop offset="95%" stopColor="#10b981" stopOpacity={0.05} />
                  </linearGradient>
                  <linearGradient id="gDeg" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="5%" stopColor="#f59e0b" stopOpacity={0.7} />
                    <stop offset="95%" stopColor="#f59e0b" stopOpacity={0.05} />
                  </linearGradient>
                  <linearGradient id="gCrit" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="5%" stopColor="#ef4444" stopOpacity={0.8} />
                    <stop offset="95%" stopColor="#ef4444" stopOpacity={0.05} />
                  </linearGradient>
                </defs>
                <CartesianGrid strokeDasharray="3 3" stroke="#f1f5f9" />
                <XAxis dataKey="label" tick={{ fontSize: 11, fill: "#94a3b8" }} />
                <YAxis allowDecimals={false} tick={{ fontSize: 11, fill: "#94a3b8" }} />
                <Tooltip
                  contentStyle={{ borderRadius: 8, border: "1px solid #e2e8f0", fontSize: 12 }}
                />
                <Legend wrapperStyle={{ fontSize: 12 }} />
                <Area
                  type="monotone"
                  isAnimationActive={false}
                  dataKey="critical"
                  name="Critical"
                  stackId="1"
                  stroke="#ef4444"
                  fill="url(#gCrit)"
                />
                <Area
                  type="monotone"
                  isAnimationActive={false}
                  dataKey="degraded"
                  name="Degraded"
                  stackId="1"
                  stroke="#f59e0b"
                  fill="url(#gDeg)"
                />
                <Area
                  type="monotone"
                  isAnimationActive={false}
                  dataKey="ok"
                  name="OK"
                  stackId="1"
                  stroke="#10b981"
                  fill="url(#gOk)"
                />
              </AreaChart>
            </ResponsiveContainer>
          </div>
        )}
      </div>
    </section>
  );
}
