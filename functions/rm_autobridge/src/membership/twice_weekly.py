"""Twice weekly membership handler."""

from typing import List, Tuple
from datetime import date, timedelta
from .base import MembershipHandler
from ..models import Property, OrderInput, ServiceType


class TwiceWeeklyMonthlyHandler(MembershipHandler):
    """Handler for twice-weekly maintenance with monthly D&D."""

    DD_GROUP_MAP = {
        "Week 1": 1,
        "Week 2": 2,
        "Week 3": 3,
        "Week 4": 4,
        "Never": 0,
    }

    def generate_orders(self, property: Property, year: int, scheduler) -> List[OrderInput]:
        """Generate twice-weekly standard visits + monthly D&D.

        Args:
            property: Property details
            year: Year to generate orders for
            scheduler: GlobalScheduler for business day scheduling

        Returns:
            List of service orders (up to ~104 standard + 12 D&D per year)
        """
        orders = []

        preferred_days = self._get_two_preferred_days(property)

        # Generate visit dates week by week to guarantee one visit per preferred
        # day per week with no collisions (the two-independent-series approach
        # caused duplicates and wrong-weekday visits on holiday and year-boundary weeks).
        all_visit_dates = self._generate_twice_weekly_dates(year, preferred_days, scheduler)

        dd_service_group = self._parse_dd_service_group(property.dd_service_group)

        # "Never" → no D&D orders for this property
        if dd_service_group == 0:
            for visit_date in all_visit_dates:
                orders.append(
                    self._create_base_order(
                        property=property,
                        service_type=ServiceType.STANDARD,
                        service_date=visit_date,
                    )
                )
            return orders

        # Select D&D directly from visit list by calendar month + target week range.
        # Using calculate_monthly + ISO-week snap causes cross-month errors: when the
        # target day (e.g. day 4) falls on a Friday, the ISO week spans the previous
        # month and the snap jumps to that month's last Monday.
        dd_dates = self._find_dd_from_visits(all_visit_dates, year, dd_service_group)
        dd_set = set(dd_dates)
        all_visit_dates = [d for d in all_visit_dates if d not in dd_set]

        for visit_date in all_visit_dates:
            orders.append(
                self._create_base_order(
                    property=property, service_type=ServiceType.STANDARD, service_date=visit_date
                )
            )

        for dd_date in dd_dates:
            orders.append(
                self._create_base_order(
                    property=property, service_type=ServiceType.DRAIN, service_date=dd_date
                )
            )
            orders.append(
                self._create_base_order(
                    property=property, service_type=ServiceType.FILL, service_date=dd_date
                )
            )

        return orders

    def _generate_twice_weekly_dates(
        self, year: int, preferred_days: List[int], scheduler
    ) -> List[date]:
        """Generate visit dates by iterating week by week.

        For each week that overlaps the target year, assigns one visit per
        preferred day. If the preferred day is a holiday or weekend, falls back
        to the least-loaded available business day in that week that hasn't
        already been claimed by the other preferred day this week.

        Args:
            year: Target year
            preferred_days: Two weekday numbers (0=Mon … 6=Sun)
            scheduler: GlobalScheduler (daily_load updated in place)

        Returns:
            Sorted list of visit dates, all within the target year
        """
        calendar = scheduler.calendar
        result = []

        jan1 = date(year, 1, 1)
        year_end = date(year, 12, 31)

        # Start from the Monday of the week that contains Jan 1
        week_start = jan1 - timedelta(days=jan1.weekday())

        while week_start <= year_end:
            week_used = []  # dates claimed so far in this week

            for preferred_day in preferred_days:
                # Candidate date for this preferred day in this week
                target = week_start + timedelta(days=preferred_day)

                # Skip dates outside the target year
                if target.year != year:
                    continue

                if calendar.is_business_day(target) and target not in week_used:
                    chosen = target
                else:
                    # Preferred day is a holiday; find another business day
                    # in the same week that hasn't already been used this week.
                    week_bdays = calendar.get_business_days_in_week(target)
                    available = [d for d in week_bdays if d not in week_used]
                    if available:
                        # Pick least-loaded for load balancing
                        min_load = min(scheduler.daily_load[d] for d in available)
                        candidates = [d for d in available if scheduler.daily_load[d] == min_load]
                        chosen = min(candidates)  # deterministic: earliest of tied days
                    elif week_bdays:
                        # All business days in this week are already used by the
                        # other preferred day — skip this slot rather than duplicate.
                        continue
                    else:
                        # Entire week is holidays — skip
                        continue

                scheduler.daily_load[chosen] += 1
                week_used.append(chosen)
                result.append(chosen)

            week_start += timedelta(weeks=1)

        return sorted(result)

    def _get_two_preferred_days(self, property: Property) -> List[int]:
        """Get two preferred weekday numbers from property.

        Returns first and last parsed day for maximum spacing, or a sensible
        default pair when only one (or zero) days are specified.

        Returns:
            List of two weekday numbers (0-6), or [0, 3] as default (Mon, Thu)
        """
        days = self.weekday_resolver.parse_preferred_days(property.preferred_day_of_week)

        if len(days) >= 2:
            return [days[0], days[-1]]
        if len(days) == 1:
            return [days[0], (days[0] + 3) % 7]

        return [0, 3]  # Default: Monday and Thursday

    def _find_dd_from_visits(self, visit_dates: list, year: int, service_group: int) -> list:
        """Select one D&D date per month directly from the twice-weekly visit schedule.

        For each month picks the earliest visit that falls in the target calendar
        week (week N = days (N-1)*7+1 through N*7).  When no visit falls in the
        target window (holiday week), falls back to the visit in that month
        closest to the middle of the target week.
        """
        week_start_day = (service_group - 1) * 7 + 1
        week_end_day = service_group * 7
        mid_target = (week_start_day + week_end_day) // 2

        dd_dates = []
        used: set = set()

        for month in range(1, 13):
            in_target = [
                d
                for d in visit_dates
                if d not in used
                and d.year == year
                and d.month == month
                and week_start_day <= d.day <= week_end_day
            ]

            if in_target:
                chosen = min(in_target)
            else:
                month_visits = [
                    d for d in visit_dates if d not in used and d.year == year and d.month == month
                ]
                if not month_visits:
                    continue
                chosen = min(month_visits, key=lambda d: abs(d.day - mid_target))

            dd_dates.append(chosen)
            used.add(chosen)

        return dd_dates

    def _snap_dd_to_recurring_visits(
        self, recurring_dates: List, dd_dates: List
    ) -> Tuple[List, List]:
        """Override: snap each D&D to the FIRST recurring visit in its target week.

        The spec requires D&D on the first eligible day of the target week.
        The base implementation snaps to the nearest visit globally, which for a
        twice-weekly customer (e.g. M/R) would often land on the second visit of
        the week. This override finds all recurring visits in the same ISO week as
        the scheduled D&D date and picks the earliest one.
        """
        if not dd_dates or not recurring_dates:
            return recurring_dates, dd_dates

        snapped_dd_dates = []
        used_recurring_indices = set()

        for dd_date in dd_dates:
            dd_iso_year, dd_iso_week, _ = dd_date.isocalendar()

            same_week = [
                (idx, d)
                for idx, d in enumerate(recurring_dates)
                if idx not in used_recurring_indices
                and d.isocalendar()[:2] == (dd_iso_year, dd_iso_week)
            ]

            if same_week:
                chosen_idx, chosen_date = min(same_week, key=lambda x: x[1])
            else:
                # Fallback: nearest recurring visit globally (e.g. holiday week)
                candidates = [
                    (idx, d)
                    for idx, d in enumerate(recurring_dates)
                    if idx not in used_recurring_indices
                ]
                if not candidates:
                    snapped_dd_dates.append(dd_date)
                    continue
                chosen_idx, chosen_date = min(candidates, key=lambda x: abs((dd_date - x[1]).days))

            snapped_dd_dates.append(chosen_date)
            used_recurring_indices.add(chosen_idx)

        adjusted_recurring_dates = [
            d for idx, d in enumerate(recurring_dates) if idx not in used_recurring_indices
        ]

        return adjusted_recurring_dates, snapped_dd_dates
