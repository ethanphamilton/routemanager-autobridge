"""Property data model."""

from dataclasses import dataclass
from typing import Optional

from ..utils import PhoneValidator


@dataclass
class Property:
    """Represents a customer property with maintenance membership."""

    # Core identification
    record_id: str
    property_name: str
    combined_address: str

    # Membership details
    maintenance_membership: str
    membership_status: str

    # Scheduling parameters
    dd_service_group: int  # 1-12 depending on frequency
    monthly_service_group: Optional[int] = None  # 1-4 for week distribution when applicable
    preferred_day_of_week: Optional[str] = None  # M, T, W, R, F, S, U or "Any Day"

    # Contact information
    property_name_if_used: Optional[str] = None
    property_owners_name: Optional[str] = None
    property_managers_name: Optional[str] = None
    property_mgmt_company: Optional[str] = None
    property_owners_phone: Optional[str] = None
    property_managers_phone: Optional[str] = None
    pm_phone: Optional[str] = None

    # Access and instructions
    home_access_code: Optional[str] = None
    home_access_instructions: Optional[str] = None
    neighborhood_access_code: Optional[str] = None
    neighborhood_access_instructions: Optional[str] = None
    property_access_code: Optional[str] = None
    property_access_instructions: Optional[str] = None
    turn_by_turn_directions: Optional[str] = None
    internal_notes_for_techs: Optional[str] = None

    # Service specifics
    sanitizer_selection: Optional[str] = None
    pre_filter_needed: Optional[str] = None
    erosion_drain_instructions: Optional[str] = None
    fill_time: Optional[str] = None
    must_confirm_drain: Optional[str] = None  # Either "Must confirm" or None

    # Additional metadata
    tag: Optional[str] = None

    def get_contact_name(self) -> str:
        """Get primary contact name (owner > manager > company)."""
        if self.property_owners_name:
            return self.property_owners_name
        elif self.property_managers_name:
            return self.property_managers_name
        elif self.property_mgmt_company:
            return self.property_mgmt_company
        return "No Contact Name"

    def get_contact_phone(self) -> str:
        """Get contact phone number with validation (owner > manager > PM)."""
        for phone in [self.property_owners_phone, self.property_managers_phone, self.pm_phone]:
            result = PhoneValidator.get_valid_phone(phone, fallback=None)
            if result:
                return result
        return "000-000-0000"

    def get_property_display_name(self) -> str:
        """Get property name with fallback priority: used name > owner name > address.

        Skips numeric values (e.g. Zoho record IDs accidentally entered in name fields).
        """
        for candidate in [self.property_name_if_used, self.property_owners_name]:
            if candidate:
                try:
                    float(candidate)
                except (ValueError, TypeError):
                    return candidate
        return self.combined_address

    def parse_address(self) -> tuple[str, str, str, str]:
        """Parse combined address into components.

        Returns:
            Tuple of (street, city, state, zip)
        """
        if not self.combined_address:
            return ("", "", "", "")

        # Assuming format: "Street, City, State Zip"
        parts = self.combined_address.split(",")
        if len(parts) < 3:
            return (self.combined_address, "", "", "")

        street = parts[0].strip()
        city = parts[1].strip()

        # Split state and zip
        state_zip = parts[2].strip().split()
        state = state_zip[0] if len(state_zip) > 0 else ""
        zip_code = state_zip[1][:5] if len(state_zip) > 1 else ""

        return (street, city, state, zip_code)
