"""Complete AI — the single evolving TaskState the agent owns."""

from __future__ import annotations

import datetime as dt
from dataclasses import asdict, dataclass, field


@dataclass
class AuditEntry:
    timestamp: str
    phase: str  # UNDERSTAND | SEARCH | READ | RUN | EDIT | TEST | VERIFY | REQUEST_APPROVAL | CLOSE
    tool: str | None
    summary: str
    data: dict = field(default_factory=dict)


@dataclass
class TaskState:
    task_id: str
    objective: str

    task_type: str = "unclassified"  # knowledge_only | engineering | mixed
    plan: list[dict] = field(default_factory=list)  # [{"step": str, "status": "done|active|pending|failed"}]

    observations: list[dict] = field(default_factory=list)
    evidence: list[dict] = field(default_factory=list)
    hypotheses: list[dict] = field(default_factory=list)
    tool_history: list[str] = field(default_factory=list)
    artifacts: list[dict] = field(default_factory=list)
    code_changes: list[dict] = field(default_factory=list)
    test_results: list[dict] = field(default_factory=list)
    git_operations: list[dict] = field(default_factory=list)
    quality_checks: list[dict] = field(default_factory=list)
    approvals: list[dict] = field(default_factory=list)
    auto_merged: bool = False
    merge_policy: dict | None = None
    multi_repo_results: list[dict] = field(default_factory=list)
    cross_service_check: dict | None = None
    reasoning_policy: str = "reference"
    llm_usage: dict | None = None
    unresolved_questions: list[str] = field(default_factory=list)

    context_graph_nodes: set[str] = field(default_factory=set)

    audit_trail: list[AuditEntry] = field(default_factory=list)

    iteration: int = 0
    status: str = "RUNNING"
    final_answer: str | None = None
    final_verdict: dict | None = None

    def log(self, phase: str, summary: str, tool: str | None = None, data: dict | None = None):
        self.audit_trail.append(
            AuditEntry(
                timestamp=dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
                phase=phase,
                tool=tool,
                summary=summary,
                data=data or {},
            )
        )

    def add_plan_step(self, step: str, status: str = "pending"):
        self.plan.append({"step": step, "status": status})

    def set_plan_status(self, step: str, status: str):
        for p in self.plan:
            if p["step"] == step:
                p["status"] = status
                return

    def add_evidence(self, items: list[dict]):
        self.evidence.extend(items)
        for item in items:
            for eid in [item.get("source_id")] + (item.get("related_entities") or []):
                if eid:
                    self.context_graph_nodes.add(eid)

    def to_dict(self) -> dict:
        return {
            "task_id": self.task_id,
            "objective": self.objective,
            "task_type": self.task_type,
            "plan": self.plan,
            "observations": self.observations,
            "evidence": self.evidence,
            "hypotheses": self.hypotheses,
            "tool_history": self.tool_history,
            "artifacts": self.artifacts,
            "code_changes": self.code_changes,
            "test_results": self.test_results,
            "approvals": self.approvals,
            "git_operations": self.git_operations,
            "quality_checks": self.quality_checks,
            "auto_merged": self.auto_merged,
            "merge_policy": self.merge_policy,
            "multi_repo_results": self.multi_repo_results,
            "cross_service_check": self.cross_service_check,
            "reasoning_policy": self.reasoning_policy,
            "llm_usage": self.llm_usage,
            "unresolved_questions": self.unresolved_questions,
            "context_graph_nodes": sorted(self.context_graph_nodes),
            "audit_trail": [asdict(a) for a in self.audit_trail],
            "iteration": self.iteration,
            "status": self.status,
            "final_answer": self.final_answer,
            "final_verdict": self.final_verdict,
        }
