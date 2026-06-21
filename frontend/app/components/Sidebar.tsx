// Static navigation sidebar (visual only for the prototype).

const NAV = [
  { label: "Dashboard", icon: "▦", active: true },
  { label: "Network", icon: "🌐", active: false },
  { label: "Tickets", icon: "🎫", active: false },
  { label: "Knowledge Base", icon: "📚", active: false },
  { label: "Settings", icon: "⚙️", active: false },
];

export default function Sidebar() {
  return (
    <aside className="hidden w-64 shrink-0 flex-col bg-slate-900 p-5 text-slate-300 md:flex">
      <div className="mb-8 flex items-center gap-2">
        <span className="flex h-9 w-9 items-center justify-center rounded-lg bg-emerald-500 font-bold text-white">
          E
        </span>
        <div>
          <p className="font-semibold text-white">EduGuard BW</p>
          <p className="text-xs text-slate-400">Self-hosted SOC</p>
        </div>
      </div>

      <nav className="flex flex-col gap-1">
        {NAV.map((item) => (
          <a
            key={item.label}
            className={`flex items-center gap-3 rounded-lg px-3 py-2 text-sm transition ${
              item.active
                ? "bg-slate-800 font-medium text-white"
                : "text-slate-400 hover:bg-slate-800/60 hover:text-white"
            }`}
          >
            <span aria-hidden>{item.icon}</span>
            {item.label}
          </a>
        ))}
      </nav>

      <div className="mt-auto rounded-lg border border-slate-700 bg-slate-800/40 p-3 text-xs text-slate-400">
        <p className="font-medium text-emerald-400">● GDPR-compliant</p>
        <p className="mt-1">All data stays on-premises. No external calls.</p>
      </div>
    </aside>
  );
}
