"""
Complete AI — editing, testing, and shell tools.

Every operation here is a REAL change to the task's sandboxed copy of a
repository, and every test/command result is a REAL subprocess execution.
Nothing is faked or pre-scripted — the agent's next decision is only ever
as good as what these tools actually observe.
"""

from __future__ import annotations

import difflib
import os
import shutil

from sandbox.workspace import Sandbox


def edit_file(sandbox: Sandbox, repo_id: str, file_path: str, old_str: str, new_str: str) -> dict:
    """Applies a literal find/replace patch (must match exactly once), like a
    real diff-based edit rather than regenerating the whole file."""
    content = sandbox.read_file(repo_id, file_path)
    count = content.count(old_str)
    if count != 1:
        return {"success": False, "reason": f"old_str matched {count} times (expected exactly 1)"}
    new_content = content.replace(old_str, new_str, 1)
    sandbox.write_file(repo_id, file_path, new_content)
    _purge_pycache(sandbox, repo_id)
    diff = "\n".join(
        difflib.unified_diff(
            content.splitlines(),
            new_content.splitlines(),
            fromfile=f"a/{file_path}",
            tofile=f"b/{file_path}",
            lineterm="",
        )
    )
    return {"success": True, "diff": diff}


def _purge_pycache(sandbox: Sandbox, repo_id: str):
    """Belt-and-suspenders alongside PYTHONDONTWRITEBYTECODE: remove any
    compiled bytecode left over from a previous test run in this sandbox so
    a subsequent test run can never see stale cached modules."""
    root = sandbox.repo_path(repo_id)
    for dirpath, dirnames, _filenames in os.walk(root):
        if "__pycache__" in dirnames:
            shutil.rmtree(os.path.join(dirpath, "__pycache__"), ignore_errors=True)


def create_file(sandbox: Sandbox, repo_id: str, file_path: str, content: str) -> dict:
    sandbox.write_file(repo_id, file_path, content)
    return {"success": True, "file_path": file_path}


def run_tests(sandbox: Sandbox, repo_id: str, target: str = "tests/") -> dict:
    """target may be a single path or multiple space-separated paths
    (e.g. "tests/test_checkout.py tests/test_gateway_timeout_regression.py")
    to scope a rerun to exactly the tests relevant to one investigation
    without picking up unrelated pre-existing failures elsewhere in tests/."""
    targets = target.split()
    result = sandbox.run_command(
        repo_id, ["python3", "-m", "pytest", *targets, "-v", "--tb=short", "-p", "no:randomly"]
    )
    passed = result["exit_code"] == 0
    failing_tests = []
    for line in result["stdout"].splitlines():
        if line.startswith("FAILED "):
            failing_tests.append(line.split(" ")[1] if " " in line else line)
    return {
        "passed": passed,
        "exit_code": result["exit_code"],
        "stdout": result["stdout"],
        "stderr": result["stderr"],
        "failing_tests": failing_tests,
    }


def run_command(sandbox: Sandbox, repo_id: str, command: list[str]) -> dict:
    return sandbox.run_command(repo_id, command)


def run_linter(sandbox: Sandbox, repo_id: str) -> dict:
    """Real ruff run — not simulated."""
    result = sandbox.run_command(repo_id, ["python3", "-m", "ruff", "check", "."])
    return {"passed": result["exit_code"] == 0, "stdout": result["stdout"], "stderr": result["stderr"]}


def run_formatter(sandbox: Sandbox, repo_id: str, check_only: bool = True) -> dict:
    """Real black run. check_only=True reports whether formatting is needed
    without changing files; check_only=False actually reformats in place."""
    args = ["python3", "-m", "black", "."]
    if check_only:
        args.append("--check")
    result = sandbox.run_command(repo_id, args)
    return {"passed": result["exit_code"] == 0, "stdout": result["stdout"], "stderr": result["stderr"]}


def create_branch(sandbox: Sandbox, repo_id: str, branch_name: str) -> dict:
    """Real `git checkout -b`."""
    result = sandbox.run_command(repo_id, ["git", "checkout", "-b", branch_name])
    return {
        "success": result["exit_code"] == 0,
        "branch": branch_name,
        "stdout": result["stdout"],
        "stderr": result["stderr"],
    }


def commit_changes(sandbox: Sandbox, repo_id: str, message: str) -> dict:
    """Real `git add -A && git commit`."""
    sandbox.run_command(repo_id, ["git", "add", "-A"])
    result = sandbox.run_command(repo_id, ["git", "commit", "-m", message])
    sha = None
    if result["exit_code"] == 0:
        sha_result = sandbox.run_command(repo_id, ["git", "rev-parse", "--short", "HEAD"])
        sha = sha_result["stdout"].strip()
    return {
        "success": result["exit_code"] == 0,
        "commit_sha": sha,
        "stdout": result["stdout"],
        "stderr": result["stderr"],
    }


def create_test_file(sandbox: Sandbox, repo_id: str, file_path: str, content: str) -> dict:
    """Creates a NEW test file (as opposed to editing an existing one) — used
    for the regression-test-creation requirement."""
    sandbox.write_file(repo_id, file_path, content)
    return {"success": True, "file_path": file_path}


def review_pull_request(diff: str, test_summary: dict) -> dict:
    """Deterministic automated PR review: real checks against the actual
    diff and test results, not a canned LLM narrative."""
    issues = []
    suggestions = []
    lines = diff.splitlines()
    added = [line for line in lines if line.startswith("+") and not line.startswith("+++")]
    removed = [line for line in lines if line.startswith("-") and not line.startswith("---")]

    if not diff.strip():
        issues.append("No code change present in the diff.")
    if not test_summary.get("full_suite_passed"):
        issues.append("Full test suite is not passing.")
    if not test_summary.get("reproduction_passed"):
        issues.append("The original reproduction case does not pass.")
    if len(added) + len(removed) > 120:
        suggestions.append("Large diff for a single fix — consider whether this is in scope.")
    if not any("test" in line.lower() for line in added):
        suggestions.append("Consider adding a dedicated regression test for this change.")

    verdict = "BLOCKED" if issues else "APPROVED"
    return {
        "verdict": verdict,
        "issues": issues,
        "suggestions": suggestions,
        "lines_added": len(added),
        "lines_removed": len(removed),
    }


def reproduce_issue(sandbox: Sandbox, repo_id: str, test_name: str) -> dict:
    """Runs one specific test as a targeted reproduction, not the whole suite."""
    result = sandbox.run_command(repo_id, ["python3", "-m", "pytest", test_name, "-v", "--tb=long"])
    return {"reproduced": result["exit_code"] != 0, "stdout": result["stdout"], "stderr": result["stderr"]}
