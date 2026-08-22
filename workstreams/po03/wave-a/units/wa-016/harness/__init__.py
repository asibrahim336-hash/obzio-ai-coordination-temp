"""PO03-WA-016 transition fault-injection harness.

Dependency-free, deterministic, and runnable from a clean clone with the
standard library only.  The harness never writes outside its owned subtree and
never mutates the read-only seeded controls it composes.
"""
