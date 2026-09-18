from dataclasses import dataclass
from datetime import date, timedelta
from typing import Optional

from .enums import ServiceType


@dataclass
class OrderInput:
    name: str  # Format: "Property Name: Service Type"
    company: str
    zoho_id: str

    # Contact Information
    customer_phone: str
    auto_texting_phone: str

    # Service Location
    service_street: str
    service_city: str
    service_state: str
    service_zip: str

    # Service Details
    service_type: ServiceType
    service_time: int  # Minutes
    notes: str

    # Scheduling
    maintenance_frequency: str
    preferred_days: str
    eligibility_start: Optional[date] = None
    eligibility_end: Optional[date] = None
    verification_required: Optional[str] = None  # Must confirm Drain and Detail

    # Identifies which Autobridge run produced this order.
    # Set by OrderGenerator.generate(); validated at to_dict() time so every
    # order serialized to the WorkWave API carries the tag.
    run_id: str = ""

    def to_dict(self) -> dict:
        if not self.run_id:
            raise ValueError(
                "OrderInput.run_id must be set before serializing for WorkWave; "
                "OrderGenerator.generate() is responsible for tagging."
            )
        step = self._order_step_input()  # OrderStepInput dict

        is_service = self.service_type == ServiceType.STANDARD

        # WorkWave order type mapping:
        #   STANDARD → Service  (isService=True, delivery populated)
        #   DRAIN    → Drop-Off (delivery populated, pickup null)
        #   FILL     → Pick-up  (pickup populated, delivery null)
        pickup = step if self.service_type == ServiceType.FILL else None
        delivery = step if self.service_type in (ServiceType.DRAIN, ServiceType.STANDARD) else None

        return {
            "name": self.name,
            "eligibility": {"type": "on", "onDates": self._format_eligibility()},
            "forceVehicleId": None,
            "priority": 0,
            "loads": None,
            "pickup": pickup,
            "delivery": delivery,
            "isService": is_service,
            "acceptBadGeocodes": False,
            "companyId": None,
        }

    def _order_step_input(self) -> dict:
        return {
            "depotId": None,
            "location": {"address": self._format_address()},
            "timeWindows": None,
            "notes": self.notes,
            "email": None,
            "phone": self.customer_phone,
            "serviceTimeSec": int(self.service_time) * 60,
            "tagsIn": [],
            "tagsOut": [],
            "customFields": {
                "Zoho Id": self.zoho_id,
                "Client Phone": self.customer_phone,  # Phone must also be included in custom field or else technicians cannot see it
                "Prefered Days": self.preferred_days,
                "Service Type": self.service_type.value,
                "Maintenance Frequency": self.maintenance_frequency,
                "Autobridge Run": self.run_id,
                **({"Verification": "Must Confirm"} if self.verification_required else {}),
            },
            "barcodes": [],
            "acceptBadGeocodes": False,
        }

    def _format_address(self) -> str:
        """Build address string for WorkWave geocoding.

        When Zoho stores the full address in a single combined field, parse_address()
        returns the whole string as street with empty city/state/zip. In that case,
        just append ", USA" to the combined string rather than emitting ", ,  , USA".
        """
        parts = [self.service_street]
        if self.service_city:
            parts.append(self.service_city)
        state_zip = f"{self.service_state} {self.service_zip}".strip()
        if state_zip:
            parts.append(state_zip)
        parts.append("USA")
        return ", ".join(parts)

    def _format_eligibility(self) -> list[str]:
        """Expand the eligibility window into WorkWave's YYYYMMDD date list.

        Saturdays and Sundays are excluded. Tiers with no preferred day
        (annual, semi-annual, quarterly) are given a whole-month window and
        RouteManager picks the day within it, so without this filter those
        visits are eligible to be dispatched on a weekend. See
        PackageDescriptions.md, which specifies the month "except Saturdays
        and Sundays" for those tiers.

        Single-date orders come from the scheduler already snapped to a
        business day, so the filter is a no-op for them. If a window somehow
        contains no weekday at all, the unfiltered dates are returned rather
        than an empty list, which WorkWave would treat as unschedulable.
        """
        if not self.eligibility_start:
            return []
        start = self.eligibility_start
        end = self.eligibility_end or start
        every_day = []
        weekdays = []
        cur = start
        while cur <= end:
            every_day.append(cur.strftime("%Y%m%d"))
            if cur.weekday() < 5:
                weekdays.append(cur.strftime("%Y%m%d"))
            cur += timedelta(days=1)
        return weekdays or every_day
