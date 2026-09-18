"""Phone number validation utilities."""

import re
from typing import Optional


class PhoneValidator:
    """Validates and formats phone numbers."""

    @staticmethod
    def validate_phone(phone: str) -> bool:
        """Check if phone number is valid.

        Args:
            phone: Phone number string

        Returns:
            True if valid phone number format
        """
        if not phone:
            return False

        # Remove common separators
        cleaned = re.sub(r"[\s\-\(\)\.]", "", phone)

        # Check if it's all digits and reasonable length
        return cleaned.isdigit() and 10 <= len(cleaned) <= 15

    @staticmethod
    def format_phone(phone: str) -> str:
        """Format phone number to standard format.

        Args:
            phone: Raw phone number

        Returns:
            Formatted phone number (or original if invalid)
        """
        if not phone:
            return ""

        # Remove common separators
        cleaned = re.sub(r"[\s\-\(\)\.]", "", phone)

        # If it's a valid 10-digit US number, format it
        if cleaned.isdigit() and len(cleaned) == 10:
            return f"({cleaned[:3]}) {cleaned[3:6]}-{cleaned[6:]}"

        # If 11 digits starting with 1, assume US with country code
        if cleaned.isdigit() and len(cleaned) == 11 and cleaned[0] == "1":
            return f"+1 ({cleaned[1:4]}) {cleaned[4:7]}-{cleaned[7:]}"

        # Otherwise return first 13 chars as-is (legacy behavior)
        return phone[:13]

    @staticmethod
    def get_valid_phone(
        phone: Optional[str], fallback: Optional[str] = "No Phone"
    ) -> Optional[str]:
        """Get valid phone or fallback.

        Args:
            phone: Phone number to validate
            fallback: Fallback value if invalid

        Returns:
            Valid phone number or fallback
        """
        if phone and PhoneValidator.validate_phone(phone):
            return PhoneValidator.format_phone(phone)
        return fallback
