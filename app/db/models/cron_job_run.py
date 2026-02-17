"""
Cron Job Run Model (summary_cron_metadata).

Stores the last run time and status for each cron job (e.g. chat summary).
Used to serve real-time cron status via GET /api/v1/admin/cron/status.
"""
from sqlalchemy import Column, String, DateTime, Text, text
from sqlalchemy.dialects.postgresql import UUID

from app.db.base import Base


class CronJobRun(Base):
    """
    One row per cron job execution. Query latest by job_name for "last run" info.
    Maps to table summary_cron_metadata.
    """
    __tablename__ = "summary_cron_metadata"

    id = Column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("uuid_generate_v4()"),
    )
    job_name = Column(String(65), nullable=False, default="summary-cron", server_default=text("'summary-cron'"))
    ran_at = Column(DateTime(timezone=True), nullable=False)
    status = Column(String(200), nullable=False)
    message = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=text("NOW()"))
