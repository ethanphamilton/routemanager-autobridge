"""Catalyst cron handler for RM-Autobridge.

Configured to fire daily at 14:00 UTC (9 AM EST) via Catalyst Cloud Scale › Cron.

Date routing (all operations target NEXT calendar month):
  - Last weekday before the 15th  → dry-run audit email
  - Last weekday before the 26th  → dry-run audit email
  - Last weekday on or before 26th → full WorkWave load + post-run email

On days that overlap (e.g. when the 26th falls on a weekend, the Friday
before is both the pre-26th dry-run day and the load day), the dry-run
fires first, then the load.
"""

import logging
import os
import sys
from datetime import date, timedelta
from pathlib import Path

# Make the src package importable when Catalyst runs this file
sys.path.insert(0, os.path.dirname(__file__))

from src.utils import setup_logger, set_run_id  # noqa: E402

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Date helpers
# ---------------------------------------------------------------------------


def _next_month(year: int, month: int):
    """Return (year, month) for the month after the given one."""
    if month == 12:
        return year + 1, 1
    return year, month + 1


def _last_weekday_before(target_day: int, year: int, month: int) -> date:
    """Last Mon–Fri strictly before target_day of month."""
    d = date(year, month, target_day - 1)
    while d.weekday() >= 5:
        d -= timedelta(days=1)
    return d


def _last_weekday_on_or_before(day: int, year: int, month: int) -> date:
    """Last Mon–Fri on or before the given day of month."""
    d = date(year, month, day)
    while d.weekday() >= 5:
        d -= timedelta(days=1)
    return d


def _build_run_id(year: int, month: int) -> str:
    return f"autobridge-{year}-{month:02d}"


def _initialize_catalyst(context):
    """Initialize zcatalyst-sdk app from the cron context.

    Returns the app on success, None on failure (logged). The pipeline runs
    without Datastore/File Store integration when app is None — falls back
    gracefully to stdout-only logging."""
    try:
        import zcatalyst_sdk

        return zcatalyst_sdk.initialize(context)
    except Exception as exc:
        logger.error(f"rm_autobridge: catalyst init failed: {exc}", exc_info=True)
        return None


# ---------------------------------------------------------------------------
# Catalyst entry point
# ---------------------------------------------------------------------------


def handler(cron_details, context):
    today = date.today()
    target_year, target_month = _next_month(today.year, today.month)
    run_id = _build_run_id(target_year, target_month)

    artifacts_dir = Path("/tmp")
    setup_logger(
        level="INFO",
        log_file=artifacts_dir / f"run-{run_id}.log",
        jsonl_file=artifacts_dir / f"run-{run_id}.log.jsonl",
    )
    set_run_id(run_id)

    load_day = _last_weekday_on_or_before(26, today.year, today.month)
    dry_run_days = {
        _last_weekday_before(15, today.year, today.month),
        _last_weekday_before(26, today.year, today.month),
    }

    is_load_day = today == load_day
    is_dry_run_day = today in dry_run_days

    if not is_load_day and not is_dry_run_day:
        logger.info(f"rm_autobridge: {today} is not a scheduled day — skipping.")
        return

    logger.info(
        f"rm_autobridge: {today} — targeting {target_month}/{target_year} "
        f"(load={is_load_day}, dry_run={is_dry_run_day}, run_id={run_id})"
    )

    catalyst_app = _initialize_catalyst(context) if is_load_day else None

    if is_dry_run_day:
        from src.dry_run import run as dry_run

        dry_run(month=target_month, year=target_year, run_id=run_id)

    if is_load_day:
        from src.main import run as pipeline

        pipeline(
            month=target_month,
            year=target_year,
            run_id=run_id,
            catalyst_app=catalyst_app,
            log_artifacts_dir=artifacts_dir,
        )
