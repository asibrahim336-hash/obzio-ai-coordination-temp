"""Dependency-free support libraries for PO-03 worker a5 research units.

Everything under this package is standard-library Python 3.12 only and is
owned exclusively by ``po03-worker-a5`` (see
``workstreams/po03/control/path-ownership.json``). Nothing here imports or
mutates ``workstreams/po03/tools/control_plane.py``; that module is
coordinator-owned and is only ever imported read-only as a library so its
real behaviour can be exercised inside reproductions.
"""
