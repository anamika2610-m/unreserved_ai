"""add cron_job_runs table for real-time cron last run

Revision ID: 008
Revises: 007
Create Date: 2026-02-12

"""
from alembic import op

revision = "008"
down_revision = "007"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
        CREATE TABLE IF NOT EXISTS cron_job_runs (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            job_name VARCHAR(64) NOT NULL,
            ran_at TIMESTAMP WITH TIME ZONE NOT NULL,
            status VARCHAR(16) NOT NULL,
            message TEXT
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS idx_cron_job_runs_job_name_ran_at ON cron_job_runs (job_name, ran_at DESC)")


def downgrade():
    op.drop_table("cron_job_runs")
