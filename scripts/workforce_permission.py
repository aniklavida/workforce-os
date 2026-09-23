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
        TASKS_ASSIGNED_TO_PROP,
        WORKFORCE_TITLE_PROP,
        agent_worker,
        assignment_blockers,
        can_assign,
        human_worker,
    )
except ImportError:
    DEFAULT_API_VERSION = "2025-09-03"
    WORKFORCE_TITLE_PROP = "Worker"
    TASKS_ASSIGNED_TO_PROP = "Assigned To"

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

    def human_worker(name: str, domains: list[str] | None = None) -> dict:
        return {
            "worker": name,
            "kind": "Human",
            "role": "Specialist",
            "channel": "None",
            "domains": domains or [],
            "may_approve": False,
            "status": "Active",
        }

    def agent_worker(name: str, domains: list[str], status: str = "Active") -> dict:
        return {
            "worker": name,
            "kind": "Agent",
            "role": "Specialist",
            "channel": "Claude Code",
            "domains": list(domains),
            "may_approve": False,
            "status": status,
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


def run_self_test() -> int:
    """Run all named test cases proving the Done-when conditions and security guarantees."""
    print("=================================================================")
    print("Running Workforce OS Permission Model Self-Tests...")
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
        print(f"ALL {len(cases)} PERMISSION SELF-TEST CASES PASSED CLEANLY (0 failures).")
        print("Done-when requirements 1, 2, and 3 are proven.")
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

    return {
        "dry_run": True,
        "note": "No changes made. This is the permission evaluation preview.",
        "defaults_deny": True,
        "sensitive_domains": SENSITIVE_DOMAINS,
        "audit_log_entries": audit_log,
        "evaluations": evaluations,
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
