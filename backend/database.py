"""
EduGuard BW — PostgreSQL connection (SQLAlchemy).

A single sync engine + session factory. The DATABASE_URL is supplied by
docker-compose (points at the `postgres` service); locally it falls back to
localhost so the app can run against a port-forwarded DB.
"""
from __future__ import annotations

import os

from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker

DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql+psycopg2://eduguard:eduguard_dev_pw@localhost:5432/eduguard",
)

# pool_pre_ping avoids stale connections after the DB container restarts.
engine = create_engine(DATABASE_URL, pool_pre_ping=True, future=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)

Base = declarative_base()


def init_db() -> None:
    """Create tables if they don't exist (prototype-grade; use Alembic later)."""
    # Import models so they register on Base.metadata before create_all.
    import models  # noqa: F401

    Base.metadata.create_all(bind=engine)


def get_db():
    """FastAPI dependency — yields a session and always closes it."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
