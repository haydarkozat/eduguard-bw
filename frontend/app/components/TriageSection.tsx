"use client";

// Stateful parent: holds the triaged tickets and wires the simulator (input)
// to the feed (output). Newest ticket first.

import { useEffect, useState } from "react";
import {
  getTickets,
  patchTicketStatus,
  recordToTriage,
  type TicketStatus,
  type TriageResponse,
} from "../../lib/api";
import TriageSimulator from "./TriageSimulator";
import TicketFeed from "./TicketFeed";

export default function TriageSection() {
  const [tickets, setTickets] = useState<TriageResponse[]>([]);

  async function reload() {
    try {
      const rows = await getTickets();
      setTickets(rows.map(recordToTriage));
    } catch {
      /* backend not ready yet — leave current state */
    }
  }

  // Load existing tickets from PostgreSQL on mount so the feed survives reloads.
  useEffect(() => {
    reload();
  }, []);

  const addTicket = (t: TriageResponse) =>
    setTickets((prev) => [{ status: "open", ...t }, ...prev]);

  // Optimistic status update; reload from DB if the PATCH fails.
  async function changeStatus(id: number, status: TicketStatus) {
    setTickets((prev) =>
      prev.map((t) => (t.ticket_id === id ? { ...t, status } : t)),
    );
    try {
      await patchTicketStatus(id, status);
    } catch {
      reload();
    }
  }

  return (
    <section className="grid gap-6 lg:grid-cols-2">
      <TriageSimulator onResult={addTicket} />
      <TicketFeed tickets={tickets} onStatusChange={changeStatus} />
    </section>
  );
}
