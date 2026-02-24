"""
In-app scheduler for the daily chat summary job.
Runs at SUMMARY_CRON_HOUR:SUMMARY_CRON_MINUTE (default 11:20) server local time.
"""
import asyncio
import logging
import os
from datetime import datetime, timezone, timedelta

from app.db.connection import get_session_maker

logger = logging.getLogger(__name__)

SUMMARY_CRON_HOUR = int(os.getenv("SUMMARY_CRON_HOUR", "11"))
SUMMARY_CRON_MINUTE = int(os.getenv("SUMMARY_CRON_MINUTE", "58"))
ENABLE_INAPP_SUMMARY_CRON = os.getenv("ENABLE_INAPP_SUMMARY_CRON", "true").lower() == "true"


async def _run_summary_job_and_record() -> None:
    """Run nightly summary job and record to cron_job_runs for status endpoint."""
    try:
        from app.services.summary_cron_service import SummaryCronService
        from app.db.models.cron_job_run import CronJobRun

        cron_service = SummaryCronService()
        results = await cron_service.run_nightly_summary_job(days_required=7)
        session_maker = get_session_maker()
        async with session_maker() as db:
            db.add(CronJobRun(
                job_name="chat_summary",
                ran_at=datetime.now(timezone.utc),
                status="200",
                message=None,
            ))
            await db.commit()
        logger.info(
            "Summary cron job completed: %s succeeded, %s skipped, %s failed",
            results.get("listings_succeeded", 0),
            results.get("listings_skipped", 0),
            results.get("listings_failed", 0),
        )
    except Exception as e:
        logger.exception("Summary cron job failed: %s", e)
        try:
            from app.db.models.cron_job_run import CronJobRun
            session_maker = get_session_maker()
            async with session_maker() as db:
                db.add(CronJobRun(
                    job_name="chat_summary",
                    ran_at=datetime.now(timezone.utc),
                    status="500",
                    message=str(e)[:500],
                ))
                await db.commit()
        except Exception:
            pass


def _seconds_until_next_run(hour: int, minute: int) -> float:
    """Seconds until next run at hour:minute (server local time)."""
    from datetime import datetime as dt_local
    now = dt_local.now()
    today_run = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if today_run <= now:
        today_run += timedelta(days=1)
    return (today_run - now).total_seconds()


async def _summary_cron_loop() -> None:
    """Background loop: wait until scheduled time, run job, repeat."""
    if not ENABLE_INAPP_SUMMARY_CRON:
        logger.info("In-app summary cron disabled (ENABLE_INAPP_SUMMARY_CRON=false)")
        return
    logger.info(
        "In-app summary cron started: daily at %02d:%02d",
        SUMMARY_CRON_HOUR,
        SUMMARY_CRON_MINUTE,
    )
    while True:
        try:
            secs = _seconds_until_next_run(SUMMARY_CRON_HOUR, SUMMARY_CRON_MINUTE)
            logger.debug("Next summary cron run in %.0f seconds", secs)
            await asyncio.sleep(secs)
            await _run_summary_job_and_record()
        except asyncio.CancelledError:
            logger.info("In-app summary cron stopped")
            break
        except Exception as e:
            logger.exception("Summary cron loop error: %s", e)
            await asyncio.sleep(3600)


def start_summary_scheduler() -> asyncio.Task | None:
    """
    Start the in-app summary cron loop as a background task.
    Returns the task if started, None if disabled.
    """
    if not ENABLE_INAPP_SUMMARY_CRON:
        return None
    return asyncio.create_task(_summary_cron_loop())
