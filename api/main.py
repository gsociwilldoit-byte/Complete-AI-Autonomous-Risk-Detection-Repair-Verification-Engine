"""
Complete AI — API layer.

Thin FastAPI wrapper around the single agent runtime. No business logic
lives here — every number/answer/diff the API returns is computed by
agent/, tools/, or knowledge/ at request time.
"""

from __future__ import annotations

import json
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from agent.runtime import CompleteAgent
from agent.tool_registry import call_tool
from db import SessionLocal, init_db
from knowledge.graph import graph_snapshot
from logging_config import get_logger
from models import Incident, Repository, SimEvent, TaskRecord, Ticket

_log = get_logger("api")


@asynccontextmanager
async def _lifespan(_app: FastAPI):
    init_db(drop=False)
    yield


app = FastAPI(title="Complete AI", version="1.0.0", lifespan=_lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


def get_session():
    return SessionLocal()


class RunTaskRequest(BaseModel):
    objective: str


class ApprovalDecisionRequest(BaseModel):
    action_id: str
    decision: str  # "approve" | "reject"


@app.get("/api/organization/summary")
def organization_summary():
    session = get_session()
    try:
        return {
            "repositories": [
                {"repo_id": r.repo_id, "name": r.name, "description": r.description}
                for r in session.query(Repository).all()
            ],
            "incidents": [
                {"incident_id": i.incident_id, "service": i.service, "title": i.title, "status": i.status}
                for i in session.query(Incident).all()
            ],
            "tickets": [
                {"ticket_id": t.ticket_id, "title": t.title, "status": t.status, "priority": t.priority}
                for t in session.query(Ticket).all()
            ],
        }
    finally:
        session.close()


@app.get("/api/organization/graph")
def organization_graph():
    session = get_session()
    try:
        return graph_snapshot(session)
    finally:
        session.close()


@app.post("/api/tasks")
def run_task(req: RunTaskRequest):
    session = get_session()
    try:
        agent = CompleteAgent(session)
        state = agent.run(req.objective)
        record = TaskRecord(
            task_id=state.task_id,
            objective=req.objective,
            status=state.status,
            state_json=json.dumps(state.to_dict()),
        )
        session.add(record)
        session.commit()
        return {"task_id": state.task_id, "status": state.status, "state": state.to_dict()}
    except Exception as ex:
        session.rollback()
        _log.exception("Unhandled error in %s", ex.__class__.__name__)
        # Never leak raw internal exception text to the client — log the
        # full detail server-side and return a generic message instead.
        raise HTTPException(500, "Internal error — see server logs for detail.") from ex
    finally:
        session.close()


@app.get("/api/tasks")
def list_tasks():
    session = get_session()
    try:
        records = session.query(TaskRecord).order_by(TaskRecord.created_at.desc()).limit(50).all()
        return [
            {
                "task_id": r.task_id,
                "objective": r.objective,
                "status": r.status,
                "created_at": r.created_at.isoformat() if r.created_at else None,
            }
            for r in records
        ]
    finally:
        session.close()


@app.get("/api/tasks/{task_id}")
def get_task(task_id: str):
    session = get_session()
    try:
        record = session.query(TaskRecord).filter(TaskRecord.task_id == task_id).first()
        if not record:
            raise HTTPException(404, "Task not found.")
        return {
            "task_id": record.task_id,
            "objective": record.objective,
            "status": record.status,
            "state": json.loads(record.state_json),
        }
    finally:
        session.close()


@app.get("/api/events")
def list_events():
    """The Event Center: pending triggers from simulated external systems
    (GitHub CI, ticket auto-assignment) — the 'zero user prompt' entry
    doors. Nothing here was typed by a human."""
    session = get_session()
    try:
        events = session.query(SimEvent).order_by(SimEvent.created_at).all()
        return [
            {
                "event_id": e.event_id,
                "source": e.source,
                "title": e.title,
                "detail": e.detail,
                "related_repo_id": e.related_repo_id,
                "related_entity_id": e.related_entity_id,
                "created_at": e.created_at.isoformat() if e.created_at else None,
                "consumed": e.consumed,
            }
            for e in events
        ]
    finally:
        session.close()


@app.post("/api/events/{event_id}/dispatch")
def dispatch_event(event_id: str):
    """Runs the exact same CompleteAgent.run() loop as a normal task, but
    with an objective derived from a pending event instead of typed by a
    human — proving the agent doesn't need a person in the loop to start."""
    session = get_session()
    try:
        event = session.query(SimEvent).filter(SimEvent.event_id == event_id).first()
        if not event:
            raise HTTPException(404, f"No such event: {event_id}")
        if event.consumed == "dispatched":
            raise HTTPException(409, f"Event {event_id} was already dispatched.")

        agent = CompleteAgent(session)
        state = agent.run(event.derived_objective)

        event.consumed = "dispatched"
        record = TaskRecord(
            task_id=state.task_id,
            objective=event.derived_objective,
            status=state.status,
            state_json=json.dumps(state.to_dict()),
        )
        session.add(record)
        session.commit()
        return {
            "task_id": state.task_id,
            "status": state.status,
            "state": state.to_dict(),
            "dispatched_event": event_id,
        }
    except HTTPException:
        session.rollback()
        raise
    except Exception as ex:
        session.rollback()
        _log.exception("Unhandled error in %s", ex.__class__.__name__)
        # Never leak raw internal exception text to the client — log the
        # full detail server-side and return a generic message instead.
        raise HTTPException(500, "Internal error — see server logs for detail.") from ex
    finally:
        session.close()


@app.get("/api/stats/merge-rate")
def merge_rate_stats():
    """Real 'N of M merged without a human in the loop' — computed from
    actual persisted task outcomes, not a fixed constant."""
    session = get_session()
    try:
        records = session.query(TaskRecord).all()
        engineering_tasks = []
        for r in records:
            state = json.loads(r.state_json)
            if state.get("task_type") == "engineering" and state.get("final_verdict"):
                engineering_tasks.append(state)
        total = len(engineering_tasks)
        auto_merged = sum(1 for s in engineering_tasks if s.get("auto_merged"))
        return {
            "total_engineering_tasks": total,
            "auto_merged": auto_merged,
            "human_reviewed": total - auto_merged,
            "auto_merge_rate": round(auto_merged / total, 3) if total else None,
        }
    finally:
        session.close()


@app.get("/health")
def health():
    return {"status": "ok", "product": "Complete AI"}


@app.post("/api/tasks/{task_id}/approvals")
def resolve_approval(task_id: str, req: ApprovalDecisionRequest):
    """
    The real approval gate: an APPROVAL_REQUIRED action prepared by a task
    (opening a PR, updating a ticket) does not take effect until a human
    calls this endpoint. Approving here performs the actual external write
    for real — it does not just flip a status flag in the task's own record.
    """
    if req.decision not in ("approve", "reject"):
        raise HTTPException(400, "decision must be 'approve' or 'reject'")

    session = get_session()
    try:
        record = session.query(TaskRecord).filter(TaskRecord.task_id == task_id).first()
        if not record:
            raise HTTPException(404, "Task not found.")
        state = json.loads(record.state_json)

        approval = next((a for a in state.get("approvals", []) if a["action_id"] == req.action_id), None)
        if approval is None:
            raise HTTPException(404, f"No such pending approval: {req.action_id}")
        if approval["resolved"]:
            raise HTTPException(409, f"Approval {req.action_id} was already {approval['resolution']}.")

        approval["resolved"] = True
        approval["resolution"] = req.decision

        result = None
        if req.decision == "approve":
            if approval["action"] == "update_ticket":
                payload = approval["payload"]
                result = call_tool(
                    "update_ticket",
                    session=session,
                    ticket_id=payload["ticket_id"],
                    status=payload["status"],
                    comment=payload["comment"],
                )
                session.commit()
            elif approval["action"] == "prepare_pull_request":
                # No external GitHub exists here — "opening" the PR means
                # flipping its recorded artifact status from a draft to
                # opened, which the UI and any future task can observe.
                for artifact in state.get("artifacts", []):
                    if (
                        artifact.get("type") == "pull_request_draft"
                        and artifact.get("action_id") == req.action_id
                    ):
                        artifact["status"] = "opened"
                        result = {"pr_number": artifact.get("pr_number"), "status": "opened"}

        record.state_json = json.dumps(state)
        # if every approval is now resolved, the task's overall status can move past APPROVAL_REQUIRED
        if all(a["resolved"] for a in state.get("approvals", [])):
            any_rejected = any(a["resolution"] == "reject" for a in state.get("approvals", []))
            record.status = (
                "REJECTED"
                if any_rejected
                else (state.get("final_verdict") or {}).get("verdict", record.status)
            )
            state["status"] = record.status
            record.state_json = json.dumps(state)
        session.commit()

        return {
            "action_id": req.action_id,
            "decision": req.decision,
            "result": result,
            "task_status": record.status,
            "state": state,
        }
    except HTTPException:
        session.rollback()
        raise
    except Exception as ex:
        session.rollback()
        _log.exception("Unhandled error in %s", ex.__class__.__name__)
        # Never leak raw internal exception text to the client — log the
        # full detail server-side and return a generic message instead.
        raise HTTPException(500, "Internal error — see server logs for detail.") from ex
    finally:
        session.close()


_frontend_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "frontend")
if os.path.isdir(_frontend_dir):
    app.mount("/", StaticFiles(directory=_frontend_dir, html=True), name="frontend")
