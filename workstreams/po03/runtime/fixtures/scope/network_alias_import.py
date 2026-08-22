"""Scope fixture: the from-import form of a network module.

Rules keyed only on plain imports would miss this, so the prober resolves the
module root of a from-import as well.
"""

from urllib import request

opener = request
