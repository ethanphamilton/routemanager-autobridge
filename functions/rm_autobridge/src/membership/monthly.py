"""Monthly membership handler."""

from typing import List
from .base import MembershipHandler
from ..models import Property, OrderInput, ServiceType
from ..scheduling import FrequencyCalculator  # used by generate_orders via scheduler


class MonthlyHandler(MembershipHandler):
    """Handler for monthly maintenance memberships."""

    DD_GROUP_MAP = {
        "Quarterly 1) Jan, Apr, Jul, Oct": 1,
        "Quarterly 2) Feb, May, Aug, Nov": 2,
        "Quarterly 3) Mar, Jun, Sep, Dec": 3,
        "Never": 0,
        "On Request": 0,
    }

    VALID_MONTHLY_SERVICE_GROUPS = {1, 2, 3, 4}

    def generate_orders(self, property: Property, year: int, scheduler) -> List[OrderInput]:
        """Generate monthly standard visits + quarterly D&D.

        Args:
            property: Property details
            year: Year to generate orders for
            scheduler: GlobalScheduler for business day scheduling

        Returns:
            List of service orders
        """
        if property.monthly_service_group not in self.VALID_MONTHLY_SERVICE_GROUPS:
            raise ValueError(
                f"Missing or invalid Monthly Service Group: {property.monthly_service_group!r}"
            )

        dd_service_group = self._parse_dd_service_group(
            property.dd_service_group
        )  # Raises ValueError with Reason

        orders = []
        preferred_weekday = self._get_preferred_weekday(property)

        # Generate ideal monthly visit dates
        monthly_service_group = property.monthly_service_group
        ideal_monthly = FrequencyCalculator.calculate_monthly(
            year, service_group=monthly_service_group
        )

        # Schedule monthly visits
        monthly_dates = scheduler.schedule_property(
            property, ideal_monthly, preferred_weekday=preferred_weekday
        )

        # Select D&D directly from the monthly visit list to avoid cross-month errors
        if dd_service_group != 0:
            dd_dates = self._find_quarterly_dd_from_monthly(monthly_dates, year, dd_service_group)
        else:
            dd_dates = []

        dd_set = set(dd_dates)
        monthly_dates = [d for d in monthly_dates if d not in dd_set]

        # Create standard visit orders
        for visit_date in monthly_dates:
            standard_order = self._create_base_order(
                property=property, service_type=ServiceType.STANDARD, service_date=visit_date
            )
            orders.append(standard_order)

        # Create D&D orders
        for dd_date in dd_dates:
            # Create drain order
            drain_order = self._create_base_order(
                property=property, service_type=ServiceType.DRAIN, service_date=dd_date
            )
            orders.append(drain_order)

            # Create fill order
            fill_order = self._create_base_order(
                property=property, service_type=ServiceType.FILL, service_date=dd_date
            )
            orders.append(fill_order)

        return orders

    def _find_quarterly_dd_from_monthly(
        self, monthly_dates: list, year: int, service_group: int
    ) -> list:
        """Select one D&D date per quarter from the monthly visit schedule.

        Target months are determined by service_group:
          1 → Jan, Apr, Jul, Oct
          2 → Feb, May, Aug, Nov
          3 → Mar, Jun, Sep, Dec

        Each monthly customer has exactly one visit per target month, so we
        just pick that visit. Falls back to any visit in the month if the
        target month has no visit (e.g. holiday edge case).
        """
        target_months = [service_group + i * 3 for i in range(4)]

        dd_dates = []
        used: set = set()

        for month in target_months:
            month_visits = [
                d for d in monthly_dates if d not in used and d.year == year and d.month == month
            ]
            if not month_visits:
                continue
            chosen = min(month_visits)
            dd_dates.append(chosen)
            used.add(chosen)

        return dd_dates
