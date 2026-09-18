"""Weekday preference resolution."""

from typing import Optional
from ..models.enums import DayOfWeek


class WeekdayResolver:
    """Resolves preferred day of week from various formats."""

    @staticmethod
    def parse_preferred_day(day_str: Optional[str]) -> Optional[int]:
        """Parse the first preferred day to a weekday number.

        Args:
            day_str: Day string (e.g., "M", "T;R", "Any Day")

        Returns:
            Weekday number (0=Monday, 6=Sunday) or None if "Any Day"
        """
        days = WeekdayResolver.parse_preferred_days(day_str)
        return days[0] if days else None

    @staticmethod
    def parse_preferred_days(day_str: Optional[str]) -> list[int]:
        """Parse one or more preferred days to weekday numbers.

        Args:
            day_str: Day string (e.g., "M", "M;R", "Any Day")

        Returns:
            Ordered list of weekday numbers (0=Monday, 6=Sunday)
        """
        if not day_str or day_str.strip().lower() == "any day":
            return []

        tokens = [token.strip() for token in day_str.split(";") if token.strip()]
        days: list[int] = []

        for token in tokens:
            day_enum = DayOfWeek.from_code(token.upper())
            if day_enum is None:
                continue
            if day_enum.value not in days:
                days.append(day_enum.value)

        return days

    @staticmethod
    def format_preferred_days(day_str: Optional[str]) -> str:
        """Format preferred day string for WorkWave export.

        Args:
            day_str: Raw day string from input

        Returns:
            Formatted day string for export
        """
        if not day_str or day_str.strip().lower() == "any day":
            return "Any Day"

        # Pass through as-is for now
        # Can be enhanced to standardize format
        return day_str.strip()

    @staticmethod
    def get_day_name(weekday: int) -> str:
        """Get day name from weekday number.

        Args:
            weekday: Weekday number (0=Monday, 6=Sunday)

        Returns:
            Day name
        """
        days = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
        return days[weekday] if 0 <= weekday < 7 else "Unknown"
