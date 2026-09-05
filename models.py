"""
Complete AI — organizational data model.

Every entity type the agent can search or reason across gets one table.
Cross-references between entities (e.g. an Incident's related_deployment_id)
are plain string ids, not foreign keys with cascades — this mirrors how a
real fragmented organization's systems actually reference each other (a
ticket mentions a deployment id in free text; a Slack message mentions a
PR number) rather than a single clean relational schema.

GroundTruth is stored separately and is never imported by agent/ or tools/ —
enforced by convention and checked by a static-analysis test, same pattern
as FullCircle AI.
"""

from __future__ import annotations

import datetime as dt
import json

from sqlalchemy import Column, DateTime, Float, Integer, String, Text
from sqlalchemy.orm import declarative_base


def _utcnow() -> dt.datetime:
    """SQLAlchemy Column default callable. Stored as a naive UTC datetime
    (SQLite has no native timezone-aware storage), but produced from the
    non-deprecated timezone-aware API rather than the deprecated
    datetime.utcnow(), then stripped of tzinfo for storage consistency with
    the rest of this schema."""
    return dt.datetime.now(dt.timezone.utc).replace(tzinfo=None)


Base = declarative_base()


class Person(Base):
    __tablename__ = "people"
    person_id = Column(String, primary_key=True)
    name = Column(String, nullable=False)
    role = Column(String, nullable=False)
    team = Column(String, nullable=False)


class Message(Base):
    """A single Slack-like message within a channel/thread."""

    __tablename__ = "messages"
    message_id = Column(String, primary_key=True)
    channel = Column(String, index=True, nullable=False)
    thread_id = Column(String, index=True)
    author_id = Column(String, index=True)
    timestamp = Column(DateTime, nullable=False)
    content = Column(Text, nullable=False)
    mentions_json = Column(Text, default="[]")  # entity ids referenced (PR-219, DEP-82, etc.)

    @property
    def mentions(self) -> list[str]:
        return json.loads(self.mentions_json or "[]")

    @mentions.setter
    def mentions(self, value: list[str]):
        self.mentions_json = json.dumps(value or [])


class Document(Base):
    """Architecture docs, runbooks, RFCs, policies — all markdown."""

    __tablename__ = "documents"
    doc_id = Column(String, primary_key=True)
    title = Column(String, nullable=False)
    doc_type = Column(String, nullable=False)  # runbook | architecture | rfc | policy | onboarding
    owner_id = Column(String)
    updated_at = Column(DateTime, nullable=False)
    content = Column(Text, nullable=False)
    mentions_json = Column(Text, default="[]")

    @property
    def mentions(self) -> list[str]:
        return json.loads(self.mentions_json or "[]")

    @mentions.setter
    def mentions(self, value: list[str]):
        self.mentions_json = json.dumps(value or [])


class Repository(Base):
    __tablename__ = "repositories"
    repo_id = Column(String, primary_key=True)
    name = Column(String, nullable=False)
    description = Column(Text, default="")
    path = Column(String, nullable=False)  # path on disk under the sandbox workspace root


class Commit(Base):
    __tablename__ = "commits"
    commit_id = Column(String, primary_key=True)  # short sha
    repo_id = Column(String, index=True, nullable=False)
    author_id = Column(String)
    timestamp = Column(DateTime, nullable=False)
    message = Column(Text, nullable=False)
    files_changed_json = Column(Text, default="[]")

    @property
    def files_changed(self) -> list[str]:
        return json.loads(self.files_changed_json or "[]")

    @files_changed.setter
    def files_changed(self, value: list[str]):
        self.files_changed_json = json.dumps(value or [])


class PullRequest(Base):
    __tablename__ = "pull_requests"
    pr_id = Column(String, primary_key=True)
    repo_id = Column(String, index=True, nullable=False)
    title = Column(String, nullable=False)
    description = Column(Text, default="")
    author_id = Column(String)
    commit_id = Column(String, index=True)
    merged_at = Column(DateTime)
    status = Column(String, default="merged")


class Deployment(Base):
    __tablename__ = "deployments"
    deployment_id = Column(String, primary_key=True)
    repo_id = Column(String, index=True, nullable=False)
    pr_ids_json = Column(Text, default="[]")
    deployed_at = Column(DateTime, nullable=False)
    status = Column(String, default="succeeded")

    @property
    def pr_ids(self) -> list[str]:
        return json.loads(self.pr_ids_json or "[]")

    @pr_ids.setter
    def pr_ids(self, value: list[str]):
        self.pr_ids_json = json.dumps(value or [])


class Ticket(Base):
    __tablename__ = "tickets"
    ticket_id = Column(String, primary_key=True)
    title = Column(String, nullable=False)
    description = Column(Text, default="")
    priority = Column(String, default="P2")
    status = Column(String, default="open")
    assignee_id = Column(String)
    related_incident_id = Column(String)
    related_pr_id = Column(String)
    comments_json = Column(Text, default="[]")

    @property
    def comments(self) -> list[dict]:
        return json.loads(self.comments_json or "[]")

    @comments.setter
    def comments(self, value: list[dict]):
        self.comments_json = json.dumps(value or [])


class Incident(Base):
    __tablename__ = "incidents"
    incident_id = Column(String, primary_key=True)
    service = Column(String, index=True, nullable=False)
    title = Column(String, nullable=False)
    symptoms = Column(Text, default="")
    started_at = Column(DateTime, nullable=False)
    related_deployment_id = Column(String, index=True)
    status = Column(String, default="open")
    timeline_json = Column(Text, default="[]")

    @property
    def timeline(self) -> list[dict]:
        return json.loads(self.timeline_json or "[]")

    @timeline.setter
    def timeline(self, value: list[dict]):
        self.timeline_json = json.dumps(value or [])


class LogEntry(Base):
    __tablename__ = "log_entries"
    log_id = Column(String, primary_key=True)
    timestamp = Column(DateTime, nullable=False)
    service = Column(String, index=True, nullable=False)
    severity = Column(String, index=True, nullable=False)
    request_id = Column(String)
    trace_id = Column(String, index=True)
    deployment_id = Column(String, index=True)
    message = Column(Text, nullable=False)
    latency_ms = Column(Float)
    status_code = Column(Integer)


class WikiPage(Base):
    """Confluence/Notion-like wiki — the 6th organizational source type,
    distinct from architecture docs/RFCs (which are modeled as 'drive'
    documents). Wiki pages tend to be more informal/team-maintained."""

    __tablename__ = "wiki_pages"
    page_id = Column(String, primary_key=True)
    title = Column(String, nullable=False)
    space = Column(String, nullable=False)  # e.g. "Engineering", "Onboarding"
    owner_id = Column(String)
    updated_at = Column(DateTime, nullable=False)
    content = Column(Text, nullable=False)
    mentions_json = Column(Text, default="[]")

    @property
    def mentions(self) -> list[str]:
        return json.loads(self.mentions_json or "[]")

    @mentions.setter
    def mentions(self, value: list[str]):
        self.mentions_json = json.dumps(value or [])


class GroundTruthBug(Base):
    """
    Hidden ground truth for injected engineering bugs. Never imported by
    agent/ or tools/ — only simulator/ writes it and evaluation/ reads it.
    """

    __tablename__ = "ground_truth_bugs"
    bug_id = Column(String, primary_key=True)
    repo_id = Column(String, nullable=False)
    bug_type = Column(String, nullable=False)
    file_path = Column(String, nullable=False)
    description = Column(Text, default="")
    related_incident_id = Column(String)
    related_deployment_id = Column(String)
    related_pr_id = Column(String)


class SimEvent(Base):
    """
    A pending trigger from a simulated external system — a GitHub CI failure
    notification or a ticket auto-assignment. This is the 'zero user prompt'
    entry door: something appears here on its own (seeded by the
    organization generator, exactly like every other entity), and dispatching
    it runs the SAME CompleteAgent.run() loop as any other task, with an
    objective derived from the event rather than typed by a human.
    """

    __tablename__ = "sim_events"
    event_id = Column(String, primary_key=True)
    source = Column(String, nullable=False)  # "github_ci" | "ticket_assigned"
    title = Column(String, nullable=False)
    detail = Column(Text, default="")
    derived_objective = Column(Text, nullable=False)
    related_repo_id = Column(String)
    related_entity_id = Column(String)
    created_at = Column(DateTime, nullable=False)
    consumed = Column(String, default="pending")  # pending | dispatched


class TaskRecord(Base):
    """Persisted Complete AI task runs (audit trail + final state), for the API/UI."""

    __tablename__ = "tasks"
    task_id = Column(String, primary_key=True)
    objective = Column(Text, nullable=False)
    status = Column(String, default="RUNNING")
    state_json = Column(Text, default="{}")
    created_at = Column(DateTime, default=_utcnow)
    updated_at = Column(DateTime, default=_utcnow, onupdate=_utcnow)


class TaskMemory(Base):
    """Long-term organizational memory: summaries of completed tasks."""

    __tablename__ = "task_memory"
    memory_id = Column(String, primary_key=True)
    objective = Column(Text, nullable=False)
    summary = Column(Text, default="")
    created_at = Column(DateTime, default=_utcnow)
