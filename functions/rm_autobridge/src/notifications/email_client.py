"""Resend email client."""

from typing import Optional
import resend


class EmailClient:
    def __init__(self, api_key: str, from_address: str):
        resend.api_key = api_key
        self.from_address = from_address

    def send(
        self,
        to: str,
        subject: str,
        body_html: str,
        attachments: Optional[list] = None,
    ) -> None:
        """Send an email via Resend.

        Args:
            to: Recipient address
            subject: Email subject line
            body_html: HTML body content
            attachments: Optional list of dicts with keys:
                  content (bytes), filename (str), mime_type (str)
        """
        params = {
            "from": self.from_address,
            "to": [to],
            "subject": subject,
            "html": body_html,
        }

        if attachments:
            params["attachments"] = [
                {
                    "filename": att["filename"],
                    "content": list(att["content"]),
                }
                for att in attachments
            ]

        resend.Emails.send(params)
