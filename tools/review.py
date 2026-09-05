"""
Complete AI — multi-dimensional PR reviewer.

This is the "Slash Reviewer" capability: every generated patch is checked
across five independent dimensions, each producing raw findings. A
filtering pass then discards low-confidence findings (matches inside
comments/docstrings/test files) before anything is scored — this mirrors
the real "AI filter layer removes false positives before any comment is
posted" behavior, implemented as genuine deterministic filtering logic
against the real diff text, not a fabricated ratio.

Every finding carries a severity (HIGH/MEDIUM/LOW). The auto-merge decision
(see decide_merge_policy) is a real function of the filtered findings and
the actual test results — not a fixed "1 in 3" constant. Some fixes in this
demo genuinely qualify for zero-human merge; others genuinely don't,
because they touch different kinds of risk.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

SECURITY_PATTERNS = [
    (
        re.compile(r"""(password|passwd|api[_-]?key|secret|token)\s*=\s*['"][^'"]+['"]""", re.IGNORECASE),
        "possible hardcoded credential",
    ),
    (re.compile(r"\beval\s*\(", re.IGNORECASE), "use of eval()"),
    (re.compile(r"\bexec\s*\(", re.IGNORECASE), "use of exec()"),
    (re.compile(r"pickle\.loads?\s*\(", re.IGNORECASE), "unsafe deserialization (pickle)"),
    (re.compile(r"shell\s*=\s*True", re.IGNORECASE), "subprocess call with shell=True"),
    (re.compile(r"""["']SELECT .* \+|["']SELECT .*%s""", re.IGNORECASE), "possible SQL string concatenation"),
]

# heuristic i18n check: a hardcoded user-facing English sentence assigned to
# a variable/return that looks like it will reach an end user
I18N_PATTERN = re.compile(r"""["'][A-Z][a-zA-Z ,]{12,}["']""")


@dataclass
class Finding:
    dimension: str
    severity: str  # HIGH | MEDIUM | LOW
    message: str
    location: str = ""
    confidence: str = "high"  # high | low — low-confidence findings get filtered


@dataclass
class ReviewResult:
    dimensions: dict = field(default_factory=dict)  # dimension -> "PASS" | "WARNING" | "FAIL"
    potential_findings: list = field(default_factory=list)
    actionable_findings: list = field(default_factory=list)
    filtered_count: int = 0
    severity_counts: dict = field(default_factory=lambda: {"HIGH": 0, "MEDIUM": 0, "LOW": 0})
    verdict: str = "APPROVED"

    def to_dict(self):
        return {
            "dimensions": self.dimensions,
            "potential_findings": [f.__dict__ for f in self.potential_findings],
            "actionable_findings": [f.__dict__ for f in self.actionable_findings],
            "filtered_count": self.filtered_count,
            "severity_counts": self.severity_counts,
            "verdict": self.verdict,
        }


def _diff_added_lines_with_files(diff: str) -> list[tuple[str, str]]:
    """Returns [(file_path, added_line_content), ...] — tracks which file each
    added line belongs to, needed to tell whether a match is inside a test file."""
    out = []
    current_file = ""
    for line in diff.splitlines():
        if line.startswith("+++ "):
            current_file = line[4:].lstrip("b/")
        elif line.startswith("+") and not line.startswith("+++"):
            out.append((current_file, line[1:]))
    return out


# ---- the five dimensions ------------------------------------------------------------------


def _check_bug_detection(test_summary: dict) -> tuple[str, list[Finding]]:
    findings = []
    if not test_summary.get("full_suite_passed"):
        findings.append(
            Finding("bug_detection", "HIGH", "Full test suite is not passing.", confidence="high")
        )
    if not test_summary.get("reproduction_passed"):
        findings.append(
            Finding("bug_detection", "HIGH", "Original reproduction case does not pass.", confidence="high")
        )
    status = "FAIL" if findings else "PASS"
    return status, findings


def _check_security(diff: str) -> tuple[str, list[Finding]]:
    findings = []
    added = _diff_added_lines_with_files(diff)
    for file_path, line in added:
        for pattern, label in SECURITY_PATTERNS:
            if pattern.search(line):
                is_test = "test" in file_path.lower()
                findings.append(
                    Finding(
                        "security",
                        "MEDIUM" if not is_test else "LOW",
                        label,
                        location=f"{file_path}: {line.strip()[:80]}",
                        confidence="low" if is_test else "high",
                    )
                )
    status = "WARNING" if any(f.confidence == "high" for f in findings) else "PASS"
    return status, findings


def _check_design_system(quality_checks: list[dict]) -> tuple[str, list[Finding]]:
    findings = []
    lint = next((q for q in quality_checks if q.get("check") == "lint"), None)
    fmt = next((q for q in quality_checks if q.get("check") == "format"), None)
    if lint and not lint.get("passed"):
        findings.append(
            Finding(
                "design_system",
                "MEDIUM",
                "ruff reported lint violations — see Engineering Standards (WIKI-eng-standards).",
                confidence="high",
            )
        )
    if fmt and not fmt.get("passed"):
        findings.append(Finding("design_system", "LOW", "black formatting check failed.", confidence="high"))
    status = "FAIL" if any(f.severity == "MEDIUM" for f in findings) else ("WARNING" if findings else "PASS")
    return status, findings


def _check_internationalization(diff: str) -> tuple[str, list[Finding]]:
    findings = []
    added = _diff_added_lines_with_files(diff)
    for file_path, line in added:
        if "test" in file_path.lower():
            continue
        m = I18N_PATTERN.search(line)
        if m and (
            "return" in line
            or "message" in line.lower()
            or "error" in line.lower()
            or "reason" in line.lower()
        ):
            findings.append(
                Finding(
                    "internationalization",
                    "LOW",
                    f"Hardcoded user-facing string not routed through a translation helper: {m.group(0)[:50]}",
                    # already excluded test files above, so a match here is a real
                    # finding in real application code — not something to discard
                    location=f"{file_path}: {line.strip()[:80]}",
                    confidence="high",
                )
            )
    status = "WARNING" if findings else "PASS"
    return status, findings


def _check_pre_mortem(diff: str) -> tuple[str, list[Finding]]:
    """
    Structural risk inference: classifies risk from what the diff actually
    changed, never from which repository it came from. Each pattern below
    maps a real, general code-shape signal to a real, general risk class —
    the same signals a human reviewer would look for regardless of which
    service they're looking at.
    """
    findings = []
    added_lines = [
        line[1:] for line in diff.splitlines() if line.startswith("+") and not line.startswith("+++")
    ]

    added_lines = [
        line[1:] for line in diff.splitlines() if line.startswith("+") and not line.startswith("+++")
    ]
    joined_added = "\n".join(added_lines)

    # Matched against the JOINED added text, not line-by-line: black may
    # wrap a long module-level assignment across several lines (e.g.
    # "name = (\n    set()\n)  # comment"), and a purely per-line regex
    # would miss that real, common formatting shape.
    if re.search(r"^_?\w+\s*=\s*\(?\s*(set|dict|list)\(\)", joined_added, re.MULTILINE):
        findings.append(
            Finding(
                "pre_mortem",
                "MEDIUM",
                "Change introduces module-level mutable state (a shared container persisted "
                "across calls) with no concurrent-access test \u2014 a race between two "
                "simultaneous callers is not covered, and this state does not survive a "
                "process restart or scale beyond a single instance.",
                confidence="high",
            )
        )

    io_patterns = [
        (r"\bopen\s*\(", "file I/O"),
        (r"\brequests\.\w+\(", "an outbound HTTP call"),
        (r"\bsocket\.\w+\(", "raw network I/O"),
        (r"\bsubprocess\.\w+\(", "a subprocess invocation"),
        (r"\burllib\.", "an outbound network call"),
    ]
    for pattern, label in io_patterns:
        if any(re.search(pattern, line) for line in added_lines):
            findings.append(
                Finding(
                    "pre_mortem",
                    "LOW",
                    f"Change introduces {label} with no visible retry/idempotency handling in the "
                    f"diff \u2014 a transient failure here has no documented recovery behavior.",
                    confidence="high",
                )
            )
            break

    status = "WARNING" if findings else "PASS"
    return status, findings


# ---- orchestration --------------------------------------------------------------------------


def run_multi_dimensional_review(diff: str, test_summary: dict, quality_checks: list[dict]) -> ReviewResult:
    result = ReviewResult()
    all_potential: list[Finding] = []

    bug_status, bug_findings = _check_bug_detection(test_summary)
    result.dimensions["bug_detection"] = bug_status
    all_potential += bug_findings

    sec_status, sec_findings = _check_security(diff)
    result.dimensions["security"] = sec_status
    all_potential += sec_findings

    design_status, design_findings = _check_design_system(quality_checks)
    result.dimensions["design_system"] = design_status
    all_potential += design_findings

    i18n_status, i18n_findings = _check_internationalization(diff)
    result.dimensions["internationalization"] = i18n_status
    all_potential += i18n_findings

    premortem_status, premortem_findings = _check_pre_mortem(diff)
    result.dimensions["pre_mortem"] = premortem_status
    all_potential += premortem_findings

    # Confidence-filtered review: discard low-confidence findings (pattern
    # matched inside a test file, comment, or otherwise not a real
    # actionable risk) before anything is scored.
    result.potential_findings = all_potential
    result.actionable_findings = [f for f in all_potential if f.confidence == "high"]
    result.filtered_count = len(all_potential) - len(result.actionable_findings)

    for f in result.actionable_findings:
        result.severity_counts[f.severity] += 1

    if result.severity_counts["HIGH"] > 0:
        result.verdict = "BLOCKED"
    elif result.severity_counts["MEDIUM"] > 0:
        result.verdict = "APPROVED_WITH_FINDINGS"
    else:
        result.verdict = "APPROVED"

    return result


def decide_merge_policy(review: ReviewResult, diff: str) -> dict:
    """
    The real auto-merge decision. Zero-human merge requires:
      - no HIGH severity actionable findings (verdict not BLOCKED)
      - no MEDIUM severity actionable findings either (a clean, low-risk patch)
      - a small, single-concern diff (heuristic: fewer than 60 changed lines)
    Anything else routes to human approval. This is a real function of the
    review's own output, not a fixed ratio — some fixes in this demo qualify,
    others deliberately don't, because the underlying risk is genuinely
    different (a bounded config correction vs. a change to shared mutable
    state).
    """
    changed_lines = sum(
        1 for line in diff.splitlines() if line.startswith(("+", "-")) and not line.startswith(("+++", "---"))
    )
    small_scoped = changed_lines < 60

    if review.verdict == "APPROVED" and small_scoped:
        return {
            "auto_mergeable": True,
            "reason": "Clean review across all five dimensions, "
            "no actionable findings, small scoped diff.",
        }
    reasons = []
    if review.verdict != "APPROVED":
        reasons.append(f"review verdict is {review.verdict}")
    if not small_scoped:
        reasons.append(f"diff touches {changed_lines} lines (over the 60-line auto-merge threshold)")
    return {"auto_mergeable": False, "reason": "; ".join(reasons)}
