"""Planted defect fixture: import-path mutation.

Never imported and never executed.  It exists so SYS_PATH_MUTATION can be
proved to fire.
"""

import sys


def install():
    sys.path.insert(0, "vendor")
    sys.path.append("extra")
