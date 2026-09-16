"""
sfp_mixin.py

Opt-in mixin for a platform plugin's ``Sfp`` class.  When the mock
backend's sentinel file (or ``MOCK_SFP=1``) is set, ``get_presence``,
``read_eeprom`` and ``get_error_description`` are routed through the
backend.  Otherwise calls fall through to the real ``Sfp`` implementation
via ``super()``.

Usage in the platform plugin::

    from sonic_platform_base.mock import MockSfpMixin
    from sonic_platform_base.sfp_base import SfpBase

    class Sfp(MockSfpMixin, SfpBase):
        def __init__(self, index, ...):
            self.index = index           # required: mock keys off this
            super().__init__(...)
            ...
"""

from __future__ import absolute_import

from .backend import (
    MockSfpBackend,
    STATUS_INSERTED,
    STATUS_REMOVED,
    STATUS_I2C_STUCK,
    STATUS_BAD_EEPROM,
    STATUS_UNSUPPORTED_CABLE,
    STATUS_HIGH_TEMPERATURE,
    STATUS_BAD_CABLE,
)


class MockSfpMixin(object):
    """Mixin that routes a few ``Sfp`` calls through ``MockSfpBackend``.

    The mixin reads ``self.index`` (1-based port number, matching SONiC
    convention) to address the backend.  The attribute must be set on the
    instance before any of the overridden methods is called.
    """

    # Subclasses can override this to point at a different backend instance,
    # e.g. for tests.  By default we use the process-wide singleton.
    _mock_backend = None

    def _get_mock_backend(self):
        backend = self._mock_backend
        if backend is None:
            backend = MockSfpBackend.instance()
        return backend

    def _mock_port_index(self):
        # SONiC platform plugins commonly use a 1-based ``index`` attribute
        # on ``Sfp``.  Fall back to ``port_num`` if a plugin uses that name.
        for attr in ('index', 'port_num', '_index', '_port_num'):
            if hasattr(self, attr):
                return getattr(self, attr)
        raise AttributeError(
            "MockSfpMixin requires the Sfp instance to expose 'index' "
            "(or 'port_num') for backend addressing"
        )

    # ------------------------------------------------------------------
    # Overrides
    # ------------------------------------------------------------------
    def get_presence(self):
        backend = self._get_mock_backend()
        if backend.enabled():
            return backend.get_presence(self._mock_port_index())
        return super(MockSfpMixin, self).get_presence()

    def read_eeprom(self, offset, num_bytes):
        backend = self._get_mock_backend()
        if backend.enabled():
            data = backend.read_eeprom(self._mock_port_index(), offset, num_bytes)
            if data is not None:
                return data
            # No EEPROM dump for this port -- fall through so the caller
            # gets the real hardware response (typically ``None`` for an
            # absent module), which keeps the contract intact.
        return super(MockSfpMixin, self).read_eeprom(offset, num_bytes)

    def get_error_description(self):
        backend = self._get_mock_backend()
        if backend.enabled():
            # Lazily import to avoid an import cycle.  ``SfpBase`` already
            # imports cleanly here because the mixin module is loaded by
            # the platform plugin _after_ ``sfp_base``.
            from ..sfp_base import SfpBase

            status = backend.get_status(self._mock_port_index())
            if status == STATUS_INSERTED:
                return SfpBase.SFP_STATUS_OK
            if status == STATUS_REMOVED:
                return SfpBase.SFP_STATUS_UNPLUGGED
            if status == STATUS_I2C_STUCK:
                return SfpBase.SFP_ERROR_DESCRIPTION_I2C_STUCK
            if status == STATUS_BAD_EEPROM:
                return SfpBase.SFP_ERROR_DESCRIPTION_BAD_EEPROM
            if status == STATUS_UNSUPPORTED_CABLE:
                return SfpBase.SFP_ERROR_DESCRIPTION_UNSUPPORTED_CABLE
            if status == STATUS_HIGH_TEMPERATURE:
                return SfpBase.SFP_ERROR_DESCRIPTION_HIGH_TEMP
            if status == STATUS_BAD_CABLE:
                return SfpBase.SFP_ERROR_DESCRIPTION_BAD_CABLE
        return super(MockSfpMixin, self).get_error_description()
