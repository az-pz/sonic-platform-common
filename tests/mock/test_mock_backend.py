"""Unit tests for :mod:`sonic_platform_base.mock.backend`."""

import os

import pytest

from sonic_platform_base.mock.backend import (
    MockSfpBackend,
    STATUS_BAD_EEPROM,
    STATUS_INSERTED,
    STATUS_REMOVED,
)


@pytest.fixture(autouse=True)
def _clear_env(monkeypatch):
    monkeypatch.delenv('MOCK_SFP', raising=False)
    monkeypatch.delenv('MOCK_SFP_ROOT', raising=False)
    MockSfpBackend._reset_singletons_for_tests()
    yield
    MockSfpBackend._reset_singletons_for_tests()


def test_enabled_via_sentinel(tmp_path):
    backend = MockSfpBackend(str(tmp_path))
    assert backend.enabled() is False
    backend.set_enabled(True)
    assert backend.enabled() is True
    backend.set_enabled(False)
    assert backend.enabled() is False


def test_enabled_via_env(tmp_path, monkeypatch):
    backend = MockSfpBackend(str(tmp_path))
    monkeypatch.setenv('MOCK_SFP', '1')
    assert backend.enabled() is True


def test_get_presence_defaults_false(tmp_path):
    backend = MockSfpBackend(str(tmp_path))
    assert backend.get_presence(0) is False
    backend.set_presence(0, True)
    assert backend.get_presence(0) is True
    backend.set_presence(0, False)
    assert backend.get_presence(0) is False


def test_get_status_precedence(tmp_path):
    backend = MockSfpBackend(str(tmp_path))
    # No presence file -> removed.
    assert backend.get_status(5) == STATUS_REMOVED
    # Present with no status override -> inserted.
    backend.set_presence(5, True)
    assert backend.get_status(5) == STATUS_INSERTED
    # Override to bad EEPROM while present -> error code.
    backend.set_status(5, STATUS_BAD_EEPROM)
    assert backend.get_status(5) == STATUS_BAD_EEPROM
    # Removing the port forces removed regardless of override.
    backend.set_presence(5, False)
    assert backend.get_status(5) == STATUS_REMOVED


def test_get_status_rejects_invalid_codes(tmp_path):
    backend = MockSfpBackend(str(tmp_path))
    with pytest.raises(ValueError):
        backend.set_status(0, '9')


def test_read_eeprom_slicing(tmp_path):
    backend = MockSfpBackend(str(tmp_path))
    payload = bytes(range(64))
    backend.write_eeprom_file(11, payload)

    out = backend.read_eeprom(11, 0, 16)
    assert isinstance(out, bytearray)
    assert bytes(out) == payload[0:16]

    out = backend.read_eeprom(11, 10, 8)
    assert bytes(out) == payload[10:18]


def test_read_eeprom_zero_pads_past_eof(tmp_path):
    backend = MockSfpBackend(str(tmp_path))
    backend.write_eeprom_file(0, b'\x01\x02\x03')
    out = backend.read_eeprom(0, 1, 5)
    assert bytes(out) == b'\x02\x03\x00\x00\x00'


def test_read_eeprom_missing_returns_none(tmp_path):
    backend = MockSfpBackend(str(tmp_path))
    assert backend.read_eeprom(7, 0, 8) is None


def test_read_eeprom_rejects_negative(tmp_path):
    backend = MockSfpBackend(str(tmp_path))
    backend.write_eeprom_file(0, b'abc')
    assert backend.read_eeprom(0, -1, 4) is None
    assert backend.read_eeprom(0, 0, -1) is None


def test_snapshot_lists_known_ports(tmp_path):
    backend = MockSfpBackend(str(tmp_path))
    backend.set_presence(0, True)
    backend.set_presence(1, False)
    backend.set_presence(3, True)
    backend.set_status(3, STATUS_BAD_EEPROM)

    snap = backend.snapshot()
    assert snap == {0: STATUS_INSERTED, 1: STATUS_REMOVED, 3: STATUS_BAD_EEPROM}


def test_snapshot_ignores_non_integer_filenames(tmp_path):
    backend = MockSfpBackend(str(tmp_path))
    backend.set_presence(0, True)
    # Drop a junk file into presence/
    with open(os.path.join(backend.root, 'presence', 'README'), 'w') as fh:
        fh.write('ignore me')
    assert backend.snapshot() == {0: STATUS_INSERTED}


def test_mtime_cache_refresh(tmp_path):
    backend = MockSfpBackend(str(tmp_path))
    backend.set_presence(0, True)
    assert backend.get_presence(0) is True
    # Mutate and ensure the new content is observed.
    backend.set_presence(0, False)
    # Bump mtime explicitly in case the test runs faster than mtime resolution.
    path = os.path.join(backend.root, 'presence', '0')
    st = os.stat(path)
    os.utime(path, ns=(st.st_atime_ns, st.st_mtime_ns + 1_000_000))
    assert backend.get_presence(0) is False


def test_instance_singleton(tmp_path):
    a = MockSfpBackend.instance(str(tmp_path))
    b = MockSfpBackend.instance(str(tmp_path))
    assert a is b
    c = MockSfpBackend.instance(str(tmp_path / 'other'))
    assert c is not a
