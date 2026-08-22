"""Shared helpers for the WA-015 focused test suite."""

from __future__ import annotations

import contextlib
import io
import sys
from pathlib import Path


UNIT_ROOT = Path(__file__).resolve().parents[1]
if str(UNIT_ROOT) not in sys.path:
    sys.path.insert(0, str(UNIT_ROOT))


class _NullStream(io.StringIO):
    """A text stream that also absorbs writes made through ``.buffer``."""

    @property
    def buffer(self) -> io.BytesIO:
        return io.BytesIO()


@contextlib.contextmanager
def silenced():
    """Discard stdout and stderr, including byte writes, during CLI tests."""
    with contextlib.redirect_stdout(_NullStream()), contextlib.redirect_stderr(
        _NullStream()
    ):
        yield
