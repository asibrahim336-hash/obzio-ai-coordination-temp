"""Planted defect for unit a3-u06: a test that needs the remote and says nothing.

This is the failure the offline gate exists to catch. It reaches the network
without setting ``PO03_REQUIRES_NETWORK``, so a run with outbound network
disabled must fail rather than skip. If ``offline_check.sh`` ever reports PASS
over this directory, the gate is not measuring anything.

It lives under ``runtime/fixtures`` so that ordinary suite discovery, which
starts at ``workstreams/po03/tests``, never picks it up, and so that the
hermeticity prober does not report its deliberate network import as a finding
in the real tree.
"""

from __future__ import annotations

import socket
import unittest


class ReachesTheNetworkWithoutSayingSo(unittest.TestCase):
    def test_resolves_a_public_host(self) -> None:
        socket.getaddrinfo("github.com", 443)


if __name__ == "__main__":
    unittest.main()
