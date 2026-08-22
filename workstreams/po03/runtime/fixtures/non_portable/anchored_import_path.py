"""Planted fixture: the accepted form of import-path mutation.

Never imported and never executed.  It is the seventh fixture and the only one
that must *not* fail the gate, which is why it exists: the downgrade from
SYS_PATH_MUTATION to the advisory SYS_PATH_ANCHORED is a judgement, and a
judgement with no fixture behind it is an assertion.

There is no installable package in this repository and the suite runs under
``python3 -I``, which implies ``-P``, so a test cannot import a module beside it
by any means except this or ``importlib.util.spec_from_file_location``. Flagging
one of the only two available mechanisms would be a style preference wearing a
gate's clothing. What makes the difference is where the directory comes from: a
path derived from ``__file__`` is inside the clone by construction, so a clean
clone always has it. Its unanchored counterpart is in
``import_path_mutation.py`` and still fires at full severity.

The three shapes below are all the ones the tree actually uses: direct, through
one module-level root, and through a chain of them.
"""

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
PO03 = HERE.parents[1]
RESEARCH_ROOT = PO03 / "research"


def install_direct():
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def install_through_one_root():
    sys.path.insert(0, str(HERE))


def install_through_a_chain():
    sys.path.insert(0, str(RESEARCH_ROOT))
