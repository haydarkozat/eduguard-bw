// EduGuard BW — IT Dashboard (App Router).
// Layout: fixed sidebar + scrollable main content area.

import Sidebar from "./components/Sidebar";
import NetworkPulse from "./components/NetworkPulse";
import NetworkTrendChart from "./components/NetworkTrendChart";
import TriageSection from "./components/TriageSection";
import SecurityEvents from "./components/SecurityEvents";

export default function DashboardPage() {
  return (
    <div className="flex min-h-screen bg-slate-100 text-slate-900">
      <Sidebar />

      <main className="flex-1 overflow-y-auto">
        <header className="sticky top-0 z-10 border-b border-slate-200 bg-white/80 px-6 py-4 backdrop-blur">
          <div className="flex items-center justify-between">
            <div>
              <h1 className="text-xl font-bold text-slate-900">IT Operations Dashboard</h1>
              <p className="text-sm text-slate-500">
                Network monitoring &amp; AI ticket triage — Baden-Württemberg schools
              </p>
            </div>
            <span className="rounded-full bg-emerald-100 px-3 py-1 text-xs font-medium text-emerald-700">
              ● Self-hosted
            </span>
          </div>
        </header>

        <div className="mx-auto max-w-6xl px-6 py-8">
          <NetworkPulse />
          <NetworkTrendChart />
          <TriageSection />
          <SecurityEvents />
        </div>
      </main>
    </div>
  );
}
