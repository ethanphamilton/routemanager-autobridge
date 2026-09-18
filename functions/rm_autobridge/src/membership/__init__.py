"""Membership handlers module."""

from .base import MembershipHandler
from .factory import MembershipFactory
from .annual import AnnualHandler
from .semi_annual import SemiAnnualHandler
from .quarterly import QuarterlyHandler
from .monthly import MonthlyHandler
from .bimonthly import BiMonthlyHandler
from .weekly import WeeklyHandler, WeeklyQuarterlyHandler, WeeklyMonthlyHandler
from .twice_weekly import TwiceWeeklyMonthlyHandler
from .custom_biweekly_dd import CustomBiWeeklyDDHandler

from ..models import Frequency

# Register all handlers
MembershipFactory.register_handler(Frequency.ANNUAL, AnnualHandler)
MembershipFactory.register_handler(Frequency.SEMI_ANNUAL, SemiAnnualHandler)
MembershipFactory.register_handler(Frequency.QUARTERLY, QuarterlyHandler)
MembershipFactory.register_handler(Frequency.MONTHLY, MonthlyHandler)
MembershipFactory.register_handler(Frequency.BI_MONTHLY, BiMonthlyHandler)
MembershipFactory.register_handler(Frequency.WEEKLY, WeeklyQuarterlyHandler)
MembershipFactory.register_handler(Frequency.WEEKLY_MONTHLY, WeeklyMonthlyHandler)
MembershipFactory.register_handler(Frequency.TWICE_WEEKLY, TwiceWeeklyMonthlyHandler)
MembershipFactory.register_handler(Frequency.CUSTOM_BIWEEKLY_DD, CustomBiWeeklyDDHandler)

__all__ = [
    "MembershipHandler",
    "MembershipFactory",
    "AnnualHandler",
    "SemiAnnualHandler",
    "QuarterlyHandler",
    "MonthlyHandler",
    "BiMonthlyHandler",
    "WeeklyHandler",
    "WeeklyQuarterlyHandler",
    "WeeklyMonthlyHandler",
    "TwiceWeeklyMonthlyHandler",
    "CustomBiWeeklyDDHandler",
]
