"""Python version compatibility helpers."""

from __future__ import annotations

__all__ = ("IS_PY312_PLUS",)

import sys

# Python 3.12+ introduced significant pathlib changes
IS_PY312_PLUS = sys.version_info >= (3, 12)
