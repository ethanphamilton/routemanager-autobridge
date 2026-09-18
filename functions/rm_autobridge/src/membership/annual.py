"""Annual membership handler."""

import calendar
from datetime import date
from typing import List
from .base import MembershipHandler
from ..models import Property, OrderInput, ServiceType


class AnnualHandler(MembershipHandler):
    """Handler for annual drain and fill memberships."""

    DD_GROUP_MAP = {
        "Annual - Jan": 1,
        "Annual - Feb": 2,
        "Annual - Mar": 3,
        "Annual - Apr": 4,
        "Annual - May": 5,
        "Annual - Jun": 6,
        "Annual - Jul": 7,
        "Annual - Aug": 8,
        "Annual - Sep": 9,
        "Annual - Oct": 10,
        "Annual - Nov": 11,
        "Annual - Dec": 12,
    }

    def generate_orders(self, property: Property, year: int, scheduler) -> List[OrderInput]:
        """Generate annual D&D orders (1 per year).

        Eligibility spans the full target month (Mon–Fri); RouteManager
        schedules the visit on the best available business day within that window.
        """
        dd_service_group = self._parse_dd_service_group(property.dd_service_group)

        month = dd_service_group
        month_start = date(year, month, 1)
        month_end = date(year, month, calendar.monthrange(year, month)[1])

        return [
            self._create_base_order(
                property=property,
                service_type=ServiceType.DRAIN,
                service_date=month_start,
                eligibility_end=month_end,
            ),
            self._create_base_order(
                property=property,
                service_type=ServiceType.FILL,
                service_date=month_start,
                eligibility_end=month_end,
            ),
        ]
