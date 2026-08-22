"""Planted defect fixture: home-directory dependence.

Never imported and never executed.  It exists so HOME_API and
HOME_PATH_LITERAL can be proved to fire.
"""

import os.path
from pathlib import Path

CREDENTIAL_HINT = "~/.obzio/credentials"


def state_dir():
    return Path.home() / ".obzio"


def expanded():
    return os.path.expanduser(CREDENTIAL_HINT)
