"""Provide a stub ``sonic_py_common`` so the package import succeeds."""

import sys
from unittest import mock

if 'sonic_py_common' not in sys.modules:
    sys.modules['sonic_py_common'] = mock.MagicMock()
    sys.modules['sonic_py_common.logger'] = mock.MagicMock()
