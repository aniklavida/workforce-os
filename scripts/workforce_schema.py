#!/usr/bin/env python3
"""Workforce OS schema reference and assignment gate.

This is a small, dependency-free reference for the part of the Workforce OS
schema that replaced the old hard-coded `Assigned To` select:

  * the **Workforce** database, one row per worker (agent or human), and
  * the **`Assigned To` relation** on the Tasks database that points at it.

It exists for three reasons:

  1. `--dry-run` prints the exact Notion request payloads for the Workforce
     database and the Tasks relation, without any network call. This is the
     schema-creation logic in executable form; the setup skill describes the
     same thing in prose and drives it through the agent's Notion MCP.
  2. `--self-test` runs the assignment gate against fixture workers. The gate
     is the rule the operating protocol applies: a `Paused` worker and a
     worker whose `Domains` do not cover the task's domain receive no new
     assignment. Empty `Domains` means no scope, not all scope.
  3. `--live` is the one-command procedure to create the Workforce database in
     a real workspace and (optionally) install the relation on an existing
     Tasks data source. It has not been run in this repository, because no
     Notion credential exists here. See docs/ARCHITECTURE.md for the honest
     verification status.

The Notion API version 2025-09-03 makes the **data source** the primary
abstraction. Databases are addressed through their data source ids. This script
therefore configures the relation with a `data_source_id`, not the older
`database_id`. Confirm that key against the live API the first time you run
`--live`; it is called out in the architecture verification table.

Credentials are never committed. Supply them through the environment:

    NOTION_TOKEN            internal integration secret
    NOTION_PARENT_PAGE_ID   the page the Workforce database is created under
    NOTION_API_VERSION      optional, defaults to 2025-09-03

Dry run (no network, no credentials):

    python3 scripts/workforce_schema.py --dry-run

Assignment-gate self-test (no network, no credentials):

    python3 scripts/workforce_schema.py --self-test

Live run (creates the Workforce database, prints its data source id):

    NOTION_TOKEN=... NOTION_PARENT_PAGE_ID=... \\
        python3 scripts/workforce_schema.py --live

Add the relation to an existing Tasks data source in the same run:

    NOTION_TOKEN=... NOTION_PARENT_PAGE_ID=... \\
        python3 scripts/workforce_schema.py --live \\
        --tasks-data-source-id <tasks_data_source_id>
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request

API_BASE = "https://api.notion.com/v1"
DEFAULT_API_VERSION = "2025-09-03"

# -- option sets, locked by the schema decision ----------------------------

KINDS = ["Agent", "Human"]
ROLES = ["Assistant", "Advisor", "Specialist"]
CHANNELS = ["Claude Code", "Codex", "Telegram", "Discord", "CLI", "None"]
WORKER_STATUSES = ["Active", "Paused"]

WORKFORCE_TITLE_PROP = "Worker"
TASKS_ASSIGNED_TO_PROP = "Assigned To"

# The Tasks `Assigned To` property becomes a one-way relation to Workforce.
# Single-property relation: a task points at one worker, nothing is written
# back onto the worker row. There is no claim or lock property on either side.
RELATION_TYPE = "single_property"

# Name of the key the relation target is configured under. The 2025-09-03 API
# addresses data sources, so this is `data_source_id`; older docs use
# `database_id`. Verify on first live run.
RELATION_TARGET_KEY = "data_source_id"


# --------------------------------------------------------------------------
# The Workforce database schema
# --------------------------------------------------------------------------

def workforce_database_properties() -> dict:
    """The eight Workforce properties, each carrying who writes it.

    The ninth item in the field contract is not a property: it is the page
    body of each row, which holds the worker's full startup instructions.
    """
    return {
        WORKFORCE_TITLE_PROP: {
            "title": {},
            "description": (
                "Assistant. Display name for this worker. This is what a "
                "task's Assigned To points at."),
        },
        "Kind": {
            "select": {"options": [{"name": k} for k in KINDS]},
            "description": (
                "Assistant. Agent or Human. A human teammate is a worker "
                "with Kind = Human and Channel = None; adding one needs no "
                "schema change."),
        },
        "Role": {
            "select": {"options": [{"name": r} for r in ROLES]},
            "description": (
                "Assistant. The worker's operating role: Assistant, Advisor "
                "or Specialist."),
        },
        "Channel": {
            "select": {"options": [{"name": c} for c in CHANNELS]},
            "description": (
                "Assistant. The host or chat surface this worker uses. Human "
                "workers use None. The channel is supplied by the worker's "
                "agent, not built by Workforce OS."),
        },
        "Domains": {
            "multi_select": {"options": []},
            "description": (
                "Assistant. The Domains this worker may work in. Empty means "
                "none: the worker may not load context for or act on any "
                "domain until one is listed."),
        },
        "May approve": {
            "checkbox": {},
            "description": (
                "Assistant. Off by default. On means this worker may approve "
                "its own output without waiting for the user."),
        },
        "Capabilities": {
            "rich_text": {},
            "description": (
                "Assistant. Plain language: what this worker does and does "
                "not do."),
        },
        "Status": {
            "select": {"options": [{"name": s} for s in WORKER_STATUSES]},
            "description": (
                "Both. Active or Paused. A Paused worker receives no new "
                "assignments."),
        },
    }


def workforce_database_create_body(parent_page_id: str) -> dict:
    return {
        "parent": {"type": "page_id", "page_id": parent_page_id},
        "title": [{"type": "text", "text": {"content": "Workforce"}}],
        "properties": workforce_database_properties(),
    }


def tasks_assigned_to_relation(workforce_data_source_id: str) -> dict:
    """The Tasks property that replaces the old `Assigned To` select."""
    return {
        TASKS_ASSIGNED_TO_PROP: {
            "relation": {
                RELATION_TARGET_KEY: workforce_data_source_id,
                "type": RELATION_TYPE,
            },
            "description": (
                "Assistant. Relation to one Workforce row. Exactly one worker "
                "per task; the Assistant only assigns Active, in-scope "
                "workers. No claim or lock property exists."),
        },
    }


def tasks_relation_update_body(workforce_data_source_id: str) -> dict:
    return {"properties": tasks_assigned_to_relation(workforce_data_source_id)}


# --------------------------------------------------------------------------
# The assignment gate
# --------------------------------------------------------------------------

def assignment_blockers(worker: dict, task_domain: str) -> list[str]:
    """Return the reasons this worker may not receive this assignment.

    An empty list means the assignment is allowed. This is the rule the setup
    skill states in prose and the operating agent applies before writing
    `Assigned To`. Notion does not enforce it; the protocol does.
    """
    blockers: list[str] = []

    status = worker.get("status")
    if status != "Active":
        blockers.append(f"worker status is {status!r}, not 'Active'")

    domains = worker.get("domains") or []
    if not domains:
        blockers.append("worker Domains is empty, which means no scope")
    elif task_domain not in domains:
        blockers.append(
            f"domain {task_domain!r} is not in worker Domains {domains!r}")

    return blockers


def can_assign(worker: dict, task_domain: str) -> bool:
    return not assignment_blockers(worker, task_domain)


def can_act_on_task(worker: dict, task: dict) -> tuple[bool, str]:
    """Protocol check: can this worker act on this task?

    Evaluates worker status and domain scope. If blocked, returns (False, reason)
    with a clear single-line explanation.
    """
    try:
        from workforce_permission import can_act_on_task as _can_act
        return _can_act(worker, task)
    except ImportError:
        worker_name = worker.get("worker", "Unknown worker")
        task_title = task.get("title") or task.get("task") or "Untitled task"
        task_domain = task.get("domain") or task.get("Domain") or "Unassigned"
        domains = worker.get("domains") or []
        if worker.get("status") != "Active":
            return False, f"Worker '{worker_name}' is {worker.get('status')!r}, not 'Active': cannot act on task '{task_title}'."
        if not domains:
            return False, f"Worker '{worker_name}' has empty Domains scope: cannot act on task '{task_title}' (domain '{task_domain}') because no domains are granted."
        if task_domain not in domains:
            return False, f"Worker '{worker_name}' domain scope {domains!r} does not include task domain '{task_domain}': cannot act on task '{task_title}'."
        return True, f"Worker '{worker_name}' is authorized to act on task '{task_title}' in domain '{task_domain}'."


def human_worker(name: str, domains: list[str] | None = None,
                 role: str = "Specialist") -> dict:
    """A human teammate is an ordinary worker row, not a schema special case."""
    return {
        "worker": name,
        "kind": "Human",
        "role": role,
        "channel": "None",
        "domains": domains or [],
        "may_approve": False,
        "status": "Active",
    }


def agent_worker(name: str, domains: list[str],
                 status: str = "Active", role: str = "Specialist") -> dict:
    return {
        "worker": name,
        "kind": "Agent",
        "role": role,
        "channel": "Claude Code",
        "domains": list(domains),
        "may_approve": False,
        "status": status,
    }


def assistant_worker(name: str, domains: list[str] | None = None,
                     status: str = "Active") -> dict:
    return agent_worker(name, domains or [], status=status, role="Assistant")


def advisor_worker(name: str, domains: list[str] | None = None,
                   status: str = "Active") -> dict:
    return agent_worker(name, domains or [], status=status, role="Advisor")


def run_self_test() -> int:
    """Fixture checks for the assignment gate. No network."""
    cases: list[tuple[str, bool, dict, str]] = [
        ("active worker in scope is assignable",
         True, agent_worker("Writer", ["Writing"]), "Writing"),
        ("paused worker gets no assignment",
         False, agent_worker("Writer", ["Writing"], status="Paused"), "Writing"),
        ("empty Domains means no scope",
         False, agent_worker("Writer", []), "Writing"),
        ("out-of-scope domain is blocked",
         False, agent_worker("Writer", ["Writing"]), "Finance"),
        ("in-scope domain of several is allowed",
         True, agent_worker("Writer", ["Writing", "Finance"]), "Finance"),
        ("human worker with matching scope is assignable",
         True, human_worker("Anik", ["Company"]), "Company"),
        ("human worker with no scope is blocked",
         False, human_worker("Anik"), "Company"),
    ]

    failures = 0
    for label, expected, worker, domain in cases:
        actual = can_assign(worker, domain)
        ok = actual == expected
        failures += 0 if ok else 1
        reasons = assignment_blockers(worker, domain)
        detail = "; ".join(reasons) if reasons else "allowed"
        print(f"[{'ok ' if ok else 'FAIL'}] {label} -> {detail}")
    print(f"\n{len(cases)} cases, {failures} failed")
    return 1 if failures else 0


# --------------------------------------------------------------------------
# HTTP (live path only)
# --------------------------------------------------------------------------

class NotionError(RuntimeError):
    pass


def notion_request(token: str, api_version: str, method: str, path: str,
                   body: dict | None = None) -> dict:
    url = f"{API_BASE}{path}"
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(
        url, data=data, method=method,
        headers={
            "Authorization": f"Bearer {token}",
            "Notion-Version": api_version,
            "Content-Type": "application/json",
        })
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")
        raise NotionError(f"{method} {path} -> HTTP {exc.code}: {detail[:600]}")


def resolve_data_source_id(database: dict) -> str | None:
    """The database object exposes its data sources; prefer the first one."""
    sources = database.get("data_sources") or []
    if sources:
        return sources[0].get("id")
    return database.get("id")


def live_run(args) -> int:
    token = os.environ.get("NOTION_TOKEN")
    parent_page_id = args.parent_page_id or os.environ.get(
        "NOTION_PARENT_PAGE_ID")
    if not token or not parent_page_id:
        print(
            "Missing credentials. Set NOTION_TOKEN and NOTION_PARENT_PAGE_ID "
            "(or pass --parent-page-id). Nothing was sent.",
            file=sys.stderr)
        return 2

    api_version = args.api_version

    print("Creating the Workforce database...")
    workforce_db = notion_request(
        token, api_version, "POST", "/databases",
        workforce_database_create_body(parent_page_id))
    workforce_ds = resolve_data_source_id(workforce_db)
    print(f"  database_id     = {workforce_db.get('id')}")
    print(f"  data_source_id  = {workforce_ds}")

    if args.tasks_data_source_id:
        if not workforce_ds:
            print("Could not resolve the Workforce data source id; the Tasks "
                  "relation was not installed.", file=sys.stderr)
            return 1
        print("Installing Assigned To -> Workforce relation on Tasks...")
        try:
            notion_request(
                token, api_version, "PATCH",
                f"/data_sources/{args.tasks_data_source_id}",
                tasks_relation_update_body(workforce_ds))
        except NotionError as exc:
            print(f"  failed: {exc}", file=sys.stderr)
            print(
                "  If Assigned To already exists as a select, rename it to "
                "'Assigned To (legacy)' first, then re-run. A Notion property "
                "cannot change type in place.", file=sys.stderr)
            return 1
        print("  relation installed.")

    print("\nNext: add worker rows through the setup skill or directly in "
          "Notion; no repository change is needed for a new worker.")
    return 0


# --------------------------------------------------------------------------
# Dry run
# --------------------------------------------------------------------------

def dry_run_plan(args) -> dict:
    tasks_ds = args.tasks_data_source_id or "{tasks_data_source_id}"
    return {
        "dry_run": True,
        "api_version": args.api_version,
        "note": "No network calls. These are the exact request bodies the "
                "live run sends.",
        "steps": [
            "POST /databases — create the Workforce database under "
            "NOTION_PARENT_PAGE_ID",
            f"PATCH /data_sources/{tasks_ds} — add the Assigned To relation "
            "pointing at the Workforce data source",
        ],
        "create_workforce_database": workforce_database_create_body(
            "{parent_page_id}"),
        "tasks_relation_update": tasks_relation_update_body(
            "{{workforce_data_source_id}}"),
        "relation_target_key": RELATION_TARGET_KEY,
        "property_descriptions_present": all(
            "description" in prop
            for prop in workforce_database_properties().values()),
        "assigned_to_is_relation": (
            "relation" in tasks_assigned_to_relation(
                "ds")[TASKS_ASSIGNED_TO_PROP]),
    }


# --------------------------------------------------------------------------
# Entry point
# --------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true",
                        help="print the request plan without any network call")
    parser.add_argument("--self-test", action="store_true",
                        help="run the assignment-gate fixture checks")
    parser.add_argument("--live", action="store_true",
                        help="create the Workforce database in a real workspace")
    parser.add_argument("--parent-page-id",
                        help="page the Workforce database is created under")
    parser.add_argument("--tasks-data-source-id",
                        help="existing Tasks data source to add the relation to")
    parser.add_argument("--api-version",
                        default=os.environ.get("NOTION_API_VERSION",
                                               DEFAULT_API_VERSION))
    args = parser.parse_args()

    if args.self_test:
        return run_self_test()

    if args.live:
        return live_run(args)

    report = dry_run_plan(args)
    print(json.dumps(report, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
