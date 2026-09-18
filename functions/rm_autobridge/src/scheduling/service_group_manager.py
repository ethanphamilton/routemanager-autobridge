"""Service group management for visit distribution."""

from datetime import date
from ..config import get_config


class ServiceGroupManager:
    """Manages service group assignments and start date calculation."""

    def __init__(self):
        """Initialize with configuration."""
        self.config = get_config()

    def get_start_date(self, service_group: int, year: int) -> date:
        """Get the start date for a service group in a given year.

        Args:
            service_group: Service group number (1-4)
            year: Target year

        Returns:
            Start date for the service pattern
        """
        start_day, end_day = self.config.get_service_group_range(service_group)

        # Use the middle day of the range as start
        mid_day = (start_day + end_day) // 2

        return date(year, 1, mid_day)

    def distribute_to_groups(self, total_count: int, num_groups: int = 4) -> dict[int, int]:
        """Distribute a count across service groups evenly.

        Args:
            total_count: Total number to distribute
            num_groups: Number of groups (default 4)

        Returns:
            Dictionary mapping group number to count
        """
        base_count = total_count // num_groups
        remainder = total_count % num_groups

        distribution = {}
        for group in range(1, num_groups + 1):
            distribution[group] = base_count + (1 if group <= remainder else 0)

        return distribution

    def get_week_of_month(self, target_date: date) -> int:
        """Get which week of the month a date falls in (1-4+).

        Args:
            target_date: Date to check

        Returns:
            Week number (1-4, or 5 for 5-week months)
        """
        day = target_date.day

        if day <= 7:
            return 1
        elif day <= 14:
            return 2
        elif day <= 21:
            return 3
        elif day <= 28:
            return 4
        else:
            return 5
