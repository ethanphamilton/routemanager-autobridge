"""Bi-monthly (every 2 weeks) membership handler."""

from typing import List
from .base import MembershipHandler
from ..models import Property, OrderInput, ServiceType
from ..scheduling import FrequencyCalculator


class BiMonthlyHandler(MembershipHandler):
    """Handler for bi-monthly (every 2 weeks) maintenance memberships."""

    DD_GROUP_MAP = {
        "Quarterly 1) Jan, Apr, Jul, Oct": 1,
        "Quarterly 2) Feb, May, Aug, Nov": 2,
        "Quarterly 3) Mar, Jun, Sep, Dec": 3,
        "Never": 0,
        "On Request": 0,
    }

    def generate_orders(self, property: Property, year: int, scheduler) -> List[OrderInput]:
        """Generate bi-monthly visits (every 14 days) + quarterly D&D.

        Args:
            property: Property details
            year: Year to generate orders for
            scheduler: GlobalScheduler for business day scheduling

        Returns:
            List of service orders
        """
        orders = []

        # Get start date based on service group
        start_date = self.service_group_manager.get_start_date(property.monthly_service_group, year)

        # Generate ideal biweekly visit dates
        ideal_visits = FrequencyCalculator.calculate_biweekly(year, start_date=start_date)

        # Schedule visits with business day adjustment
        pref_weekday = self._get_preferred_weekday(property)
        visit_dates = scheduler.schedule_property(
            property, ideal_visits, preferred_weekday=pref_weekday
        )

        dd_service_group = self._parse_dd_service_group(property.dd_service_group)

        if dd_service_group == 0:  # Never / On Request
            for d in visit_dates:
                orders.append(self._create_base_order(property, ServiceType.STANDARD, d))
            return orders

        # Select D&D directly from visit list to avoid cross-month errors
        dd_dates = self._find_quarterly_dd_from_biweekly(
            visit_dates, year, dd_service_group, pref_weekday
        )
        dd_set = set(dd_dates)

        for d in visit_dates:
            if d not in dd_set:
                orders.append(self._create_base_order(property, ServiceType.STANDARD, d))
        for d in dd_dates:
            orders.append(self._create_base_order(property, ServiceType.DRAIN, d))
            orders.append(self._create_base_order(property, ServiceType.FILL, d))

        return orders

    def _find_quarterly_dd_from_biweekly(
        self, visit_dates: list, year: int, service_group: int, pref_weekday
    ) -> list:
        """Select one D&D date per quarter from the biweekly visit schedule.

        Target months are determined by service_group:
          1 → Jan, Apr, Jul, Oct
          2 → Feb, May, Aug, Nov
          3 → Mar, Jun, Sep, Dec

        Picks the earliest preferred-day visit in the target month.
        Falls back to earliest available visit if no preferred-day visit exists.
        """
        target_months = [service_group + i * 3 for i in range(4)]

        dd_dates = []
        used: set = set()

        for month in target_months:
            month_visits = [
                d for d in visit_dates if d not in used and d.year == year and d.month == month
            ]
            if not month_visits:
                continue

            pref_candidates = (
                [d for d in month_visits if d.weekday() == pref_weekday]
                if pref_weekday is not None
                else []
            )
            chosen = min(pref_candidates) if pref_candidates else min(month_visits)

            dd_dates.append(chosen)
            used.add(chosen)

        return dd_dates
