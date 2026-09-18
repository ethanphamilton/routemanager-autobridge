"""Base membership handler."""

from abc import ABC, abstractmethod
from typing import List, ClassVar, Optional
from ..models import Property, OrderInput


class MembershipHandler(ABC):
    """Abstract base class for membership-specific order generation."""

    DD_GROUP_MAP: ClassVar[dict[str, int]] = {}

    def __init__(self):
        """Initialize handler."""
        from ..config import get_config
        from ..scheduling import ServiceGroupManager, WeekdayResolver
        from ..processors import NoteBuilder

        self.config = get_config()
        self.service_group_manager = ServiceGroupManager()
        self.weekday_resolver = WeekdayResolver()
        self.note_builder = NoteBuilder()

    @abstractmethod
    def generate_orders(self, property: Property, year: int, scheduler) -> List[OrderInput]:
        """Generate all service orders for the property for the entire year.

        Args:
            property: Property details
            year: Year to generate orders for
            scheduler: GlobalScheduler for business day scheduling

        Returns:
            List of all service orders for the year
        """

    def _create_base_order(
        self,
        property: Property,
        service_type,
        service_date=None,
        eligibility_end=None,
    ) -> OrderInput:
        """Create a base OrderInput object with common fields.

        Args:
            property: Property object
            service_type: Type of service (ServiceType enum)
            service_date: Optional service date for eligibility

        Returns:
            OrderInput instance
        """

        street, city, state, zip_code = property.parse_address()

        service_time = self._resolve_service_time(service_type)
        notes = self._build_notes(property)

        return OrderInput(
            name=f"{property.get_property_display_name()}: {service_type.value}",
            company=property.property_mgmt_company or "",
            zoho_id=property.record_id,
            customer_phone=property.get_contact_phone(),
            auto_texting_phone=property.get_contact_phone(),
            service_street=street,
            service_city=city,
            service_state=state,
            service_zip=zip_code,
            service_type=service_type,
            service_time=service_time,
            notes=notes,
            maintenance_frequency=property.maintenance_membership,
            preferred_days=self.weekday_resolver.format_preferred_days(
                property.preferred_day_of_week
            ),
            eligibility_start=service_date,
            eligibility_end=eligibility_end if eligibility_end is not None else service_date,
            verification_required=self._derive_verification_required(property, service_type),
        )

    @staticmethod
    def _derive_verification_required(property, service_type) -> Optional[str]:
        """Normalize CRM's 'Must Confirm Drain and Detail' value.

        Only drain jobs are eligible; only the literal CRM value "Must confirm"
        (case-insensitive) maps through. Anything else — empty, None, "No",
        or any other Zoho picklist text — produces None.
        """
        from ..models import ServiceType

        if service_type != ServiceType.DRAIN:
            return None
        raw = property.must_confirm_drain
        if isinstance(raw, str) and raw.strip().lower() == "must confirm":
            return "Must confirm"
        return None

    def _get_preferred_weekday(self, property: Property) -> Optional[int]:
        """Get preferred weekday number from property.

        Args:
            property: Property details

        Returns:
            Weekday number (0-6) or None
        """
        return self.weekday_resolver.parse_preferred_day(property.preferred_day_of_week)

    def _snap_dd_to_recurring_visits(self, recurring_dates: List, dd_dates: List):
        """Snap D&D dates to nearest recurring visit dates.

        For weekly/bi-weekly customers, D&D should replace their normal visit
        for that period, not happen on a different date.

        Args:
            recurring_dates: List of all recurring visit dates
            dd_dates: List of D&D dates (may not align with recurring schedule)

        Returns:
            Tuple of (adjusted_recurring_dates, snapped_dd_dates):
                - adjusted_recurring_dates: Recurring dates with D&D dates removed
                - snapped_dd_dates: D&D dates snapped to nearest recurring visit
        """

        if not dd_dates or not recurring_dates:
            return recurring_dates, dd_dates

        snapped_dd_dates = []
        used_recurring_indices = set()

        # For each D&D date, find the closest recurring visit date
        for dd_date in dd_dates:
            min_diff = float("inf")
            closest_idx = None

            for idx, recurring_date in enumerate(recurring_dates):
                if idx in used_recurring_indices:
                    continue

                diff = abs((dd_date - recurring_date).days)
                if diff < min_diff:
                    min_diff = diff
                    closest_idx = idx

            if closest_idx is not None:
                # Snap D&D to this recurring visit date
                snapped_dd_dates.append(recurring_dates[closest_idx])
                used_recurring_indices.add(closest_idx)
            else:
                # Fallback: use original D&D date if no recurring visit found
                snapped_dd_dates.append(dd_date)

        # Remove recurring visits that were replaced by D&D
        adjusted_recurring_dates = [
            d for idx, d in enumerate(recurring_dates) if idx not in used_recurring_indices
        ]

        return adjusted_recurring_dates, snapped_dd_dates

    def _resolve_service_time(self, service_type):
        """Validate and fetch the service time for a given type."""

        if not hasattr(self.config, "get_service_time"):
            raise ValueError("Config is missing required get_service_time method.")

        label = service_type.value if hasattr(service_type, "value") else str(service_type)
        service_time = self.config.get_service_time(label)

        if service_time is None:
            raise ValueError(f"Service time for '{label}' is missing from configuration.")

        return service_time

    def _build_notes(self, property: Property) -> str:
        """Validate the NoteBuilder dependency and build notes."""

        if self.note_builder is None:
            raise ValueError("NoteBuilder dependency is not configured.")

        if not hasattr(self.note_builder, "build_notes"):
            raise ValueError("NoteBuilder is missing required build_notes method.")

        notes = self.note_builder.build_notes(property)

        if not notes:
            raise ValueError("NoteBuilder produced empty notes; check configuration.")

        return notes

    @classmethod
    def _parse_dd_service_group(cls, friendly_group: str) -> int:
        """Converts user friendly group names to Int."""
        if friendly_group is None:
            raise ValueError("Drain and Detail Group is missing.")

        try:
            return cls.DD_GROUP_MAP[friendly_group]
        except KeyError as e:
            raise ValueError(
                f"Missing or invalid Drain and Detail Group: {friendly_group!r}"
            ) from e
