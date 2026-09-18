"""Note builder for service orders."""

from ..models import Property


class NoteBuilder:
    """Builds formatted notes for service orders."""

    @staticmethod
    def build_notes(property: Property) -> str:
        """Build comprehensive notes from property data.

        Args:
            property: Property with access and service information

        Returns:
            Formatted notes string
        """
        sanitizer_selection = property.sanitizer_selection or "Check with property manager"
        prefilter_needed = property.pre_filter_needed or ""
        erosion_drain = property.erosion_drain_instructions or ""

        home_access_code = property.home_access_code or "Call property manager if needed"
        neighborhood_access_code = (
            property.neighborhood_access_code or "Call property manager if needed"
        )
        neighborhood_access_instructions = property.neighborhood_access_instructions or ""

        property_access_instructions = property.property_access_instructions or ""
        home_access_instructions = property.home_access_instructions or ""

        turn_by_turn_directions = property.turn_by_turn_directions or ""
        internal_notes = property.internal_notes_for_techs or ""

        notes = (
            "Internal Notes:\n"
            f"{internal_notes}\n"
            "_____________\n"
            f"Sanitizer Selection: {sanitizer_selection}\n"
            f"Prefilter Needed for Refill: {prefilter_needed}\n"
            f"Erosion Drain or Special Draining Instructions: {erosion_drain}\n"
            "_____________\n"
            "Turn By Turn Directions:\n"
            f"{turn_by_turn_directions}\n"
            "_____________\n"
            f"Neighborhood Access Code: {neighborhood_access_code}\n"
            "Neighborhood Access Instructions:\n"
            f"{neighborhood_access_instructions}\n"
            "Property Access Instructions:\n"
            f"{property_access_instructions}\n"
            "Home Access Instructions:\n"
            f"{home_access_instructions}\n"
            f"Home Access Code: {home_access_code}"
        )

        return notes
