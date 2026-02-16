"""
Cron Job Run Model

Stores the last run time and status for each cron job (e.g. chat summary).
Used to serve real-time cron status via GET /api/v1/admin/cron/status.
"""
import uuid
from datetime import datetime
from sqlalchemy import Column, String, DateTime, Text
from sqlalchemy.dialects.postgresql import UUID

from app.db.base import Base


class CronJobRun(Base):
    """
    One row per cron job execution. Query latest by job_name for "last run" info.
    """
    __tablename__ = "cron_job_runs"

    id = Column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    job_name = Column(String(64), nullable=False, index=True)
    ran_at = Column(DateTime(timezone=True), nullable=False)
    status = Column(String(16), nullable=False)  # e.g. "200", "500"
    message = Column(Text, nullable=True)  # optional short detail
