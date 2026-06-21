"use client";

import { useState } from "react";
import { postTriage, type TriageResponse } from "../../lib/api";

const SAMPLES = [
  "My projector is making a weird noise",
  "Das ganze WLAN in Gebäude B ist ausgefallen",
  "Passwort vergessen, Konto gesperrt",
];

export default function TriageSimulator({
  onResult,
}: {
  onResult: (t: TriageResponse) => void;
}) {
  const [query, setQuery] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    const text = query.trim();
    if (!text) return;

    setLoading(true);
    setError(null);
    try {
      const result = await postTriage(text);
      onResult(result);
      setQuery("");
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm">
      <h2 className="mb-1 text-lg font-semibold text-slate-800">AI Triage Simulator</h2>
      <p className="mb-4 text-sm text-slate-500">
        Describe an IT issue. The local LangGraph + Ollama agent classifies it and
        suggests a grounded action.
      </p>

      <form onSubmit={submit} className="space-y-3">
        <textarea
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          rows={3}
          placeholder="e.g. My projector is making a weird noise"
          className="w-full resize-none rounded-lg border border-slate-300 p-3 text-sm focus:border-emerald-500 focus:outline-none focus:ring-1 focus:ring-emerald-500"
        />

        <div className="flex flex-wrap gap-2">
          {SAMPLES.map((s) => (
            <button
              key={s}
              type="button"
              onClick={() => setQuery(s)}
              className="rounded-full border border-slate-200 px-3 py-1 text-xs text-slate-500 hover:bg-slate-50"
            >
              {s.length > 34 ? s.slice(0, 34) + "…" : s}
            </button>
          ))}
        </div>

        <div className="flex items-center justify-between">
          {error ? (
            <span className="text-xs text-red-600">⚠ {error}</span>
          ) : (
            <span className="text-xs text-slate-400">Runs fully on-prem</span>
          )}
          <button
            type="submit"
            disabled={loading || !query.trim()}
            className="rounded-lg bg-emerald-600 px-4 py-2 text-sm font-medium text-white transition hover:bg-emerald-700 disabled:cursor-not-allowed disabled:opacity-50"
          >
            {loading ? "Triaging…" : "Triage ticket"}
          </button>
        </div>
      </form>
    </div>
  );
}
