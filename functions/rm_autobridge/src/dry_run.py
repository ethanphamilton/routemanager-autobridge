"""Dry-run error audit — pull from Zoho, generate, email error report."""

import os
from pathlib import Path
from dotenv import load_dotenv

from .io.zoho_client import ZohoClient
from .processors.order_generator import OrderGenerator
from .notifications import EmailClient, ReportBuilder
from .utils import get_logger

logger = get_logger()

REPORT_RECIPIENT = "maintenance@mountainleisureliving.com"
_FUNCTION_DIR = Path(__file__).resolve().parent.parent


def run(month: int, year: int, *, run_id: str):
    """Run the dry-run error audit for the given month/year.

    Pulls from Zoho, generates orders, and emails an error report to the
    maintenance inbox without submitting anything to WorkWave.

    Args:
        month: Target month (1-12).
        year: Target year.
        run_id: Autobridge run identifier — required for order generation
            even though no orders are submitted, so the generation pass
            mirrors the real pipeline.
    """
    if not run_id:
        raise ValueError("dry_run.run: run_id must be a non-empty string")

    load_dotenv(_FUNCTION_DIR / ".env")  # no-op in Catalyst; env vars set via console

    missing = [
        k
        for k in ("ZOHO_ACCOUNTS_URL", "ZOHO_CLIENT_ID", "ZOHO_CLIENT_SECRET", "ZOHO_REFRESH_TOKEN")
        if not os.getenv(k)
    ]
    if missing:
        logger.error(f"dry_run: missing env vars: {missing}")
        return

    logger.info(f"dry_run: running audit for {month}/{year} (run_id={run_id})")

    zoho = ZohoClient(
        accounts_url=os.getenv("ZOHO_ACCOUNTS_URL"),
        client_id=os.getenv("ZOHO_CLIENT_ID"),
        client_secret=os.getenv("ZOHO_CLIENT_SECRET"),
        refresh_token=os.getenv("ZOHO_REFRESH_TOKEN"),
        api_domain=os.getenv("ZOHO_API_DOMAIN"),
    )
    csv_bytes = zoho.get_properties()
    logger.info(f"dry_run: fetched {len(csv_bytes):,} bytes from Zoho")

    generator = OrderGenerator()
    result = generator.generate(csv_bytes, month=month, year=year, run_id=run_id)
    logger.info(
        f"dry_run: {result.total_properties} properties, " f"{result.failed_properties} errors"
    )

    builder = ReportBuilder()
    subject, html, attachment_csv = builder.build_error_report(
        errors=result.errors,
        month=month,
        year=year,
        dry_run=True,
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
    logger.info(f"dry_run: report sent to {REPORT_RECIPIENT} — subject: {subject}")
