"""
EduGuard BW — SQLAlchemy ORM models.

Two tables back the prototype:
  * network_logs    — one row per subnet per completed NIDS sweep
  * support_tickets — one row per triaged IT support ticket
"""
from __future__ import annotations

from sqlalchemy import Column, DateTime, Integer, String, Text, func

from database import Base


class NetworkLog(Base):
    __tablename__ = "network_logs"

    id = Column(Integer, primary_key=True, index=True)
    subnet = Column(String(50), nullable=False, index=True)
    status = Column(String(50), nullable=False)  # ok | degraded | critical
    timestamp = Column(DateTime(timezone=True), server_default=func.now(), index=True)

    def as_dict(self) -> dict:
        return {
            "id": self.id,
            "subnet": self.subnet,
            "status": self.status,
            "timestamp": self.timestamp.isoformat() if self.timestamp else None,
        }


class SecurityEvent(Base):
    __tablename__ = "security_events"

    id = Column(Integer, primary_key=True, index=True)
    subnet = Column(String(50), nullable=False, index=True)
    host = Column(String(64))
    kind = Column(String(64), index=True)        # unexpected_open_port | syn_response_burst | syn_flood
    severity = Column(String(20), index=True)    # low | medium | high
    detail = Column(Text)
    timestamp = Column(DateTime(timezone=True), server_default=func.now(), index=True)

    def as_dict(self) -> dict:
        return {
            "id": self.id,
            "subnet": self.subnet,
            "host": self.host,
            "kind": self.kind,
            "severity": self.severity,
            "detail": self.detail,
            "timestamp": self.timestamp.isoformat() if self.timestamp else None,
        }


class SupportTicket(Base):
    __tablename__ = "support_tickets"

    id = Column(Integer, primary_key=True, index=True)
    issue_text = Column(Text, nullable=False)
    category = Column(String(50))   # Network | Hardware | Software | Account
    priority = Column(String(20))   # Low | Medium | High
    suggested_action = Column(Text)
    status = Column(String(30), nullable=False, default="open")  # open | in_progress | closed
    timestamp = Column(DateTime(timezone=True), server_default=func.now(), index=True)

    def as_dict(self) -> dict:
        return {
            "id": self.id,
            "issue_text": self.issue_text,
            "category": self.category,
            "priority": self.priority,
            "suggested_action": self.suggested_action,
            "status": self.status,
            "timestamp": self.timestamp.isoformat() if self.timestamp else None,
        }
