"""
Complete AI — unified tool registry.

Every tool the agent can call lives in this one dict, regardless of whether
it searches organizational knowledge, inspects a repository, edits code,
runs tests, or prepares a workflow artifact. There is no "DiscoveryAgent"
registry and a separate "ExecutionAgent" registry — one registry, one agent.
"""

from __future__ import annotations

from tools import engineering, git_tools, tickets, workflows
from tools import search as search_tools

TOOL_REGISTRY = {
    # search / knowledge tools
    "search_organization": search_tools.search_organization,
    "search_slack": search_tools.search_slack,
    "search_docs": search_tools.search_docs,
    "search_drive": search_tools.search_drive,
    "search_wiki": search_tools.search_wiki,
    "search_github": search_tools.search_github,
    "search_tickets": search_tools.search_tickets,
    "search_incidents": search_tools.search_incidents,
    "search_logs": search_tools.search_logs,
    "find_related": search_tools.find_related,
    "trace_entity_upstream": search_tools.trace_entity_upstream,
    "trace_entity_downstream": search_tools.trace_entity_downstream,
    "get_entity_neighbors": search_tools.get_entity_neighbors,
    # repository / git tools
    "list_repositories": git_tools.list_repositories,
    "list_files": git_tools.list_files,
    "read_file": git_tools.read_file,
    "search_code": git_tools.search_code,
    "inspect_git_history": git_tools.inspect_git_history,
    "inspect_pull_requests": git_tools.inspect_pull_requests,
    "inspect_diff": git_tools.inspect_diff,
    # engineering / execution tools
    "edit_file": engineering.edit_file,
    "create_file": engineering.create_file,
    "run_tests": engineering.run_tests,
    "run_command": engineering.run_command,
    "run_linter": engineering.run_linter,
    "run_formatter": engineering.run_formatter,
    "create_branch": engineering.create_branch,
    "commit_changes": engineering.commit_changes,
    "create_test_file": engineering.create_test_file,
    "review_pull_request": engineering.review_pull_request,
    "reproduce_issue": engineering.reproduce_issue,
    # workflow tools
    "update_ticket": workflows.update_ticket,
    "prepare_pull_request": workflows.prepare_pull_request,
    "request_approval": workflows.request_approval,
    "read_ticket": tickets.read_ticket,
}


def call_tool(name: str, /, **kwargs):
    if name not in TOOL_REGISTRY:
        raise KeyError(f"Unknown tool: {name}")
    return TOOL_REGISTRY[name](**kwargs)


def available_tools() -> list[str]:
    return sorted(TOOL_REGISTRY.keys())
