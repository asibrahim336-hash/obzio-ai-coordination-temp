"""Scope fixture: prose only.

This module documents that state is never read from /tmp and never resolved
against ~/.obzio. Documentation cannot make a program non-portable, so the
prober must report nothing here. If it ever reports a finding, the gate has
started producing noise that trains reviewers to ignore it.
"""


def described():
    """Return a constant. Nothing here touches /tmp or ~/.obzio."""
    return 1
