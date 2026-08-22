"""Planted defect fixture: ambient environment dependence.

Never imported and never executed.  It exists so ENV_READ can be proved to fire
on both subscript and accessor forms.
"""

import os


def token():
    return os.environ["PO03_TOKEN"]


def optional_flag():
    return os.getenv("PO03_FLAG", "0")


def inherited():
    return os.environ.copy()
