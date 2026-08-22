"""Planted defect fixture: outbound network dependence.

Never imported and never executed.  It exists so NETWORK_IMPORT and
NETWORK_CALL can be proved to fire; unit a3-u06 asserts the real suite passes
with the network removed, and this fixture is what proves that assertion is not
vacuous.
"""

import socket
import urllib.request


def fetch():
    return urllib.request.urlopen("https://example.invalid/state.json").read()


def probe():
    return socket.create_connection(("example.invalid", 443), timeout=5)
