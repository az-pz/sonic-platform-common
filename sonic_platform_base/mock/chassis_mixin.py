"""
chassis_mixin.py

Opt-in mixin for a platform plugin's ``Chassis`` class.  Overrides
``get_change_event`` to diff snapshots from :class:`MockSfpBackend`.
When the backend is not enabled the call delegates to ``super()``, so
production hardware paths run unchanged.

Usage in the platform plugin::

    from sonic_platform_base.mock import MockChassisMixin
    from sonic_platform_base.chassis_base import ChassisBase

    class Chassis(MockChassisMixin, ChassisBase):
        ...
"""

from __future__ import absolute_import

import time

from .backend import MockSfpBackend


# Poll interval in seconds used while waiting for a change.
_POLL_INTERVAL_S = 0.5


class MockChassisMixin(object):
    """Add mock-aware ``get_change_event`` to a ``Chassis`` class."""

    _mock_backend = None
    # Cached previous snapshot and "first call" flag, lazily initialised
    # so subclasses don't have to remember to call our ``__init__``.
    _mock_prev_snapshot = None
    _mock_first_call_done = False

    def _get_mock_backend(self):
        backend = self._mock_backend
        if backend is None:
            backend = MockSfpBackend.instance()
        return backend

    def get_change_event(self, timeout=0):
        backend = self._get_mock_backend()
        if not backend.enabled():
            return super(MockChassisMixin, self).get_change_event(timeout)

        # First call after construction: capture the snapshot and return
        # an empty event so xcvrd performs its initial discovery pass via
        # get_presence.
        if not self._mock_first_call_done:
            self._mock_prev_snapshot = backend.snapshot()
            self._mock_first_call_done = True
            return (True, {'sfp': {}})

        deadline = None
        if timeout and timeout > 0:
            deadline = time.monotonic() + (timeout / 1000.0)

        while True:
            new_snap = backend.snapshot()
            diff = self._diff_snapshot(self._mock_prev_snapshot or {}, new_snap)
            if diff:
                self._mock_prev_snapshot = new_snap
                return (True, {'sfp': diff})

            if deadline is None:
                # Block forever (timeout == 0): keep polling.
                time.sleep(_POLL_INTERVAL_S)
                continue

            remaining = deadline - time.monotonic()
            if remaining <= 0:
                # Refresh the cached snapshot so the next call's diff is
                # still anchored to a recent state.
                self._mock_prev_snapshot = new_snap
                return (True, {'sfp': {}})
            time.sleep(min(_POLL_INTERVAL_S, remaining))

    @staticmethod
    def _diff_snapshot(old, new):
        """Return a ``{port: status_code}`` diff between two snapshots.

        - Ports that vanished from ``new`` are reported as removed (``'0'``).
        - Ports that appeared in ``new`` are reported with their status.
        - Ports present in both are reported only when the status changed.
        """
        diff = {}
        for port, status in new.items():
            if old.get(port) != status:
                diff[str(port)] = status
        for port in old:
            if port not in new:
                diff[str(port)] = '0'
        return diff
