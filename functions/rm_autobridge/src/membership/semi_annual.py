"""Semi-annual membership handler."""

import calendar
from datetime import date
from typing import List
from .base import MembershipHandler
from ..models import Property, OrderInput, ServiceType


class SemiAnnualHandler(MembershipHandler):
    """Handler for semi-annual drain and fill memberships."""

    DD_GROUP_MAP = {
        "Semi-Annual - Jan + Jul": 1,
        "Semi-Annual - Feb + Aug": 2,
        "Semi-Annual - Mar + Sep": 3,
        "Semi-Annual - Apr + Oct": 4,
        "Semi-Annual - May + Nov": 5,
        "Semi-Annual - Jun + Dec": 6,
    }

    def generate_orders(self, property: Property, year: int, scheduler) -> List[OrderInput]:
        """Generate semi-annual D&D orders (2 per year).

        Eligibility spans the full target month (Mon–Fri); RouteManager
        schedules the visit on the best available business day within that window.
        """
        dd_service_group = self._parse_dd_service_group(property.dd_service_group)

        target_months = [dd_service_group, dd_service_group + 6]

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
