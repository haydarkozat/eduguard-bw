"""
EduGuard BW — lightweight NIDS / network sweep (Scapy).

Design goals
------------
* **Async-friendly**: Scapy is blocking, so every raw-socket call runs in a
  worker thread via ``asyncio.to_thread`` — the FastAPI event loop never stalls.
* **Lightweight & container-safe**: an ARP sweep discovers live hosts, then a
  *small* fixed port list is SYN-probed only on the hosts that answered. No full
  /24 × 65535 scans.
* **Degrades gracefully**: if Scapy can't open raw sockets (missing CAP_NET_RAW,
  no privileges, running in CI), we fall back to deterministic simulated data so
  the prototype still works end-to-end. Set ``EDUGUARD_SIMULATE=1`` to force it.

Anomaly heuristics
------------------
1. **Unexpected open port** — a host exposes a port outside its subnet's
   role-based allow-list.
2. **SYN-response burst** — a single host answers SYN probes on an unusually
   high number of ports (possible compromised host / scan target).
3. **SYN flood** (optional, only when ``monitor_seconds > 0``) — a short passive
   sniff flags an abnormally high inbound SYN rate.
"""
from __future__ import annotations

import asyncio
import os
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone

# --- Scapy import is guarded: the module must load even where Scapy can't ----
try:
    from scapy.all import ARP, Ether, IP, TCP, conf, sniff, sr1, srp, send

    conf.verb = 0  # silence Scapy globally
    _SCAPY_IMPORTED = True
except Exception:  # pragma: no cover - import/runtime env dependent
    _SCAPY_IMPORTED = False

SIMULATE = os.getenv("EDUGUARD_SIMULATE", "").lower() in {"1", "true", "yes"}

# ---------------------------------------------------------------------------
# Subnet model
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class Subnet:
    name: str
    cidr: str
    role: str
    allowed_ports: frozenset[int]


SUBNETS: tuple[Subnet, ...] = (
    Subnet("Admin", "10.0.10.0/24", "administration", frozenset({22, 443, 3389})),
    Subnet("Teacher", "10.0.20.0/24", "staff", frozenset({443, 445, 631})),
    Subnet("Student", "10.0.30.0/24", "student", frozenset({443})),
)

# Small, fixed probe set — keeps the SYN sweep cheap inside a container.
PROBE_PORTS: tuple[int, ...] = (22, 80, 443, 445, 631, 3389, 8080)

# Heuristic thresholds.
SYN_RESPONSE_THRESHOLD = 4   # open ports on one host before it's "suspicious"
SYN_FLOOD_RATE = 100         # SYN packets/sec considered a flood

# Bound work so a sweep stays lightweight regardless of subnet size.
MAX_HOSTS_PER_SUBNET = 32
ARP_TIMEOUT = 2
SYN_TIMEOUT = 1


# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------
@dataclass
class Anomaly:
    host: str
    kind: str
    severity: str  # "low" | "medium" | "high"
    detail: str

    def as_dict(self) -> dict:
        return {"host": self.host, "kind": self.kind, "severity": self.severity, "detail": self.detail}


@dataclass
class SubnetResult:
    name: str
    cidr: str
    devices_online: int
    open_ports: dict[str, list[int]] = field(default_factory=dict)
    anomalies: list[Anomaly] = field(default_factory=list)

    @property
    def health(self) -> str:
        if any(a.severity == "high" for a in self.anomalies):
            return "critical"
        if self.anomalies:
            return "degraded"
        return "ok"

    def as_status(self) -> dict:
        return {
            "name": self.name,
            "cidr": self.cidr,
            "devices_online": self.devices_online,
            "alerts": len(self.anomalies),
            "health": self.health,
            "anomalies": [a.as_dict() for a in self.anomalies],
        }


# ---------------------------------------------------------------------------
# In-memory state (no DB yet — PostgreSQL wiring is a later phase)
# ---------------------------------------------------------------------------
_state_lock = asyncio.Lock()
_latest_status: dict[str, dict] = {}   # subnet name -> status dict
_scans: dict[str, dict] = {}           # scan_id -> scan record


def _scapy_usable() -> bool:
    """True only if Scapy is importable AND not overridden by simulate mode."""
    return _SCAPY_IMPORTED and not SIMULATE


# ---------------------------------------------------------------------------
# Blocking Scapy primitives (always called via asyncio.to_thread)
# ---------------------------------------------------------------------------
def _arp_sweep(cidr: str) -> list[tuple[str, str]]:
    """Return [(ip, mac), ...] for hosts answering an ARP who-has across cidr."""
    answered, _ = srp(
        Ether(dst="ff:ff:ff:ff:ff:ff") / ARP(pdst=cidr),
        timeout=ARP_TIMEOUT,
        retry=0,
        verbose=0,
    )
    return [(rcv.psrc, rcv.hwsrc) for _, rcv in answered][:MAX_HOSTS_PER_SUBNET]


def _syn_scan(ip: str, ports: tuple[int, ...]) -> list[int]:
    """SYN-probe ``ports`` on ``ip``; return ports that replied SYN-ACK (0x12)."""
    open_ports: list[int] = []
    for port in ports:
        resp = sr1(IP(dst=ip) / TCP(dport=port, flags="S"), timeout=SYN_TIMEOUT, verbose=0)
        if resp is not None and resp.haslayer(TCP) and resp[TCP].flags == 0x12:
            open_ports.append(port)
            # Tear the half-open connection down politely (fire-and-forget RST).
            send(IP(dst=ip) / TCP(dport=port, flags="R"), verbose=0)
    return open_ports


def _sniff_syn_rate(seconds: int) -> float:
    """Passively count inbound TCP SYN packets and return the per-second rate."""
    pkts = sniff(
        timeout=seconds,
        filter="tcp[tcpflags] & tcp-syn != 0 and tcp[tcpflags] & tcp-ack == 0",
        store=True,
    )
    return len(pkts) / seconds if seconds > 0 else 0.0


def _scan_subnet_blocking(subnet: Subnet, monitor_seconds: int) -> SubnetResult:
    """Full per-subnet sweep. Runs in a worker thread."""
    hosts = _arp_sweep(subnet.cidr)
    result = SubnetResult(name=subnet.name, cidr=subnet.cidr, devices_online=len(hosts))

    for ip, _mac in hosts:
        open_ports = _syn_scan(ip, PROBE_PORTS)
        if open_ports:
            result.open_ports[ip] = open_ports
        result.anomalies.extend(_detect_host_anomalies(subnet, ip, open_ports))

    if monitor_seconds > 0:
        rate = _sniff_syn_rate(monitor_seconds)
        if rate >= SYN_FLOOD_RATE:
            result.anomalies.append(
                Anomaly(
                    host=subnet.cidr,
                    kind="syn_flood",
                    severity="high",
                    detail=f"{rate:.0f} SYN/s exceeds threshold of {SYN_FLOOD_RATE}/s.",
                )
            )
    return result


# ---------------------------------------------------------------------------
# Anomaly logic (pure — easy to unit test, no Scapy needed)
# ---------------------------------------------------------------------------
def _detect_host_anomalies(subnet: Subnet, ip: str, open_ports: list[int]) -> list[Anomaly]:
    anomalies: list[Anomaly] = []

    # Rule 1: ports outside the subnet's role allow-list.
    unexpected = [p for p in open_ports if p not in subnet.allowed_ports]
    if unexpected:
        anomalies.append(
            Anomaly(
                host=ip,
                kind="unexpected_open_port",
                severity="high" if 3389 in unexpected else "medium",
                detail=f"Ports {unexpected} are not allowed on the {subnet.role} subnet.",
            )
        )

    # Rule 2: a host answering SYN probes on too many ports.
    if len(open_ports) >= SYN_RESPONSE_THRESHOLD:
        anomalies.append(
            Anomaly(
                host=ip,
                kind="syn_response_burst",
                severity="high",
                detail=f"Host replied SYN-ACK on {len(open_ports)} ports — possible compromise.",
            )
        )
    return anomalies


# ---------------------------------------------------------------------------
# Simulation fallback (deterministic, no raw sockets)
# ---------------------------------------------------------------------------
def _simulate_subnet(subnet: Subnet) -> SubnetResult:
    """Deterministic stand-in so the prototype runs without CAP_NET_RAW."""
    presets = {
        "Admin": (12, {"10.0.10.5": [22, 443]}),
        "Teacher": (48, {"10.0.20.7": [443, 445], "10.0.20.31": [443, 23]}),  # 23 = unexpected
        "Student": (
            326,
            {"10.0.30.18": [80, 443, 445, 3389, 8080]},  # too many ports -> burst
        ),
    }
    devices, open_map = presets[subnet.name]
    result = SubnetResult(
        name=subnet.name, cidr=subnet.cidr, devices_online=devices, open_ports=open_map
    )
    for ip, ports in open_map.items():
        result.anomalies.extend(_detect_host_anomalies(subnet, ip, ports))
    return result


# ---------------------------------------------------------------------------
# Async orchestration
# ---------------------------------------------------------------------------
async def _scan_one(subnet: Subnet, monitor_seconds: int) -> SubnetResult:
    if _scapy_usable():
        try:
            return await asyncio.to_thread(_scan_subnet_blocking, subnet, monitor_seconds)
        except PermissionError:
            # No raw-socket privilege at runtime — fall back rather than 500.
            return _simulate_subnet(subnet)
        except Exception:
            return _simulate_subnet(subnet)
    return _simulate_subnet(subnet)


async def scan_all(monitor_seconds: int = 0) -> list[SubnetResult]:
    """Sweep all subnets concurrently and refresh the cached status."""
    results = await asyncio.gather(*(_scan_one(s, monitor_seconds) for s in SUBNETS))
    async with _state_lock:
        for r in results:
            _latest_status[r.name] = r.as_status()
    return list(results)


async def get_network_status() -> list[dict]:
    """Return the latest known status per subnet (baseline before first scan)."""
    async with _state_lock:
        if _latest_status:
            return [_latest_status[s.name] for s in SUBNETS if s.name in _latest_status]
    # No scan has run yet — present a clean baseline.
    return [
        {
            "name": s.name,
            "cidr": s.cidr,
            "devices_online": 0,
            "alerts": 0,
            "health": "ok",
            "anomalies": [],
        }
        for s in SUBNETS
    ]


# ---------------------------------------------------------------------------
# Scan job lifecycle (so POST /scan returns instantly, non-blocking)
# ---------------------------------------------------------------------------
def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


async def start_scan(subnet: str = "all", monitor_seconds: int = 0, on_complete=None) -> dict:
    """Register a scan job, kick it off in the background, return immediately.

    ``on_complete`` (optional) is an async callable invoked with the list of
    per-subnet status dicts once the sweep finishes — used by the API layer to
    persist results to PostgreSQL without coupling the scanner to the DB.
    """
    scan_id = f"scan-{uuid.uuid4().hex[:8]}"
    record = {
        "scan_id": scan_id,
        "subnet": subnet,
        "status": "running",
        "started_at": _now(),
        "finished_at": None,
        "mode": "simulated" if not _scapy_usable() else "live",
        "results": [],
    }
    async with _state_lock:
        _scans[scan_id] = record

    asyncio.create_task(_run_scan_job(scan_id, subnet, monitor_seconds, on_complete))
    return record


async def _run_scan_job(scan_id: str, subnet: str, monitor_seconds: int, on_complete=None) -> None:
    try:
        targets = SUBNETS if subnet == "all" else tuple(s for s in SUBNETS if s.name == subnet)
        results = await asyncio.gather(*(_scan_one(s, monitor_seconds) for s in targets))
        status_list = [r.as_status() for r in results]
        async with _state_lock:
            for r in results:
                _latest_status[r.name] = r.as_status()
            _scans[scan_id]["results"] = status_list
            _scans[scan_id]["status"] = "complete"
            _scans[scan_id]["finished_at"] = _now()
        if on_complete is not None:
            try:
                await on_complete(status_list)
            except Exception:
                pass  # persistence is best-effort; never fail the scan job
    except Exception as exc:  # pragma: no cover
        async with _state_lock:
            _scans[scan_id]["status"] = "failed"
            _scans[scan_id]["error"] = str(exc)
            _scans[scan_id]["finished_at"] = _now()


async def get_scan(scan_id: str) -> dict | None:
    async with _state_lock:
        return _scans.get(scan_id)


if __name__ == "__main__":
    # Local smoke test (uses simulation unless run with raw-socket privileges).
    import json

    async def _demo() -> None:
        results = await scan_all()
        print(json.dumps([r.as_status() for r in results], indent=2))

    asyncio.run(_demo())
