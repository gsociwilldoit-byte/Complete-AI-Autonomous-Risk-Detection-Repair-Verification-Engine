"""Complete AI — ticket tools. Enables giving the agent ONLY a ticket id
(e.g. "TCK-1969") and having it read the ticket, resolve it to an incident
and repository, and proceed with the full engineering workflow."""

from __future__ import annotations

import re

from models import Incident, Ticket

TICKET_ID_PATTERN = re.compile(r"^\s*(TCK-\d+)\s*$")


def is_bare_ticket_id(text: str) -> str | None:
    m = TICKET_ID_PATTERN.match(text)
    return m.group(1) if m else None


def read_ticket(session, ticket_id: str) -> dict | None:
    t = session.query(Ticket).filter(Ticket.ticket_id == ticket_id).first()
    if not t:
        return None
    incident = None
    if t.related_incident_id:
        incident = session.query(Incident).filter(Incident.incident_id == t.related_incident_id).first()
    return {
        "ticket_id": t.ticket_id,
        "title": t.title,
        "description": t.description,
        "priority": t.priority,
        "status": t.status,
        "assignee_id": t.assignee_id,
        "related_incident_id": t.related_incident_id,
        "related_incident_service": incident.service if incident else None,
        "comments": t.comments,
    }
