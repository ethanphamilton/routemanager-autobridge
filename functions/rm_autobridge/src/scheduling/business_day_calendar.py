"""Business day calendar for scheduling validation."""

from datetime import date, timedelta
from typing import List, Set, Optional


class BusinessDayCalendar:
    """Manages valid business days, handling weekends and holidays."""

    # US Federal Holidays (static dates and calculated dates)
    FIXED_HOLIDAYS = [
        (1, 1),  # New Year's Day
        (7, 4),  # Independence Day
        (12, 24),  # Christmas Eve
        (12, 25),  # Christmas
    ]

    def __init__(self, year: int, custom_holidays: Optional[List[date]] = None):
        """Initialize calendar for a specific year.

        Args:
            year: Year for this calendar
            custom_holidays: Additional dates to treat as non-business days,
                on top of the standard federal holiday set
        """
        self.year = year
        self.holidays: Set[date] = self._get_holidays(year)
        if custom_holidays:
            self.holidays.update(custom_holidays)
        self.business_days: Set[date] = self._calculate_business_days(year)

    def _get_holidays(self, year: int) -> Set[date]:
        """Add holidays for the year."""
        holidays: Set[date] = set()

        holidays.add(self._nth_weekday(year, 11, 3, 4))  # Thanksgiving - 4th Thursday in November

        for month, day in self.FIXED_HOLIDAYS:
            holidays.add(date(year, month, day))

        return holidays

    def _calculate_business_days(self, year: int) -> Set[date]:
        """Pre-calculate all valid business days for the year.

        Returns:
            Set of all business days (Mon-Fri, excluding holidays)
        """
        business_days = set()
        current = date(year, 1, 1)
        year_end = date(year, 12, 31)

        while current <= year_end:
            if self._is_weekday(current) and current not in self.holidays:
                business_days.add(current)
            current += timedelta(days=1)

        return business_days

    def _nth_weekday(self, year: int, month: int, weekday: int, n: int) -> date:
        """Find the nth occurrence of a weekday in a month.

        Args:
            year: Year
            month: Month (1-12)
            weekday: Day of week (0=Monday, 6=Sunday)
            n: Which occurrence (1=first, 2=second, etc.)

        Returns:
            Date of the nth weekday
        """
        # Start with first day of month
        first_day = date(year, month, 1)
        first_weekday = first_day.weekday()  # Gets 0-6 representation of weekday of first day

        # Calculate days until first occurrence of target weekday
        days_until = (weekday - first_weekday) % 7

        # Add weeks to get to nth occurrence
        target_date = first_day + timedelta(days=days_until + (n - 1) * 7)

        return target_date

    def _last_weekday(self, year: int, month: int, weekday: int) -> date:
        """Find the last occurrence of a weekday in a month.

        Args:
            year: Year
            month: Month (1-12)
            weekday: Day of week (0=Monday, 6=Sunday)

        Returns:
            Date of the last occurrence
        """
        # Start with last day of month
        if month == 12:
            last_day = date(year, 12, 31)
        else:
            last_day = date(year, month + 1, 1) - timedelta(days=1)

        # Work backwards to find last occurrence of weekday
        days_back = (last_day.weekday() - weekday) % 7
        target_date = last_day - timedelta(days=days_back)

        return target_date

    @staticmethod
    def _is_weekday(d: date) -> bool:
        """Check if date is Monday-Friday."""
        return d.weekday() < 5

    def is_business_day(self, d: date) -> bool:
        """Check if a date is a valid business day.

        Args:
            d: Date to check

        Returns:
            True if date is a weekday and not a holiday
        """
        return d in self.business_days

    def next_business_day(self, d: date, prefer_weekday: Optional[int] = None) -> date:
        """Find the next business day, optionally preferring a specific weekday.

        Args:
            d: Starting date
            prefer_weekday: Optional preferred day of week (0=Monday, 6=Sunday)

        Returns:
            Next valid business day
        """
        # If no preference, just find next business day
        if prefer_weekday is None:
            current = d
            while not self.is_business_day(current):
                current += timedelta(days=1)
            return current

        # With preference, try to find nearest business day matching weekday
        # Search forward up to 7 days
        for days_ahead in range(7):
            candidate = d + timedelta(days=days_ahead)
            if self.is_business_day(candidate) and candidate.weekday() == prefer_weekday:
                return candidate

        # If no match found in next week, just return next business day
        return self.next_business_day(d, prefer_weekday=None)

    def get_business_days_in_month(self, month: int) -> List[date]:
        """Get all business days in a specific month.

        Args:
            month: Month (1-12)

        Returns:
            List of business days in the month, sorted
        """
        return sorted([d for d in self.business_days if d.month == month])

    def get_business_days_in_week(self, target_date: date) -> List[date]:
        """Get all business days in the same week as target date.

        Week is defined as Monday-Sunday containing the target date.

        Args:
            target_date: Any date in the target week

        Returns:
            List of business days in that week, sorted
        """
        # Find Monday of this week
        days_since_monday = target_date.weekday()
        week_start = target_date - timedelta(days=days_since_monday)

        # Collect business days for the week
        week_days = []
        for i in range(7):
            day = week_start + timedelta(days=i)
            if self.is_business_day(day):
                week_days.append(day)

        return week_days
