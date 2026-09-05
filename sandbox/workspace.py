"""
Complete AI — sandbox workspace.

Every task gets its own copy of the organizational repositories, so edits
and test runs from one task never affect another (or the canonical
demo_org/workspace used for re-running the same scenario repeatedly). This
is the ONLY module allowed to run shell commands, and every command is
confined to a task's sandbox directory — no access outside it.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import uuid
from pathlib import Path

_VALID_REPO_ID = re.compile(r"^[A-Za-z0-9_.-]+$")


def _validate_repo_id(repo_id: str) -> str:
    """A repo_id is used to build a filesystem path — it must not be able
    to contain path separators, `..`, or an absolute-path prefix. Rejecting
    anything outside a strict allow-list of characters is safer than
    trying to enumerate every way a traversal string could be encoded."""
    if not repo_id or not _VALID_REPO_ID.match(repo_id) or ".." in repo_id:
        raise PermissionError(f"invalid repository id: {repo_id!r}")
    return repo_id


def _workspace_root() -> str:
    """Read fresh at call time, not cached at import time. A module-level
    constant here would silently defeat test isolation: pytest imports this
    module (transitively, via agent.runtime etc.) during collection, before
    any fixture that sets COMPLETE_AI_WORKSPACE_ROOT has run — so a bare
    module-level assignment would permanently bind to whatever the
    environment held at import time, regardless of what a fixture sets
    afterward. This was a real bug, not a hypothetical one: found by
    running `evaluation.run` (which regenerates the real demo_org/workspace
    with a different seed) immediately before the test suite — the test
    suite's own isolated-workspace fixture had no effect, because the
    stale import-time value was already locked in.
    """
    return os.environ.get("COMPLETE_AI_WORKSPACE_ROOT", "demo_org/workspace")


def _sandbox_root() -> str:
    """See _workspace_root — same reasoning, read fresh at call time."""
    return os.environ.get("COMPLETE_AI_SANDBOX_ROOT", "demo_org/sandboxes")


class Sandbox:
    def __init__(self, task_id: str):
        self.task_id = task_id
        self.root = os.path.abspath(os.path.join(_sandbox_root(), task_id))

    def provision(self, repo_ids: list[str] | None = None):
        os.makedirs(self.root, exist_ok=True)
        source_root = os.path.abspath(_workspace_root())
        available = list(os.listdir(source_root)) if os.path.isdir(source_root) else []
        for repo_id in repo_ids or available:
            repo_id = _validate_repo_id(repo_id)
            src = os.path.join(source_root, repo_id)
            dst = os.path.join(self.root, repo_id)
            if os.path.isdir(src) and not os.path.isdir(dst):
                shutil.copytree(src, dst)
                self._configure_local_git_identity(dst)
        return self

    @staticmethod
    def _configure_local_git_identity(repo_dir: str):
        """Every sandboxed repo gets its OWN local git identity, set
        immediately after cloning — never inherited from (and never
        dependent on) the host machine's global git config. `git commit`
        inside this sandbox must work on a machine with no global identity
        configured at all; this is what makes that true, not an assumption
        about the demo environment.
        """
        if not os.path.isdir(os.path.join(repo_dir, ".git")):
            return
        for key, value in (("user.email", "agent@complete.ai"), ("user.name", "Complete AI Agent")):
            subprocess.run(
                ["git", "config", "--local", key, value],
                cwd=repo_dir,
                capture_output=True,
                check=False,
            )

    def repo_path(self, repo_id: str) -> str:
        return os.path.join(self.root, _validate_repo_id(repo_id))

    def resolve(self, repo_id: str, relative_path: str) -> str:
        """
        Resolves a path within a repo, refusing to escape the sandbox root.

        A plain `candidate.startswith(repo_root)` string check has a real
        prefix-collision bug: repo_root="/sbx/checkout-service" would
        wrongly accept "/sbx/checkout-service-evil/secret.txt", since that
        string literally starts with the repo_root string while actually
        being a sibling directory, not a subdirectory. Path.resolve() +
        is_relative_to() compares real path components, not string
        prefixes, and resolve() also follows symlinks to their real target
        before that comparison — so a symlink planted inside the repo that
        points outside it is caught too, not just a literal `../`.
        """
        repo_root = Path(self.repo_path(repo_id)).resolve()
        candidate = (repo_root / relative_path).resolve()
        if not candidate.is_relative_to(repo_root):
            raise PermissionError(f"path escapes sandbox: {relative_path}")
        return str(candidate)

    def read_file(self, repo_id: str, relative_path: str) -> str:
        path = self.resolve(repo_id, relative_path)
        with open(path, "r") as f:
            return f.read()

    def write_file(self, repo_id: str, relative_path: str, content: str):
        path = self.resolve(repo_id, relative_path)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as f:
            f.write(content)

    def run_command(self, repo_id: str, command: list[str], timeout: int = 30) -> dict:
        """Runs a command with cwd confined to this task's copy of the repo.

        PYTHONDONTWRITEBYTECODE is set to prevent a real correctness bug:
        Python's default .pyc cache invalidates on (mtime, size). Two rapid
        edits to the same file (e.g. "5000" -> "1450", both 4 characters,
        within the same wall-clock second) can leave size AND mtime
        unchanged from Python's perspective, causing a stale compiled
        module to be reused instead of the actual new source — silently
        re-running tests against the previous edit.
        """
        cwd = self.repo_path(repo_id)
        if not os.path.isdir(cwd):
            return {"exit_code": -1, "stdout": "", "stderr": f"no such repo in sandbox: {repo_id}"}
        env = dict(os.environ)
        env["PYTHONDONTWRITEBYTECODE"] = "1"
        try:
            proc = subprocess.run(
                command,
                cwd=cwd,
                capture_output=True,
                text=True,
                timeout=timeout,
                env=env,
                check=False,
            )
            return {"exit_code": proc.returncode, "stdout": proc.stdout, "stderr": proc.stderr}
        except subprocess.TimeoutExpired:
            return {"exit_code": -1, "stdout": "", "stderr": "command timed out"}

    def cleanup(self):
        if os.path.isdir(self.root):
            shutil.rmtree(self.root)


def new_sandbox(repo_ids: list[str] | None = None) -> Sandbox:
    task_id = f"task-{uuid.uuid4().hex[:10]}"
    return Sandbox(task_id).provision(repo_ids)
