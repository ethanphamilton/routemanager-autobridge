"""Data validation utilities."""

import pandas as pd
from typing import Optional, Dict, Any, Tuple, Union
from ..models import MembershipStatus


class PropertyValidator:

    @staticmethod
    def validate_property(row_data: Dict[str, Any]) -> tuple[bool, Optional[str], bool]:
        """Validate a property row.

        Args:
            row_data: Dictionary of property data

        Returns:
            Tuple of (is_valid, error_reason, should_skip)
        """
        # Check membership status
        raw_status = row_data.get("Membership Status", "")
        status = "" if pd.isna(raw_status) else str(raw_status).strip()

        if status not in (
            MembershipStatus.ACTIVE.value,
            MembershipStatus.COMPLIMENTARY.value,
        ):
            return False, "Invalid Membership Status", True

        # Check for combined address (required)
        combined_address = row_data.get("Combined Address", "")
        if pd.isna(combined_address) or not combined_address.strip():
            return False, "Missing Combined Address", False

        # Check for membership type
        membership = row_data.get("Maintenance Membership", "")
        if pd.isna(membership) or not membership.strip():
            return False, "Missing Maintenance Membership Type", False

        return True, None, False

    @staticmethod
    def safe_int(
        value: Any, default: int = 0, report_error: bool = False
    ) -> Union[int, Tuple[int, Optional[str]]]:
        """Safely convert value to int, optionally reporting fallbacks.

        Args:
            value: Value to convert
            default: Default if conversion fails
            report_error: Whether to return a tuple of (value, error_message)

        Returns:
            Integer value or tuple of (int, Optional[str]) when ``report_error`` is True
        """
        if pd.isna(value):
            error = f"Missing integer value; using default {default}"
            return (default, error) if report_error else default

        try:
            int_value = int(value)
            return (int_value, None) if report_error else int_value
        except (ValueError, TypeError):
            error = f"Invalid integer '{value}'; using default {default}"
            return (default, error) if report_error else default

    @staticmethod
    def safe_str(
        value: Any, default: Optional[str] = "", report_error: bool = False
    ) -> Union[str, Tuple[Optional[str], Optional[str]]]:
        """Safely convert value to string, optionally reporting fallbacks.

        Args:
            value: Value to convert
            default: Default if value is NaN
            report_error: Whether to return a tuple of (value, error_message)

        Returns:
            String value or tuple of (str | None, Optional[str]) when ``report_error`` is True
        """
        if pd.isna(value):
            error = "Missing string value; using default"
            return (default, error) if report_error else default

        result = str(value).strip()
        return (result, None) if report_error else result
