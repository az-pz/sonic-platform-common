"""Tests for :class:`MockChassisMixin.get_change_event`."""

import pytest

from sonic_platform_base.mock.backend import (
    MockSfpBackend,
    STATUS_BAD_EEPROM,
    STATUS_INSERTED,
    STATUS_REMOVED,
)
from sonic_platform_base.mock import chassis_mixin
from sonic_platform_base.mock.chassis_mixin import MockChassisMixin


class _FakeRealChassis(object):
    def __init__(self):
        self.real_calls = []

    def get_change_event(self, timeout=0):
        self.real_calls.append(timeout)
        return (True, {'sfp': {'__real__': '1'}})


class _MockChassis(MockChassisMixin, _FakeRealChassis):
    def __init__(self, backend):
        super(_MockChassis, self).__init__()
        self._mock_backend = backend


@pytest.fixture(autouse=True)
def _no_sleep(monkeypatch):
    """Skip real sleeping so tests run quickly."""
    monkeypatch.setattr(chassis_mixin.time, 'sleep', lambda _s: None)
    MockSfpBackend._reset_singletons_for_tests()
    yield
    MockSfpBackend._reset_singletons_for_tests()


def _make(tmp_path, enabled=True):
    backend = MockSfpBackend(str(tmp_path))
    if enabled:
        backend.set_enabled(True)
    return backend, _MockChassis(backend)


def test_disabled_falls_through(tmp_path):
    backend, chassis = _make(tmp_path, enabled=False)
    ok, payload = chassis.get_change_event(timeout=123)
    assert ok is True
    assert payload == {'sfp': {'__real__': '1'}}
    assert chassis.real_calls == [123]


def test_first_call_returns_empty_and_seeds_snapshot(tmp_path):
    backend, chassis = _make(tmp_path)
    backend.set_presence(0, True)
    backend.set_presence(1, False)

    ok, payload = chassis.get_change_event(timeout=100)
    assert ok is True
    assert payload == {'sfp': {}}
    assert chassis._mock_first_call_done is True
    assert chassis._mock_prev_snapshot == {0: STATUS_INSERTED, 1: STATUS_REMOVED}


def test_detects_insert(tmp_path):
    backend, chassis = _make(tmp_path)
    chassis.get_change_event(timeout=10)  # seed
    backend.set_presence(11, True)

    ok, payload = chassis.get_change_event(timeout=10)
    assert ok is True
    assert payload == {'sfp': {'11': STATUS_INSERTED}}


def test_detects_remove(tmp_path):
    backend, chassis = _make(tmp_path)
    backend.set_presence(11, True)
    chassis.get_change_event(timeout=10)  # seed with port 11 present

    backend.set_presence(11, False)
    ok, payload = chassis.get_change_event(timeout=10)
    assert payload == {'sfp': {'11': STATUS_REMOVED}}


def test_detects_status_change(tmp_path):
    backend, chassis = _make(tmp_path)
    backend.set_presence(3, True)
    chassis.get_change_event(timeout=10)  # seed: port 3 = '1'

    backend.set_status(3, STATUS_BAD_EEPROM)
    ok, payload = chassis.get_change_event(timeout=10)
    assert payload == {'sfp': {'3': STATUS_BAD_EEPROM}}


def test_no_change_returns_empty_after_timeout(tmp_path):
    backend, chassis = _make(tmp_path)
    backend.set_presence(0, True)
    chassis.get_change_event(timeout=10)  # seed

    ok, payload = chassis.get_change_event(timeout=10)
    assert ok is True
    assert payload == {'sfp': {}}


def test_diff_unrelated_to_str_keys(tmp_path):
    backend, chassis = _make(tmp_path)
    chassis.get_change_event(timeout=10)
    backend.set_presence(7, True)
    _, payload = chassis.get_change_event(timeout=10)
    # Status-code values are strings; port keys are stringified too.
    for k, v in payload['sfp'].items():
        assert isinstance(k, str)
        assert isinstance(v, str)


def test_real_path_not_called_when_enabled(tmp_path):
    backend, chassis = _make(tmp_path)
    chassis.get_change_event(timeout=10)
    chassis.get_change_event(timeout=10)
    assert chassis.real_calls == []
