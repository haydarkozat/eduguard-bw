"""
EduGuard BW — FastAPI entrypoint.

Endpoints:
  - GET  /api/network/status      -> live status of the three school subnets
  - POST /api/nids/scan           -> trigger a Scapy sweep asynchronously
  - GET  /api/nids/scan/{scan_id} -> poll a scan job's result
  - POST /api/support/triage      -> classify an IT ticket via LangGraph + Ollama

On scan completion, subnet statuses are written to PostgreSQL (network_logs);
each triage is written to support_tickets. Knowledge retrieval is grounded in
Qdrant (seeded at startup).
"""
from __future__ import annotations

import asyncio
import csv
import io
import json
import logging
import os
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone

from fastapi import Depends, FastAPI, HTTPException, Query, Response
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ai_triage import triage_ticket
from database import SessionLocal, get_db, init_db
from models import NetworkLog, SecurityEvent, SupportTicket
import network_scanner as scanner
import rag_engine

logger = logging.getLogger("eduguard")
logging.basicConfig(level=logging.INFO)


# ---------------------------------------------------------------------------
# Startup / shutdown — initialise DB tables and the Qdrant collection
# ---------------------------------------------------------------------------
@asynccontextmanager
async def lifespan(app: FastAPI):
    # PostgreSQL: create tables. Best-effort so the API still boots if DB is slow.
    try:
        await asyncio.to_thread(init_db)
        logger.info("PostgreSQL ready — tables ensured.")
    except Exception as exc:
        logger.warning("DB init failed (continuing): %s", exc)

    # Qdrant: create collection + seed mock IT docs.
    try:
        info = await asyncio.to_thread(rag_engine.init_rag)
        logger.info("Qdrant ready — %s", info)
    except Exception as exc:
        logger.warning("RAG init failed (continuing, will use mock KB): %s", exc)

    yield


app = FastAPI(
    title="EduGuard BW API",
    description="GDPR-compliant, self-hosted school IT monitoring & AI triage.",
    version="0.3.0",
    lifespan=lifespan,
)

# CORS — the Next.js dashboard may be served on a remapped host port (e.g. the
# default 3000, or 13000 when 3000 is taken). Allow an explicit comma-separated
# CORS_ORIGINS list when provided; otherwise permit any localhost port in dev.
_cors_env = os.getenv("CORS_ORIGINS", "").strip()
if _cors_env:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[o.strip() for o in _cors_env.split(",") if o.strip()],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
else:
    app.add_middleware(
        CORSMiddleware,
        allow_origin_regex=r"http://(localhost|127\.0\.0\.1):\d+",
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------
class AnomalyModel(BaseModel):
    host: str
    kind: str
    severity: str
    detail: str


class SubnetStatus(BaseModel):
    name: str
    cidr: str
    devices_online: int
    alerts: int
    health: str  # "ok" | "degraded" | "critical"
    anomalies: list[AnomalyModel] = []


class ScanRequest(BaseModel):
    subnet: str = Field("all", description="Subnet name (Admin/Teacher/Student) or 'all'.")
    monitor_seconds: int = Field(
        0, ge=0, le=60, description="Optional passive SYN-flood sniff window (0 = skip)."
    )


class ScanJob(BaseModel):
    scan_id: str
    subnet: str
    status: str
    started_at: str
    finished_at: str | None = None
    mode: str
    results: list[SubnetStatus] = []


class NetworkHistoryPoint(BaseModel):
    timestamp: str
    ok: int
    degraded: int
    critical: int
    anomalies: int  # degraded + critical


class SecurityEventRecord(BaseModel):
    id: int
    subnet: str
    host: str | None = None
    kind: str | None = None
    severity: str | None = None
    detail: str | None = None
    timestamp: str | None = None


class TriageRequest(BaseModel):
    query: str = Field(..., examples=["Smartboard no signal in room 204"])
    room: str | None = None
    reporter: str | None = None


class TriageResponse(BaseModel):
    ticket_id: int | None = None
    query: str
    category: str          # "Network" | "Hardware" | "Software" | "Account"
    priority: str          # "Low" | "Medium" | "High"
    summary: str
    suggested_action: str
    kb_source: str         # provenance of the suggestion (Qdrant doc ids / mock)


class TicketRecord(BaseModel):
    id: int
    issue_text: str
    category: str | None = None
    priority: str | None = None
    suggested_action: str | None = None
    status: str
    timestamp: str | None = None


ALLOWED_TICKET_STATUSES = {"open", "in_progress", "closed"}


class TicketStatusUpdate(BaseModel):
    status: str = Field(..., description="One of: open, in_progress, closed.")


# ---------------------------------------------------------------------------
# Persistence helpers
# ---------------------------------------------------------------------------
async def _persist_scan_results(status_list: list[dict]) -> None:
    """After a scan: one network_logs row per subnet + one security_events row per anomaly."""

    def _write() -> int:
        events = 0
        with SessionLocal() as db:
            for s in status_list:
                db.add(NetworkLog(subnet=s["name"], status=s["health"]))
                for a in s.get("anomalies", []):
                    db.add(
                        SecurityEvent(
                            subnet=s["name"],
                            host=a.get("host"),
                            kind=a.get("kind"),
                            severity=a.get("severity"),
                            detail=a.get("detail"),
                        )
                    )
                    events += 1
            db.commit()
        return events

    try:
        events = await asyncio.to_thread(_write)
        logger.info(
            "Persisted %d network log row(s) and %d security event(s).",
            len(status_list),
            events,
        )
    except Exception as exc:
        logger.warning("Could not persist scan results: %s", exc)


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------
@app.get("/health", tags=["system"])
def health() -> dict:
    return {
        "status": "ok",
        "service": "eduguard-backend",
        "qdrant_ready": rag_engine.is_ready(),
    }


# ---------------------------------------------------------------------------
# Network status
# ---------------------------------------------------------------------------
@app.get("/api/network/status", response_model=list[SubnetStatus], tags=["network"])
async def network_status() -> list[dict]:
    """Return the latest known pulse of each subnet (baseline before first scan)."""
    return await scanner.get_network_status()


@app.get("/api/network/history", response_model=list[NetworkHistoryPoint], tags=["network"])
def network_history(
    hours: int = Query(24, ge=1, le=168, description="Look-back window in hours."),
    db: Session = Depends(get_db),
) -> list[NetworkHistoryPoint]:
    """Time series of subnet health per scan over the last N hours (for the trend chart).

    Each scan writes one network_logs row per subnet sharing a timestamp, so we
    group by timestamp: each point is one sweep, counting ok/degraded/critical.
    """
    since = datetime.now(timezone.utc) - timedelta(hours=hours)
    rows = (
        db.query(NetworkLog)
        .filter(NetworkLog.timestamp >= since)
        .order_by(NetworkLog.timestamp.asc())
        .all()
    )

    buckets: dict[str, dict] = {}
    for r in rows:
        key = r.timestamp.isoformat() if r.timestamp else "unknown"
        b = buckets.setdefault(key, {"timestamp": key, "ok": 0, "degraded": 0, "critical": 0})
        if r.status in ("ok", "degraded", "critical"):
            b[r.status] += 1

    points = sorted(buckets.values(), key=lambda p: p["timestamp"])
    return [
        NetworkHistoryPoint(
            timestamp=p["timestamp"],
            ok=p["ok"],
            degraded=p["degraded"],
            critical=p["critical"],
            anomalies=p["degraded"] + p["critical"],
        )
        for p in points
    ]


# ---------------------------------------------------------------------------
# NIDS scan — async sweep; persists results to PostgreSQL on completion
# ---------------------------------------------------------------------------
@app.post("/api/nids/scan", response_model=ScanJob, status_code=202, tags=["nids"])
async def nids_scan(req: ScanRequest) -> dict:
    """Kick off a Scapy sweep (non-blocking) and persist results when it finishes."""
    if req.subnet != "all" and req.subnet not in {s.name for s in scanner.SUBNETS}:
        raise HTTPException(status_code=400, detail=f"Unknown subnet '{req.subnet}'.")
    return await scanner.start_scan(
        subnet=req.subnet,
        monitor_seconds=req.monitor_seconds,
        on_complete=_persist_scan_results,
    )


@app.get("/api/nids/scan/{scan_id}", response_model=ScanJob, tags=["nids"])
async def nids_scan_result(scan_id: str) -> dict:
    record = await scanner.get_scan(scan_id)
    if record is None:
        raise HTTPException(status_code=404, detail=f"No scan with id '{scan_id}'.")
    return record


# ---------------------------------------------------------------------------
# Security events — anomalies detected by the NIDS, persisted per scan
# ---------------------------------------------------------------------------
@app.get("/api/security/events", response_model=list[SecurityEventRecord], tags=["security"])
def list_security_events(
    limit: int = Query(50, ge=1, le=200, description="Max rows to return (newest first)."),
    severity: str | None = Query(None, description="Filter by severity (low/medium/high)."),
    subnet: str | None = Query(None, description="Filter by subnet name."),
    db: Session = Depends(get_db),
) -> list[SecurityEventRecord]:
    """List NIDS-detected security events from PostgreSQL, newest first."""
    q = db.query(SecurityEvent).order_by(SecurityEvent.id.desc())
    if severity:
        q = q.filter(SecurityEvent.severity == severity)
    if subnet:
        q = q.filter(SecurityEvent.subnet == subnet)
    return [SecurityEventRecord(**row.as_dict()) for row in q.limit(limit).all()]


# ---------------------------------------------------------------------------
# Support triage — LangGraph + Ollama (RAG-grounded), persisted to PostgreSQL
# ---------------------------------------------------------------------------
@app.post("/api/support/triage", response_model=TriageResponse, tags=["support"])
def support_triage(req: TriageRequest, db: Session = Depends(get_db)) -> TriageResponse:
    """Run a ticket through the triage graph and store it as a support_tickets row.

    Sync def on purpose: FastAPI offloads it to a worker thread, so the blocking
    local-Ollama call never stalls the event loop.
    """
    result = triage_ticket(req.query)

    ticket_id: int | None = None
    try:
        ticket = SupportTicket(
            issue_text=req.query,
            category=result["category"],
            priority=result["priority"],
            suggested_action=result["suggested_action"],
            status="open",
        )
        db.add(ticket)
        db.commit()
        db.refresh(ticket)
        ticket_id = ticket.id
    except Exception as exc:
        db.rollback()
        logger.warning("Could not persist support ticket: %s", exc)

    return TriageResponse(
        ticket_id=ticket_id,
        query=req.query,
        category=result["category"],
        priority=result["priority"],
        summary=result["summary"],
        suggested_action=result["suggested_action"],
        kb_source=result["kb_source"],
    )


@app.get("/api/support/tickets", response_model=list[TicketRecord], tags=["support"])
def list_tickets(
    limit: int = Query(50, ge=1, le=200, description="Max rows to return (newest first)."),
    status: str | None = Query(None, description="Filter by status (open/in_progress/closed)."),
    category: str | None = Query(None, description="Filter by category."),
    priority: str | None = Query(None, description="Filter by priority."),
    db: Session = Depends(get_db),
) -> list[TicketRecord]:
    """List triaged support tickets from PostgreSQL, newest first, with optional filters."""
    q = db.query(SupportTicket).order_by(SupportTicket.id.desc())
    if status:
        q = q.filter(SupportTicket.status == status)
    if category:
        q = q.filter(SupportTicket.category == category)
    if priority:
        q = q.filter(SupportTicket.priority == priority)
    return [TicketRecord(**row.as_dict()) for row in q.limit(limit).all()]


@app.patch("/api/support/tickets/{ticket_id}", response_model=TicketRecord, tags=["support"])
def update_ticket_status(
    ticket_id: int,
    body: TicketStatusUpdate,
    db: Session = Depends(get_db),
) -> TicketRecord:
    """Update a ticket's workflow status (open → in_progress → closed)."""
    if body.status not in ALLOWED_TICKET_STATUSES:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid status '{body.status}'. Allowed: {sorted(ALLOWED_TICKET_STATUSES)}.",
        )
    ticket = db.get(SupportTicket, ticket_id)
    if ticket is None:
        raise HTTPException(status_code=404, detail=f"No ticket with id {ticket_id}.")

    ticket.status = body.status
    db.commit()
    db.refresh(ticket)
    return TicketRecord(**ticket.as_dict())


# ---------------------------------------------------------------------------
# ERP-ready export — hand IT tickets (e.g. hardware failures / EOL devices) off
# to enterprise systems (SAP S/4HANA, ServiceNow, …) as CSV or JSON.
# ---------------------------------------------------------------------------
# Maps internal fields onto neutral, integration-friendly column names. A SAP
# adapter would map these onto e.g. a PM notification (IW21) or asset record.
EXPORT_FIELDS = [
    ("id", "TicketID"),
    ("category", "Category"),
    ("priority", "Priority"),
    ("status", "Status"),
    ("issue_text", "Description"),
    ("suggested_action", "RecommendedAction"),
    ("timestamp", "CreatedAt"),
]


@app.get("/api/export/tickets", tags=["export"])
def export_tickets(
    format: str = Query("csv", pattern="^(csv|json)$", description="csv or json."),
    category: str | None = Query(None, description="e.g. Hardware for asset/EOL reporting."),
    status: str | None = Query(None, description="Filter by status."),
    db: Session = Depends(get_db),
) -> Response:
    """Export tickets as a downloadable CSV/JSON file for ERP ingestion."""
    q = db.query(SupportTicket).order_by(SupportTicket.id.desc())
    if category:
        q = q.filter(SupportTicket.category == category)
    if status:
        q = q.filter(SupportTicket.status == status)
    rows = [r.as_dict() for r in q.all()]

    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    suffix = f"_{category.lower()}" if category else ""

    if format == "json":
        payload = {
            "source_system": "EduGuard BW",
            "schema_version": "1.0",
            "exported_at": datetime.now(timezone.utc).isoformat(),
            "record_count": len(rows),
            "records": [{label: r.get(key) for key, label in EXPORT_FIELDS} for r in rows],
        }
        return Response(
            content=json.dumps(payload, ensure_ascii=False, indent=2),
            media_type="application/json",
            headers={"Content-Disposition": f'attachment; filename="eduguard_tickets{suffix}_{stamp}.json"'},
        )

    # CSV
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow([label for _key, label in EXPORT_FIELDS])
    for r in rows:
        writer.writerow([r.get(key, "") for key, _label in EXPORT_FIELDS])
    return Response(
        content=buf.getvalue(),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="eduguard_tickets{suffix}_{stamp}.csv"'},
    )


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
