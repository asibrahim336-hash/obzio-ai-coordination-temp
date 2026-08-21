"""Repository engineering: branch -> write -> PR -> read-back verify.

The read-back is the whole point. An operator that writes a file and reports
success has proven nothing: the write may have gone to the wrong ref, been
silently rejected, been mangled by encoding, or landed on a stale branch. The
only evidence that a write happened is reading the bytes back from the remote
and comparing digests.
"""

import hashlib
from dataclasses import dataclass, asdict, field
from typing import List, Dict

from transport import Transport, TransportError, ProtectedRefError


class VerificationError(RuntimeError):
    pass


def digest(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


@dataclass
class FileWrite:
    path: str
    intended_sha256: str
    byte_count: int
    commit_sha: str = ""
    blob_sha: str = ""

    def to_json(self):
        return asdict(self)


@dataclass
class ReadBack:
    path: str
    ref: str
    intended_sha256: str
    observed_sha256: str
    observed_bytes: int
    match: bool

    def to_json(self):
        return asdict(self)


def execute(tp: "Transport", branch: str, files: Dict[str, bytes],
            pr_title: str, pr_body: str, base: str = None) -> dict:
    """The full operation. Returns the four artefact payloads.

    Ordering is deliberate: read-back happens AFTER the PR is opened, against
    the remote ref, so it verifies what a reviewer of that PR would actually
    see."""
    if not files:
        raise ValueError("no files supplied; refusing to open an empty PR")

    base = base or tp.default_branch()
    if branch == base:
        raise ProtectedRefError(
            f"target branch {branch!r} is the base branch; refusing")

    # --- branch ---------------------------------------------------------
    br = tp.create_branch(branch, from_ref=base)

    # --- write ----------------------------------------------------------
    writes: List[FileWrite] = []
    for path in sorted(files):
        content = files[path]
        if not isinstance(content, (bytes, bytearray)):
            raise TypeError(f"content for {path!r} must be bytes")
        w = FileWrite(path=path, intended_sha256=digest(content),
                      byte_count=len(content))
        res = tp.put_file(branch, path, bytes(content),
                          f"{pr_title} :: {path}")
        w.commit_sha = res["commit_sha"]
        w.blob_sha = res["blob_sha"]
        writes.append(w)

    # --- PR -------------------------------------------------------------
    pr = tp.open_pr(head=branch, base=base, title=pr_title, body=pr_body)

    # --- read-back verify ----------------------------------------------
    readbacks: List[ReadBack] = []
    for w in writes:
        try:
            observed = tp.get_file(branch, w.path)
        except TransportError as e:
            readbacks.append(ReadBack(w.path, branch, w.intended_sha256,
                                      f"READ_FAILED:{e}", 0, False))
            continue
        od = digest(observed)
        readbacks.append(ReadBack(
            path=w.path, ref=branch, intended_sha256=w.intended_sha256,
            observed_sha256=od, observed_bytes=len(observed),
            match=(od == w.intended_sha256)))

    verified = all(r.match for r in readbacks)

    return {
        "branch_record": {
            "branch": br["branch"], "base": br["base"],
            "base_sha": br["base_sha"], "ref": br["ref"],
            "protected_refs": list(tp.protected),
            "credential": tp.cred.redacted(),
        },
        "commit_record": {
            "branch": branch,
            "file_count": len(writes),
            "files": [w.to_json() for w in writes],
            "head_commit": writes[-1].commit_sha if writes else None,
        },
        "pr_record": {
            "number": pr["number"], "head": pr["head"], "base": pr["base"],
            "state": pr.get("state", "open"),
            "merged": bool(pr.get("merged", False)),
            "url": pr.get("url", ""),
            "title": pr_title,
        },
        "readback_verification": {
            "ref": branch,
            "all_verified": verified,
            "checked": len(readbacks),
            "results": [r.to_json() for r in readbacks],
        },
        "_audit": list(tp.calls),
    }
