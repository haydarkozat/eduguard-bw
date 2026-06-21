// EduGuard BW — typed API client for the FastAPI backend.

export const API_BASE =
  process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export type Health = "ok" | "degraded" | "critical";
export type Priority = "Low" | "Medium" | "High";
export type Category = "Network" | "Hardware" | "Software" | "Account";

export interface Anomaly {
  host: string;
  kind: string;
  severity: "low" | "medium" | "high";
  detail: string;
}

export interface SubnetStatus {
  name: string;
  cidr: string;
  devices_online: number;
  alerts: number;
  health: Health;
  anomalies: Anomaly[];
}

export const TICKET_STATUSES = ["open", "in_progress", "closed"] as const;
export type TicketStatus = (typeof TICKET_STATUSES)[number];

export interface TriageResponse {
  ticket_id: number | null;
  query: string;
  category: Category;
  priority: Priority;
  summary: string;
  suggested_action: string;
  kb_source: string;
  status?: TicketStatus;
}

export async function getNetworkStatus(): Promise<SubnetStatus[]> {
  const res = await fetch(`${API_BASE}/api/network/status`, { cache: "no-store" });
  if (!res.ok) throw new Error(`network/status failed: ${res.status}`);
  return res.json();
}

export interface ScanJob {
  scan_id: string;
  subnet: string;
  status: "running" | "complete" | "failed";
  started_at: string;
  finished_at: string | null;
  mode: "live" | "simulated";
  results: SubnetStatus[];
}

export async function postScan(subnet = "all"): Promise<ScanJob> {
  const res = await fetch(`${API_BASE}/api/nids/scan`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ subnet }),
  });
  if (!res.ok) throw new Error(`nids/scan failed: ${res.status}`);
  return res.json();
}

export async function getScan(scanId: string): Promise<ScanJob> {
  const res = await fetch(`${API_BASE}/api/nids/scan/${scanId}`, { cache: "no-store" });
  if (!res.ok) throw new Error(`nids/scan/${scanId} failed: ${res.status}`);
  return res.json();
}

export interface NetworkHistoryPoint {
  timestamp: string;
  ok: number;
  degraded: number;
  critical: number;
  anomalies: number;
}

export async function getNetworkHistory(hours = 24): Promise<NetworkHistoryPoint[]> {
  const res = await fetch(`${API_BASE}/api/network/history?hours=${hours}`, {
    cache: "no-store",
  });
  if (!res.ok) throw new Error(`network/history failed: ${res.status}`);
  return res.json();
}

// Direct download URL for the ERP-ready export (used by anchor buttons).
export function exportTicketsUrl(
  format: "csv" | "json",
  category?: string,
): string {
  const params = new URLSearchParams({ format });
  if (category) params.set("category", category);
  return `${API_BASE}/api/export/tickets?${params.toString()}`;
}

export interface SecurityEvent {
  id: number;
  subnet: string;
  host: string | null;
  kind: string | null;
  severity: "low" | "medium" | "high" | null;
  detail: string | null;
  timestamp: string | null;
}

export async function getSecurityEvents(limit = 50): Promise<SecurityEvent[]> {
  const res = await fetch(`${API_BASE}/api/security/events?limit=${limit}`, {
    cache: "no-store",
  });
  if (!res.ok) throw new Error(`security/events failed: ${res.status}`);
  return res.json();
}

export async function postTriage(query: string): Promise<TriageResponse> {
  const res = await fetch(`${API_BASE}/api/support/triage`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ query }),
  });
  if (!res.ok) throw new Error(`support/triage failed: ${res.status}`);
  return res.json();
}

export interface TicketRecord {
  id: number;
  issue_text: string;
  category: Category | null;
  priority: Priority | null;
  suggested_action: string | null;
  status: string;
  timestamp: string | null;
}

export async function getTickets(limit = 50): Promise<TicketRecord[]> {
  const res = await fetch(`${API_BASE}/api/support/tickets?limit=${limit}`, {
    cache: "no-store",
  });
  if (!res.ok) throw new Error(`support/tickets failed: ${res.status}`);
  return res.json();
}

// Map a persisted DB row onto the shape the Ticket Feed renders.
export function recordToTriage(r: TicketRecord): TriageResponse {
  return {
    ticket_id: r.id,
    query: r.issue_text,
    category: (r.category ?? "Software") as Category,
    priority: (r.priority ?? "Medium") as Priority,
    summary: "",
    suggested_action: r.suggested_action ?? "",
    kb_source: "db",
    status: (r.status as TicketStatus) ?? "open",
  };
}

export async function patchTicketStatus(
  id: number,
  status: TicketStatus,
): Promise<TicketRecord> {
  const res = await fetch(`${API_BASE}/api/support/tickets/${id}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ status }),
  });
  if (!res.ok) throw new Error(`PATCH ticket ${id} failed: ${res.status}`);
  return res.json();
}
