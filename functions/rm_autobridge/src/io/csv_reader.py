import io

from typing import List, Tuple
import pandas as pd
from ..config import get_config
from ..models import Frequency, Property
from ..utils import get_logger
from .validators import PropertyValidator


class CSVReader:
    def __init__(self):
        self.validator = PropertyValidator()
        self.logger = get_logger()
        self.config = get_config()

    def read_properties(self, input_bytes: bytes) -> Tuple[List[Property], List[dict]]:
        df = pd.read_csv(io.BytesIO(input_bytes))

        properties = []
        errors = []

        for idx, row in df.iterrows():
            row_data = row.to_dict()

            # Validate row
            is_valid, error_reason, should_skip = self.validator.validate_property(row_data)

            if should_skip:
                continue

            if not is_valid:
                errors.append(
                    {
                        **row_data,
                        "Error Reason": error_reason,
                        "Row Number": idx + 2,  # +2 for header and 0-indexing
                    }
                )
                continue

            # Parse into Property object
            try:
                property_obj = self._parse_property(row_data)
                properties.append(property_obj)
            except Exception as e:
                errors.append(
                    {**row_data, "Error Reason": f"Parsing error: {e!s}", "Row Number": idx + 2}
                )

        return properties, errors

    def _parse_property(self, row_data: dict) -> Property:
        """Parse row data into Property object.

        Args:
            row_data: Dictionary of property data

        Returns:
            Property instance
        """
        v = self.validator

        def _required_str(column: str) -> str:
            value, error = v.safe_str(row_data.get(column, ""), report_error=True)
            if error:
                raise ValueError(f"{column}: {error}")
            return value  # type: ignore[return-value]

        def _required_int(column: str, default: int = 0) -> int:
            value, error = v.safe_int(
                row_data.get(column, default), default=default, report_error=True
            )
            if error:
                raise ValueError(f"{column}: {error}")
            return value  # type: ignore[return-value]

        membership_type = _required_str("Maintenance Membership")

        # Determine whether monthly service group should be parsed
        frequency = None
        try:
            category = self.config.get_membership_category(membership_type)
            frequency = Frequency(category)
        except ValueError:
            # Unknown membership types fall back to no monthly group requirement
            frequency = None

        requires_monthly_group = frequency in (Frequency.MONTHLY, Frequency.BI_MONTHLY)

        monthly_service_group = None
        if requires_monthly_group:
            raw_msg = row_data.get("Monthly Service Group")
            if (
                raw_msg is None
                or raw_msg == ""
                or (isinstance(raw_msg, float) and pd.isna(raw_msg))
            ):
                raise ValueError("Monthly Service Group: Missing required value")
            monthly_service_group = _required_int("Monthly Service Group")
        else:
            monthly_service_group = None

        return Property(
            record_id=_required_str("Record Id"),
            property_name=_required_str("Property Name"),
            property_name_if_used=v.safe_str(
                row_data.get("Property Name if one is used"), default=None
            ),
            combined_address=_required_str("Combined Address"),
            maintenance_membership=membership_type,
            membership_status=_required_str("Membership Status"),
            dd_service_group=_required_str("Drain and Detail Group"),
            monthly_service_group=monthly_service_group,
            preferred_day_of_week=v.safe_str(row_data.get("Preferred Day of Week"), default=None),
            property_owners_name=v.safe_str(row_data.get("Property Owners Name"), default=None),
            property_managers_name=v.safe_str(row_data.get("Property Managers Name"), default=None),
            property_mgmt_company=v.safe_str(row_data.get("Property Mgmt Company"), default=None),
            property_owners_phone=v.safe_str(row_data.get("Property Owners Phone"), default=None),
            property_managers_phone=v.safe_str(
                row_data.get("Property Managers Phone"), default=None
            ),
            pm_phone=v.safe_str(row_data.get("PM Phone"), default=None),
            home_access_code=v.safe_str(row_data.get("Home Access Code"), default=None),
            home_access_instructions=v.safe_str(
                row_data.get("Home Access Instructions"), default=None
            ),
            neighborhood_access_code=v.safe_str(
                row_data.get("Neighborhood Access Code"), default=None
            ),
            neighborhood_access_instructions=v.safe_str(
                row_data.get("Neighborhood Access Instructions"), default=None
            ),
            property_access_code=v.safe_str(row_data.get("Property Access Code"), default=None),
            property_access_instructions=v.safe_str(
                row_data.get("Property Access Instructions"), default=None
            ),
            turn_by_turn_directions=v.safe_str(
                row_data.get("Turn By Turn Directions"), default=None
            ),
            internal_notes_for_techs=v.safe_str(
                row_data.get("Internal Notes for Techs Reference"), default=None
            ),
            sanitizer_selection=v.safe_str(row_data.get("Sanitizer Selection"), default=None),
            pre_filter_needed=v.safe_str(
                row_data.get("Pre-Filter Needed for Refill?"), default=None
            ),
            erosion_drain_instructions=v.safe_str(
                row_data.get("Erosion Drain Special Instructions"), default=None
            ),
            fill_time=v.safe_str(row_data.get("Fill Time"), default=None),
            must_confirm_drain=v.safe_str(
                row_data.get("Must Confirm Drain and Detail"), default=None
            ),
        )
