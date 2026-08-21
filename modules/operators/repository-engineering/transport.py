"""Authenticated repository transports.

Two implementations of one interface:

  GitHubTransport -- real REST calls to api.github.com over urllib. Deployable.
                     NOT exercised by test_pack.py (no token in the sandbox).
                     Treat it as unproven code until it runs against a repo.
  LocalGitTransport -- drives the real `git` binary against a real local repo.
                     Fully exercised by the tests. PRs are modelled as refs
                     plus a metadata record, because local git has no PR
                     concept -- that difference is a real fidelity gap and is
                     declared in BOUNDARIES.md.

Both refuse every operation without a credential, so the authenticated path is
exercised offline rather than only in production.
"""

import json
import os
import subprocess
import urllib.error
import urllib.request
from dataclasses import dataclass


class TransportError(RuntimeError):
    pass


class AuthError(TransportError):
    pass


class ProtectedRefError(TransportError):
    pass


@dataclass(frozen=True)
class Credential:
    """Holds the token. `redacted()` is the ONLY form allowed into artefacts."""
    principal: str
    token: str

    def redacted(self) -> dict:
        t = self.token
        return {
            "principal": self.principal,
            "token_present": bool(t),
            "token_len": len(t),
            "token_fingerprint": __import__("hashlib").sha256(
                t.encode()).hexdigest()[:12] if t else None,
        }

    def __repr__(self):
        return f"Credential(principal={self.principal!r}, token=<redacted>)"

    __str__ = __repr__


PROTECTED_DEFAULT = ("main", "master", "release", "production")


class Transport:
    def __init__(self, credential: "Credential", protected=PROTECTED_DEFAULT):
        if credential is None or not credential.token:
            raise AuthError("no credential supplied; refusing to operate")
        self.cred = credential
        self.protected = tuple(protected)
        self.calls = []                      # audit trail of every op attempted

    def _audit(self, op, **kw):
        self.calls.append({"op": op, **kw})

    def _guard_ref(self, branch):
        if branch in self.protected:
            raise ProtectedRefError(
                f"refusing to write to protected ref {branch!r}")

    # interface
    def default_branch(self) -> str: raise NotImplementedError
    def create_branch(self, name, from_ref=None) -> dict: raise NotImplementedError
    def put_file(self, branch, path, content: bytes, message) -> dict: raise NotImplementedError
    def get_file(self, ref, path) -> bytes: raise NotImplementedError
    def open_pr(self, head, base, title, body) -> dict: raise NotImplementedError


# --------------------------------------------------------------- GitHub (real)

class GitHubTransport(Transport):
    """Real GitHub REST v3. UNPROVEN in this sandbox -- no token available.

    Every method below issues a genuine authenticated HTTPS request. The
    request shapes follow the documented API, but none of them has been run
    against a live repository from here, so this class is a deployment
    artefact, not a verified one."""

    API = "https://api.github.com"

    def __init__(self, credential, owner, repo, protected=PROTECTED_DEFAULT):
        super().__init__(credential, protected)
        self.owner, self.repo = owner, repo

    def _req(self, method, path, body=None):
        url = f"{self.API}{path}"
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(url, data=data, method=method)
        req.add_header("Authorization", f"Bearer {self.cred.token}")
        req.add_header("Accept", "application/vnd.github+json")
        req.add_header("X-GitHub-Api-Version", "2022-11-28")
        req.add_header("User-Agent", "obzio-repository-engineering/1")
        if data:
            req.add_header("Content-Type", "application/json")
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                return json.loads(r.read().decode() or "{}")
        except urllib.error.HTTPError as e:
            raise TransportError(
                f"{method} {path} -> HTTP {e.code}: {e.read().decode()[:400]}") from e

    def default_branch(self):
        return self._req("GET", f"/repos/{self.owner}/{self.repo}")["default_branch"]

    def create_branch(self, name, from_ref=None):
        self._guard_ref(name)
        base = from_ref or self.default_branch()
        sha = self._req(
            "GET", f"/repos/{self.owner}/{self.repo}/git/ref/heads/{base}"
        )["object"]["sha"]
        out = self._req("POST", f"/repos/{self.owner}/{self.repo}/git/refs",
                        {"ref": f"refs/heads/{name}", "sha": sha})
        self._audit("create_branch", branch=name, base=base, force=False)
        return {"branch": name, "base": base, "base_sha": sha,
                "ref": out.get("ref", f"refs/heads/{name}")}

    def put_file(self, branch, path, content, message):
        self._guard_ref(branch)
        import base64
        body = {"message": message, "branch": branch,
                "content": base64.b64encode(content).decode()}
        # If the file exists on this branch we must pass its blob sha.
        try:
            cur = self._req(
                "GET",
                f"/repos/{self.owner}/{self.repo}/contents/{path}?ref={branch}")
            if isinstance(cur, dict) and "sha" in cur:
                body["sha"] = cur["sha"]
        except TransportError:
            pass
        out = self._req("PUT", f"/repos/{self.owner}/{self.repo}/contents/{path}", body)
        self._audit("put_file", branch=branch, path=path, force=False)
        return {"path": path, "branch": branch,
                "commit_sha": out["commit"]["sha"], "blob_sha": out["content"]["sha"]}

    def get_file(self, ref, path):
        import base64
        out = self._req(
            "GET", f"/repos/{self.owner}/{self.repo}/contents/{path}?ref={ref}")
        self._audit("get_file", ref=ref, path=path)
        return base64.b64decode(out["content"])

    def open_pr(self, head, base, title, body):
        out = self._req("POST", f"/repos/{self.owner}/{self.repo}/pulls",
                        {"title": title, "head": head, "base": base, "body": body})
        self._audit("open_pr", head=head, base=base)
        return {"number": out["number"], "head": head, "base": base,
                "url": out["html_url"], "state": out["state"], "merged": False}


# ----------------------------------------------------------- local git (proven)

class LocalGitTransport(Transport):
    """Drives the real git binary. Exercised end to end by the tests."""

    def __init__(self, credential, work_dir, remote_dir, protected=PROTECTED_DEFAULT):
        super().__init__(credential, protected)
        self.work = work_dir
        self.remote = remote_dir
        self.prs = {}
        self._pr_seq = 0

    def _git(self, *args, cwd=None, check=True):
        r = subprocess.run(["git"] + list(args), cwd=cwd or self.work,
                           capture_output=True, text=True)
        if check and r.returncode != 0:
            raise TransportError(
                f"git {' '.join(args)} failed ({r.returncode}): {r.stderr.strip()}")
        return r.stdout.strip()

    def default_branch(self):
        return self._git("symbolic-ref", "--short", "HEAD")

    def create_branch(self, name, from_ref=None):
        self._guard_ref(name)
        base = from_ref or self.default_branch()
        base_sha = self._git("rev-parse", base)
        self._git("checkout", "-b", name, base)
        self._audit("create_branch", branch=name, base=base, force=False)
        return {"branch": name, "base": base, "base_sha": base_sha,
                "ref": f"refs/heads/{name}"}

    def put_file(self, branch, path, content, message):
        self._guard_ref(branch)
        self._git("checkout", branch)
        full = os.path.join(self.work, path)
        os.makedirs(os.path.dirname(full), exist_ok=True) if os.path.dirname(path) else None
        with open(full, "wb") as f:
            f.write(content)
        self._git("add", path)
        self._git("commit", "-m", message)
        sha = self._git("rev-parse", "HEAD")
        blob = self._git("rev-parse", f"HEAD:{path}")
        # push WITHOUT force -- a force push is not reachable through this API
        self._git("push", "origin", branch)
        self._audit("put_file", branch=branch, path=path, force=False)
        return {"path": path, "branch": branch, "commit_sha": sha, "blob_sha": blob}

    def get_file(self, ref, path):
        """Read back from the REMOTE, not the working tree. Reading back the
        file you just wrote from your own disk proves nothing."""
        out = subprocess.run(["git", "show", f"{ref}:{path}"],
                             cwd=self.remote, capture_output=True)
        if out.returncode != 0:
            raise TransportError(
                f"read-back failed for {ref}:{path}: {out.stderr.decode().strip()}")
        self._audit("get_file", ref=ref, path=path)
        return out.stdout

    def open_pr(self, head, base, title, body):
        self._pr_seq += 1
        n = self._pr_seq
        head_sha = self._git("rev-parse", head)
        self.prs[n] = {"number": n, "head": head, "base": base, "title": title,
                       "body": body, "state": "open", "merged": False,
                       "head_sha": head_sha}
        self._audit("open_pr", head=head, base=base)
        return dict(self.prs[n], url=f"local://pr/{n}")
