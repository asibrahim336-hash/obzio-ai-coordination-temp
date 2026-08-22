"""Control for unit a3-u06: the same network need, declared and guarded.

The marker convention from ``offline-policy.json`` is a module-scope constant
plus a guard that turns an unreachable remote into a skip. A run with outbound
network disabled must therefore pass over this directory and report the module
as separated, while the unmarked sibling in this directory fails.

The pair is what makes the acceptance checkable. Marking alone would let a
module declare a need it does not have; the guard alone would let a module skip
silently without appearing in the separated list.
"""

from __future__ import annotations

import socket
import unittest

PO03_REQUIRES_NETWORK = True


def remote_reachable() -> bool:
    try:
        socket.getaddrinfo("github.com", 443)
    except OSError:
        return False
    return True


@unittest.skipUnless(remote_reachable(), "declared network dependence; remote unreachable")
class ReachesTheNetworkAndDeclaresIt(unittest.TestCase):
    def test_resolves_a_public_host(self) -> None:
        self.assertTrue(socket.getaddrinfo("github.com", 443))


if __name__ == "__main__":
    unittest.main()
