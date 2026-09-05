"""
Complete AI — workflow tools.

update_ticket and prepare_pull_request are EXTERNAL_WRITE tier — they don't
touch a real Jira/GitHub (none exists here), but they do write real rows to
Complete AI's own database representing "the outside world," and are
gated by the safety gate exactly like a real external write would be.
"""

from __future__ import annotations

import datetime as dt
import uuid

from models import Ticket


def update_ticket(session, ticket_id: str, status: str | None = None, comment: str | None = None) -> dict:
    ticket = session.query(Ticket).filter(Ticket.ticket_id == ticket_id).first()
    if not ticket:
        return {"success": False, "reason": f"no such ticket: {ticket_id}"}
    if status:
        ticket.status = status
    if comment:
        comments = ticket.comments
        comments.append(
            {
                "author": "complete-ai",
                "text": comment,
                "timestamp": dt.datetime.now(dt.timezone.utc).isoformat(),
            }
        )
        ticket.comments = comments
    session.flush()
    return {"success": True, "ticket_id": ticket_id, "status": ticket.status}


def prepare_pull_request(
    repo_id: str, title: str, description: str, diff: str, test_summary: dict, risk_assessment: str
) -> dict:
    pr_draft_id = f"DRAFT-PR-{uuid.uuid4().hex[:8]}"
    return {
        "pr_draft_id": pr_draft_id,
        "repo_id": repo_id,
        "title": title,
        "description": description,
        "diff": diff,
        "test_summary": test_summary,
        "risk_assessment": risk_assessment,
        "status": "awaiting_review",
    }


def request_approval(action: str, reason: str, risk_level: str) -> dict:
    return {
        "approval_id": f"APR-{uuid.uuid4().hex[:8]}",
        "action": action,
        "reason": reason,
        "risk_level": risk_level,
        "status": "PENDING_HUMAN_APPROVAL",
    }
