"""
backend.py

Central, file-backed mock state for SFP simulation.

Layout under ``MOCK_SFP_ROOT`` (default ``/tmp/sonic_sfp_mock``)::

    enabled                       # presence of this file activates mock mode
    presence/<port_index>         # contents "1" = present, "0" = absent
    status/<port_index>           # optional: "1".."6" override (error states)
    eeprom/<port_index>.bin       # raw EEPROM image to serve to read_eeprom()

The backend is stdlib-only and thread-safe.  An mtime cache avoids
re-reading files on every poll.
"""

from __future__ import absolute_import

import os
import threading


# Status codes used by ``Chassis.get_change_event`` per the contract in
# ``ChassisBase.get_change_event``.
STATUS_REMOVED              = '0'
STATUS_INSERTED             = '1'
STATUS_I2C_STUCK            = '2'
STATUS_BAD_EEPROM           = '3'
STATUS_UNSUPPORTED_CABLE    = '4'
STATUS_HIGH_TEMPERATURE     = '5'
STATUS_BAD_CABLE            = '6'

VALID_STATUS_CODES = {
    STATUS_REMOVED,
    STATUS_INSERTED,
    STATUS_I2C_STUCK,
    STATUS_BAD_EEPROM,
    STATUS_UNSUPPORTED_CABLE,
    STATUS_HIGH_TEMPERATURE,
    STATUS_BAD_CABLE,
}

DEFAULT_ROOT = '/tmp/sonic_sfp_mock'
ENABLED_SENTINEL = 'enabled'

_singletons_lock = threading.Lock()
_singletons = {}


def _resolve_root(root):
    if root is not None:
        return root
    return os.environ.get('MOCK_SFP_ROOT', DEFAULT_ROOT)


class MockSfpBackend(object):
    """File-backed mock state for SFP presence, status and EEPROM data.

    Instances are cheap; a process-wide singleton keyed by root path is
    available through :meth:`instance` so that ``Sfp`` objects and the
    ``Chassis`` share the same cache.
    """

    def __init__(self, root=None):
        self._root = _resolve_root(root)
        self._lock = threading.Lock()
        # path -> (mtime_ns, size, cached_bytes)
        self._file_cache = {}

    # ------------------------------------------------------------------
    # Singleton helper
    # ------------------------------------------------------------------
    @classmethod
    def instance(cls, root=None):
        """Return a process-wide singleton keyed by the resolved root."""
        resolved = _resolve_root(root)
        with _singletons_lock:
            backend = _singletons.get(resolved)
            if backend is None:
                backend = cls(resolved)
                _singletons[resolved] = backend
            return backend

    @classmethod
    def _reset_singletons_for_tests(cls):
        """Test-only helper: clear cached singletons."""
        with _singletons_lock:
            _singletons.clear()

    # ------------------------------------------------------------------
    # Paths
    # ------------------------------------------------------------------
    @property
    def root(self):
        return self._root

    def _sentinel_path(self):
        return os.path.join(self._root, ENABLED_SENTINEL)

    def _presence_dir(self):
        return os.path.join(self._root, 'presence')

    def _status_dir(self):
        return os.path.join(self._root, 'status')

    def _eeprom_path(self, port):
        return os.path.join(self._root, 'eeprom', '{}.bin'.format(port))

    def _presence_path(self, port):
        return os.path.join(self._presence_dir(), str(port))

    def _status_path(self, port):
        return os.path.join(self._status_dir(), str(port))

    # ------------------------------------------------------------------
    # Enabled check
    # ------------------------------------------------------------------
    def enabled(self):
        """Return True if mock mode is active.

        Mock mode is on when either ``MOCK_SFP=1`` is set in the env or
        the ``enabled`` sentinel file exists under the root.
        """
        if os.environ.get('MOCK_SFP') == '1':
            return True
        try:
            return os.path.exists(self._sentinel_path())
        except OSError:
            return False

    # ------------------------------------------------------------------
    # File reading with mtime cache
    # ------------------------------------------------------------------
    def _read_file(self, path):
        """Read a file via the mtime/size cache.  Returns bytes or None."""
        with self._lock:
            try:
                st = os.stat(path)
            except (OSError, ValueError):
                # File missing -- drop any stale cache entry and return None
                self._file_cache.pop(path, None)
                return None

            key = (st.st_mtime_ns, st.st_size)
            cached = self._file_cache.get(path)
            if cached is not None and cached[0] == key[0] and cached[1] == key[1]:
                return cached[2]

            try:
                with open(path, 'rb') as fh:
                    data = fh.read()
            except OSError:
                self._file_cache.pop(path, None)
                return None

            self._file_cache[path] = (key[0], key[1], data)
            return data

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def get_presence(self, port):
        """Return ``True`` iff ``presence/<port>`` contains ``"1"``."""
        data = self._read_file(self._presence_path(port))
        if data is None:
            return False
        return data.strip() == b'1'

    def get_status(self, port):
        """Return the status code (``'0'``-``'6'``) for ``port``.

        Precedence:
        1. A valid value in ``status/<port>`` (``'1'``-``'6'``) wins, but
           only if the port is currently present.  ``'0'`` is accepted
           and forces removed.
        2. Otherwise derive from presence: ``'1'`` if present else ``'0'``.
        """
        present = self.get_presence(port)
        data = self._read_file(self._status_path(port))
        if data is not None:
            code = data.strip().decode('ascii', errors='replace')
            if code in VALID_STATUS_CODES:
                # A removed port can never report an error status.
                if code == STATUS_REMOVED:
                    return STATUS_REMOVED
                if not present:
                    return STATUS_REMOVED
                return code
        return STATUS_INSERTED if present else STATUS_REMOVED

    def read_eeprom(self, port, offset, size):
        """Return ``bytearray`` slice of the captured EEPROM for ``port``.

        Returns ``None`` if no dump exists for that port.  Reads outside
        the dump are zero-padded so callers requesting a region partly
        beyond EOF still get a full-length buffer.
        """
        if offset < 0 or size < 0:
            return None
        data = self._read_file(self._eeprom_path(port))
        if data is None:
            return None
        end = offset + size
        chunk = data[offset:end]
        if len(chunk) < size:
            chunk = chunk + b'\x00' * (size - len(chunk))
        return bytearray(chunk)

    def snapshot(self):
        """Return ``{port_index: status_code}`` across every known port.

        Ports are discovered by scanning the ``presence/`` directory.
        Only entries whose name is a non-negative integer are included.
        """
        result = {}
        try:
            entries = os.listdir(self._presence_dir())
        except OSError:
            return result
        for name in entries:
            try:
                port = int(name)
            except ValueError:
                continue
            if port < 0:
                continue
            result[port] = self.get_status(port)
        return result

    # ------------------------------------------------------------------
    # Convenience writers (used by tests and the optional `mock-sfp` CLI
    # in downstream platform packages).  Kept here so the file format is
    # owned by a single module.
    # ------------------------------------------------------------------
    def _ensure_dirs(self):
        for sub in ('presence', 'status', 'eeprom'):
            try:
                os.makedirs(os.path.join(self._root, sub))
            except OSError:
                if not os.path.isdir(os.path.join(self._root, sub)):
                    raise

    def set_enabled(self, enabled):
        """Create or remove the ``enabled`` sentinel."""
        self._ensure_dirs()
        path = self._sentinel_path()
        if enabled:
            with open(path, 'w') as fh:
                fh.write('1')
        else:
            try:
                os.remove(path)
            except OSError:
                pass

    def set_presence(self, port, present):
        self._ensure_dirs()
        with open(self._presence_path(port), 'w') as fh:
            fh.write('1' if present else '0')

    def set_status(self, port, code):
        if code not in VALID_STATUS_CODES:
            raise ValueError('invalid status code: {!r}'.format(code))
        self._ensure_dirs()
        with open(self._status_path(port), 'w') as fh:
            fh.write(code)

    def clear_status(self, port):
        try:
            os.remove(self._status_path(port))
        except OSError:
            pass

    def write_eeprom_file(self, port, data):
        """Write ``data`` (bytes) as the EEPROM dump for ``port``."""
        self._ensure_dirs()
        with open(self._eeprom_path(port), 'wb') as fh:
            fh.write(data)
