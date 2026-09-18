"""Quarterly membership handler."""

import calendar
from datetime import date
from typing import List
from .base import MembershipHandler
from ..models import Property, OrderInput, ServiceType


class QuarterlyHandler(MembershipHandler):
    """Handler for quarterly drain and fill memberships."""

    DD_GROUP_MAP = {
        "Quarterly 1) Jan, Apr, Jul, Oct": 1,
        "Quarterly 2) Feb, May, Aug, Nov": 2,
        "Quarterly 3) Mar, Jun, Sep, Dec": 3,
    }

    def generate_orders(self, property: Property, year: int, scheduler) -> List[OrderInput]:
        """Generate quarterly D&D orders (4 per year).

        Eligibility spans the full target month (Mon–Fri); RouteManager
        schedules the visit on the best available business day within that window.
        """
        dd_service_group = self._parse_dd_service_group(property.dd_service_group)

        target_months = [dd_service_group + i * 3 for i in range(4)]

        orders = []
        for month in target_months:
            month_start = date(year, month, 1)
            month_end = date(year, month, calendar.monthrange(year, month)[1])
            orders.append(
                self._create_base_order(
                    property=property,
                    service_type=ServiceType.DRAIN,
                    service_date=month_start,
                    eligibility_end=month_end,
                )
            )
            orders.append(
                self._create_base_order(
                    property=property,
                    service_type=ServiceType.FILL,
                    service_date=month_start,
                    eligibility_end=month_end,
                )
            )

        return orders
