"""Core pipeline: Zoho pull → generate orders → CSV backup → WorkWave submit → email."""

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv

from .io import ZohoClient, WorkwaveClient, AmbiguousBatchError
from .processors import OrderGenerator
from .notifications import EmailClient, ReportBuilder
from .utils import get_logger

logger = get_logger()

REPORT_RECIPIENT = "maintenance@mountainleisureliving.com"
_FUNCTION_DIR = Path(__file__).resolve().parent.parent

# Catalyst File Store folder ID for uploaded run artifacts (jsonl + summary).
# Provisioned in the Catalyst console; ID injected via env var.
FILESTORE_FOLDER_ENV = "CATALYST_RUN_ARTIFACTS_FOLDER_ID"


def run(
    month: int,
    year: int,
    *,
    run_id: str,
    output_dir: Optional[Path] = None,
    catalyst_app=None,
    log_artifacts_dir: Optional[Path] = None,
):
    """Run the full pipeline for the given month/year.

    1. Pull property data from Zoho CRM
    2. Generate service orders (tagged with run_id)
    3. Write CSV backup
    4. Submit orders to WorkWave RouteManager
    5. Write run summary JSON, upload log+summary to Catalyst File Store
    6. Send post-run email report

    Args:
        month: Target month (1-12).
        year: Target year.
        run_id: Autobridge run identifier — required, threaded everywhere.
        output_dir: Where CSV backups go. Defaults to function dir / "output".
        catalyst_app: Initialized zcatalyst_sdk app, or None for local runs.
            When provided, enables Datastore writes (RmRunSubmissions) and
            File Store uploads of log artifacts.
        log_artifacts_dir: Directory containing per-run log artifacts written
            by the logger (`.log.jsonl` etc.). Defaults to /tmp.
    """
    if not run_id:
        raise ValueError("main.run: run_id must be a non-empty string")

    load_dotenv(_FUNCTION_DIR / ".env")  # no-op in Catalyst; env vars set via console

    started_at = datetime.now(timezone.utc)

    missing = [
        k
        for k in ("ZOHO_ACCOUNTS_URL", "ZOHO_CLIENT_ID", "ZOHO_CLIENT_SECRET", "ZOHO_REFRESH_TOKEN")
        if not os.getenv(k)
    ]
    if missing:
        logger.error(f"pipeline: missing env vars: {missing}")
        return

    if output_dir is None:
        output_dir = _FUNCTION_DIR / "output"
    if log_artifacts_dir is None:
        log_artifacts_dir = Path("/tmp")

    logger.info(
        f"pipeline: starting run_id={run_id} for {month}/{year}",
        extra={
            "event": "pipeline.start",
            "fields": {
                "run_id": run_id,
                "month": month,
                "year": year,
                "started_at": started_at.isoformat(),
            },
        },
    )

    # --- Pull from Zoho ---
    zoho = ZohoClient(
        accounts_url=os.getenv("ZOHO_ACCOUNTS_URL"),
        client_id=os.getenv("ZOHO_CLIENT_ID"),
        client_secret=os.getenv("ZOHO_CLIENT_SECRET"),
        refresh_token=os.getenv("ZOHO_REFRESH_TOKEN"),
        api_domain=os.getenv("ZOHO_API_DOMAIN"),
    )
    csv_bytes = zoho.get_properties()
    logger.info(f"pipeline: fetched {len(csv_bytes):,} bytes from Zoho")

    # --- Generate orders ---
    generator = OrderGenerator()
    result = generator.generate(input_bytes=csv_bytes, month=month, year=year, run_id=run_id)
    logger.info(
        f"pipeline: {result.total_properties} properties — "
        f"{result.successful_properties} succeeded, {result.failed_properties} failed"
    )

    # --- Write CSV backup ---
    generator.write_output(result, output_dir)
    logger.info(f"pipeline: CSV backup written to {output_dir}")

    # --- Submit to WorkWave ---
    workwave = WorkwaveClient(
        api_key=os.getenv("WORKWAVE_API_KEY"),
        territory_id=os.getenv("WORKWAVE_TERRITORY_ID"),
        catalyst_app=catalyst_app,
    )
    all_orders = result.service_orders + result.drain_orders + result.fill_orders
    logger.info(f"pipeline: submitting {len(all_orders)} orders to WorkWave...")

    submission_aborted = None
    try:
        request_ids, submission_failures, attempts_per_batch = workwave.submit_orders(
            all_orders, run_id=run_id
        )
        logger.info(
            f"pipeline: WorkWave — {len(request_ids)} batch(es) queued, "
            f"{len(submission_failures)} orders failed submission"
        )
    except AmbiguousBatchError as exc:
        # Deliberately not re-raised: the run stops submitting, but the
        # summary and alert email must still go out so a human knows the run
        # needs reconciling. Re-running blind would duplicate.
        submission_aborted = str(exc)
        request_ids, submission_failures, attempts_per_batch = [], [], []
        logger.error(
            f"pipeline: submission ABORTED — {exc}. "
            f"Run `trigger.py reconcile` before any re-run.",
            extra={
                "event": "pipeline.submission.aborted",
                "fields": {"run_id": run_id, "reason": str(exc)},
            },
        )

    # --- Run summary & log upload ---
    completed_at = datetime.now(timezone.utc)
    summary = _build_run_summary(
        run_id=run_id,
        started_at=started_at,
        completed_at=completed_at,
        order_count=len(all_orders),
        request_ids=request_ids,
        attempts_per_batch=attempts_per_batch,
        submission_failures=submission_failures,
        submission_aborted=submission_aborted,
    )
    summary_path = log_artifacts_dir / f"run-{run_id}.summary.json"
    try:
        summary_path.write_text(json.dumps(summary, indent=2, default=str))
        logger.info(
            f"pipeline: summary written to {summary_path}",
            extra={"event": "pipeline.summary", "fields": summary},
        )
    except Exception as exc:
        logger.error(f"pipeline: failed to write summary file: {exc}", exc_info=True)

    _upload_run_artifacts(
        catalyst_app=catalyst_app,
        run_id=run_id,
        log_artifacts_dir=log_artifacts_dir,
    )

    # --- Send post-run email ---
    all_errors = result.errors + submission_failures
    builder = ReportBuilder()
    subject, html, attachment_csv = builder.build_error_report(
        errors=all_errors,
        month=month,
        year=year,
        dry_run=False,
    )
    email = EmailClient(
        api_key=os.getenv("RESEND_API_KEY"),
        from_address=os.getenv("RESEND_FROM_ADDRESS", "noreply@mountainleisureliving.com"),
    )
    email.send(
        to=REPORT_RECIPIENT,
        subject=subject,
        body_html=html,
        attachments=[
            {
                "content": attachment_csv,
                "filename": f"errors_{year}_{month:02d}.csv",
                "mime_type": "text/csv",
            }
        ],
    )
    logger.info(f"pipeline: post-run report sent — subject: {subject}")


def _build_run_summary(
    *,
    run_id: str,
    started_at: datetime,
    completed_at: datetime,
    order_count: int,
    request_ids: list,
    attempts_per_batch: list,
    submission_failures: list,
    submission_aborted: str = None,
) -> dict:
    retried_batches = [idx + 1 for idx, a in enumerate(attempts_per_batch) if a > 1]
    failed_batches = [
        idx + 1 for idx, a in enumerate(attempts_per_batch) if idx >= len(request_ids)
    ]
    return {
        "run_id": run_id,
        "started_at": started_at.isoformat(),
        "completed_at": completed_at.isoformat(),
        "orders_submitted": order_count,
        "batches": len(attempts_per_batch),
        "total_attempts": sum(attempts_per_batch),
        "retried_batches": retried_batches,
        "failed_batches": failed_batches,
        "request_ids": request_ids,
        "submission_aborted": submission_aborted,
        "needs_reconciliation": bool(submission_aborted),
        "orders_failed": len(submission_failures),
    }


def _upload_run_artifacts(
    *,
    catalyst_app,
    run_id: str,
    log_artifacts_dir: Path,
) -> None:
    """Best-effort upload of run-<id>.log.jsonl + run-<id>.summary.json to
    Catalyst File Store. Errors are logged but never raised."""
    if catalyst_app is None:
        logger.info(
            "pipeline: skipping File Store upload (no catalyst_app)",
            extra={"event": "pipeline.filestore.skipped", "fields": {"run_id": run_id}},
        )
        return

    folder_id = os.getenv(FILESTORE_FOLDER_ENV)
    if not folder_id:
        logger.warning(
            f"pipeline: {FILESTORE_FOLDER_ENV} not set — skipping File Store upload",
            extra={
                "event": "pipeline.filestore.skipped",
                "fields": {"run_id": run_id, "reason": "no_folder_id"},
            },
        )
        return

    artifact_paths = [
        log_artifacts_dir / f"run-{run_id}.log.jsonl",
        log_artifacts_dir / f"run-{run_id}.summary.json",
    ]
    for path in artifact_paths:
        if not path.exists():
            logger.warning(
                f"pipeline: artifact not found, skipping: {path}",
                extra={
                    "event": "pipeline.filestore.missing",
                    "fields": {"run_id": run_id, "path": str(path)},
                },
            )
            continue
        try:
            folder = catalyst_app.filestore().folder(folder_id)
            folder.upload_file(str(path))
            logger.info(
                f"pipeline: uploaded {path.name} to File Store folder {folder_id}",
                extra={
                    "event": "pipeline.filestore.uploaded",
                    "fields": {"run_id": run_id, "file": path.name},
                },
            )
        except Exception as exc:
            logger.error(
                f"pipeline: File Store upload failed for {path.name}: {exc}",
                extra={
                    "event": "pipeline.filestore.failed",
                    "fields": {
                        "run_id": run_id,
                        "file": path.name,
                        "error_class": type(exc).__name__,
                        "error_message": str(exc),
                    },
                },
                exc_info=True,
            )
