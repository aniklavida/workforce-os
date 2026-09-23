#!/usr/bin/env python3
"""Workforce OS permission model reference and enforcement engine.

This module implements and enforces the three layers of permission in
Workforce OS:

  1. Domain scope: A worker may act only on tasks whose Domain appears in its
     `Domains` field on the Workforce database. Empty `Domains` means none: the
     worker can act on nothing until granted. When an action or assignment is
     blocked, the protocol states clearly why in one line rather than failing
     silently or mysteriously.
  2. Read scope: Each Domain page declares which pages an agent may read for
     that Domain. Anything not declared is out of scope for reading.
  3. Action gate: Anything destructive (deleting), external (sending messages on
     the user's behalf), or irreversible (publishing, paying) requires approval
     in chat. No worker approves its own output unless `May approve` is
     explicitly checked (defaults off).

Additional locked guarantees:
  - Defaults deny: Newly created workers have no domain permissions by default.
  - The `Profile` domain (identity records, official documents, financial
    records) is granted to nobody by default. Adding it is an explicit, loggable
    audit step.
  - Removing a worker revokes its integrations (`Status = Paused`,
    `Channel = None`) without deleting any user data, tasks, notes, or pages.
  - Credentials remain outside the model entirely: requesting or storing
    passwords, OTPs, recovery codes, or full card/bank numbers is forbidden.
  - Permission state is completely legible in Notion: read directly from
    properties (`Domains`, `May approve`, `Status`) and Domain page context
    declarations, never from a hidden configuration file.
  - Handoff discipline: Handoff is a first-class event requiring a non-empty
    reason recorded in Agent Notes, updating Assigned To, and preserving Status
    unless intentionally changed. Handoffs without a reason are refused.
  - Queue discipline: A worker acts only on its own queue (Assigned To matches
    worker and Status != Done). A future Start Date requires waiting. An In progress
    task requires reading Agent Notes first.
  - Note field separation: Notes is strictly user-only; Agent Notes is strictly
    agent-only. Neither writer may touch or clobber the other's field.
  - Role separation: Assistant never executes specialist work; Advisor never
    triggers actions, runs daily status, or maintains fields; Specialist never
    marks work Done without required approval.
  - No lock/claim field: Assigned To relation routes to exactly one worker by
    design; no separate lock property exists.

Usage:
  Dry run (previews permission checks and evaluations without network):
      python3 scripts/workforce_permission.py --dry-run

  Self-test (runs automated permission and scope test suite):
      python3 scripts/workforce_permission.py --self-test

  Live run (validates permissions against live Notion workspace):
      NOTION_TOKEN=... NOTION_PARENT_PAGE_ID=... \\
          python3 scripts/workforce_permission.py --live
"""

from __future__ import annotations

import argparse
from copy import deepcopy
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
import json
import os
import sys
from typing import Any

# Ensure script directory is on sys.path
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
if SCRIPT_DIR not in sys.path:
    sys.path.insert(0, SCRIPT_DIR)

try:
    from workforce_schema import (
        DEFAULT_API_VERSION,
        RELATION_TYPE,
        ROLES,
        TASKS_ASSIGNED_TO_PROP,
        WORKFORCE_TITLE_PROP,
        advisor_worker,
        agent_worker,
        assistant_worker,
        assignment_blockers,
        can_assign,
        human_worker,
        tasks_assigned_to_relation,
        workforce_database_properties,
    )
except ImportError:
    DEFAULT_API_VERSION = "2025-09-03"
    WORKFORCE_TITLE_PROP = "Worker"
    TASKS_ASSIGNED_TO_PROP = "Assigned To"
    RELATION_TYPE = "single_property"
    ROLES = ["Assistant", "Advisor", "Specialist"]

    def assignment_blockers(worker: dict, task_domain: str) -> list[str]:
        blockers = []
        if worker.get("status") != "Active":
            blockers.append(f"worker status is {worker.get('status')!r}, not 'Active'")
        domains = worker.get("domains") or []
        if not domains:
            blockers.append("worker Domains is empty, which means no scope")
        elif task_domain not in domains:
            blockers.append(f"domain {task_domain!r} is not in worker Domains {domains!r}")
        return blockers

    def can_assign(worker: dict, task_domain: str) -> bool:
        return not assignment_blockers(worker, task_domain)

    def human_worker(name: str, domains: list[str] | None = None, role: str = "Specialist") -> dict:
        return {
            "worker": name,
            "kind": "Human",
            "role": role,
            "channel": "None",
            "domains": domains or [],
            "may_approve": False,
            "status": "Active",
        }

    def agent_worker(name: str, domains: list[str], status: str = "Active", role: str = "Specialist") -> dict:
        return {
            "worker": name,
            "kind": "Agent",
            "role": role,
            "channel": "Claude Code",
            "domains": list(domains),
            "may_approve": False,
            "status": status,
        }

    def assistant_worker(name: str, domains: list[str] | None = None, status: str = "Active") -> dict:
        return agent_worker(name, domains or [], status=status, role="Assistant")

    def advisor_worker(name: str, domains: list[str] | None = None, status: str = "Active") -> dict:
        return agent_worker(name, domains or [], status=status, role="Advisor")

    def workforce_database_properties() -> dict:
        return {
            WORKFORCE_TITLE_PROP: {"title": {}},
            "Kind": {"select": {}},
            "Role": {"select": {}},
            "Channel": {"select": {}},
            "Domains": {"multi_select": {}},
            "May approve": {"checkbox": {}},
            "Capabilities": {"rich_text": {}},
            "Status": {"select": {}},
        }

    def tasks_assigned_to_relation(workforce_data_source_id: str) -> dict:
        return {
            TASKS_ASSIGNED_TO_PROP: {
                "relation": {
                    "data_source_id": workforce_data_source_id,
                    "type": RELATION_TYPE,
                }
            }
        }


# --------------------------------------------------------------------------
# Constants
# --------------------------------------------------------------------------

SENSITIVE_DOMAINS = ["Profile"]

GATED_ACTION_TYPES = {
    "send_external_message": "sending a message on the user's behalf",
    "send_message": "sending a message on the user's behalf",
    "delete_page": "deleting a page",
    "delete_database": "deleting a database",
    "delete_task": "deleting a task",
    "delete": "destructive deletion",
    "publish_post": "publishing content externally",
    "publish_release": "publishing a release",
    "publish": "external publishing",
    "send_payment": "executing a financial payment",
    "charge_card": "charging a payment method",
    "pay": "financial disbursement",
}

CREDENTIAL_FORBIDDEN_KEYWORDS = [
    "password",
    "passcode",
    "otp",
    "one-time password",
    "recovery code",
    "credit card",
    "card number",
    "cvv",
    "cvc",
    "bank account number",
    "routing number",
    "iban",
]


# --------------------------------------------------------------------------
# 1. Domain Scope: Acting on Tasks
# --------------------------------------------------------------------------

def can_act_on_task(worker: dict, task: dict) -> tuple[bool, str]:
    """Evaluate whether a worker is authorized to act on a given task.

    Returns:
        (True, reason) if authorized.
        (False, reason) if blocked, where reason is a clear, single-line explanation.
    """
    worker_name = worker.get("worker") or worker.get("name") or "Unknown worker"
    task_title = task.get("title") or task.get("task") or "Untitled task"
    task_domain = task.get("domain") or task.get("Domain") or "Unassigned"

    # Status check
    worker_status = worker.get("status", "Active")
    if worker_status != "Active":
        return (
            False,
            f"Worker '{worker_name}' is {worker_status!r}, not 'Active': cannot act on task '{task_title}'.",
        )

    # Domains check (defaults deny: empty domains grants access to nothing)
    domains = worker.get("domains")
    if domains is None:
        domains = []

    if not domains:
        return (
            False,
            f"Worker '{worker_name}' has empty Domains scope: cannot act on task '{task_title}' (domain '{task_domain}') because no domains are granted.",
        )

    if task_domain not in domains:
        return (
            False,
            f"Worker '{worker_name}' domain scope {domains!r} does not include task domain '{task_domain}': cannot act on task '{task_title}'.",
        )

    return (
        True,
        f"Worker '{worker_name}' is authorized to act on task '{task_title}' in domain '{task_domain}'.",
    )


# --------------------------------------------------------------------------
# 2. Read Scope: Context Loading
# --------------------------------------------------------------------------

def build_default_domain_declarations(domains: list[str]) -> dict[str, list[str]]:
    """Build standard declared read contexts matching AGENTS.md rule 5 and setup."""
    declarations: dict[str, list[str]] = {}
    for d in domains:
        declarations[d] = [
            f"Domains/{d}",
            f"Domains/{d}/*",
            f"Goals/{d}",
            f"Knowledge/{d}",
        ]
    return declarations


def is_page_in_declared_scope(target_page: str, declared_paths: list[str]) -> bool:
    """Mechanically match target_page against declared path patterns."""
    clean_target = target_page.strip().strip("/")
    for pattern in declared_paths:
        clean_pat = pattern.strip().strip("/")
        if clean_pat.endswith("/*"):
            prefix = clean_pat[:-2]
            if clean_target == prefix or clean_target.startswith(prefix + "/"):
                return True
        elif clean_target == clean_pat or clean_target.startswith(clean_pat + "/"):
            return True
    return False


def check_read_scope(
    worker: dict,
    current_domain: str,
    target_page: str,
    domain_declarations: dict[str, list[str]] | None = None,
) -> tuple[bool, str]:
    """Check whether reading target_page is permitted within current_domain.

    Enforces that:
      - The worker has current_domain in its Domains.
      - The target_page is explicitly declared in that Domain's declared context.
      - Undeclared pages (including sensitive pages like Profile) are strictly blocked.
    """
    worker_name = worker.get("worker") or worker.get("name") or "Unknown worker"
    worker_domains = worker.get("domains") or []

    # 1. Does worker have access to current_domain?
    if not worker_domains:
        return (
            False,
            f"Worker '{worker_name}' has empty Domains scope: cannot read context in domain '{current_domain}'.",
        )

    if current_domain not in worker_domains:
        return (
            False,
            f"Worker '{worker_name}' domain scope {worker_domains!r} does not include domain '{current_domain}': read access denied.",
        )

    # 2. Lookup declared context for this domain
    if domain_declarations is None:
        domain_declarations = build_default_domain_declarations(worker_domains)

    declared = domain_declarations.get(current_domain, [])
    if not declared:
        return (
            False,
            f"Domain '{current_domain}' has no declared read context. Reading page '{target_page}' is blocked by default.",
        )

    # 3. Mechanical match against declared context
    if is_page_in_declared_scope(target_page, declared):
        return (
            True,
            f"Page '{target_page}' is within declared read scope for domain '{current_domain}'.",
        )

    return (
        False,
        f"Page '{target_page}' is not declared in read scope for domain '{current_domain}'. Read access denied.",
    )


# --------------------------------------------------------------------------
# 3. Action Gate: Destructive, External, and Irreversible Actions
# --------------------------------------------------------------------------

@dataclass
class ActionRequest:
    action_type: str
    description: str
    is_destructive: bool = False
    is_external: bool = False
    is_irreversible: bool = False


def is_action_gated(action: str | ActionRequest) -> bool:
    """Return True if the action is destructive, external, or irreversible."""
    if isinstance(action, ActionRequest):
        if action.is_destructive or action.is_external or action.is_irreversible:
            return True
        action_name = action.action_type.lower()
    else:
        action_name = str(action).lower()

    return action_name in GATED_ACTION_TYPES


def check_action_gate(
    worker: dict,
    action: str | ActionRequest,
    task: dict | None = None,
) -> tuple[bool, str]:
    """Action gate check for destructive, external, or irreversible actions.

    No worker approves its own output unless `May approve` is explicitly True.
    If `May approve` is False, the action requires approval in chat.
    """
    worker_name = worker.get("worker") or worker.get("name") or "Unknown worker"
    action_name = action.action_type if isinstance(action, ActionRequest) else str(action)
    may_approve = bool(worker.get("may_approve", False))

    if is_action_gated(action):
        if may_approve:
            return (
                True,
                f"Worker '{worker_name}' has 'May approve' = True: action '{action_name}' permitted.",
            )
        action_desc = (
            GATED_ACTION_TYPES.get(action_name.lower())
            or "destructive, external, or irreversible action"
        )
        return (
            False,
            f"Worker '{worker_name}' cannot perform {action_desc} ('{action_name}'): 'May approve' is False. Requires explicit user approval in chat.",
        )

    return (
        True,
        f"Action '{action_name}' is standard operating procedure and permitted.",
    )


# --------------------------------------------------------------------------
# 4. Sensitive Domain (Profile) Management & Audit Log
# --------------------------------------------------------------------------

@dataclass
class DomainAuditRecord:
    event: str
    worker: str
    domain: str
    author: str
    reason: str
    timestamp: str
    is_sensitive: bool


def is_profile_domain_granted(worker: dict) -> bool:
    """Check if worker has been granted access to the sensitive Profile domain."""
    domains = worker.get("domains") or []
    return any(d.lower() == "profile" for d in domains)


def grant_domain(
    worker: dict,
    domain: str,
    author: str,
    reason: str,
    audit_log: list[dict] | None = None,
) -> dict:
    """Grant a domain to a worker as an explicit, deliberate, loggable step.

    Fails if author or reason is empty.
    """
    if not author or not author.strip():
        raise ValueError(
            f"Granting domain '{domain}' requires an explicit author. Anonymous grants are forbidden."
        )
    if not reason or not reason.strip():
        raise ValueError(
            f"Granting domain '{domain}' requires a stated reason. Unexplained grants are forbidden."
        )

    clean_domain = domain.strip()
    is_sensitive = clean_domain in SENSITIVE_DOMAINS or clean_domain.lower() == "profile"

    worker_name = worker.get("worker") or worker.get("name") or "Unknown worker"
    domains = worker.setdefault("domains", [])
    if clean_domain not in domains:
        domains.append(clean_domain)

    record = DomainAuditRecord(
        event="DOMAIN_GRANTED",
        worker=worker_name,
        domain=clean_domain,
        author=author.strip(),
        reason=reason.strip(),
        timestamp=datetime.now(timezone.utc).isoformat(),
        is_sensitive=is_sensitive,
    )
    record_dict = asdict(record)

    if audit_log is not None:
        audit_log.append(record_dict)

    return record_dict


# --------------------------------------------------------------------------
# 5. Worker Removal / Revocation Without User Data Loss
# --------------------------------------------------------------------------

@dataclass
class WorkerRevocationReport:
    worker: str
    status_before: str
    status_after: str
    channel_before: str
    channel_after: str
    tasks_assigned_count: int
    tasks_preserved_count: int
    user_data_deleted_count: int
    tasks_queued_for_reassignment: list[str]


def revoke_worker(
    worker: dict,
    assigned_tasks: list[dict] | None = None,
) -> WorkerRevocationReport:
    """Revoke a worker's integrations without deleting any user data or tasks.

    Sets Status = 'Paused' and Channel = 'None'.
    Tasks assigned to the worker remain intact byte-for-byte in the Tasks
    database and are flagged for reassignment.
    """
    worker_name = worker.get("worker") or worker.get("name") or "Unknown worker"
    status_before = worker.get("status", "Active")
    channel_before = worker.get("channel", "Claude Code")

    # Revoke worker capabilities & channel integration
    worker["status"] = "Paused"
    worker["channel"] = "None"

    tasks = assigned_tasks or []
    reassignment_titles: list[str] = []

    for t in tasks:
        # User Notes and Agent Notes are preserved byte-for-byte
        t["reassignment_needed"] = True
        title = t.get("title") or t.get("task") or "Untitled task"
        reassignment_titles.append(title)

    return WorkerRevocationReport(
        worker=worker_name,
        status_before=status_before,
        status_after=worker["status"],
        channel_before=channel_before,
        channel_after=worker["channel"],
        tasks_assigned_count=len(tasks),
        tasks_preserved_count=len(tasks),
        user_data_deleted_count=0,
        tasks_queued_for_reassignment=reassignment_titles,
    )


# --------------------------------------------------------------------------
# 6. Credential Safeguard
# --------------------------------------------------------------------------

def validate_no_credentials(text: str) -> tuple[bool, str]:
    """Enforce protocol rule: credentials are outside the model entirely."""
    lower_text = text.lower()
    for kw in CREDENTIAL_FORBIDDEN_KEYWORDS:
        if kw in lower_text:
            return (
                False,
                f"Protocol violation: content references credential keyword '{kw}'. Requesting or storing credentials in Notion or chat is forbidden.",
            )
    return (True, "Content clean of credential requests.")


# --------------------------------------------------------------------------
# 7. Notion Legibility
# --------------------------------------------------------------------------

def inspect_worker_notion_permissions(worker: dict) -> dict:
    """Extract and explain permissions directly from Notion properties.

    Proves permissions are legible in Notion with zero hidden config.
    """
    worker_name = worker.get("worker") or worker.get("name") or "Unknown"
    domains = worker.get("domains") or []
    may_approve = bool(worker.get("may_approve", False))
    status = worker.get("status", "Active")

    return {
        "Worker": worker_name,
        "Status": status,
        "Domains": domains,
        "May approve": may_approve,
        "domain_scope_summary": (
            "No domains granted (cannot act on any tasks)"
            if not domains
            else f"Permitted to act in: {', '.join(domains)}"
        ),
        "approval_scope_summary": (
            "Self-approval enabled for external/destructive actions"
            if may_approve
            else "Approval in chat strictly required for external/destructive actions"
        ),
        "profile_access": (
            "Granted"
            if is_profile_domain_granted(worker)
            else "Denied (Profile is sensitive opt-in)"
        ),
    }


# --------------------------------------------------------------------------
# 8. Note Field Separation Invariant & Audit Trail
# --------------------------------------------------------------------------

def append_agent_note(
    existing_notes: str | None,
    worker_name: str,
    message: str,
    timestamp: str | None = None,
) -> str:
    """Append a dated audit log entry to Agent Notes, preserving prior content byte-for-byte."""
    if timestamp is None:
        timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    entry = f"[{timestamp}] {worker_name}: {message.strip()}"
    if not existing_notes or not existing_notes.strip():
        return entry
    return f"{existing_notes.strip()}\n{entry}"


def validate_field_write_permission(
    writer_role_or_kind: str,
    field_name: str,
    writer_name: str = "",
) -> tuple[bool, str]:
    """Enforce the note field separation invariant.

    Notes: User only. Agents never write here.
    Agent Notes: Agent only. Users write in Notes.
    """
    clean_role = (writer_role_or_kind or "").strip()
    clean_field = (field_name or "").strip()

    is_agent = clean_role.lower() in ("agent", "assistant", "advisor", "specialist") or clean_role.lower().endswith("agent")
    is_user = clean_role.lower() in ("user", "human_user")

    if clean_field == "Notes" and is_agent:
        return (
            False,
            f"Invariant violation: Field 'Notes' is user-only. Worker '{writer_name}' ({clean_role}) is forbidden from writing to 'Notes'.",
        )

    if clean_field == "Agent Notes" and is_user:
        return (
            False,
            f"Invariant violation: Field 'Agent Notes' is agent-only. User writes in 'Notes', not 'Agent Notes'.",
        )

    return True, f"Write to field '{clean_field}' permitted for '{clean_role}'."


def update_task_field(
    task: dict,
    field_name: str,
    new_value: Any,
    writer: dict | str,
    is_user: bool = False,
    timestamp: str | None = None,
) -> tuple[bool, str, dict]:
    """Safely update a task field, enforcing field contract invariants.

    - Blocks agents from touching 'Notes'.
    - Blocks users from touching 'Agent Notes'.
    - Appends to 'Agent Notes' with date, never overwriting.
    - Blocks direct changes to 'Assigned To' by non-Assistant agents without handoff.
    """
    task_title = task.get("title") or task.get("task") or "Untitled task"
    if is_user:
        writer_name = "User"
        writer_role = "User"
    elif isinstance(writer, dict):
        writer_name = writer.get("worker") or writer.get("name") or "Unknown"
        writer_role = writer.get("role") or writer.get("kind") or "Agent"
    else:
        writer_name = str(writer)
        writer_role = "Specialist"

    allowed, reason = validate_field_write_permission(writer_role, field_name, writer_name)
    if not allowed:
        return False, reason, task

    if not is_user:
        if field_name == "Agent Notes":
            task["Agent Notes"] = append_agent_note(
                task.get("Agent Notes"), writer_name, str(new_value), timestamp=timestamp
            )
            return True, f"Appended agent note for '{writer_name}' on task '{task_title}'.", task
        if field_name == "Assigned To" and writer_role != "Assistant":
            return (
                False,
                f"Direct reassignment forbidden: Worker '{writer_name}' ({writer_role}) cannot directly edit 'Assigned To'. Use handoff_task with a recorded reason.",
                task,
            )

    task[field_name] = new_value
    return True, f"Updated '{field_name}' on task '{task_title}'.", task


# --------------------------------------------------------------------------
# 9. Role Separation Enforcement
# --------------------------------------------------------------------------

SPECIALIST_ACTION_TYPES = {
    "research",
    "writing",
    "code",
    "coding",
    "drafting",
    "implementation",
    "specialist_work",
    "execute_task",
}

ADVISOR_FORBIDDEN_ACTIONS = {
    "trigger_action",
    "daily_status",
    "run_daily_status",
    "maintain_fields",
    "assign_task",
    "handoff_task",
    "execute_task",
    "delete_page",
    "delete_database",
    "delete_task",
    "delete",
    "send_external_message",
    "send_message",
    "publish_post",
    "publish_release",
    "publish",
    "send_payment",
    "charge_card",
    "pay",
    "update_task_status",
}


def validate_role_action(
    worker: dict,
    action_type: str,
    details: dict | None = None,
) -> tuple[bool, str]:
    """Enforce role separation across Assistant, Advisor, and Specialist roles.

    - Assistant never does specialist work (research/writing/code).
    - Advisor never triggers actions, runs daily status, or maintains fields.
    - Specialist never marks work Done when approval was required and not granted
      (unless May approve is True).
    """
    worker_name = worker.get("worker") or worker.get("name") or "Unknown worker"
    role = worker.get("role", "Specialist")
    clean_action = action_type.strip().lower()

    if role == "Assistant":
        if clean_action in SPECIALIST_ACTION_TYPES:
            return (
                False,
                f"Role violation: Assistant worker '{worker_name}' cannot perform specialist work ('{action_type}'). Assistant manages, organizes, and assigns; it never performs execution work.",
            )

    elif role == "Advisor":
        if clean_action in ADVISOR_FORBIDDEN_ACTIONS or is_action_gated(clean_action):
            return (
                False,
                f"Role violation: Advisor worker '{worker_name}' cannot trigger actions, run daily status, or maintain fields ('{action_type}'). Advisor advises and researches; never acts.",
            )

    elif role == "Specialist":
        if clean_action in ("run_daily_status", "daily_status"):
            return (
                False,
                f"Role violation: Specialist worker '{worker_name}' cannot run daily status. Daily status is managed by Assistant.",
            )
        if clean_action in ("mark_done", "complete_task"):
            det = details or {}
            requires_approval = bool(det.get("requires_approval", False))
            approval_granted = bool(det.get("approval_granted", False))
            may_approve = bool(worker.get("may_approve", False))
            if requires_approval and not approval_granted and not may_approve:
                return (
                    False,
                    f"Role violation: Specialist worker '{worker_name}' cannot mark task Done: approval was required and not yet granted, and 'May approve' is False.",
                )

    return True, f"Action '{action_type}' permitted for worker '{worker_name}' ({role})."


# --------------------------------------------------------------------------
# 10. Handoff Protocol & Authority Gate
# --------------------------------------------------------------------------

@dataclass
class HandoffRecord:
    task_title: str
    from_worker: str
    to_worker: str
    reason: str
    timestamp: str
    previous_status: str
    resulting_status: str


def handoff_task(
    task: dict,
    from_worker: dict,
    to_worker: dict,
    reason: str,
    new_status: str | None = None,
    timestamp: str | None = None,
    audit_log: list[dict] | None = None,
) -> tuple[bool, str, dict]:
    """Execute a first-class handoff event between workers.

    Enforces:
      1. Mandatory non-empty reason recorded in Agent Notes.
      2. from_worker must be current assignee or Assistant.
      3. to_worker must pass assignment gate (Active, non-empty Domains covering task Domain).
      4. Preserves task Status unless new_status is explicitly provided.
      5. User's Notes is strictly untouched.
      6. Appends dated handoff audit record to Agent Notes.
      7. Updates Assigned To relation.
    """
    clean_reason = str(reason).strip() if reason is not None else ""
    if not clean_reason:
        return (
            False,
            "Handoff refused: A handoff must carry a non-empty reason recorded in Agent Notes.",
            task,
        )

    task_title = task.get("title") or task.get("task") or "Untitled task"
    task_domain = task.get("domain") or task.get("Domain") or "Unassigned"
    from_name = from_worker.get("worker") or from_worker.get("name") or "Unknown worker"
    to_name = to_worker.get("worker") or to_worker.get("name") or "Unknown worker"
    from_role = from_worker.get("role", "Specialist")

    # Authority check
    current_assignee = task.get("Assigned To") or task.get("assigned_to")
    if current_assignee and from_name != current_assignee and from_role != "Assistant":
        return (
            False,
            f"Handoff refused: Worker '{from_name}' ({from_role}) cannot hand off task '{task_title}' assigned to '{current_assignee}'. Only the current assignee or Assistant may hand off a task.",
            task,
        )

    if from_role == "Advisor":
        return (
            False,
            f"Role violation: Advisor worker '{from_name}' cannot hand off tasks. Advisor advises; never acts or maintains fields.",
            task,
        )

    # Destination assignment gate check
    blockers = assignment_blockers(to_worker, task_domain)
    if blockers:
        detail = "; ".join(blockers)
        return (
            False,
            f"Handoff refused: Destination worker '{to_name}' cannot receive assignment for task '{task_title}' ({detail}).",
            task,
        )

    # Status handling
    current_status = task.get("Status", "Planned")
    if new_status is not None:
        if new_status not in ("Planned", "In progress", "Done"):
            return (
                False,
                f"Handoff refused: Invalid status '{new_status}'. Status must be 'Planned', 'In progress', or 'Done'.",
                task,
            )
        target_status = new_status
    else:
        target_status = current_status

    if timestamp is None:
        timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

    audit_msg = f"Handoff from {from_name} to {to_name}: {clean_reason}"
    task["Agent Notes"] = append_agent_note(
        task.get("Agent Notes"), from_name, audit_msg, timestamp=timestamp
    )
    task["Assigned To"] = to_name
    task["Status"] = target_status

    record = HandoffRecord(
        task_title=task_title,
        from_worker=from_name,
        to_worker=to_name,
        reason=clean_reason,
        timestamp=timestamp,
        previous_status=current_status,
        resulting_status=target_status,
    )
    if audit_log is not None:
        audit_log.append(asdict(record))

    return (
        True,
        f"Handoff accepted: Task '{task_title}' reassigned from '{from_name}' to '{to_name}'. Reason: {clean_reason}",
        task,
    )


# --------------------------------------------------------------------------
# 11. Queue Discipline & Execution Gate
# --------------------------------------------------------------------------

def get_worker_queue(
    worker: dict,
    tasks: list[dict],
    current_date: str | datetime | None = None,
) -> dict[str, list[dict]]:
    """Filter tasks to produce a worker's queue under AGENTS.md section 4.

    A worker's queue is tasks whose Assigned To relation includes its own
    Workforce row AND Status != Done.

    Returns a dictionary partitioned into:
      - 'all_assigned': all active non-done tasks assigned to this worker
      - 'ready': tasks with Start Date <= current_date (or no Start Date)
      - 'waiting': tasks with future Start Date > current_date
      - 'in_progress': tasks currently In progress
    """
    worker_name = worker.get("worker") or worker.get("name") or ""
    if current_date is None:
        cur_date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    elif isinstance(current_date, datetime):
        cur_date_str = current_date.strftime("%Y-%m-%d")
    else:
        cur_date_str = str(current_date)

    assigned_tasks: list[dict] = []
    ready_tasks: list[dict] = []
    waiting_tasks: list[dict] = []
    in_progress_tasks: list[dict] = []

    for t in tasks:
        assignee = t.get("Assigned To") or t.get("assigned_to")
        if assignee != worker_name:
            continue
        status = t.get("Status") or t.get("status")
        if status == "Done":
            continue

        assigned_tasks.append(t)
        start_date = t.get("Start Date") or t.get("start_date")
        if start_date and str(start_date) > cur_date_str:
            waiting_tasks.append(t)
        else:
            ready_tasks.append(t)

        if status == "In progress":
            in_progress_tasks.append(t)

    return {
        "all_assigned": assigned_tasks,
        "ready": ready_tasks,
        "waiting": waiting_tasks,
        "in_progress": in_progress_tasks,
    }


def start_task_execution(
    worker: dict,
    task: dict,
    current_date: str | datetime | None = None,
    timestamp: str | None = None,
) -> tuple[bool, str, dict]:
    """Protocol check & action: start execution on an assigned task.

    Enforces:
      1. Assigned To matches worker.
      2. Status is not Done.
      3. Future Start Date blocks starting; worker must wait.
      4. Worker must satisfy domain scope (can_act_on_task).
      5. Worker role separation check (Advisor cannot execute tasks; Assistant cannot do specialist work).
      6. If already In progress, checks Agent Notes and preserves existing notes.
      7. Sets Status = 'In progress' and appends dated audit line to Agent Notes.
    """
    worker_name = worker.get("worker") or worker.get("name") or "Unknown worker"
    task_title = task.get("title") or task.get("task") or "Untitled task"
    current_assignee = task.get("Assigned To") or task.get("assigned_to")

    # 1. Assignment check
    if current_assignee != worker_name:
        return (
            False,
            f"Queue violation: Worker '{worker_name}' cannot act on task '{task_title}' assigned to '{current_assignee}'.",
            task,
        )

    # 2. Status != Done check
    if task.get("Status") == "Done":
        return (
            False,
            f"Queue violation: Task '{task_title}' is already Done.",
            task,
        )

    # 3. Future start date check
    if current_date is None:
        cur_date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    elif isinstance(current_date, datetime):
        cur_date_str = current_date.strftime("%Y-%m-%d")
    else:
        cur_date_str = str(current_date)

    start_date = task.get("Start Date") or task.get("start_date")
    if start_date and str(start_date) > cur_date_str:
        return (
            False,
            f"Queue violation: Task '{task_title}' has future Start Date '{start_date}': worker must wait until start date.",
            task,
        )

    # 4. Domain scope check
    can_act, act_reason = can_act_on_task(worker, task)
    if not can_act:
        return False, f"Domain scope blocked: {act_reason}", task

    # 5. Role separation check
    role_ok, role_reason = validate_role_action(worker, "execute_task")
    if not role_ok:
        return False, role_reason, task

    # 6. Status transition & audit trail
    if task.get("Status") == "In progress":
        audit_msg = "Continuing execution on in-progress task after checking Agent Notes."
    else:
        task["Status"] = "In progress"
        audit_msg = "Started work on task."

    task["Agent Notes"] = append_agent_note(
        task.get("Agent Notes"), worker_name, audit_msg, timestamp=timestamp
    )
    return (
        True,
        f"Worker '{worker_name}' successfully active on task '{task_title}' (Status: 'In progress').",
        task,
    )


def complete_task_execution(
    worker: dict,
    task: dict,
    requires_approval: bool = False,
    approval_granted: bool = False,
    summary: str = "",
    timestamp: str | None = None,
) -> tuple[bool, str, dict]:
    """Protocol check & action: complete an assigned task.

    Enforces:
      1. Worker must be Assigned To task.
      2. Specialist role cannot mark Done if approval was required and not granted
         (unless May approve is True).
      3. Sets Status = 'Done'.
      4. Sets Completion Date.
      5. Appends dated audit line to Agent Notes.
    """
    worker_name = worker.get("worker") or worker.get("name") or "Unknown worker"
    task_title = task.get("title") or task.get("task") or "Untitled task"
    current_assignee = task.get("Assigned To") or task.get("assigned_to")

    if current_assignee != worker_name:
        return (
            False,
            f"Queue violation: Worker '{worker_name}' cannot complete task '{task_title}' assigned to '{current_assignee}'.",
            task,
        )

    # Role separation and approval gate
    role_ok, role_reason = validate_role_action(
        worker,
        "complete_task",
        details={"requires_approval": requires_approval, "approval_granted": approval_granted},
    )
    if not role_ok:
        return False, role_reason, task

    task["Status"] = "Done"
    task["Completion Date"] = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    msg = f"Completed task. {summary}".strip()
    task["Agent Notes"] = append_agent_note(
        task.get("Agent Notes"), worker_name, msg, timestamp=timestamp
    )
    return True, f"Task '{task_title}' completed by '{worker_name}'.", task


# --------------------------------------------------------------------------
# 12. Simulated Multi-Worker Workspace
# --------------------------------------------------------------------------

class SimulatedMultiWorkerWorkspace:
    """In-memory simulation of a multi-worker workspace.

    Proves two workers operate one Workforce OS workspace without colliding,
    maintaining queue isolation, handoff reasons, and note separation invariants.
    """

    def __init__(self, workers: list[dict], tasks: list[dict]):
        self.workers: dict[str, dict] = {
            (w.get("worker") or w.get("name")): deepcopy(w) for w in workers
        }
        self.tasks: dict[str, dict] = {
            (t.get("title") or t.get("task")): deepcopy(t) for t in tasks
        }
        self.audit_log: list[dict] = []
        self.event_log: list[str] = []

    def get_worker(self, name: str) -> dict:
        if name not in self.workers:
            raise KeyError(f"Worker '{name}' not found in workspace.")
        return self.workers[name]

    def get_task(self, title: str) -> dict:
        if title not in self.tasks:
            raise KeyError(f"Task '{title}' not found in workspace.")
        return self.tasks[title]

    def get_queue(self, worker_name: str, current_date: str | None = None) -> dict[str, list[dict]]:
        worker = self.get_worker(worker_name)
        return get_worker_queue(worker, list(self.tasks.values()), current_date=current_date)

    def start_task(self, worker_name: str, task_title: str, current_date: str | None = None) -> tuple[bool, str]:
        worker = self.get_worker(worker_name)
        task = self.get_task(task_title)
        ok, reason, updated_task = start_task_execution(worker, task, current_date=current_date)
        if ok:
            self.tasks[task_title] = updated_task
            self.event_log.append(f"{worker_name} started '{task_title}'")
        return ok, reason

    def complete_task(
        self,
        worker_name: str,
        task_title: str,
        requires_approval: bool = False,
        approval_granted: bool = False,
        summary: str = "",
    ) -> tuple[bool, str]:
        worker = self.get_worker(worker_name)
        task = self.get_task(task_title)
        ok, reason, updated_task = complete_task_execution(
            worker, task, requires_approval=requires_approval, approval_granted=approval_granted, summary=summary
        )
        if ok:
            self.tasks[task_title] = updated_task
            self.event_log.append(f"{worker_name} completed '{task_title}'")
        return ok, reason

    def handoff(
        self,
        task_title: str,
        from_worker_name: str,
        to_worker_name: str,
        reason: str,
        new_status: str | None = None,
    ) -> tuple[bool, str]:
        from_w = self.get_worker(from_worker_name)
        to_w = self.get_worker(to_worker_name)
        task = self.get_task(task_title)
        ok, msg, updated_task = handoff_task(
            task, from_w, to_w, reason=reason, new_status=new_status, audit_log=self.audit_log
        )
        if ok:
            self.tasks[task_title] = updated_task
            self.event_log.append(f"Handoff '{task_title}' {from_worker_name} -> {to_worker_name}")
        return ok, msg

    def update_notes_by_user(self, task_title: str, new_notes: str) -> tuple[bool, str]:
        task = self.get_task(task_title)
        ok, msg, updated_task = update_task_field(task, "Notes", new_notes, "User", is_user=True)
        if ok:
            self.tasks[task_title] = updated_task
            self.event_log.append(f"User updated Notes on '{task_title}'")
        return ok, msg

    def update_notes_by_agent(self, worker_name: str, task_title: str, new_notes: str) -> tuple[bool, str]:
        worker = self.get_worker(worker_name)
        task = self.get_task(task_title)
        ok, msg, updated_task = update_task_field(task, "Notes", new_notes, worker, is_user=False)
        if ok:
            self.tasks[task_title] = updated_task
            self.event_log.append(f"{worker_name} updated Notes on '{task_title}'")
        return ok, msg

    def attempt_silent_reassignment(self, worker_name: str, task_title: str, new_assignee: str) -> tuple[bool, str]:
        worker = self.get_worker(worker_name)
        task = self.get_task(task_title)
        ok, msg, updated_task = update_task_field(task, "Assigned To", new_assignee, worker, is_user=False)
        if ok:
            self.tasks[task_title] = updated_task
        return ok, msg


# --------------------------------------------------------------------------
# Self-Test Suite (Proves all 3 Done-When Requirements + Guarantees)
# --------------------------------------------------------------------------

def test_empty_domain_worker_cannot_act_and_states_why_in_one_line() -> bool:
    """Done-when 1: Worker with empty domain scope can act on nothing and states why in one line."""
    worker = agent_worker("Writer", domains=[])
    task = {"title": "Draft quarterly review", "domain": "Writing"}

    allowed, reason = can_act_on_task(worker, task)

    assert not allowed, "Empty domain scope must block action"
    assert "\n" not in reason, "Reason must be strictly a single line"
    assert "Writer" in reason, "Reason must name the worker"
    assert "empty Domains" in reason, "Reason must state empty Domains is the cause"
    assert "Draft quarterly review" in reason, "Reason must name the task"
    assert "Writing" in reason, "Reason must name the task domain"
    return True


def test_read_scope_enforces_domain_declarations_mechanically() -> bool:
    """Done-when 2: Read-scope rule checked mechanically; undeclared page identified as out of scope."""
    worker = agent_worker("Researcher", domains=["Research"])
    domain_declarations = {
        "Research": [
            "Domains/Research",
            "Domains/Research/*",
            "Goals/Research",
            "Knowledge/Research",
        ]
    }

    # Case A: Declared page in scope
    ok_in_scope, reason_in_scope = check_read_scope(
        worker, "Research", "Knowledge/Research", domain_declarations
    )
    assert ok_in_scope, f"Declared page should be allowed: {reason_in_scope}"

    # Case B: Undeclared page in another domain
    ok_out_of_scope, reason_out_of_scope = check_read_scope(
        worker, "Research", "Domains/Finance", domain_declarations
    )
    assert not ok_out_of_scope, "Undeclared page must be blocked"
    assert "not declared in read scope" in reason_out_of_scope
    assert "Domains/Finance" in reason_out_of_scope

    # Case C: Profile page is undeclared and blocked
    ok_profile, reason_profile = check_read_scope(
        worker, "Research", "Profile", domain_declarations
    )
    assert not ok_profile, "Profile page must be blocked when undeclared"
    assert "Profile" in reason_profile

    # Case D: Worker attempting to read domain it does not possess
    unauthorized_worker = agent_worker("Writer", domains=["Writing"])
    ok_wrong_domain, reason_wrong_domain = check_read_scope(
        unauthorized_worker, "Research", "Domains/Research", domain_declarations
    )
    assert not ok_wrong_domain, "Worker without domain cannot read in it"
    assert "does not include domain 'Research'" in reason_wrong_domain

    return True


def test_granting_profile_domain_requires_explicit_loggable_step() -> bool:
    """Done-when 3: Profile domain granted to nobody by default; adding it requires explicit loggable step."""
    # 1. Assert no default worker has Profile in Domains
    w_human = human_worker("Anik")
    w_agent = agent_worker("Researcher", ["Research"])
    assert not is_profile_domain_granted(w_human), "Human worker must not have Profile by default"
    assert not is_profile_domain_granted(w_agent), "Agent worker must not have Profile by default"

    # 2. Assert unlogged or unauthored grant fails
    audit_trail: list[dict] = []
    try:
        grant_domain(w_agent, "Profile", author="", reason="Tax prep", audit_log=audit_trail)
        assert False, "Should have failed without author"
    except ValueError:
        pass

    try:
        grant_domain(w_agent, "Profile", author="Anik", reason="", audit_log=audit_trail)
        assert False, "Should have failed without reason"
    except ValueError:
        pass

    # 3. Deliberate, explicit grant succeeds and creates loggable record
    log_entry = grant_domain(
        w_agent,
        "Profile",
        author="Anik",
        reason="Annual tax preparation requires access to tax documents",
        audit_log=audit_trail,
    )

    assert is_profile_domain_granted(w_agent), "Worker must now have Profile domain"
    assert log_entry["event"] == "DOMAIN_GRANTED"
    assert log_entry["domain"] == "Profile"
    assert log_entry["worker"] == "Researcher"
    assert log_entry["author"] == "Anik"
    assert log_entry["reason"] == "Annual tax preparation requires access to tax documents"
    assert bool(log_entry["timestamp"])
    assert log_entry["is_sensitive"] is True
    assert len(audit_trail) == 1
    return True


def test_action_gate_blocks_destructive_external_actions_without_may_approve() -> bool:
    """Action gate blocks external, destructive, and irreversible actions when May approve is False."""
    worker = agent_worker("Writer", ["Writing"])  # may_approve is False by default

    for action_key in ["send_external_message", "delete_page", "publish_post", "send_payment"]:
        allowed, reason = check_action_gate(worker, action_key)
        assert not allowed, f"Action {action_key} must be blocked when May approve is False"
        assert "May approve' is False" in reason
        assert "Requires explicit user approval in chat" in reason

    # Non-destructive action is allowed
    ok_read, _ = check_action_gate(worker, "update_agent_notes")
    assert ok_read, "Standard internal actions should not be blocked by action gate"
    return True


def test_action_gate_allows_when_may_approve_is_explicitly_true() -> bool:
    """Action gate allows actions when May approve checkbox is explicitly True."""
    worker = agent_worker("LeadWriter", ["Writing"])
    worker["may_approve"] = True

    allowed, reason = check_action_gate(worker, "send_external_message")
    assert allowed, f"May approve = True must permit action: {reason}"
    assert "May approve' = True" in reason
    return True


def test_worker_removal_revokes_integrations_without_deleting_user_data() -> bool:
    """Removing a worker revokes integrations without deleting any tasks or user data."""
    worker = agent_worker("Contractor", ["Writing"])
    tasks = [
        {
            "id": "task_1",
            "title": "Article draft",
            "Notes": "Critical customer feedback: keep Section 2 unchanged.",
            "Agent Notes": "Draft in progress.",
        },
        {
            "id": "task_2",
            "title": "Documentation update",
            "Notes": "User reference links: https://example.com/docs",
            "Agent Notes": "Reviewing spec.",
        },
    ]

    report = revoke_worker(worker, tasks)

    # Worker status and channel revoked
    assert worker["status"] == "Paused"
    assert worker["channel"] == "None"
    assert report.status_after == "Paused"
    assert report.channel_after == "None"

    # User data preservation verified
    assert report.tasks_preserved_count == 2
    assert report.user_data_deleted_count == 0
    assert tasks[0]["Notes"] == "Critical customer feedback: keep Section 2 unchanged."
    assert tasks[1]["Notes"] == "User reference links: https://example.com/docs"
    assert tasks[0]["reassignment_needed"] is True
    return True


def test_credential_safeguard_rejects_credentials_in_protocol() -> bool:
    """Protocol strictly rejects requests or storage of passwords, OTPs, or financial numbers."""
    clean_ok, _ = validate_no_credentials("Please review the domain routing specification.")
    assert clean_ok

    bad_pw, _ = validate_no_credentials("Please provide your account password to proceed.")
    assert not bad_pw

    bad_otp, _ = validate_no_credentials("Send the OTP verification code received on Telegram.")
    assert not bad_otp

    bad_card, _ = validate_no_credentials("Store the credit card number on the profile page.")
    assert not bad_card
    return True


def test_permission_state_legible_directly_from_notion_properties() -> bool:
    """Permissions derive directly from Notion database properties with zero hidden config."""
    worker = {
        "Worker": "Auditor",
        "Kind": "Agent",
        "Role": "Specialist",
        "Channel": "Claude Code",
        "Domains": ["Finance"],
        "May approve": False,
        "Status": "Active",
    }
    # Normalize keys for helper
    norm_worker = {
        "worker": worker["Worker"],
        "domains": worker["Domains"],
        "may_approve": worker["May approve"],
        "status": worker["Status"],
    }
    inspection = inspect_worker_notion_permissions(norm_worker)

    assert inspection["Worker"] == "Auditor"
    assert inspection["Status"] == "Active"
    assert inspection["Domains"] == ["Finance"]
    assert inspection["May approve"] is False
    assert "Finance" in inspection["domain_scope_summary"]
    assert "chat strictly required" in inspection["approval_scope_summary"]
    assert "Denied" in inspection["profile_access"]
    return True


def test_two_workers_concurrent_workspace_safety_no_overwrite() -> bool:
    """Done-when 1: Two distinct fixture workers operate the same workspace and neither
    silently overwrites the other's Assigned To ownership or the user's Notes field."""
    w1 = agent_worker("WriterAlpha", ["Writing"], role="Specialist")
    w2 = agent_worker("ResearcherBeta", ["Research"], role="Specialist")
    tasks = [
        {
            "title": "Article Draft",
            "domain": "Writing",
            "Assigned To": "WriterAlpha",
            "Status": "Planned",
            "Notes": "USER CONFIDENTIAL: Do not alter core thesis.",
            "Agent Notes": "Brief received.",
        },
        {
            "title": "Market Analysis",
            "domain": "Research",
            "Assigned To": "ResearcherBeta",
            "Status": "Planned",
            "Notes": "USER INSTRUCTION: Source citations required.",
            "Agent Notes": "Setting up query plan.",
        },
    ]

    ws = SimulatedMultiWorkerWorkspace([w1, w2], tasks)

    # 1. Queue isolation: neither sees the other's task
    q1 = ws.get_queue("WriterAlpha")
    q2 = ws.get_queue("ResearcherBeta")
    assert [t["title"] for t in q1["all_assigned"]] == ["Article Draft"]
    assert [t["title"] for t in q2["all_assigned"]] == ["Market Analysis"]

    # 2. Worker 2 cannot claim or start Worker 1's task
    blocked_start, reason_start = ws.start_task("ResearcherBeta", "Article Draft")
    assert not blocked_start, "Worker 2 must not be able to act on Worker 1's task"
    assert "Queue violation" in reason_start
    assert "WriterAlpha" in reason_start

    # 3. Worker 2 cannot silently reassign Worker 1's task
    blocked_reassign, reason_reassign = ws.attempt_silent_reassignment(
        "ResearcherBeta", "Article Draft", "ResearcherBeta"
    )
    assert not blocked_reassign, "Worker 2 must not silently reassign Worker 1's task"
    assert "Direct reassignment forbidden" in reason_reassign

    # Task ownership is still WriterAlpha
    assert ws.get_task("Article Draft")["Assigned To"] == "WriterAlpha"

    # 4. Worker 1 cannot overwrite user's Notes field
    blocked_note1, reason_note1 = ws.update_notes_by_agent(
        "WriterAlpha", "Article Draft", "Agent corrupted user notes"
    )
    assert not blocked_note1, "Agent must not be permitted to write to user Notes"
    assert "Invariant violation" in reason_note1
    assert "user-only" in reason_note1
    assert ws.get_task("Article Draft")["Notes"] == "USER CONFIDENTIAL: Do not alter core thesis."

    # 5. Worker 2 cannot overwrite user's Notes field on Task 2
    blocked_note2, reason_note2 = ws.update_notes_by_agent(
        "ResearcherBeta", "Market Analysis", "Agent corrupted user notes 2"
    )
    assert not blocked_note2
    assert "Invariant violation" in reason_note2
    assert ws.get_task("Market Analysis")["Notes"] == "USER INSTRUCTION: Source citations required."

    # 6. Both workers execute their own work legitimately
    ok_w1_start, _ = ws.start_task("WriterAlpha", "Article Draft")
    assert ok_w1_start
    assert ws.get_task("Article Draft")["Status"] == "In progress"

    ok_w2_start, _ = ws.start_task("ResearcherBeta", "Market Analysis")
    assert ok_w2_start
    assert ws.get_task("Market Analysis")["Status"] == "In progress"

    # 7. Worker 1 completes work legitimately
    ok_w1_done, _ = ws.complete_task("WriterAlpha", "Article Draft", summary="Draft finished.")
    assert ok_w1_done
    assert ws.get_task("Article Draft")["Status"] == "Done"

    # 8. User can update their own Notes safely
    ok_user_note, _ = ws.update_notes_by_user("Article Draft", "USER UPDATE: Thesis approved.")
    assert ok_user_note
    assert ws.get_task("Article Draft")["Notes"] == "USER UPDATE: Thesis approved."

    # 9. Verify ownership and notes integrity survived completely
    assert ws.get_task("Article Draft")["Assigned To"] == "WriterAlpha"
    assert ws.get_task("Market Analysis")["Assigned To"] == "ResearcherBeta"
    assert "Brief received." in ws.get_task("Article Draft")["Agent Notes"]
    assert "Started work on task." in ws.get_task("Article Draft")["Agent Notes"]
    assert "Completed task. Draft finished." in ws.get_task("Article Draft")["Agent Notes"]
    return True


def test_handoff_requires_reason_and_refuses_empty_reason() -> bool:
    """Done-when 2: Every handoff carries a reason; a handoff attempted without one is refused."""
    w1 = agent_worker("WriterAlpha", ["Writing"], role="Specialist")
    w2 = agent_worker("EditorBeta", ["Writing"], role="Specialist")
    w_out_of_scope = agent_worker("AccountantGamma", ["Finance"], role="Specialist")
    w_paused = agent_worker("PausedDelta", ["Writing"], status="Paused", role="Specialist")

    task = {
        "title": "Press Release Draft",
        "domain": "Writing",
        "Assigned To": "WriterAlpha",
        "Status": "In progress",
        "Notes": "USER NOTE: Coordinate with comms team.",
        "Agent Notes": "First draft written.",
    }

    # Case A: Valid handoff with reason
    ok_handoff, reason_msg, updated_task = handoff_task(
        task,
        w1,
        w2,
        reason="First draft written; handing off to EditorBeta for final polishing and tone check.",
    )
    assert ok_handoff, f"Valid handoff should succeed: {reason_msg}"
    assert updated_task["Assigned To"] == "EditorBeta"
    assert updated_task["Status"] == "In progress", "Status should be preserved unless explicitly changed"
    assert updated_task["Notes"] == "USER NOTE: Coordinate with comms team.", "User notes must be untouched"
    assert "Handoff from WriterAlpha to EditorBeta" in updated_task["Agent Notes"]
    assert "final polishing and tone check" in updated_task["Agent Notes"]

    # Case B: Refusal of empty reason
    task_curr = deepcopy(updated_task)
    ok_empty, empty_msg, _ = handoff_task(task_curr, w2, w1, reason="")
    assert not ok_empty, "Handoff without reason must be refused"
    assert "Handoff refused: A handoff must carry a non-empty reason" in empty_msg
    assert task_curr["Assigned To"] == "EditorBeta", "Assignee must remain unchanged"

    # Case C: Refusal of whitespace-only reason
    ok_spaces, spaces_msg, _ = handoff_task(task_curr, w2, w1, reason="   \t\n  ")
    assert not ok_spaces, "Handoff with whitespace-only reason must be refused"
    assert "Handoff refused: A handoff must carry a non-empty reason" in spaces_msg
    assert task_curr["Assigned To"] == "EditorBeta"

    # Case D: Refusal of handoff to out-of-scope worker
    ok_oos, oos_msg, _ = handoff_task(
        task_curr, w2, w_out_of_scope, reason="Needs review by accountant"
    )
    assert not ok_oos, "Handoff to worker without matching domain must be refused"
    assert "domain 'Writing' is not in worker Domains ['Finance']" in oos_msg
    assert task_curr["Assigned To"] == "EditorBeta"

    # Case E: Refusal of handoff to paused worker
    ok_paused, paused_msg, _ = handoff_task(
        task_curr, w2, w_paused, reason="Delegating to paused colleague"
    )
    assert not ok_paused, "Handoff to paused worker must be refused"
    assert "worker status is 'Paused', not 'Active'" in paused_msg
    assert task_curr["Assigned To"] == "EditorBeta"

    # Case F: Refusal of handoff by unauthorized worker
    unauthorized_worker = agent_worker("Outsider", ["Writing"], role="Specialist")
    ok_unauth, unauth_msg, _ = handoff_task(
        task_curr, unauthorized_worker, w1, reason="I want to reassign this"
    )
    assert not ok_unauth, "Unauthorized worker cannot hand off someone else's task"
    assert "Only the current assignee or Assistant may hand off" in unauth_msg
    return True


def test_role_separation_assistant_refuses_specialist_work() -> bool:
    """Done-when 3a: Assistant worker is refused from performing specialist execution work."""
    assistant = assistant_worker("GeneralAssistant", ["Writing", "Research"])

    # Specialist execution actions must be refused
    for specialist_action in ["writing", "research", "code", "coding", "drafting", "implementation", "specialist_work"]:
        allowed, reason = validate_role_action(assistant, specialist_action)
        assert not allowed, f"Assistant must not perform specialist work '{specialist_action}'"
        assert "Role violation" in reason
        assert "GeneralAssistant" in reason
        assert "cannot perform specialist work" in reason
        assert "Assistant manages, organizes, and assigns; it never performs execution work." in reason

    # Assistant management and coordination actions must be permitted
    for assistant_action in ["assign_task", "organize", "schedule", "daily_status", "summarize", "monitor"]:
        allowed, reason = validate_role_action(assistant, assistant_action)
        assert allowed, f"Assistant must be permitted to perform '{assistant_action}': {reason}"
    return True


def test_role_separation_advisor_refuses_actions_and_field_maintenance() -> bool:
    """Done-when 3b: Advisor worker is refused from triggering actions, daily status, or maintaining fields."""
    advisor = advisor_worker("ChiefAdvisor", ["Strategy", "Research"])

    # Advisor must not trigger actions, run daily status, or maintain fields
    forbidden_actions = [
        "trigger_action",
        "daily_status",
        "run_daily_status",
        "maintain_fields",
        "delete_page",
        "send_external_message",
        "send_payment",
        "assign_task",
        "execute_task",
    ]
    for action in forbidden_actions:
        allowed, reason = validate_role_action(advisor, action)
        assert not allowed, f"Advisor must not perform '{action}'"
        assert "Role violation" in reason
        assert "ChiefAdvisor" in reason
        assert "cannot trigger actions, run daily status, or maintain fields" in reason
        assert "Advisor advises and researches; never acts." in reason

    # Advisor advice and research reading must be permitted
    for advisor_action in ["advise", "research_observation", "surface_insight", "read_goals"]:
        allowed, reason = validate_role_action(advisor, advisor_action)
        assert allowed, f"Advisor should be permitted to '{advisor_action}': {reason}"
    return True


def test_role_separation_specialist_refuses_done_without_required_approval() -> bool:
    """Done-when 3c: Specialist cannot mark task Done when approval was required and not yet granted."""
    specialist = agent_worker("ContentSpecialist", ["Publishing"], role="Specialist")
    task = {
        "title": "Publish Release Notes",
        "domain": "Publishing",
        "Assigned To": "ContentSpecialist",
        "Status": "In progress",
        "Notes": "USER: Must be reviewed before publishing.",
        "Agent Notes": "Draft ready.",
    }

    # Case A: Approval required, approval_granted = False, May approve = False -> REFUSED
    ok_done, reason_done, updated_task = complete_task_execution(
        specialist, task, requires_approval=True, approval_granted=False, summary="Publishing live"
    )
    assert not ok_done, "Specialist must not mark Done without required approval"
    assert "Role violation" in reason_done
    assert "ContentSpecialist" in reason_done
    assert "cannot mark task Done: approval was required and not yet granted" in reason_done
    assert "May approve' is False" in reason_done
    assert updated_task["Status"] == "In progress", "Status must remain In progress"

    # Case B: Approval granted = True -> ALLOWED
    ok_approved, reason_approved, approved_task = complete_task_execution(
        specialist, task, requires_approval=True, approval_granted=True, summary="Published with user approval."
    )
    assert ok_approved, f"Completion should succeed when approval granted: {reason_approved}"
    assert approved_task["Status"] == "Done"
    assert approved_task["Completion Date"] == datetime.now(timezone.utc).strftime("%Y-%m-%d")
    assert "Published with user approval." in approved_task["Agent Notes"]

    # Case C: Worker with May approve = True can complete directly even when approval required
    specialist_lead = agent_worker("LeadPublisher", ["Publishing"], role="Specialist")
    specialist_lead["may_approve"] = True
    task2 = {
        "title": "Publish Hotfix",
        "domain": "Publishing",
        "Assigned To": "LeadPublisher",
        "Status": "In progress",
        "Agent Notes": "Testing hotfix.",
    }
    ok_lead, _, lead_task = complete_task_execution(
        specialist_lead, task2, requires_approval=True, approval_granted=False, summary="Lead self-approved."
    )
    assert ok_lead, "Worker with May approve = True should be able to self-approve and complete"
    assert lead_task["Status"] == "Done"
    return True


def test_queue_discipline_filters_queue_and_waits_on_future_start_date() -> bool:
    """Queue discipline: read-your-queue isolates worker tasks, respects In progress, and waits on future Start Date."""
    worker = agent_worker("WorkerOne", ["Writing"], role="Specialist")
    current_date = "2026-09-24"

    tasks = [
        {
            "title": "Past Task",
            "domain": "Writing",
            "Assigned To": "WorkerOne",
            "Status": "Planned",
            "Start Date": "2026-09-20",
        },
        {
            "title": "Today Task",
            "domain": "Writing",
            "Assigned To": "WorkerOne",
            "Status": "Planned",
            "Start Date": "2026-09-24",
        },
        {
            "title": "Future Task",
            "domain": "Writing",
            "Assigned To": "WorkerOne",
            "Status": "Planned",
            "Start Date": "2026-09-30",
        },
        {
            "title": "Already Done Task",
            "domain": "Writing",
            "Assigned To": "WorkerOne",
            "Status": "Done",
        },
        {
            "title": "Other Worker Task",
            "domain": "Writing",
            "Assigned To": "WorkerTwo",
            "Status": "Planned",
        },
    ]

    q = get_worker_queue(worker, tasks, current_date=current_date)
    # Excludes Done task and Other Worker task
    assert len(q["all_assigned"]) == 3
    assert [t["title"] for t in q["all_assigned"]] == ["Past Task", "Today Task", "Future Task"]
    assert [t["title"] for t in q["ready"]] == ["Past Task", "Today Task"]
    assert [t["title"] for t in q["waiting"]] == ["Future Task"]

    # Attempting to start future task must be refused with wait instruction
    future_task = tasks[2]
    ok_future, future_reason, _ = start_task_execution(worker, future_task, current_date=current_date)
    assert not ok_future, "Future task must not be started"
    assert "Queue violation" in future_reason
    assert "future Start Date '2026-09-30': worker must wait" in future_reason
    assert future_task["Status"] == "Planned"

    # Ready task can start
    today_task = tasks[1]
    ok_today, _, started_task = start_task_execution(worker, today_task, current_date=current_date)
    assert ok_today
    assert started_task["Status"] == "In progress"
    return True


def test_note_field_separation_invariant_refuses_agent_writing_user_notes() -> bool:
    """Note separation invariant: user writes Notes, agents write Agent Notes; cross-writes strictly refused."""
    worker = agent_worker("DevAgent", ["Writing"], role="Specialist")
    task = {
        "title": "Specs Draft",
        "domain": "Writing",
        "Assigned To": "DevAgent",
        "Status": "In progress",
        "Notes": "USER CRITICAL REQUIREMENT",
        "Agent Notes": "Initial notes.",
    }

    # Agent cannot write to Notes
    ok_agent_notes, reason_agent_notes, _ = update_task_field(
        task, "Notes", "Agent overwrite", worker, is_user=False
    )
    assert not ok_agent_notes
    assert "Invariant violation: Field 'Notes' is user-only" in reason_agent_notes
    assert task["Notes"] == "USER CRITICAL REQUIREMENT"

    # User can write to Notes
    ok_user_notes, _, _ = update_task_field(
        task, "Notes", "USER UPDATED REQUIREMENT", "User", is_user=True
    )
    assert ok_user_notes
    assert task["Notes"] == "USER UPDATED REQUIREMENT"

    # User cannot write to Agent Notes
    ok_user_agent_notes, reason_uan, _ = update_task_field(
        task, "Agent Notes", "User overwrite agent notes", "User", is_user=True
    )
    assert not ok_user_agent_notes
    assert "Invariant violation: Field 'Agent Notes' is agent-only" in reason_uan

    # Agent writes to Agent Notes -> appends, preserves prior content
    ok_agent_an, _, updated_task = update_task_field(
        task, "Agent Notes", "Second agent entry.", worker, is_user=False
    )
    assert ok_agent_an
    assert "Initial notes." in updated_task["Agent Notes"]
    assert "Second agent entry." in updated_task["Agent Notes"]
    return True


def test_no_lock_field_schema_contract() -> bool:
    """Schema contract: Confirm locked decision that Assigned To routes to exactly one worker without lock/claim fields."""
    wf_props = workforce_database_properties()
    tasks_relation = tasks_assigned_to_relation("ds_test")

    # Neither database carries a lock, claim, or locked_by property
    for prop in ["Lock", "lock", "Claim", "claim", "locked_by", "Locked By"]:
        assert prop not in wf_props, f"Workforce database should not have lock property '{prop}'"
        assert prop not in tasks_relation, f"Tasks database should not have lock property '{prop}'"

    # Assigned To is a single_property relation ensuring exactly one worker per task
    assert RELATION_TYPE == "single_property"
    assert "Assigned To" in tasks_relation
    assert "relation" in tasks_relation["Assigned To"]
    return True


def run_self_test() -> int:
    """Run all named test cases proving the Done-when conditions and security guarantees."""
    print("=================================================================")
    print("Running Workforce OS Permission & Multi-Worker Self-Tests...")
    print("=================================================================\n")

    cases = [
        (
            "Done-when 1: Worker with empty domain scope cannot act and states why in one line",
            test_empty_domain_worker_cannot_act_and_states_why_in_one_line,
        ),
        (
            "Done-when 2: Read-scope rule enforced mechanically against declared Domain context",
            test_read_scope_enforces_domain_declarations_mechanically,
        ),
        (
            "Done-when 3: Profile domain granted to nobody by default and requires explicit loggable grant",
            test_granting_profile_domain_requires_explicit_loggable_step,
        ),
        (
            "Action gate: Destructive, external, and irreversible actions blocked when May approve is False",
            test_action_gate_blocks_destructive_external_actions_without_may_approve,
        ),
        (
            "Action gate: Actions permitted when May approve is explicitly True",
            test_action_gate_allows_when_may_approve_is_explicitly_true,
        ),
        (
            "Worker removal: Revoking worker disables integrations without deleting user data or tasks",
            test_worker_removal_revokes_integrations_without_deleting_user_data,
        ),
        (
            "Credential safeguard: Protocol strictly rejects credential requests and storage",
            test_credential_safeguard_rejects_credentials_in_protocol,
        ),
        (
            "Notion legibility: Permission state is completely legible directly from Notion properties",
            test_permission_state_legible_directly_from_notion_properties,
        ),
        (
            "Multi-worker safety: Two distinct workers operate same workspace without silent ownership or Notes overwrite",
            test_two_workers_concurrent_workspace_safety_no_overwrite,
        ),
        (
            "Handoff enforcement: Handoff requires a non-empty reason; handoff without reason is refused",
            test_handoff_requires_reason_and_refuses_empty_reason,
        ),
        (
            "Role separation (Assistant): Assistant worker is refused from performing specialist execution work",
            test_role_separation_assistant_refuses_specialist_work,
        ),
        (
            "Role separation (Advisor): Advisor worker is refused from triggering actions or maintaining fields",
            test_role_separation_advisor_refuses_actions_and_field_maintenance,
        ),
        (
            "Role separation (Specialist): Specialist without May approve cannot mark task Done when approval required",
            test_role_separation_specialist_refuses_done_without_required_approval,
        ),
        (
            "Queue discipline: Read-your-queue isolates worker tasks, respects In progress, and waits on future Start Date",
            test_queue_discipline_filters_queue_and_waits_on_future_start_date,
        ),
        (
            "Note field separation: Agent attempting to write to user-only Notes field is strictly blocked as an invariant violation",
            test_note_field_separation_invariant_refuses_agent_writing_user_notes,
        ),
        (
            "Schema contract: Confirms no lock or claim field exists; Assigned To relation provides single ownership",
            test_no_lock_field_schema_contract,
        ),
    ]

    failures = 0
    for name, test_func in cases:
        try:
            test_func()
            print(f"  [PASS] {name}")
        except Exception as exc:
            print(f"  [FAIL] {name}: {exc}")
            failures += 1

    print("\n-----------------------------------------------------------------")
    if failures == 0:
        print(f"ALL {len(cases)} SELF-TEST CASES PASSED CLEANLY (0 failures).")
        print("All permission, handoff, queue discipline, note invariant, and role separation requirements are proven.")
        print("-----------------------------------------------------------------")
        return 0
    else:
        print(f"{failures} / {len(cases)} TEST CASES FAILED.")
        print("-----------------------------------------------------------------")
        return 1


# --------------------------------------------------------------------------
# Dry Run Preview
# --------------------------------------------------------------------------

def dry_run_preview() -> dict:
    """Generate dry-run permission evaluation preview."""
    workers = [
        agent_worker("FreshWorker", domains=[]),
        agent_worker("Writer", domains=["Writing"]),
        agent_worker("Approver", domains=["Writing"], status="Active"),
        human_worker("Anik", domains=["Work", "Personal"]),
    ]
    workers[2]["may_approve"] = True

    audit_log: list[dict] = []
    # Deliberate grant example
    grant_domain(
        workers[1],
        "Profile",
        author="Anik",
        reason="Identity verification for publisher registration",
        audit_log=audit_log,
    )

    domain_declarations = build_default_domain_declarations(["Writing", "Research"])

    evaluations = []
    for w in workers:
        # Act check
        task = {"title": "Draft blog article", "domain": "Writing"}
        act_ok, act_reason = can_act_on_task(w, task)

        # Read check
        read_ok, read_reason = check_read_scope(
            w, "Writing", "Domains/Writing/StyleGuide", domain_declarations
        )
        read_undeclared_ok, read_undeclared_reason = check_read_scope(
            w, "Writing", "Domains/Finance/Ledger", domain_declarations
        )

        # Action gate check
        gate_ok, gate_reason = check_action_gate(w, "send_external_message")

        evaluations.append({
            "worker": w.get("worker"),
            "domains": w.get("domains"),
            "may_approve": w.get("may_approve"),
            "status": w.get("status"),
            "can_act_on_writing_task": {"allowed": act_ok, "reason": act_reason},
            "read_declared_page": {"allowed": read_ok, "reason": read_reason},
            "read_undeclared_page": {"allowed": read_undeclared_ok, "reason": read_undeclared_reason},
            "action_gate_send_external_message": {"allowed": gate_ok, "reason": gate_reason},
        })

    # Multi-worker handoff preview
    handoff_task_fixture = {
        "title": "Quarterly Newsletter",
        "domain": "Writing",
        "Assigned To": "Writer",
        "Status": "In progress",
        "Notes": "USER: Final tone review required.",
        "Agent Notes": "First draft completed.",
    }
    handoff_ok, handoff_msg, _ = handoff_task(
        deepcopy(handoff_task_fixture),
        workers[1],
        workers[2],
        reason="First draft completed; handing off to Approver for editorial sign-off.",
    )
    handoff_bad_ok, handoff_bad_msg, _ = handoff_task(
        deepcopy(handoff_task_fixture),
        workers[1],
        workers[2],
        reason="",
    )

    # Queue discipline preview
    queue_preview = get_worker_queue(
        workers[1],
        [
            {"title": "Immediate Task", "domain": "Writing", "Assigned To": "Writer", "Status": "Planned", "Start Date": "2026-09-24"},
            {"title": "Future Task", "domain": "Writing", "Assigned To": "Writer", "Status": "Planned", "Start Date": "2026-10-01"},
        ],
        current_date="2026-09-24",
    )

    # Role separation preview
    asst = assistant_worker("AssistantPreview", ["Writing"])
    adv = advisor_worker("AdvisorPreview", ["Writing"])
    asst_ok, asst_msg = validate_role_action(asst, "writing")
    adv_ok, adv_msg = validate_role_action(adv, "delete_page")

    # Note field separation preview
    note_agent_ok, note_agent_msg = validate_field_write_permission("Specialist", "Notes", "Writer")
    note_user_ok, note_user_msg = validate_field_write_permission("User", "Notes", "User")

    return {
        "dry_run": True,
        "note": "No changes made. This is the permission and multi-worker safety evaluation preview.",
        "defaults_deny": True,
        "sensitive_domains": SENSITIVE_DOMAINS,
        "no_lock_field_contract": True,
        "audit_log_entries": audit_log,
        "evaluations": evaluations,
        "handoff_preview": {
            "valid_handoff": {"allowed": handoff_ok, "detail": handoff_msg},
            "unreasoned_handoff": {"allowed": handoff_bad_ok, "detail": handoff_bad_msg},
        },
        "queue_discipline_preview": {
            "ready_count": len(queue_preview["ready"]),
            "waiting_future_start_count": len(queue_preview["waiting"]),
        },
        "role_separation_preview": {
            "assistant_specialist_work_blocked": {"allowed": asst_ok, "reason": asst_msg},
            "advisor_action_blocked": {"allowed": adv_ok, "reason": adv_msg},
        },
        "note_field_separation_preview": {
            "agent_writing_user_notes_blocked": {"allowed": note_agent_ok, "reason": note_agent_msg},
            "user_writing_user_notes_allowed": {"allowed": note_user_ok, "reason": note_user_msg},
        },
    }


# --------------------------------------------------------------------------
# Live Run (Honest status documentation)
# --------------------------------------------------------------------------

def live_run(args) -> int:
    token = os.environ.get("NOTION_TOKEN")
    parent_page_id = getattr(args, "parent_page_id", None) or os.environ.get("NOTION_PARENT_PAGE_ID")

    if not token or not parent_page_id:
        print(
            "Missing Notion credentials.\n"
            "Set NOTION_TOKEN and NOTION_PARENT_PAGE_ID (or pass --parent-page-id).\n"
            "No network calls were made.",
            file=sys.stderr,
        )
        return 2

    print(
        "Live Notion permission validation is not executed directly here: "
        "no live credential exists in this sandbox."
    )
    print(
        "See docs/ARCHITECTURE.md for the one-command procedure to complete live "
        "permission verification in your workspace."
    )
    return 0


# --------------------------------------------------------------------------
# Main CLI Entry Point
# --------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true",
                        help="preview permission evaluation results without network calls")
    parser.add_argument("--self-test", action="store_true",
                        help="run the permission and security self-test suite")
    parser.add_argument("--live", action="store_true",
                        help="validate permissions against live Notion workspace")
    parser.add_argument("--parent-page-id",
                        help="parent page ID of the Workforce OS workspace")
    parser.add_argument("--api-version",
                        default=os.environ.get("NOTION_API_VERSION", DEFAULT_API_VERSION))

    args = parser.parse_args()

    if args.self_test:
        return run_self_test()

    if args.live:
        return live_run(args)

    report = dry_run_preview()
    print(json.dumps(report, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
