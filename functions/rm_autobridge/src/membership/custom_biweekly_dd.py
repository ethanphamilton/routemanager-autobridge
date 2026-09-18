"""Custom bi-weekly D&D membership handler."""

from datetime import date
from typing import List
from .base import MembershipHandler
from ..models import Property, OrderInput, ServiceType
from ..scheduling import FrequencyCalculator


class CustomBiWeeklyDDHandler(MembershipHandler):
    """Handler for custom weekly maintenance with bi-weekly D&D.

    Package: "CUSTOM: Once Weekly Maintenance / Every Other Week Drain and Detail"
    - 52 weekly standard visits
    - 26 bi-weekly D&D
    - Result: 26 standard + 26 D&D per year (alternating weeks)
    """

    DD_GROUP_MAP = {
        "Every other Week: Cycle 1": 1,
        "Every other Week: Cycle 2": 2,
        "Every other Week: Weeks 1 & 3": 1,
        "Every other Week: Weeks 2 & 4": 2,
        "Never": 0,
    }

    def generate_orders(self, property: Property, year: int, scheduler) -> List[OrderInput]:
        """Generate weekly standard visits + bi-weekly D&D.

        Args:
            property: Property details
            year: Year to generate orders for
            scheduler: GlobalScheduler for business day scheduling

        Returns:
            List of service orders (26 standard + 26 D&D per year)
        """
        orders = []

        # Generate ideal weekly dates
        ideal_weekly = FrequencyCalculator.calculate_weekly(year, start_date=date(year, 1, 1))

        # Schedule weekly visits
        weekly_dates = scheduler.schedule_property(
            property, ideal_weekly, preferred_weekday=self._get_preferred_weekday(property)
        )

        # Get bi-weekly D&D start date based on service group
        dd_group = self._parse_dd_service_group(property.dd_service_group)
        if dd_group == 1:
            # Weeks 1 & 3 - start on week 1
            dd_start = date(year, 1, 1)
        else:
            # Weeks 2 & 4 - start on week 2 (add 7 days)
            dd_start = date(year, 1, 8)

        # Generate bi-weekly D&D ideal dates
        ideal_dd = FrequencyCalculator.calculate_biweekly(year, start_date=dd_start)

        # Schedule D&D dates
        dd_dates = scheduler.schedule_property(
            property, ideal_dd, preferred_weekday=self._get_preferred_weekday(property)
        )

        # Snap D&D to nearest recurring visit (replaces that week's standard visit)
        # This creates the alternating pattern: Week 1 = D&D, Week 2 = Standard, etc.
        weekly_dates, dd_dates = self._snap_dd_to_recurring_visits(weekly_dates, dd_dates)

        # Create standard visit orders
        for visit_date in weekly_dates:
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
