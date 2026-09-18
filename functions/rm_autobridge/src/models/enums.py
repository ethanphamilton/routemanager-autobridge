"""Enumerations for the RouteManager system."""

from enum import Enum


class ServiceType(Enum):
    """Types of service orders."""

    STANDARD = "Weekly"
    DRAIN = "Drain"
    FILL = "Fill"


class Frequency(Enum):
    """Maintenance frequency categories."""

    ANNUAL = "annual"
    SEMI_ANNUAL = "semi_annual"
    QUARTERLY = "quarterly"
    MONTHLY = "monthly"
    BI_MONTHLY = "bi_monthly"
    WEEKLY = "weekly"
    WEEKLY_MONTHLY = "weekly_monthly"  # Weekly with monthly D&D (vacation rentals)
    TWICE_WEEKLY = "twice_weekly"
    CUSTOM_BIWEEKLY_DD = "custom_biweekly_dd"  # Weekly with bi-weekly D&D
    MANUAL = "manual"


class MembershipStatus(Enum):
    """Customer membership status."""

    ACTIVE = "Active Maintenance Member"
    COMPLIMENTARY = "Complimentary Maintenance Member"
    INACTIVE = "Inactive"


class DayOfWeek(Enum):
    """Days of the week."""

    MONDAY = 0
    TUESDAY = 1
    WEDNESDAY = 2
    THURSDAY = 3
    FRIDAY = 4
    SATURDAY = 5
    SUNDAY = 6

    @classmethod
    def from_code(cls, code: str) -> "DayOfWeek":
        """Convert day code (M, T, W, R, F, S, U) to DayOfWeek enum."""
        mapping = {
            "M": cls.MONDAY,
            "T": cls.TUESDAY,
            "W": cls.WEDNESDAY,
            "R": cls.THURSDAY,
            "F": cls.FRIDAY,
            "S": cls.SATURDAY,
            "U": cls.SUNDAY,
        }
        return mapping.get(code.upper())
