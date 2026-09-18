"""Global scheduler for load-balanced service date assignment."""

import random
from datetime import date, timedelta
from typing import List, Dict, Optional
from collections import defaultdict

from .business_day_calendar import BusinessDayCalendar
from ..models import Property


class GlobalScheduler:
    """Assigns service dates to properties with load balancing."""

    def __init__(self, calendar: BusinessDayCalendar):
        """Initialize scheduler with a business day calendar.

        Args:
            calendar: BusinessDayCalendar for the year
        """
        self.calendar = calendar
        self.daily_load: Dict[date, int] = defaultdict(int)

    def schedule_property(
        self, property: Property, pattern_dates: List[date], preferred_weekday: Optional[int] = None
    ) -> List[date]:
        """Schedule a single property, adjusting dates to business days.

        Args:
            property: Property being scheduled
            pattern_dates: Ideal dates from frequency calculation (may include weekends/holidays)
            preferred_weekday: Optional preferred day of week (0=Monday, 6=Sunday)

        Returns:
            List of actual scheduled dates (all business days)
        """
        scheduled = []

        for ideal_date in pattern_dates:
            # If preferred weekday specified and ideal date matches, use it
            if (
                preferred_weekday is not None
                and self.calendar.is_business_day(ideal_date)
                and ideal_date.weekday() == preferred_weekday
            ):
                actual_date = ideal_date
            else:
                # Either need to adjust to business day, honor preference, or load balance
                actual_date = self._find_best_business_day(
                    ideal_date, preferred_weekday=preferred_weekday
                )

            scheduled.append(actual_date)
            self.daily_load[actual_date] += 1

        return scheduled

    def _find_best_business_day(
        self, ideal_date: date, preferred_weekday: Optional[int] = None
    ) -> date:
        """Find the best business day near the ideal date.

        Strategy:
        1. If preferred_weekday specified, try to find that weekday in same week
        2. Otherwise, pick a random business day in the same week for load distribution
        3. If week has no business days (rare), move forward

        Args:
            ideal_date: Target date (may not be a business day)
            preferred_weekday: Optional preferred day of week

        Returns:
            Best available business day
        """
        # Get all business days in the same week
        week_business_days = self.calendar.get_business_days_in_week(ideal_date)

        if not week_business_days:
            # EDGE CASE: entire week is holidays, move forward
            return self.calendar.next_business_day(ideal_date)

        # If preferred weekday specified, try to use it
        if preferred_weekday is not None:
            matching_days = [d for d in week_business_days if d.weekday() == preferred_weekday]
            if matching_days:
                # Prefer the one closest to ideal date
                return min(
                    matching_days, key=lambda d: abs((d - ideal_date).days)
                )  # Currently we only parse the first preferred day. Could improve by parsing both.

        # No preference or preference not available - pick least loaded day in the week
        return self._pick_least_loaded_day(week_business_days)

    def _pick_least_loaded_day(self, candidate_days: List[date]) -> date:
        """Pick the least loaded day from candidates.

        If multiple days have same load, pick randomly for distribution.

        Args:
            candidate_days: List of possible dates

        Returns:
            Selected date
        """
        if not candidate_days:
            raise ValueError("No candidate days provided")

        # Find minimum load
        min_load = min(self.daily_load[d] for d in candidate_days)

        # Get all days with minimum load
        least_loaded = [d for d in candidate_days if self.daily_load[d] == min_load]

        # Randomly pick one if multiple options (for distribution)
        return random.choice(least_loaded)

    def get_load_summary(self) -> Dict[date, int]:
        """Get the current load for all scheduled days.

        Returns:
            Dictionary mapping dates to number of services scheduled
        """
        return dict(self.daily_load)

    def get_load_statistics(self) -> Dict[str, float]:
        """Get statistics about load distribution.

        Returns:
            Dictionary with mean, max, and min daily loads
        """
        if not self.daily_load:
            return {"mean": 0, "max": 0, "min": 0}

        loads = list(self.daily_load.values())
        return {"mean": sum(loads) / len(loads), "max": max(loads), "min": min(loads)}


class FrequencyCalculator:
    """Calculates ideal date patterns based on service frequency.

    This replaces the DateCalculator's complex logic with simpler patterns.
    """

    @staticmethod
    def calculate_weekly(year: int, start_date: Optional[date] = None) -> List[date]:
        """Calculate weekly service dates.

        Args:
            year: Year to generate for
            start_date: Optional start date (defaults to Jan 1)

        Returns:
            List of dates 7 days apart
        """
        if start_date is None:
            start_date = date(year, 1, 1)

        dates = []
        current = start_date
        year_end = date(year, 12, 31)

        while current <= year_end:
            dates.append(current)
            current += timedelta(days=7)

        return dates

    @staticmethod
    def calculate_biweekly(year: int, start_date: Optional[date] = None) -> List[date]:
        """Calculate bi-weekly service dates.

        Args:
            year: Year to generate for
            start_date: Optional start date (defaults to Jan 1)

        Returns:
            List of dates 14 days apart
        """
        if start_date is None:
            start_date = date(year, 1, 1)

        dates = []
        current = start_date
        year_end = date(year, 12, 31)

        while current <= year_end:
            dates.append(current)
            current += timedelta(days=14)

        return dates

    @staticmethod
    def calculate_twice_weekly(year: int, start_date: Optional[date] = None) -> List[date]:
        """Calculate twice-weekly service dates.

        Args:
            year: Year to generate for
            start_date: Optional start date (defaults to Jan 1)

        Returns:
            List of dates 3-4 days apart (targeting ~2x per week)
        """
        if start_date is None:
            start_date = date(year, 1, 1)

        dates = []
        current = start_date
        year_end = date(year, 12, 31)

        # Alternate between 3 and 4 day intervals for ~2x per week
        interval = 3

        while current <= year_end:
            dates.append(current)
            current += timedelta(days=interval)
            interval = 7 - interval  # Toggle between 3 and 4

        return dates

    @staticmethod
    def calculate_monthly(year: int, service_group: int) -> List[date]:
        """Calculate monthly service dates.

        Args:
            year: Year to generate for
            service_group: Week of month (1-4)

        Returns:
            List of 12 dates, one per month
        """
        dates = []

        for month in range(1, 13):
            # Target day in week of month
            target_day = (service_group - 1) * 7 + 4  # Middle of target week

            # Create date (will be adjusted to business day by scheduler)
            dates.append(date(year, month, min(target_day, 28)))

        return dates

    @staticmethod
    def calculate_quarterly(year: int, start_month: int) -> List[date]:
        """Calculate quarterly service dates.

        Args:
            year: Year to generate for
            start_month: Starting month (1-12)

        Returns:
            List of 4 dates, 3 months apart
        """
        dates = []
        months = []

        # Generate 4 quarters starting from start_month
        for i in range(4):
            month = start_month + (i * 3)
            if month > 12:
                month = month - 12
            months.append(month)

        # Use middle of month as target (will be adjusted by scheduler)
        for month in months:
            if month <= 12:
                dates.append(date(year, month, 15))

        return dates

    @staticmethod
    def calculate_semi_annual(year: int, service_group: int) -> List[date]:
        """Calculate semi-annual service dates.

        Args:
            year: Year to generate for
            service_group: Determines which months (1-6)

        Returns:
            List of 2 dates, 6 months apart
        """
        month_pairs = {
            1: [1, 7],
            2: [2, 8],
            3: [3, 9],
            4: [4, 10],
            5: [5, 11],
            6: [6, 12],
        }

        months = month_pairs.get(service_group, [1, 7])
        return [date(year, month, 15) for month in months]

    @staticmethod
    def calculate_annual(year: int, month: int) -> List[date]:
        """Calculate annual service date.

        Args:
            year: Year to generate for
            month: Target month (1-12)

        Returns:
            List with one date
        """
        return [date(year, month, 15)]
