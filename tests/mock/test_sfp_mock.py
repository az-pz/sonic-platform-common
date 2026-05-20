"""Tests for :class:`MockSfpMixin`."""

import pytest

from sonic_platform_base.mock.backend import (
    MockSfpBackend,
    STATUS_BAD_EEPROM,
    STATUS_HIGH_TEMPERATURE,
)
from sonic_platform_base.mock.sfp_mixin import MockSfpMixin
from sonic_platform_base.sfp_base import SfpBase


class _FakeRealSfp(object):
    """Stand-in for the hardware ``Sfp`` base class.

    Records calls so tests can assert fall-through behaviour without
    instantiating ``SfpBase`` (which imports XcvrApiFactory).
    """

    def __init__(self):
        self.read_calls = []
        self.presence_value = False
        self.error_value = 'real-error'
        self.eeprom_value = bytearray(b'real-eeprom')

    def get_presence(self):
        return self.presence_value

    def read_eeprom(self, offset, num_bytes):
        self.read_calls.append((offset, num_bytes))
        return self.eeprom_value

    def get_error_description(self):
        return self.error_value


class _MockSfp(MockSfpMixin, _FakeRealSfp):
    def __init__(self, index, backend):
        super(_MockSfp, self).__init__()
        self.index = index
        self._mock_backend = backend


@pytest.fixture(autouse=True)
def _clear_singletons():
    MockSfpBackend._reset_singletons_for_tests()
    yield
    MockSfpBackend._reset_singletons_for_tests()


def test_get_presence_disabled_falls_through(tmp_path):
    backend = MockSfpBackend(str(tmp_path))
    sfp = _MockSfp(1, backend)
    sfp.presence_value = True
    # Backend disabled => real path returns its own value.
    assert sfp.get_presence() is True
    sfp.presence_value = False
    assert sfp.get_presence() is False


def test_get_presence_enabled_routes_to_backend(tmp_path):
    backend = MockSfpBackend(str(tmp_path))
    backend.set_enabled(True)
    backend.set_presence(1, True)
    sfp = _MockSfp(1, backend)
    sfp.presence_value = False  # real hw says absent
    assert sfp.get_presence() is True


def test_read_eeprom_disabled_falls_through(tmp_path):
    backend = MockSfpBackend(str(tmp_path))
    sfp = _MockSfp(1, backend)
    out = sfp.read_eeprom(0, 4)
    assert sfp.read_calls == [(0, 4)]
    assert out == bytearray(b'real-eeprom')


def test_read_eeprom_enabled_with_dump(tmp_path):
    backend = MockSfpBackend(str(tmp_path))
    backend.set_enabled(True)
    backend.write_eeprom_file(2, b'\xaa\xbb\xcc\xdd')
    sfp = _MockSfp(2, backend)
    out = sfp.read_eeprom(1, 2)
    assert bytes(out) == b'\xbb\xcc'
    # Hardware path was not called.
    assert sfp.read_calls == []


def test_read_eeprom_enabled_without_dump_falls_through(tmp_path):
    backend = MockSfpBackend(str(tmp_path))
    backend.set_enabled(True)
    sfp = _MockSfp(3, backend)
    out = sfp.read_eeprom(0, 4)
    # No dump for port 3 => real path runs.
    assert sfp.read_calls == [(0, 4)]
    assert out == bytearray(b'real-eeprom')


def test_get_error_description_maps_status_codes(tmp_path):
    backend = MockSfpBackend(str(tmp_path))
    backend.set_enabled(True)
    backend.set_presence(4, True)
    sfp = _MockSfp(4, backend)

    # Inserted, no override -> OK
    assert sfp.get_error_description() == SfpBase.SFP_STATUS_OK

    backend.set_status(4, STATUS_BAD_EEPROM)
    assert sfp.get_error_description() == SfpBase.SFP_ERROR_DESCRIPTION_BAD_EEPROM

    backend.set_status(4, STATUS_HIGH_TEMPERATURE)
    assert sfp.get_error_description() == SfpBase.SFP_ERROR_DESCRIPTION_HIGH_TEMP

    backend.set_presence(4, False)
    assert sfp.get_error_description() == SfpBase.SFP_STATUS_UNPLUGGED


def test_get_error_description_disabled_falls_through(tmp_path):
    backend = MockSfpBackend(str(tmp_path))
    sfp = _MockSfp(1, backend)
    assert sfp.get_error_description() == 'real-error'


def test_missing_index_raises(tmp_path):
    class Indexless(MockSfpMixin, _FakeRealSfp):
        def __init__(self, backend):
            super(Indexless, self).__init__()
            self._mock_backend = backend

    backend = MockSfpBackend(str(tmp_path))
    backend.set_enabled(True)
    sfp = Indexless(backend)
    with pytest.raises(AttributeError):
        sfp.get_presence()
