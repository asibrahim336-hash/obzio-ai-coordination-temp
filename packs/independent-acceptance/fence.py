"""The production fence.

An acceptance operator that can edit the work it is reviewing is not a
reviewer. The obvious failure is not malice -- it is helpfulness: the reviewer
spots a small problem, fixes it, and then accepts. The defect is gone from the
artefact and gone from the record, and nobody downstream learns it existed.

So this pack cannot write into the subject. Three layers:

  1. WriteFence      -- every write goes through it; paths under the subject
                        root are refused before any file is opened.
  2. SubjectHandle   -- the only handle to the subject exposes read methods.
                        There is no write method to call.
  3. IndependenceProof -- digests of every subject file snapshotted at scope
                        time and re-verified at verdict time. Even a write
                        that bypassed layers 1 and 2 (os.open, a shell out)
                        makes the review VOID rather than merely wrong.

Layer 3 is the one that matters, because it does not depend on the reviewer
cooperating with layers 1 and 2.
"""

import os

from obzio_spine.artefacts import sha256_file


class ProductionAttemptError(PermissionError):
    """The reviewer tried to produce or modify the work under review."""


class IndependenceViolation(RuntimeError):
    """The subject changed while under review. The review is void."""


def _within(path: str, root: str) -> bool:
    p = os.path.realpath(path)
    r = os.path.realpath(root)
    return p == r or p.startswith(r + os.sep)


class WriteFence:
    """Wraps every write this pack performs."""

    def __init__(self, subject_root: str, review_root: str):
        self.subject_root = os.path.realpath(subject_root)
        self.review_root = os.path.realpath(review_root)
        if _within(self.review_root, self.subject_root):
            raise ProductionAttemptError(
                f"review output dir {review_root!r} is inside the subject "
                f"{subject_root!r}; the review would contaminate its own subject")
        self.refused = []

    def check(self, path: str) -> str:
        target = os.path.realpath(path)
        if _within(target, self.subject_root):
            self.refused.append(target)
            raise ProductionAttemptError(
                f"refusing to write {path!r}: it is inside the subject under "
                f"review. This pack reviews work; it cannot produce it.")
        if not _within(target, self.review_root):
            self.refused.append(target)
            raise ProductionAttemptError(
                f"refusing to write {path!r}: outside the review output "
                f"directory {self.review_root!r}")
        return target

    def write_json(self, path, obj):
        from obzio_spine.artefacts import write_json as _wj
        return _wj(self.check(path), obj)


class SubjectHandle:
    """Read-only view of the work under review. Exposes no write method."""

    def __init__(self, subject_root: str):
        self.root = os.path.realpath(subject_root)
        if not os.path.isdir(self.root):
            raise FileNotFoundError(f"subject root {subject_root!r} does not exist")

    def files(self):
        out = []
        for dirpath, dirnames, filenames in os.walk(self.root):
            dirnames[:] = sorted(d for d in dirnames if d != "__pycache__")
            for fn in sorted(filenames):
                out.append(os.path.relpath(os.path.join(dirpath, fn), self.root))
        return sorted(out)

    def exists(self, rel):
        return os.path.exists(os.path.join(self.root, rel))

    def read_bytes(self, rel):
        with open(os.path.join(self.root, rel), "rb") as f:
            return f.read()

    def read_json(self, rel):
        import json
        return json.loads(self.read_bytes(rel).decode("utf-8"))

    def digest(self, rel):
        return sha256_file(os.path.join(self.root, rel))

    def snapshot(self):
        return {rel: self.digest(rel) for rel in self.files()}


class IndependenceProof:
    """Snapshot at scope, re-verify at verdict."""

    def __init__(self, handle: "SubjectHandle"):
        self.handle = handle
        self.before = handle.snapshot()
        self.after = None

    def verify(self):
        self.after = self.handle.snapshot()
        added = sorted(set(self.after) - set(self.before))
        removed = sorted(set(self.before) - set(self.after))
        modified = sorted(k for k in set(self.before) & set(self.after)
                          if self.before[k] != self.after[k])
        if added or removed or modified:
            raise IndependenceViolation(
                f"subject changed during review -- added={added} "
                f"removed={removed} modified={modified}")
        return True

    def to_json(self):
        return {
            "subject_root": self.handle.root,
            "files_snapshotted": len(self.before),
            "before": self.before,
            "after": self.after,
            "unchanged": self.after == self.before,
            "note": ("digests taken before review and re-taken at verdict; "
                     "any difference voids the review"),
        }
