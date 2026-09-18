"""Builds email reports from GenerationResult."""

import csv
import io
from datetime import date


class ReportBuilder:

    def build_error_report(
        self,
        errors: list[dict],
        month: int,
        year: int,
        dry_run: bool = True,
    ) -> tuple[str, str, bytes]:
        """Build subject, HTML body, and CSV attachment for an error report.

        Args:
            errors: List of error dicts from GenerationResult
            month: Target month
            year: Target year
            dry_run: True for pre-run audit report, False for post-run summary

        Returns:
            (subject, html_body, csv_bytes)
        """
        month_name = date(year, month, 1).strftime("%B %Y")
        label = "Pre-Run Audit" if dry_run else "Post-Run Summary"
        count = len(errors)

        error_summary = "No errors" if count == 0 else f"{count} error{'s' if count != 1 else ''}"
        subject = f"RM-Autobridge {label} — {month_name} — {error_summary}"

        html = self._build_html(errors, month_name, label, dry_run)
        csv_bytes = self._build_csv(errors)

        return subject, html, csv_bytes

    def _build_html(self, errors: list[dict], month_name: str, label: str, dry_run: bool) -> str:
        count = len(errors)

        if dry_run:
            intro = (
                f"This is the automated pre-run audit for <strong>{month_name}</strong>. "
                f"The properties listed below have errors that will prevent them from being loaded to RouteManager. "
                f"If these are not corrected in Zoho CRM before the 26th at 8 AM, "
                f"they will need to be scheduled manually for the month."
            )
        else:
            intro = (
                f"The RouteManager load for <strong>{month_name}</strong> has completed. "
                f"The properties below failed and were not loaded to RouteManager. "
                f"Manual scheduling may be required."
            )

        if count == 0:
            body = "<p style='color:green;'>&#10003; No errors — all properties processed successfully.</p>"
        else:
            rows = "".join(
                f"<tr>"
                f"<td style='padding:4px 12px;border:1px solid #ddd;'>{e.get('Property Name', '—')}</td>"
                f"<td style='padding:4px 12px;border:1px solid #ddd;'>{e.get('Error Reason', '—')}</td>"
                f"</tr>"
                for e in errors
            )
            body = f"""
            <table style='border-collapse:collapse;font-family:sans-serif;font-size:14px;'>
              <thead>
                <tr style='background:#f2f2f2;'>
                  <th style='padding:6px 12px;border:1px solid #ddd;text-align:left;'>Property</th>
                  <th style='padding:6px 12px;border:1px solid #ddd;text-align:left;'>Error Reason</th>
                </tr>
              </thead>
              <tbody>{rows}</tbody>
            </table>
            """

        return f"""
        <html><body style='font-family:sans-serif;font-size:14px;color:#333;'>
          <h2>RM-Autobridge {label} — {month_name}</h2>
          <p>{intro}</p>
          <p><strong>{count} error{'s' if count != 1 else ''}</strong></p>
          {body}
          <hr/>
          <p style='font-size:12px;color:#999;'>
            A full error CSV is attached. This email was generated automatically by RM-Autobridge.
          </p>
        </body></html>
        """

    def _build_csv(self, errors: list[dict]) -> bytes:
        if not errors:
            return b"Property Name,Record Id,Error Reason\n"

        fields = ["Property Name", "Record Id", "Error Reason"]
        buf = io.StringIO()
        writer = csv.DictWriter(buf, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(errors)
        return buf.getvalue().encode()
