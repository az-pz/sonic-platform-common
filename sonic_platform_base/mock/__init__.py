"""
sonic_platform_base.mock

Optional, opt-in helpers that allow a platform plugin to simulate SFP
insert/remove/error events from userspace without any hardware present.

A platform plugin enables the mock by having its ``Sfp`` class inherit
:class:`MockSfpMixin` and its ``Chassis`` class inherit
:class:`MockChassisMixin`.  When the on-disk sentinel file (or the
``MOCK_SFP=1`` environment variable) is not present, both mixins are
no-ops and the original hardware code paths run unchanged.
"""

from .backend import MockSfpBackend
from .sfp_mixin import MockSfpMixin
from .chassis_mixin import MockChassisMixin

__all__ = ["MockSfpBackend", "MockSfpMixin", "MockChassisMixin"]
