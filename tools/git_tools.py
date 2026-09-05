"""Complete AI — repository, filesystem, and git-history tools."""

from __future__ import annotations

import os

from logging_config import get_logger
from models import Commit, PullRequest, Repository
from sandbox.workspace import Sandbox

_log = get_logger("git_tools")


def list_repositories(session) -> list[dict]:
    return [
        {"repo_id": r.repo_id, "name": r.name, "description": r.description}
        for r in session.query(Repository).all()
    ]


def list_files(sandbox: Sandbox, repo_id: str) -> list[str]:
    root = sandbox.repo_path(repo_id)
    files = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d != ".git"]
        for f in filenames:
            rel = os.path.relpath(os.path.join(dirpath, f), root)
            files.append(rel)
    return sorted(files)


def read_file(sandbox: Sandbox, repo_id: str, file_path: str) -> str:
    return sandbox.read_file(repo_id, file_path)


def search_code(sandbox: Sandbox, repo_id: str, query: str) -> list[dict]:
    """Naive but real grep-style search across the sandbox's copy of the repo."""
    matches = []
    for rel_path in list_files(sandbox, repo_id):
        if not rel_path.endswith(".py"):
            continue
        try:
            content = sandbox.read_file(repo_id, rel_path)
        except (OSError, UnicodeDecodeError) as ex:
            # A single unreadable/non-text file must not abort the whole
            # search — but skipping it silently with zero trace is exactly
            # how "search found nothing" bugs go unexplained.
            _log.debug(
                "Skipping unreadable file %s in %s during search_code: %s",
                rel_path,
                repo_id,
                ex.__class__.__name__,
            )
            continue
        for i, line in enumerate(content.splitlines(), start=1):
            if query.lower() in line.lower():
                matches.append({"file": rel_path, "line": i, "content": line.strip()})
    return matches


def inspect_git_history(session, repo_id: str) -> list[dict]:
    commits = session.query(Commit).filter(Commit.repo_id == repo_id).order_by(Commit.timestamp).all()
    return [
        {
            "commit_id": c.commit_id,
            "message": c.message,
            "timestamp": c.timestamp.isoformat(),
            "files_changed": c.files_changed,
        }
        for c in commits
    ]


def inspect_pull_requests(session, repo_id: str) -> list[dict]:
    prs = session.query(PullRequest).filter(PullRequest.repo_id == repo_id).all()
    return [
        {
            "pr_id": p.pr_id,
            "title": p.title,
            "description": p.description,
            "commit_id": p.commit_id,
            "merged_at": p.merged_at.isoformat() if p.merged_at else None,
        }
        for p in prs
    ]


def inspect_diff(sandbox: Sandbox, repo_id: str) -> str:
    """Real git diff. Prefers uncommitted working-tree changes; if the fix
    was already committed (Complete AI's own commit_changes tool does this
    once tests+lint+format all pass), falls back to the diff introduced by
    the most recent commit instead of reporting an empty diff."""
    working = sandbox.run_command(repo_id, ["git", "diff"])
    if working["stdout"].strip():
        return working["stdout"]
    last_commit_diff = sandbox.run_command(repo_id, ["git", "diff", "HEAD~1", "HEAD"])
    if last_commit_diff["exit_code"] == 0:
        return last_commit_diff["stdout"]
    return ""
