"""Planted defect fixture: dependence on system temporary state.

Never imported and never executed.  It exists so TEMP_PATH_LITERAL can be
proved to fire on the exact failure mode the commission forbids -- a suite that
passes only because an earlier run left something behind outside the tree.
"""

CHECKPOINT = "/tmp/po03-checkpoint.json"
FALLBACK = "/var/tmp/po03-fallback.json"


def resume():
    return open(CHECKPOINT, encoding="utf-8").read()
