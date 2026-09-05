"""
Complete AI — deterministic safety gate.

Never trusts the reasoning policy's own judgment about whether an action is
safe. Every tool call is looked up against a fixed classification table and
resolved to one of: ALLOWED (read tools execute freely), SANDBOX_ONLY
(write tools that only touch the task's sandbox execute freely), or
APPROVAL_REQUIRED (external-write tools always pause for a human — there is
no autonomy-limit-style auto-approval for these, unlike FullCircle AI's
amount-bounded actions, because "did this ticket update look reasonable" has
no analogous deterministic amount check). DENIED tools never execute at all,
regardless of the reasoning policy's confidence.
"""

from __future__ import annotations

TOOL_TIERS = {
    # READ — always allowed, no approval needed
    "search_organization": "ALLOWED",
    "search_slack": "ALLOWED",
    "search_docs": "ALLOWED",
    "search_drive": "ALLOWED",
    "search_wiki": "ALLOWED",
    "search_github": "ALLOWED",
    "search_tickets": "ALLOWED",
    "search_incidents": "ALLOWED",
    "search_logs": "ALLOWED",
    "find_related": "ALLOWED",
    "trace_entity_upstream": "ALLOWED",
    "trace_entity_downstream": "ALLOWED",
    "get_entity_neighbors": "ALLOWED",
    "list_repositories": "ALLOWED",
    "list_files": "ALLOWED",
    "read_file": "ALLOWED",
    "search_code": "ALLOWED",
    "inspect_git_history": "ALLOWED",
    "inspect_pull_requests": "ALLOWED",
    "inspect_diff": "ALLOWED",
    "read_ticket": "ALLOWED",
    # SANDBOX WRITE — allowed autonomously, but confined to the task's sandbox
    "edit_file": "SANDBOX_ONLY",
    "create_file": "SANDBOX_ONLY",
    "run_tests": "SANDBOX_ONLY",
    "run_command": "SANDBOX_ONLY",
    "run_linter": "SANDBOX_ONLY",
    "reproduce_issue": "SANDBOX_ONLY",
    "run_formatter": "SANDBOX_ONLY",
    "create_branch": "SANDBOX_ONLY",
    "commit_changes": "SANDBOX_ONLY",
    "create_test_file": "SANDBOX_ONLY",
    "review_pull_request": "SANDBOX_ONLY",
    # EXTERNAL WRITE — always requires approval
    "update_ticket": "APPROVAL_REQUIRED",
    "prepare_pull_request": "APPROVAL_REQUIRED",
    # HIGH RISK — never auto-executed, full stop
    "deploy_to_production": "DENIED",
    "delete_database": "DENIED",
    "rotate_credentials": "DENIED",
    "send_customer_communication": "DENIED",
}


def classify_tool(tool_name: str) -> str:
    return TOOL_TIERS.get(tool_name, "APPROVAL_REQUIRED")  # unknown tools default to safe


def evaluate_action(tool_name: str, sandbox_confined: bool = True) -> dict:
    tier = classify_tool(tool_name)
    if tier == "DENIED":
        return {
            "verdict": "DENIED",
            "tier": tier,
            "reasons": [f"{tool_name} is a high-risk action; never auto-executed"],
        }
    if tier == "APPROVAL_REQUIRED":
        return {
            "verdict": "APPROVAL_REQUIRED",
            "tier": tier,
            "reasons": [f"{tool_name} is an external write; requires human approval before it takes effect"],
        }
    if tier == "SANDBOX_ONLY" and not sandbox_confined:
        return {
            "verdict": "DENIED",
            "tier": tier,
            "reasons": ["write action attempted outside the sandbox boundary"],
        }
    return {"verdict": "ALLOWED", "tier": tier, "reasons": []}


def evaluate_merge_action(tool_name: str, merge_policy: dict) -> dict:
    """
    The single, central, auditable place the 'may this external write
    proceed without a human' decision is made for prepare_pull_request and
    update_ticket. This function — not orchestration code in agent/runtime.py
    — is the authority: every call site (auto-merge branch and
    human-required branch alike) must call this, so there is no code path
    that silently bypasses the gate for one branch but not the other.

    merge_policy is the real, already-computed output of
    tools/review.py::decide_merge_policy (itself driven by the deterministic
    review gate's actual findings and the actual diff size) — this function
    does not accept a bare boolean from the caller, precisely so a caller
    can't manufacture 'verified_low_risk=True' on its own authority.
    """
    tier = classify_tool(tool_name)
    if tier != "APPROVAL_REQUIRED":
        return evaluate_action(tool_name)
    if merge_policy.get("auto_mergeable"):
        return {
            "verdict": "SAFE_TO_EXECUTE",
            "tier": tier,
            "reasons": [
                f"verified low-risk by the deterministic review gate: {merge_policy.get('reason', '')}"
            ],
        }
    return {
        "verdict": "APPROVAL_REQUIRED",
        "tier": tier,
        "reasons": [
            (
                f"{tool_name} is an external write; requires human approval before it takes effect \u2014 "
                f"{merge_policy.get('reason', 'review gate did not certify this as low-risk')}"
            )
        ],
    }
