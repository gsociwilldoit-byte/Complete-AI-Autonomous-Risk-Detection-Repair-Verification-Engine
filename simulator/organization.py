"""
Complete AI — organization orchestrator.

Run:
    python -m simulator.organization --seed 42
"""

from __future__ import annotations

import argparse
import datetime as dt
import os
import random

from db import init_db, session_scope
from models import (
    Commit,
    Deployment,
    Document,
    GroundTruthBug,
    Incident,
    LogEntry,
    Message,
    Person,
    PullRequest,
    Repository,
    SimEvent,
    Ticket,
    WikiPage,
)
from simulator.communications import (
    PEOPLE,
    build_deployments,
    build_documents,
    build_incidents,
    build_logs,
    build_messages,
    build_pull_requests,
    build_sim_events,
    build_tickets,
    build_wiki_pages,
)
from simulator.repositories import build_all_repositories


def generate_organization(seed: int, workspace_root: str = "demo_org/workspace"):
    rng = random.Random(seed)
    # Deliberately naive: this is the anchor point of the SIMULATED
    # organization's internal timeline, not a real-world timestamp — every
    # generated entity's date is computed relative to it via consistent
    # (also-naive) arithmetic throughout the simulator. Making it
    # timezone-aware would need every generator function's date math to
    # follow suit for no behavioral benefit, since nothing here is ever
    # compared against real wall-clock time.
    base_time = dt.datetime(2026, 6, 8)  # noqa: DTZ001

    repos = build_all_repositories(workspace_root, rng, base_time)
    deployments = build_deployments(rng, repos, base_time)
    prs = build_pull_requests(rng, repos, deployments)
    incidents = build_incidents(rng, repos, deployments, base_time)
    logs = build_logs(rng, repos, incidents)
    tickets = build_tickets(rng, incidents, prs)
    messages = build_messages(rng, repos, incidents, prs, base_time)
    documents = build_documents(rng, repos, base_time)
    wiki_pages = build_wiki_pages(rng, repos, base_time)
    sim_events = build_sim_events(rng, repos, incidents, tickets, deployments, base_time)

    return {
        "repos": repos,
        "deployments": deployments,
        "prs": prs,
        "incidents": incidents,
        "logs": logs,
        "tickets": tickets,
        "messages": messages,
        "documents": documents,
        "wiki_pages": wiki_pages,
        "sim_events": sim_events,
    }


def persist(data: dict, workspace_root: str, drop: bool = True):
    init_db(drop=drop)
    with session_scope() as session:
        for p in PEOPLE:
            session.merge(Person(**p))

        for r in data["repos"]:
            session.merge(
                Repository(
                    repo_id=r.repo_id, name=r.name, description=r.description, path=os.path.relpath(r.path)
                )
            )
            for c in r.commits:
                commit = Commit(
                    commit_id=c["commit_id"],
                    repo_id=r.repo_id,
                    author_id=None,
                    timestamp=c["timestamp"],
                    message=c["message"],
                )
                commit.files_changed = c["files_changed"]
                session.merge(commit)
            if r.bug:
                bug = GroundTruthBug(
                    bug_id=f"BUG-{r.repo_id}",
                    repo_id=r.repo_id,
                    bug_type=r.bug["bug_type"],
                    file_path=r.bug["file_path"],
                    description=r.bug["description"],
                )
                session.merge(bug)

        for d in data["deployments"]:
            dep = Deployment(
                deployment_id=d["deployment_id"],
                repo_id=d["repo_id"],
                deployed_at=d["deployed_at"],
                status=d["status"],
            )
            dep.pr_ids = d.get("pr_ids", [])
            session.merge(dep)

        for p in data["prs"]:
            session.merge(PullRequest(**p))

        session.flush()  # ensure GroundTruthBug rows from the repos loop above are queryable below

        for i in data["incidents"]:
            inc = Incident(
                incident_id=i["incident_id"],
                service=i["service"],
                title=i["title"],
                symptoms=i["symptoms"],
                started_at=i["started_at"],
                related_deployment_id=i.get("related_deployment_id"),
                status=i["status"],
            )
            inc.timeline = i["timeline"]
            session.merge(inc)
            # backfill GroundTruthBug.related_incident_id where applicable
            repo = next((r for r in data["repos"] if r.repo_id == i["service"]), None)
            if repo and repo.bug:
                bug_row = (
                    session.query(GroundTruthBug)
                    .filter(GroundTruthBug.bug_id == f"BUG-{repo.repo_id}")
                    .first()
                )
                if bug_row:
                    bug_row.related_incident_id = i["incident_id"]
                    bug_row.related_deployment_id = i.get("related_deployment_id")

        for log_dict in data["logs"]:
            session.merge(LogEntry(**log_dict))

        for t in data["tickets"]:
            ticket = Ticket(
                ticket_id=t["ticket_id"],
                title=t["title"],
                description=t["description"],
                priority=t["priority"],
                status=t["status"],
                assignee_id=t["assignee_id"],
                related_incident_id=t.get("related_incident_id"),
                related_pr_id=t.get("related_pr_id"),
            )
            ticket.comments = t.get("comments", [])
            session.merge(ticket)

        for m in data["messages"]:
            msg = Message(
                message_id=m["message_id"],
                channel=m["channel"],
                thread_id=m["thread_id"],
                author_id=m["author_id"],
                timestamp=m["timestamp"],
                content=m["content"],
            )
            msg.mentions = m.get("mentions", [])
            session.merge(msg)

        for d in data["documents"]:
            doc = Document(
                doc_id=d["doc_id"],
                title=d["title"],
                doc_type=d["doc_type"],
                owner_id=d["owner_id"],
                updated_at=d["updated_at"],
                content=d["content"],
            )
            doc.mentions = d.get("mentions", [])
            session.merge(doc)

        for w in data["wiki_pages"]:
            page = WikiPage(
                page_id=w["page_id"],
                title=w["title"],
                space=w["space"],
                owner_id=w["owner_id"],
                updated_at=w["updated_at"],
                content=w["content"],
            )
            page.mentions = w.get("mentions", [])
            session.merge(page)

        for e in data["sim_events"]:
            session.merge(
                SimEvent(
                    event_id=e["event_id"],
                    source=e["source"],
                    title=e["title"],
                    detail=e["detail"],
                    derived_objective=e["derived_objective"],
                    related_repo_id=e.get("related_repo_id"),
                    related_entity_id=e.get("related_entity_id"),
                    created_at=e["created_at"],
                    consumed="pending",
                )
            )


def main():
    parser = argparse.ArgumentParser(description="Generate Complete AI's simulated organization.")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--workspace-root", type=str, default="demo_org/workspace")
    args = parser.parse_args()

    data = generate_organization(args.seed, args.workspace_root)
    persist(data, args.workspace_root)

    print(f"[Complete AI] Generated organization for seed={args.seed}")
    print(f"  repositories: {len(data['repos'])}")
    print(f"  commits:      {sum(len(r.commits) for r in data['repos'])}")
    print(f"  deployments:  {len(data['deployments'])}")
    print(f"  pull requests:{len(data['prs'])}")
    print(f"  incidents:    {len(data['incidents'])}")
    print(f"  tickets:      {len(data['tickets'])}")
    print(f"  messages:     {len(data['messages'])}")
    print(f"  documents:    {len(data['documents'])}")
    print(f"  wiki pages:   {len(data['wiki_pages'])}")
    print(f"  sim events:   {len(data['sim_events'])}")
    print(f"  log entries:  {len(data['logs'])}")
    print(f"  injected bugs:{sum(1 for r in data['repos'] if r.bug)}")


if __name__ == "__main__":
    main()
