"""Weekly membership handlers."""

from datetime import date
from .base import MembershipHandler
from ..models import Property, ServiceType
from ..scheduling import FrequencyCalculator


class WeeklyHandler(MembershipHandler):
    """Shared base for weekly maintenance memberships.

    Abstract: it carries the D&D cadence but no generation logic. Both
    concrete subclasses pick D&D dates from the already-scheduled weekly
    visit list rather than from an independent ideal-date pattern, which is
    what keeps a D&D from landing in a different week than the visit it
    replaces.
    """

    def __init__(self, dd_frequency: str = "quarterly"):
        """Initialize weekly handler.

        Args:
            dd_frequency: How often to do D&D (quarterly or monthly)
        """
        super().__init__()
        self.dd_frequency = dd_frequency


class WeeklyQuarterlyHandler(WeeklyHandler):
    """Weekly maintenance with quarterly D&D."""

    DD_GROUP_MAP = {
        "Quarterly 1) Jan, Apr, Jul, Oct": 1,
        "Quarterly 2) Feb, May, Aug, Nov": 2,
        "Quarterly 3) Mar, Jun, Sep, Dec": 3,
        "Never": 0,
        "On Request": 0,
    }

    def __init__(self):
        super().__init__(dd_frequency="quarterly")

    def generate_orders(self, property: Property, year: int, scheduler) -> list:
        """Generate weekly visits + quarterly D&D load-balanced across Week 1 and Week 2.

        Overrides WeeklyHandler to select D&D dates directly from the scheduled
        weekly visit list.  The base class approach uses calculate_quarterly + snap
        which crashes (undefined variable in calculate_quarterly) and would produce
        wrong-month placements even if fixed.

        D&D dates are chosen from the first two weeks (days 1-14) of each target
        month, with the scheduler's daily_load used to pick whichever of Week 1
        or Week 2 is less busy at generation time (~50/50 natural split).
        """
        orders = []

        ideal_weekly = FrequencyCalculator.calculate_weekly(year, start_date=date(year, 1, 1))
        pref_weekday = self._get_preferred_weekday(property)
        weekly_dates = scheduler.schedule_property(
            property, ideal_weekly, preferred_weekday=pref_weekday
        )

        dd_service_group = self._parse_dd_service_group(property.dd_service_group)

        if dd_service_group == 0:  # Never / On Request
            for d in weekly_dates:
                orders.append(self._create_base_order(property, ServiceType.STANDARD, d))
            return orders

        dd_dates = self._find_quarterly_dd_from_weekly(
            weekly_dates, year, dd_service_group, pref_weekday, scheduler
        )
        dd_set = set(dd_dates)

        for d in weekly_dates:
            if d not in dd_set:
                orders.append(self._create_base_order(property, ServiceType.STANDARD, d))
        for d in dd_dates:
            orders.append(self._create_base_order(property, ServiceType.DRAIN, d))
            orders.append(self._create_base_order(property, ServiceType.FILL, d))

        return orders

    def _find_quarterly_dd_from_weekly(
        self,
        weekly_dates: list,
        year: int,
        service_group: int,
        pref_weekday,
        scheduler,
    ) -> list:
        """Select one D&D date per quarter from the weekly visit schedule.

        Target months are determined by service_group:
          1 → Jan, Apr, Jul, Oct
          2 → Feb, May, Aug, Nov
          3 → Mar, Jun, Sep, Dec

        For each target month the D&D is placed in Week 1 (days 1-7) or Week 2
        (days 8-14), whichever has lower scheduler load at generation time, giving
        a natural ~50/50 split across all quarterly customers.  Prefers the visit
        on the preferred weekday within the chosen week; falls back to any visit
        in days 1-14 then any visit in the month if holidays force it.
        """
        target_months = [service_group + i * 3 for i in range(4)]  # always 1-12

        dd_dates = []
        used: set = set()

        for month in target_months:
            # Collect preferred-day candidates in Week 1 and Week 2
            def pref_visits(lo, hi, month=month):
                candidates = [
                    d
                    for d in weekly_dates
                    if d not in used
                    and d.year == year
                    and d.month == month
                    and lo <= d.day <= hi
                    and (pref_weekday is None or d.weekday() == pref_weekday)
                ]
                return min(candidates) if candidates else None

            w1 = pref_visits(1, 7)
            w2 = pref_visits(8, 14)

            if w1 and w2:
                # Both weeks have a preferred-day visit — pick the less loaded one
                chosen = w1 if scheduler.daily_load[w1] <= scheduler.daily_load[w2] else w2
            elif w1:
                chosen = w1
            elif w2:
                chosen = w2
            else:
                # No preferred-day visit in first two weeks (holiday fallback):
                # load-balance across any visit in days 1-14
                any_14 = [
                    d
                    for d in weekly_dates
                    if d not in used and d.year == year and d.month == month and 1 <= d.day <= 14
                ]
                if any_14:
                    chosen = min(any_14, key=lambda d: scheduler.daily_load[d])
                else:
                    # Last resort: any visit in the target month
                    month_visits = [
                        d
                        for d in weekly_dates
                        if d not in used and d.year == year and d.month == month
                    ]
                    if not month_visits:
                        continue
                    chosen = min(month_visits, key=lambda d: scheduler.daily_load[d])

            dd_dates.append(chosen)
            used.add(chosen)
            # Signal that this slot is now busier so subsequent properties
            # balance toward the other week rather than always picking Week 1.
            scheduler.daily_load[chosen] += 1

        return dd_dates


class WeeklyMonthlyHandler(WeeklyHandler):
    """Weekly maintenance with monthly D&D."""

    DD_GROUP_MAP = {
        "Week 1": 1,
        "Week 2": 2,
        "Week 3": 3,
        "Week 4": 4,
        "Never": 0,
    }

    def __init__(self):
        super().__init__(dd_frequency="monthly")

    def generate_orders(self, property, year: int, scheduler) -> list:
        """Generate weekly visits + monthly D&D on the preferred day.

        Overrides WeeklyHandler to select D&D dates directly from the scheduled
        weekly visit list rather than via calculate_monthly + snap.  The base
        approach misplaces D&D when the ideal target day (e.g. 4th of month)
        falls on a weekend, causing the scheduler to map it into the previous
        calendar month.  Selecting from the already-pinned weekly dates
        guarantees the D&D is always in the correct month and on the preferred
        day.
        """
        from ..models import ServiceType
        from ..scheduling import FrequencyCalculator
        from datetime import date

        orders = []

        ideal_weekly = FrequencyCalculator.calculate_weekly(year, start_date=date(year, 1, 1))
        weekly_dates = scheduler.schedule_property(
            property, ideal_weekly, preferred_weekday=self._get_preferred_weekday(property)
        )

        dd_service_group = self._parse_dd_service_group(property.dd_service_group)

        if dd_service_group == 0:  # "Never"
            for d in weekly_dates:
                orders.append(self._create_base_order(property, ServiceType.STANDARD, d))
            return orders

        pref_weekday = self._get_preferred_weekday(property)
        dd_dates = self._find_dd_from_weekly(weekly_dates, year, dd_service_group, pref_weekday)
        dd_set = set(dd_dates)
        standard_dates = [d for d in weekly_dates if d not in dd_set]

        for d in standard_dates:
            orders.append(self._create_base_order(property, ServiceType.STANDARD, d))
        for d in dd_dates:
            orders.append(self._create_base_order(property, ServiceType.DRAIN, d))
            orders.append(self._create_base_order(property, ServiceType.FILL, d))

        return orders

    def _find_dd_from_weekly(
        self, weekly_dates: list, year: int, service_group: int, pref_weekday: int = None
    ) -> list:
        """Select one D&D date per month directly from the weekly visit schedule.

        For each month picks the weekly visit that falls in the target calendar
        week (week N = days (N-1)*7+1 through N*7), preferring the visit on the
        preferred weekday when multiple visits fall in that window.  When a holiday
        pushes the preferred-day visit out of the target week entirely, falls back
        to the visit in that month closest to the middle of the target week.
        """
        week_start_day = (service_group - 1) * 7 + 1
        week_end_day = service_group * 7
        mid_target = (week_start_day + week_end_day) // 2

        dd_dates = []
        used: set = set()

        for month in range(1, 13):
            # Prefer a visit that falls exactly in the target calendar week
            in_target = [
                d
                for d in weekly_dates
                if d not in used
                and d.year == year
                and d.month == month
                and week_start_day <= d.day <= week_end_day
            ]

            if in_target:
                # Among candidates, prefer the one on the preferred weekday
                pref_candidates = (
                    [d for d in in_target if d.weekday() == pref_weekday]
                    if pref_weekday is not None
                    else []
                )
                chosen = min(pref_candidates) if pref_candidates else min(in_target)
            else:
                # Holiday pushed the visit out of the target week; use the
                # closest visit within this month.
                month_visits = [
                    d for d in weekly_dates if d not in used and d.year == year and d.month == month
                ]
                if not month_visits:
                    continue
                chosen = min(month_visits, key=lambda d: abs(d.day - mid_target))

            dd_dates.append(chosen)
            used.add(chosen)

        return dd_dates
