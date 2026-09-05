"""
Complete AI — independent task verifier.

Structurally separate from the reasoning policy: it takes no "the agent
says it's done" flag, and re-executes real checks (fresh test runs, real
diff inspection, evidence-count thresholds) rather than reading the
reasoning policy's own narrative. The actor may propose a fix is complete;
only this module's re-execution decides whether the evidence supports
that.

Regression detection is identity-aware, not count-based: comparing "3
failing before, 3 failing after" as "no regression" would miss a real
regression that happens to coincide with an unrelated fix (one test
resolved, a different one newly broken, same total count). Every
verifier here compares the actual SET of failing test node ids before and
after, so a new failure is caught even when the total count doesn't move.
"""

from __future__ import annotations

from sandbox.workspace import Sandbox
from tools.engineering import run_tests
from tools.git_tools import inspect_diff


def _normalize_test_id(test_id: str) -> str:
    return test_id.strip()


def _compare_failure_sets(baseline_failures: list, post_patch_failures: list) -> dict:
    baseline_set = {_normalize_test_id(t) for t in baseline_failures}
    post_set = {_normalize_test_id(t) for t in post_patch_failures}
    return {
        "baseline_failures": sorted(baseline_set),
        "post_patch_failures": sorted(post_set),
        "resolved_failures": sorted(baseline_set - post_set),
        "new_failures": sorted(post_set - baseline_set),
    }


def verify_engineering_task(
    sandbox: Sandbox, repo_id: str, reproduction_test: str, baseline_failures: list | None = None
) -> dict:
    """
    Re-runs the full suite fresh (not reusing any cached result the actor
    reported) and separately confirms the specific reproduction test now
    passes and the working tree actually has a non-empty diff.

    baseline_failures, when supplied, enables real identity-aware
    regression detection (see module docstring). When omitted, this
    verifier falls back to requiring the ENTIRE suite green — a strictly
    stronger bar than "no new failures", used when no real pre-fix
    baseline is available to compare against.
    """
    full = run_tests(sandbox, repo_id, target="tests/")
    repro = run_tests(sandbox, repo_id, target=reproduction_test)
    diff = inspect_diff(sandbox, repo_id)

    comparison = _compare_failure_sets(baseline_failures or [], full["failing_tests"])
    no_new_regression = len(comparison["new_failures"]) == 0

    if not diff.strip():
        return {
            "verdict": "FAILED_VERIFICATION",
            "reason": "no code change was actually made",
            "target_reproduction_passed": repro["passed"],
            "full_suite_passed": full["passed"],
            "verification_passed": False,
            **comparison,
        }

    if baseline_failures is not None:
        verification_passed = repro["passed"] and no_new_regression
        verdict = (
            "VERIFIED_COMPLETE"
            if (repro["passed"] and full["passed"])
            else ("PARTIALLY_COMPLETE" if verification_passed else "FAILED_VERIFICATION")
        )
    else:
        verification_passed = full["passed"] and repro["passed"]
        verdict = (
            "VERIFIED_COMPLETE"
            if verification_passed
            else ("PARTIALLY_COMPLETE" if repro["passed"] else "FAILED_VERIFICATION")
        )

    return {
        "verdict": verdict,
        "target_reproduction_passed": repro["passed"],
        "full_suite_passed": full["passed"],
        "no_new_regression": no_new_regression,
        "verification_passed": verification_passed,
        "diff_present": bool(diff.strip()),
        "full_suite_stdout": full["stdout"],
        **comparison,
    }


def verify_scoped_fix(
    sandbox: Sandbox, repo_id: str, reproduction_test: str, baseline_failures: list
) -> dict:
    """
    A scoped verifier for tasks that intentionally touch only one concern in
    a repository that may have other, unrelated pre-existing issues (used by
    the multi-repo flow and the general repair loop). Unlike requiring the
    ENTIRE suite to pass — which would conflate "did this specific fix
    work" with "is this repo free of every other bug" — this requires: the
    specific reproduction test passes, AND no test that was passing at
    baseline is now failing (identity-aware, not a bare count comparison).

    baseline_failures is the real list of failing test node ids captured
    BEFORE any edit was made, not an integer count — this is what makes the
    new_failures/resolved_failures comparison meaningful rather than
    coincidental.
    """
    full = run_tests(sandbox, repo_id, target="tests/")
    repro = run_tests(sandbox, repo_id, target=reproduction_test)
    diff = inspect_diff(sandbox, repo_id)

    comparison = _compare_failure_sets(baseline_failures, full["failing_tests"])
    no_new_regression = len(comparison["new_failures"]) == 0

    if not diff.strip():
        return {
            "verdict": "FAILED_VERIFICATION",
            "reason": "no code change was actually made",
            "target_reproduction_passed": repro["passed"],
            "full_suite_passed": full["passed"],
            "verification_passed": False,
            **comparison,
        }

    verification_passed = repro["passed"] and no_new_regression
    if verification_passed and full["passed"]:
        verdict = "VERIFIED_COMPLETE"
    elif verification_passed:
        verdict = "PARTIALLY_COMPLETE"  # fixed the scoped issue, no new regression, but other pre-existing failures remain
    else:
        verdict = "FAILED_VERIFICATION"

    return {
        "verdict": verdict,
        "target_reproduction_passed": repro["passed"],
        "full_suite_passed": full["passed"],
        "no_new_regression": no_new_regression,
        "verification_passed": verification_passed,
        "diff_present": bool(diff.strip()),
        **comparison,
    }


def verify_knowledge_task(
    evidence: list[dict], min_sources: int = 2, min_distinct_source_types: int = 2
) -> dict:
    """A knowledge-only answer is only VERIFIED_COMPLETE if it's actually
    grounded in enough independently-sourced evidence, not just because the
    reasoning policy says it's confident."""
    if len(evidence) < min_sources:
        return {
            "verdict": "INSUFFICIENT_EVIDENCE",
            "evidence_count": len(evidence),
            "distinct_source_types": 0,
        }
    distinct_types = {e["source"] for e in evidence}
    if len(distinct_types) < min_distinct_source_types:
        return {
            "verdict": "INSUFFICIENT_EVIDENCE",
            "evidence_count": len(evidence),
            "distinct_source_types": len(distinct_types),
        }
    return {
        "verdict": "VERIFIED_COMPLETE",
        "evidence_count": len(evidence),
        "distinct_source_types": len(distinct_types),
    }
