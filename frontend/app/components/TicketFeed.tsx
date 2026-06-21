"use client";

import {
  TICKET_STATUSES,
  exportTicketsUrl,
  type Priority,
  type TicketStatus,
  type TriageResponse,
} from "../../lib/api";

const priorityBadge: Record<Priority, string> = {
  High: "bg-red-100 text-red-700 ring-red-200",
  Medium: "bg-amber-100 text-amber-700 ring-amber-200",
  Low: "bg-emerald-100 text-emerald-700 ring-emerald-200",
};

const categoryBadge = "bg-slate-100 text-slate-600 ring-slate-200";

const statusBadge: Record<TicketStatus, string> = {
  open: "bg-sky-100 text-sky-700 ring-sky-200",
  in_progress: "bg-violet-100 text-violet-700 ring-violet-200",
  closed: "bg-slate-200 text-slate-500 ring-slate-300",
};

const statusLabel: Record<TicketStatus, string> = {
  open: "Open",
  in_progress: "In progress",
  closed: "Closed",
};

export default function TicketFeed({
  tickets,
  onStatusChange,
}: {
  tickets: TriageResponse[];
  onStatusChange: (id: number, status: TicketStatus) => void;
}) {
  return (
    <div className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm">
      <div className="mb-4 flex items-center justify-between gap-3">
        <h2 className="text-lg font-semibold text-slate-800">Ticket Feed</h2>
        <div className="flex items-center gap-2">
          <span className="text-xs text-slate-400">{tickets.length} triaged</span>
          {/* ERP-ready export (SAP S/4HANA / ServiceNow ingestion) */}
          <a
            href={exportTicketsUrl("csv")}
            className="rounded-md border border-slate-200 px-2.5 py-1 text-xs font-medium text-slate-600 hover:bg-slate-50"
            title="Export all tickets as CSV for ERP ingestion"
          >
            ⤓ CSV
          </a>
          <a
            href={exportTicketsUrl("json")}
            className="rounded-md border border-slate-200 px-2.5 py-1 text-xs font-medium text-slate-600 hover:bg-slate-50"
            title="Export all tickets as JSON for ERP ingestion"
          >
            ⤓ JSON
          </a>
          <a
            href={exportTicketsUrl("csv", "Hardware")}
            className="rounded-md border border-emerald-200 bg-emerald-50 px-2.5 py-1 text-xs font-medium text-emerald-700 hover:bg-emerald-100"
            title="Export only Hardware tickets (failures / EOL devices) for asset reporting"
          >
            ⤓ Hardware → ERP
          </a>
        </div>
      </div>

      {tickets.length === 0 ? (
        <p className="py-8 text-center text-sm text-slate-400">
          No tickets yet — submit one in the simulator.
        </p>
      ) : (
        <ul className="space-y-3">
          {tickets.map((t, i) => {
            const status = t.status ?? "open";
            return (
              <li
                key={t.ticket_id ?? `local-${i}`}
                className={`rounded-lg border border-slate-100 p-4 ${
                  status === "closed" ? "opacity-60" : ""
                }`}
              >
                <div className="mb-2 flex items-start justify-between gap-3">
                  <p className="font-medium text-slate-800">{t.query}</p>
                  <span
                    className={`shrink-0 rounded-full px-2.5 py-0.5 text-xs font-semibold ring-1 ${priorityBadge[t.priority]}`}
                  >
                    {t.priority}
                  </span>
                </div>

                <div className="mb-2 flex flex-wrap items-center gap-2 text-xs">
                  <span className={`rounded-full px-2 py-0.5 ring-1 ${categoryBadge}`}>
                    {t.category}
                  </span>
                  <span
                    className={`rounded-full px-2 py-0.5 ring-1 ${statusBadge[status]}`}
                  >
                    {statusLabel[status]}
                  </span>
                  {t.ticket_id != null && (
                    <span className="text-slate-400">#{t.ticket_id}</span>
                  )}
                  <span className="text-slate-400">· src: {t.kb_source}</span>
                </div>

                {t.suggested_action && (
                  <p className="rounded-md bg-slate-50 p-3 text-sm text-slate-600">
                    <span className="font-medium text-slate-700">Suggested action: </span>
                    {t.suggested_action}
                  </p>
                )}

                {/* Status controls */}
                <div className="mt-3 flex items-center gap-1.5">
                  {TICKET_STATUSES.map((s) => (
                    <button
                      key={s}
                      onClick={() => t.ticket_id != null && onStatusChange(t.ticket_id, s)}
                      disabled={t.ticket_id == null || status === s}
                      className={`rounded-md px-2.5 py-1 text-xs font-medium transition ${
                        status === s
                          ? "bg-slate-800 text-white"
                          : "border border-slate-200 text-slate-500 hover:bg-slate-50 disabled:opacity-40"
                      }`}
                      title={t.ticket_id == null ? "Not persisted (no DB id)" : undefined}
                    >
                      {statusLabel[s]}
                    </button>
                  ))}
                </div>
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}
