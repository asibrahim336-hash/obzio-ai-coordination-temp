"""Scope fixture: only the leading string is a docstring.

A bare string later in a function body is a value, not documentation, and must
still be flagged.
"""


def resume():
    """Return the checkpoint path."""
    return "/var/tmp/po03-late.json"
