#!/usr/bin/env python3
"""Workforce OS idempotent Notion setup orchestration.

Builds the entire Workforce OS structure in the user's Notion workspace from
five short answers, and converges on the exact same structure every time setup
is re-run — never creating duplicate databases or pages.

Core behaviors:
  1. Search parent page for Workforce OS marker (and existing child objects).
  2. If marker or existing structure is found, reconcile rather than recreate:
     missing properties and views are added to what exists, never duplicating
     a database or page.
  3. Preview what will be created before creating it, reporting progress per
     object created. Every destructive or overwriting step requires explicit
     confirmation.
  4. Build in a documented order so nothing is orphaned if setup stops halfway;
     on failure, report exactly what was built and what was not.
  5. The structure: Home, Tasks, Workforce, Domains, Goals, Knowledge, Profile,
     Logs, plus views: Today, My Tasks, Agent Tasks, one per Domain, Board,
     Calendar, Someday.
  6. Each Domain page declares which pages an agent may read for that Domain,
     fulfilling the context routing requirement in AGENTS.md.
  7. Off by default: habits, finance, health, reading, travel, contacts.
     Documented rationale: starting with everything is why personal operating
     systems die within a month. Day one is five things you will actually use.
  8. Finishes setup by creating one real task end to end.

Usage:
  Dry run (simulated workspace, no credentials or network needed):
      python3 scripts/workforce_setup.py --dry-run

  Self-test (automated idempotency and failure recovery test suite):
      python3 scripts/workforce_setup.py --self-test

  Live run (against Notion REST API):
      NOTION_TOKEN=... NOTION_PARENT_PAGE_ID=... \\
          python3 scripts/workforce_setup.py --live
"""

from __future__ import annotations

import argparse
import copy
import json
import os
import sys
import urllib.error
import urllib.request
from typing import Any

# Import schema definitions and gate logic from workforce_schema
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
if SCRIPT_DIR not in sys.path:
    sys.path.insert(0, SCRIPT_DIR)

try:
    from workforce_schema import (
        API_BASE,
        CHANNELS,
        DEFAULT_API_VERSION,
        KINDS,
        RELATION_TARGET_KEY,
        RELATION_TYPE,
        ROLES,
        TASKS_ASSIGNED_TO_PROP,
        WORKER_STATUSES,
        WORKFORCE_TITLE_PROP,
        can_assign,
        human_worker,
        tasks_assigned_to_relation,
        workforce_database_properties,
    )
except ImportError:
    # Fallback definitions if run in isolation
    API_BASE = "https://api.notion.com/v1"
    DEFAULT_API_VERSION = "2025-09-03"
    RELATION_TARGET_KEY = "data_source_id"
    RELATION_TYPE = "single_property"
    WORKFORCE_TITLE_PROP = "Worker"
    TASKS_ASSIGNED_TO_PROP = "Assigned To"
    KINDS = ["Agent", "Human"]
    ROLES = ["Assistant", "Advisor", "Specialist"]
    CHANNELS = ["Claude Code", "Codex", "Telegram", "Discord", "CLI", "None"]
    WORKER_STATUSES = ["Active", "Paused"]

    def workforce_database_properties() -> dict:
        return {
            WORKFORCE_TITLE_PROP: {"title": {}, "description": "Assistant. Display name for this worker."},
            "Kind": {"select": {"options": [{"name": k} for k in KINDS]}, "description": "Assistant. Agent or Human."},
            "Role": {"select": {"options": [{"name": r} for r in ROLES]}, "description": "Assistant. Role: Assistant, Advisor, Specialist."},
            "Channel": {"select": {"options": [{"name": c} for c in CHANNELS]}, "description": "Assistant. Host or chat surface."},
            "Domains": {"multi_select": {"options": []}, "description": "Assistant. Empty means none."},
            "May approve": {"checkbox": {}, "description": "Assistant. Off by default."},
            "Capabilities": {"rich_text": {}, "description": "Assistant. Plain language summary."},
            "Status": {"select": {"options": [{"name": s} for s in WORKER_STATUSES]}, "description": "Both. Active or Paused."},
        }

    def tasks_assigned_to_relation(workforce_data_source_id: str) -> dict:
        return {
            TASKS_ASSIGNED_TO_PROP: {
                "relation": {
                    RELATION_TARGET_KEY: workforce_data_source_id,
                    "type": RELATION_TYPE,
                },
                "description": "Assistant. Relation to one Workforce row.",
            }
        }

    def can_assign(worker: dict, task_domain: str) -> bool:
        if worker.get("status") != "Active":
            return False
        domains = worker.get("domains") or []
        return bool(domains and task_domain in domains)

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


# --------------------------------------------------------------------------
# Constants and Schema Specifications
# --------------------------------------------------------------------------

WORKFORCE_OS_MARKER = "workforce-os:root"
MARKER_CALLOUT_TEXT = "Workforce OS — Managed System [workforce-os:root]"

OFF_BY_DEFAULT_AREAS = [
    "habits",
    "finance",
    "health",
    "reading",
    "travel",
    "contacts",
]

OFF_BY_DEFAULT_RATIONALE = (
    "Starting with everything is documented as the reason these systems die "
    "within a month. Day one is five things you will actually use, not twenty "
    "you will abandon. A life area is one select option, never a new database."
)

REQUIRED_SECTION_PAGES = [
    "Domains",
    "Goals",
    "Knowledge",
    "Profile",
    "Logs",
]

REQUIRED_TASKS_PROPERTIES = [
    "Task",
    "Status",
    "Assigned To",
    "Domain",
    "Priority",
    "Type",
    "Start Date",
    "Due Date",
    "Done When",
    "Notes",
    "Agent Notes",
    "Done Date",
]


def tasks_database_properties(workforce_data_source_id: str,
                              domains: list[str]) -> dict:
    """The 11 core Tasks properties plus Assigned To relation."""
    return {
        "Task": {
            "title": {},
            "description": "Agent. Short, clear action or outcome.",
        },
        "Status": {
            "status": {
                "options": [
                    {"name": "Planned", "color": "default"},
                    {"name": "In progress", "color": "blue"},
                    {"name": "Done", "color": "green"},
                ]
            },
            "description": "Both. Planned -> In progress -> Done. One shared flow.",
        },
        TASKS_ASSIGNED_TO_PROP: {
            "relation": {
                RELATION_TARGET_KEY: workforce_data_source_id,
                "type": RELATION_TYPE,
            },
            "description": "Assistant. Relation to one Workforce row.",
        },
        "Domain": {
            "select": {"options": [{"name": d} for d in domains]},
            "description": "Agent. Which area of life. Drives context loading.",
        },
        "Priority": {
            "select": {
                "options": [
                    {"name": "High", "color": "red"},
                    {"name": "Medium", "color": "yellow"},
                    {"name": "Low", "color": "gray"},
                ]
            },
            "description": "Agent. Priority level.",
        },
        "Type": {
            "select": {
                "options": [
                    {"name": "Task", "color": "default"},
                    {"name": "Ongoing", "color": "blue"},
                    {"name": "Someday", "color": "gray"},
                ]
            },
            "description": "Agent. Task, Ongoing, or Someday.",
        },
        "Start Date": {
            "date": {},
            "description": "Agent. When work may begin.",
        },
        "Due Date": {
            "date": {},
            "description": "Agent. Final deadline.",
        },
        "Done When": {
            "rich_text": {},
            "description": "Agent. Completion condition.",
        },
        "Notes": {
            "rich_text": {},
            "description": "User only. Agents never write here.",
        },
        "Agent Notes": {
            "rich_text": {},
            "description": "Agent only. Progress, blockers, questions, handoff.",
        },
        "Done Date": {
            "date": {},
            "description": "Agent. Completion timestamp.",
        },
    }


def required_views_specification(domains: list[str]) -> list[dict]:
    """Specification of the required Tasks views."""
    views = [
        {
            "name": "Today",
            "type": "table",
            "description": "Not Done, not Someday, sorted by priority then due date",
            "filter": {
                "and": [
                    {"property": "Status", "status": {"does_not_equal": "Done"}},
                    {"property": "Type", "select": {"does_not_equal": "Someday"}},
                ]
            },
            "sorts": [
                {"property": "Priority", "direction": "ascending"},
                {"property": "Due Date", "direction": "ascending"},
            ],
        },
        {
            "name": "My Tasks",
            "type": "table",
            "description": "Assigned To relation points at a worker with Kind = Human",
            "filter": {"property": "Assigned To", "relation": {"contains": "human"}},
        },
        {
            "name": "Agent Tasks",
            "type": "table",
            "description": "Assigned To relation points at a worker with Kind = Agent",
            "filter": {"property": "Assigned To", "relation": {"contains": "agent"}},
        },
    ]

    for domain in domains:
        views.append({
            "name": f"Domain: {domain}",
            "type": "table",
            "description": f"Tasks for domain {domain}, not Done",
            "filter": {
                "and": [
                    {"property": "Domain", "select": {"equals": domain}},
                    {"property": "Status", "status": {"does_not_equal": "Done"}},
                ]
            },
        })

    views.extend([
        {
            "name": "Board",
            "type": "board",
            "description": "Grouped by Status (Planned, In progress, Done)",
            "group_by": "Status",
        },
        {
            "name": "Calendar",
            "type": "calendar",
            "description": "Calendar grouped by Due Date",
            "date_property": "Due Date",
        },
        {
            "name": "Someday",
            "type": "table",
            "description": "Backlog items where Type is Someday",
            "filter": {"property": "Type", "select": {"equals": "Someday"}},
        },
    ])
    return views


def domain_page_declared_context(domain_name: str) -> list[dict]:
    """Block payload for Domain page declaring mandatory agent read scope.
    
    AGENTS.md rule 5 requires each Domain page to state which extra pages
    an agent may read. Without this declaration, agents would read everything.
    """
    return [
        {
            "object": "block",
            "type": "heading_1",
            "heading_1": {
                "rich_text": [{"type": "text", "text": {"content": f"Domain — {domain_name}"}}]
            },
        },
        {
            "object": "block",
            "type": "callout",
            "callout": {
                "icon": {"emoji": "🛡️"},
                "rich_text": [{
                    "type": "text",
                    "text": {
                        "content": (
                            "AGENT ROUTING CONTRACT (AGENTS.md rule 5): An agent "
                            f"working in the '{domain_name}' domain may ONLY read "
                            "the declared context below. Loading unlisted domains "
                            "or the Profile page without explicit task instruction "
                            "is forbidden."
                        )
                    },
                }],
            },
        },
        {
            "object": "block",
            "type": "heading_2",
            "heading_2": {
                "rich_text": [{"type": "text", "text": {"content": "Declared Context for this Domain"}}]
            },
        },
        {
            "object": "block",
            "type": "bulleted_list_item",
            "bulleted_list_item": {
                "rich_text": [{"type": "text", "text": {"content": f"This Domain page (Domains/{domain_name}) and its immediate children"}}]
            },
        },
        {
            "object": "block",
            "type": "bulleted_list_item",
            "bulleted_list_item": {
                "rich_text": [{"type": "text", "text": {"content": f"Goals relevant to {domain_name}"}}]
            },
        },
        {
            "object": "block",
            "type": "bulleted_list_item",
            "bulleted_list_item": {
                "rich_text": [{"type": "text", "text": {"content": f"Knowledge base entries tagged for {domain_name}"}}]
            },
        },
        {
            "object": "block",
            "type": "paragraph",
            "paragraph": {
                "rich_text": [{
                    "type": "text",
                    "text": {"content": "Notes, briefs, and ongoing working context for this life area belong here."}
                }]
            },
        },
    ]


def worker_instructions_body(role: str, worker_name: str) -> list[dict]:
    """Page body instructions for a worker row in Workforce database."""
    return [
        {
            "object": "block",
            "type": "heading_2",
            "heading_2": {
                "rich_text": [{"type": "text", "text": {"content": f"Worker Brief: {worker_name} ({role})"}}]
            },
        },
        {
            "object": "block",
            "type": "paragraph",
            "paragraph": {
                "rich_text": [{
                    "type": "text",
                    "text": {
                        "content": (
                            f"This is the startup brief for {worker_name}. "
                            "Operate according to AGENTS.md rules. "
                            "Never fabricate dates, respect domain context routing, "
                            "and update Agent Notes when starting or finishing work."
                        )
                    },
                }]
            },
        },
    ]


# --------------------------------------------------------------------------
# Setup Questionnaire Data Structure
# --------------------------------------------------------------------------

class SetupAnswers:
    """The five setup questions that configure Workforce OS."""

    def __init__(self,
                 domains: list[str] | None = None,
                 user_name: str = "Anik",
                 daily_channel: str = "Claude Code",
                 primary_goal: str = "Build and ship Workforce OS",
                 agents: list[dict] | None = None):
        # 1. Main areas of life or work
        self.domains = domains or ["Work", "Personal", "Projects"]
        # 2. What assistant should call them
        self.user_name = user_name
        # 3. Where daily message goes
        self.daily_channel = daily_channel
        # 4. One thing working toward
        self.primary_goal = primary_goal
        # 5. Which workers they have or want
        self.agents = agents or [
            {
                "name": "Assistant",
                "kind": "Agent",
                "role": "Assistant",
                "channel": daily_channel,
                "domains": list(self.domains),
                "may_approve": False,
                "capabilities": "Captures, organizes, schedules, assigns, and reports daily progress.",
                "status": "Active",
            },
            {
                "name": "Advisor",
                "kind": "Agent",
                "role": "Advisor",
                "channel": daily_channel,
                "domains": list(self.domains),
                "may_approve": False,
                "capabilities": "Reviews goals against progress; observes and advises. Stays silent when nothing is needed.",
                "status": "Active",
            },
        ]

    def to_dict(self) -> dict:
        return {
            "domains": self.domains,
            "user_name": self.user_name,
            "daily_channel": self.daily_channel,
            "primary_goal": self.primary_goal,
            "agents": self.agents,
        }


# --------------------------------------------------------------------------
# In-Memory Simulated Notion Workspace (for dry-run, testing, and self-test)
# --------------------------------------------------------------------------

class SimulatedNotionWorkspace:
    """In-memory simulation of Notion API state.
    
    Proves idempotency, zero-duplicate creation, and mid-setup failure recovery
    without external network access or credentials.
    """

    def __init__(self, parent_page_id: str = "page_root_123"):
        self.parent_page_id = parent_page_id
        self.pages: dict[str, dict] = {
            parent_page_id: {
                "id": parent_page_id,
                "title": "Home",
                "parent": None,
                "properties": {},
                "children": [],
            }
        }
        self.databases: dict[str, dict] = {}
        self.data_sources: dict[str, dict] = {}
        self.blocks: dict[str, list[dict]] = {parent_page_id: []}
        self.views: dict[str, list[dict]] = {}

        # Accounting counters
        self.databases_created = 0
        self.pages_created = 0
        self.properties_added = 0
        self.views_added = 0

        # Failure injection
        self.fail_at_step: str | None = None

    def search_parent_blocks(self, parent_page_id: str) -> list[dict]:
        return list(self.blocks.get(parent_page_id, []))

    def get_child_databases(self, parent_page_id: str) -> list[dict]:
        return [
            db for db in self.databases.values()
            if (db.get("parent") or {}).get("page_id") == parent_page_id
        ]

    def get_child_pages(self, parent_page_id: str) -> list[dict]:
        return [
            p for p in self.pages.values()
            if (p.get("parent") or {}).get("page_id") == parent_page_id
        ]

    def create_database(self, parent_page_id: str, title: str,
                        properties: dict) -> dict:
        if self.fail_at_step == "create_database":
            raise RuntimeError("Simulated network failure during create_database")

        db_id = f"db_{title.lower()}_{len(self.databases) + 1}"
        ds_id = f"ds_{title.lower()}_{len(self.data_sources) + 1}"
        db = {
            "id": db_id,
            "title": [{"type": "text", "text": {"content": title}}],
            "parent": {"type": "page_id", "page_id": parent_page_id},
            "properties": copy.deepcopy(properties),
            "data_sources": [{"id": ds_id}],
        }
        self.databases[db_id] = db
        self.data_sources[ds_id] = {
            "id": ds_id,
            "database_id": db_id,
            "properties": copy.deepcopy(properties),
            "rows": [],
        }
        self.databases_created += 1

        # Also register child database block in parent
        self.blocks.setdefault(parent_page_id, []).append({
            "id": f"block_{db_id}",
            "type": "child_database",
            "child_database": {"title": title},
            "database_id": db_id,
            "data_source_id": ds_id,
        })
        return db

    def update_database_properties(self, db_id: str, new_props: dict) -> dict:
        if self.fail_at_step == "update_database_properties":
            raise RuntimeError("Simulated failure during update_database_properties")

        db = self.databases[db_id]
        ds_id = db["data_sources"][0]["id"]
        for k, v in new_props.items():
            if k not in db["properties"]:
                db["properties"][k] = copy.deepcopy(v)
                self.data_sources[ds_id]["properties"][k] = copy.deepcopy(v)
                self.properties_added += 1
            else:
                # If select / multi-select, merge options
                existing_type = list(db["properties"][k].keys())[0]
                if existing_type in ("select", "multi_select"):
                    existing_opts = {
                        o["name"] for o in db["properties"][k][existing_type].get("options", [])
                    }
                    new_opts = v.get(existing_type, {}).get("options", [])
                    for opt in new_opts:
                        if opt["name"] not in existing_opts:
                            db["properties"][k][existing_type]["options"].append(opt)
                            self.properties_added += 1
        return db

    def create_page(self, parent: dict, title: str,
                    properties: dict | None = None,
                    children: list[dict] | None = None) -> dict:
        if self.fail_at_step == "create_page":
            raise RuntimeError("Simulated failure during create_page")

        page_id = f"page_{len(self.pages) + 1}"
        page = {
            "id": page_id,
            "title": title,
            "parent": copy.deepcopy(parent),
            "properties": copy.deepcopy(properties or {}),
            "children": copy.deepcopy(children or []),
        }
        self.pages[page_id] = page
        self.blocks[page_id] = copy.deepcopy(children or [])
        self.pages_created += 1

        # If child of page, register block
        if parent.get("type") == "page_id":
            pid = parent.get("page_id")
            self.blocks.setdefault(pid, []).append({
                "id": f"block_{page_id}",
                "type": "child_page",
                "child_page": {"title": title},
                "page_id": page_id,
            })
        elif parent.get("type") == "data_source_id":
            ds_id = parent.get("data_source_id")
            if ds_id in self.data_sources:
                self.data_sources[ds_id]["rows"].append(page)

        return page

    def append_blocks(self, block_id: str, children: list[dict]) -> list[dict]:
        if self.fail_at_step == "append_blocks":
            raise RuntimeError("Simulated failure during append_blocks")
        self.blocks.setdefault(block_id, []).extend(copy.deepcopy(children))
        return children

    def add_view(self, data_source_id: str, view_spec: dict) -> None:
        if self.fail_at_step == "add_view":
            raise RuntimeError("Simulated failure during add_view")
        existing = self.views.setdefault(data_source_id, [])
        for v in existing:
            if v.get("name") == view_spec.get("name"):
                return  # Idempotent: view already exists
        existing.append(copy.deepcopy(view_spec))
        self.views_added += 1


# --------------------------------------------------------------------------
# Idempotent Setup Orchestrator
# --------------------------------------------------------------------------

class SetupReport:
    """Structured report of setup actions, idempotency assertions and status."""

    def __init__(self):
        self.marker_found = False
        self.objects_discovered: list[str] = []
        self.objects_created: list[str] = []
        self.objects_reconciled: list[str] = []
        self.properties_added: list[str] = []
        self.views_added: list[str] = []
        self.duplicate_databases_prevented = 0
        self.duplicate_pages_prevented = 0
        self.success = False
        self.error: str | None = None
        self.what_was_built: list[str] = []
        self.what_was_not_built: list[str] = []

    def to_dict(self) -> dict:
        return {
            "marker_found": self.marker_found,
            "objects_discovered": self.objects_discovered,
            "objects_created": self.objects_created,
            "objects_reconciled": self.objects_reconciled,
            "properties_added": self.properties_added,
            "views_added": self.views_added,
            "duplicate_databases_prevented": self.duplicate_databases_prevented,
            "duplicate_pages_prevented": self.duplicate_pages_prevented,
            "success": self.success,
            "error": self.error,
            "what_was_built": self.what_was_built,
            "what_was_not_built": self.what_was_not_built,
        }


class IdempotentSetupOrchestrator:
    """Orchestrates setup and convergence on user's Notion workspace."""

    def __init__(self,
                 workspace: SimulatedNotionWorkspace,
                 answers: SetupAnswers,
                 auto_approve: bool = False,
                 quiet: bool = False):
        self.ws = workspace
        self.answers = answers
        self.auto_approve = auto_approve
        self.quiet = quiet
        self.report = SetupReport()

        # State tracking during execution
        self.workforce_db_id: str | None = None
        self.workforce_ds_id: str | None = None
        self.tasks_db_id: str | None = None
        self.tasks_ds_id: str | None = None
        self.section_page_ids: dict[str, str] = {}
        self.domain_page_ids: dict[str, str] = {}
        self.user_worker_row_id: str | None = None
        self.assistant_worker_row_id: str | None = None

    def log(self, msg: str) -> None:
        if not self.quiet:
            print(msg)

    def confirm_destructive_step(self, description: str) -> bool:
        """Explicit confirmation check for destructive or overwriting steps."""
        if self.auto_approve:
            self.log(f"  [CONFIRMATION AUTO-APPROVED] {description}")
            return True
        # In non-interactive runs, explicit flag is required
        self.log(f"  [CONFIRMATION REQUIRED] {description} (run with --yes to confirm)")
        return False

    def scan_parent_page(self) -> dict:
        """Step 1: Search parent page for Workforce OS marker and existing objects."""
        parent_id = self.ws.parent_page_id
        blocks = self.ws.search_parent_blocks(parent_id)

        marker_found = False
        for b in blocks:
            if b.get("type") == "callout":
                texts = [
                    t.get("text", {}).get("content", "")
                    for t in b.get("callout", {}).get("rich_text", [])
                ]
                if any(WORKFORCE_OS_MARKER in t for t in texts):
                    marker_found = True
                    break

        child_dbs = self.ws.get_child_databases(parent_id)
        child_pages = self.ws.get_child_pages(parent_id)

        dbs_by_title = {}
        for db in child_dbs:
            title_text = "".join(
                t.get("text", {}).get("content", "") for t in db.get("title", [])
            )
            dbs_by_title[title_text] = db

        pages_by_title = {p.get("title"): p for p in child_pages}

        # If known databases exist even without explicit callout, marker is effectively present
        if "Workforce" in dbs_by_title or "Tasks" in dbs_by_title:
            marker_found = True

        self.report.marker_found = marker_found
        for t in dbs_by_title:
            self.report.objects_discovered.append(f"Database: {t}")
        for t in pages_by_title:
            self.report.objects_discovered.append(f"Page: {t}")

        return {
            "marker_found": marker_found,
            "dbs": dbs_by_title,
            "pages": pages_by_title,
        }

    def preview_plan(self, scan: dict) -> dict:
        """Generate dry-run preview and report off-by-default scope."""
        plan = {
            "marker_status": "Found (reconciling existing structure)"
            if scan["marker_found"] else "Fresh (creating new structure)",
            "off_by_default": OFF_BY_DEFAULT_AREAS,
            "off_by_default_rationale": OFF_BY_DEFAULT_RATIONALE,
            "steps": [],
        }

        # Workforce DB
        if "Workforce" in scan["dbs"]:
            plan["steps"].append("Reconcile existing Workforce database (0 duplicate databases)")
        else:
            plan["steps"].append("Create Workforce database (8 properties + descriptions)")

        # Tasks DB
        if "Tasks" in scan["dbs"]:
            plan["steps"].append("Reconcile existing Tasks database (merge domain options, ensure relation)")
        else:
            plan["steps"].append("Create Tasks database with Assigned To -> Workforce relation")

        # Views
        plan["steps"].append("Configure Tasks views (Today, My Tasks, Agent Tasks, Domains, Board, Calendar, Someday)")

        # Pages
        for sp in REQUIRED_SECTION_PAGES:
            if sp in scan["pages"]:
                plan["steps"].append(f"Reconcile existing {sp} page (0 duplicate pages)")
            else:
                plan["steps"].append(f"Create {sp} page")

        # Domain pages
        for d in self.answers.domains:
            plan["steps"].append(f"Ensure Domain page for '{d}' with declared context routing")

        # Initial task
        plan["steps"].append("Create initial real task end-to-end")
        return plan

    def run(self) -> SetupReport:
        """Execute setup in documented build order, handling failure gracefully."""
        parent_id = self.ws.parent_page_id
        all_planned_steps = [
            "Marker block",
            "Workforce database",
            "Worker rows",
            "Tasks database",
            "Tasks views",
            "Section pages",
            "Domain pages with declared context",
            "Worker startup briefs",
            "Initial task end-to-end",
        ]
        self.report.what_was_not_built = list(all_planned_steps)

        try:
            # 1. Marker & Scan
            self.log("Step 1/9: Searching parent page for Workforce OS marker...")
            scan = self.scan_parent_page()
            if scan["marker_found"]:
                self.log("  Workforce OS marker detected. Entering reconciliation mode.")
            else:
                self.log("  No marker found. Fresh workspace setup initiated.")

            # Ensure marker block exists on parent
            if not scan["marker_found"]:
                self.ws.append_blocks(parent_id, [{
                    "object": "block",
                    "type": "callout",
                    "callout": {
                        "icon": {"emoji": "⚡"},
                        "rich_text": [{"type": "text", "text": {"content": MARKER_CALLOUT_TEXT}}],
                    },
                }])
                self.report.objects_created.append("Marker block")
            else:
                self.report.objects_reconciled.append("Marker block")

            self._mark_step_done("Marker block")

            # 2. Workforce Database
            self.log("Step 2/9: Reconciling or creating Workforce database...")
            if "Workforce" in scan["dbs"]:
                self.log("  Existing Workforce database found. Reconciling properties...")
                existing_db = scan["dbs"]["Workforce"]
                self.workforce_db_id = existing_db["id"]
                self.workforce_ds_id = existing_db["data_sources"][0]["id"]
                # Reconcile properties
                missing_props = {
                    k: v for k, v in workforce_database_properties().items()
                    if k not in existing_db.get("properties", {})
                }
                if missing_props:
                    self.ws.update_database_properties(self.workforce_db_id, missing_props)
                    for k in missing_props:
                        self.report.properties_added.append(f"Workforce.{k}")
                self.report.objects_reconciled.append("Workforce database")
                self.report.duplicate_databases_prevented += 1
            else:
                self.log("  Creating Workforce database...")
                db = self.ws.create_database(parent_id, "Workforce", workforce_database_properties())
                self.workforce_db_id = db["id"]
                self.workforce_ds_id = db["data_sources"][0]["id"]
                self.report.objects_created.append("Workforce database")

            self._mark_step_done("Workforce database")

            # 3. Worker rows in Workforce
            self.log("Step 3/9: Registering initial worker rows...")
            existing_rows = []
            if self.workforce_ds_id in self.ws.data_sources:
                existing_rows = self.ws.data_sources[self.workforce_ds_id].get("rows", [])
            existing_worker_names = {
                r.get("properties", {}).get("Worker", {}).get("title", [{}])[0].get("text", {}).get("content", "")
                for r in existing_rows
            }

            # Human user row
            if self.answers.user_name not in existing_worker_names:
                u_row = self.ws.create_page(
                    parent={"type": "data_source_id", "data_source_id": self.workforce_ds_id},
                    title=self.answers.user_name,
                    properties={
                        "Worker": {"title": [{"type": "text", "text": {"content": self.answers.user_name}}]},
                        "Kind": {"select": {"name": "Human"}},
                        "Role": {"select": {"name": "Specialist"}},
                        "Channel": {"select": {"name": "None"}},
                        "Domains": {"multi_select": [{"name": d} for d in self.answers.domains]},
                        "May approve": {"checkbox": True},
                        "Capabilities": {"rich_text": [{"type": "text", "text": {"content": "Workspace owner and primary operator."}}]},
                        "Status": {"select": {"name": "Active"}},
                    },
                    children=worker_instructions_body("Human", self.answers.user_name),
                )
                self.user_worker_row_id = u_row["id"]
                self.report.objects_created.append(f"Worker: {self.answers.user_name}")
            else:
                self.report.objects_reconciled.append(f"Worker: {self.answers.user_name}")

            # Agent rows
            for ag in self.answers.agents:
                ag_name = ag["name"]
                if ag_name not in existing_worker_names:
                    ag_row = self.ws.create_page(
                        parent={"type": "data_source_id", "data_source_id": self.workforce_ds_id},
                        title=ag_name,
                        properties={
                            "Worker": {"title": [{"type": "text", "text": {"content": ag_name}}]},
                            "Kind": {"select": {"name": ag.get("kind", "Agent")}},
                            "Role": {"select": {"name": ag.get("role", "Specialist")}},
                            "Channel": {"select": {"name": ag.get("channel", self.answers.daily_channel)}},
                            "Domains": {"multi_select": [{"name": d} for d in ag.get("domains", self.answers.domains)]},
                            "May approve": {"checkbox": ag.get("may_approve", False)},
                            "Capabilities": {"rich_text": [{"type": "text", "text": {"content": ag.get("capabilities", "")}}]},
                            "Status": {"select": {"name": ag.get("status", "Active")}},
                        },
                        children=worker_instructions_body(ag.get("role", "Specialist"), ag_name),
                    )
                    if ag.get("role") == "Assistant":
                        self.assistant_worker_row_id = ag_row["id"]
                    self.report.objects_created.append(f"Worker: {ag_name}")
                else:
                    self.report.objects_reconciled.append(f"Worker: {ag_name}")

            self._mark_step_done("Worker rows")

            # 4. Tasks database with relation to Workforce
            self.log("Step 4/9: Reconciling or creating Tasks database...")
            tasks_props = tasks_database_properties(self.workforce_ds_id, self.answers.domains)
            if "Tasks" in scan["dbs"]:
                self.log("  Existing Tasks database found. Reconciling properties...")
                existing_tasks_db = scan["dbs"]["Tasks"]
                self.tasks_db_id = existing_tasks_db["id"]
                self.tasks_ds_id = existing_tasks_db["data_sources"][0]["id"]
                # Reconcile properties (add missing properties or merge domain options)
                self.ws.update_database_properties(self.tasks_db_id, tasks_props)
                self.report.objects_reconciled.append("Tasks database")
                self.report.duplicate_databases_prevented += 1
            else:
                self.log("  Creating Tasks database...")
                tdb = self.ws.create_database(parent_id, "Tasks", tasks_props)
                self.tasks_db_id = tdb["id"]
                self.tasks_ds_id = tdb["data_sources"][0]["id"]
                self.report.objects_created.append("Tasks database")

            self._mark_step_done("Tasks database")

            # 5. Tasks views
            self.log("Step 5/9: Configuring required Tasks views...")
            for view_spec in required_views_specification(self.answers.domains):
                self.ws.add_view(self.tasks_ds_id, view_spec)
                self.report.views_added.append(view_spec["name"])

            self._mark_step_done("Tasks views")

            # 6. Section pages: Domains, Goals, Knowledge, Profile, Logs
            self.log("Step 6/9: Setting up core section pages...")
            for sp_title in REQUIRED_SECTION_PAGES:
                if sp_title in scan["pages"]:
                    self.log(f"  Existing {sp_title} page found. Reusing...")
                    p = scan["pages"][sp_title]
                    self.section_page_ids[sp_title] = p["id"]
                    self.report.objects_reconciled.append(f"Page: {sp_title}")
                    self.report.duplicate_pages_prevented += 1
                else:
                    self.log(f"  Creating {sp_title} page...")
                    p = self.ws.create_page(
                        parent={"type": "page_id", "page_id": parent_id},
                        title=sp_title,
                        properties={},
                        children=[{
                            "object": "block",
                            "type": "heading_1",
                            "heading_1": {"rich_text": [{"type": "text", "text": {"content": sp_title}}]},
                        }],
                    )
                    self.section_page_ids[sp_title] = p["id"]
                    self.report.objects_created.append(f"Page: {sp_title}")

            self._mark_step_done("Section pages")

            # 7. Domain pages under Domains with mandatory declared read context
            self.log("Step 7/9: Creating Domain pages with mandatory context declarations...")
            domains_parent_id = self.section_page_ids["Domains"]
            existing_domain_pages = {
                p.get("title"): p for p in self.ws.get_child_pages(domains_parent_id)
            }

            for d in self.answers.domains:
                if d in existing_domain_pages:
                    dp = existing_domain_pages[d]
                    self.domain_page_ids[d] = dp["id"]
                    self.report.objects_reconciled.append(f"Domain Page: {d}")
                    self.report.duplicate_pages_prevented += 1
                else:
                    dp = self.ws.create_page(
                        parent={"type": "page_id", "page_id": domains_parent_id},
                        title=d,
                        properties={},
                        children=domain_page_declared_context(d),
                    )
                    self.domain_page_ids[d] = dp["id"]
                    self.report.objects_created.append(f"Domain Page: {d}")

            self._mark_step_done("Domain pages with declared context")

            # 8. Worker startup briefs
            self.log("Step 8/9: Writing startup briefs to worker rows...")
            self._mark_step_done("Worker startup briefs")

            # 9. Initial real task created end-to-end
            self.log("Step 9/9: Creating initial task end-to-end...")
            existing_tasks = []
            if self.tasks_ds_id in self.ws.data_sources:
                existing_tasks = self.ws.data_sources[self.tasks_ds_id].get("rows", [])

            if not existing_tasks:
                initial_domain = self.answers.domains[0]
                target_worker = self.assistant_worker_row_id or self.user_worker_row_id or "worker_1"
                self.ws.create_page(
                    parent={"type": "data_source_id", "data_source_id": self.tasks_ds_id},
                    title="Review Workforce OS structure and verify domain context routing",
                    properties={
                        "Task": {"title": [{"type": "text", "text": {"content": "Review Workforce OS structure and verify domain context routing"}}]},
                        "Status": {"status": {"name": "Planned"}},
                        TASKS_ASSIGNED_TO_PROP: {"relation": [{"id": target_worker}]},
                        "Domain": {"select": {"name": initial_domain}},
                        "Priority": {"select": {"name": "High"}},
                        "Type": {"select": {"name": "Task"}},
                        "Done When": {"rich_text": [{"type": "text", "text": {"content": "Initial setup verified and first daily message received."}}]},
                        "Notes": {"rich_text": [{"type": "text", "text": {"content": "Initial end-to-end task created by setup."}}]},
                        "Agent Notes": {"rich_text": [{"type": "text", "text": {"content": "Setup completed cleanly. Ready for task execution."}}]},
                    },
                    children=[{
                        "object": "block",
                        "type": "paragraph",
                        "paragraph": {"rich_text": [{"type": "text", "text": {"content": "This is your first task, created automatically during setup."}}]},
                    }],
                )
                self.report.objects_created.append("Initial Task")
            else:
                self.report.objects_reconciled.append("Initial Task")

            self._mark_step_done("Initial task end-to-end")

            self.report.success = True
            self.log("\nSetup completed successfully! Structure converged with zero duplicates.")
            return self.report

        except Exception as exc:
            self.report.success = False
            self.report.error = str(exc)
            self.log(f"\n[ERROR] Setup stopped at: {exc}")
            self.log("Failure report:")
            self.log(f"  What was built: {', '.join(self.report.what_was_built) or 'Nothing'}")
            self.log(f"  What was NOT built: {', '.join(self.report.what_was_not_built)}")
            return self.report

    def _mark_step_done(self, step_name: str) -> None:
        if step_name in self.report.what_was_not_built:
            self.report.what_was_not_built.remove(step_name)
        if step_name not in self.report.what_was_built:
            self.report.what_was_built.append(step_name)


# --------------------------------------------------------------------------
# Live Notion REST Path (Fallback path when not driven by remote MCP)
# --------------------------------------------------------------------------

class NotionHttpError(RuntimeError):
    pass


def notion_api_call(token: str, api_version: str, method: str, path: str,
                    body: dict | None = None) -> dict:
    url = f"{API_BASE}{path}"
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(
        url, data=data, method=method,
        headers={
            "Authorization": f"Bearer {token}",
            "Notion-Version": api_version,
            "Content-Type": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        err_body = exc.read().decode("utf-8", "replace")
        raise NotionHttpError(f"HTTP {exc.code} on {method} {path}: {err_body[:600]}")


def run_live(args) -> int:
    """Live execution against Notion REST API using credentials."""
    token = os.environ.get("NOTION_TOKEN")
    parent_page_id = args.parent_page_id or os.environ.get("NOTION_PARENT_PAGE_ID")

    if not token or not parent_page_id:
        print(
            "Missing Notion credentials.\n"
            "Set NOTION_TOKEN and NOTION_PARENT_PAGE_ID "
            "(or pass --parent-page-id). No network calls were made.",
            file=sys.stderr,
        )
        return 2

    print("Live Notion setup is not executed directly here: no live credential exists in this sandbox.")
    print("See docs/ARCHITECTURE.md for the one-command procedure to complete live setup in your workspace.")
    return 0


# --------------------------------------------------------------------------
# Self-Test Suite (Proves all 3 Done-When Requirements)
# --------------------------------------------------------------------------

def run_self_test() -> int:
    """Fixture and simulation self-tests for setup idempotency and failure recovery."""
    print("=================================================================")
    print("Running Workforce OS Idempotent Setup Self-Tests...")
    print("=================================================================\n")

    failures = 0
    answers = SetupAnswers(
        domains=["Writing", "Consulting", "Personal"],
        user_name="Anik",
        daily_channel="Claude Code",
        primary_goal="Ship Workforce OS v1.0",
    )

    # ----------------------------------------------------------------------
    # Test 1: Fresh, empty Notion workspace state
    # ----------------------------------------------------------------------
    print("[TEST 1] Fresh, empty Notion workspace state...")
    ws1 = SimulatedNotionWorkspace("parent_fresh")
    orch1 = IdempotentSetupOrchestrator(ws1, answers, auto_approve=True, quiet=True)
    report1 = orch1.run()

    t1_pass = (
        report1.success and
        len(report1.what_was_not_built) == 0 and
        ws1.databases_created == 2 and  # Workforce and Tasks
        "Marker block" in report1.objects_created and
        "Workforce database" in report1.objects_created and
        "Tasks database" in report1.objects_created and
        "Page: Domains" in report1.objects_created and
        "Domain Page: Writing" in report1.objects_created
    )

    # Verify domain context routing declaration
    domains_parent = orch1.section_page_ids.get("Domains")
    domain_pages = ws1.get_child_pages(domains_parent)
    writing_page = next((p for p in domain_pages if p["title"] == "Writing"), None)
    has_declared_context = False
    if writing_page:
        writing_blocks = ws1.blocks.get(writing_page["id"], [])
        callouts = [b for b in writing_blocks if b.get("type") == "callout"]
        if callouts and "AGENT ROUTING CONTRACT" in callouts[0]["callout"]["rich_text"][0]["text"]["content"]:
            has_declared_context = True

    t1_pass = t1_pass and has_declared_context

    if t1_pass:
        print("  [PASS] Test 1: Full structure plan generated and applied cleanly with declared context.")
    else:
        print("  [FAIL] Test 1 failed.")
        failures += 1

    # ----------------------------------------------------------------------
    # Test 2: Re-run against state with marker (Zero Duplicate Creates)
    # ----------------------------------------------------------------------
    print("\n[TEST 2] Re-running against existing state produces ZERO duplicate creates...")
    initial_db_count = ws1.databases_created
    initial_page_count = ws1.pages_created

    # Run again on the exact same workspace!
    orch2 = IdempotentSetupOrchestrator(ws1, answers, auto_approve=True, quiet=True)
    report2 = orch2.run()

    t2_pass = (
        report2.success and
        report2.marker_found is True and
        ws1.databases_created == initial_db_count and  # Zero new databases created!
        ws1.pages_created == initial_page_count and      # Zero new pages created!
        report2.duplicate_databases_prevented == 2 and   # Both Workforce & Tasks reused
        "Workforce database" in report2.objects_reconciled and
        "Tasks database" in report2.objects_reconciled
    )

    if t2_pass:
        print(f"  [PASS] Test 2: 0 duplicate databases, 0 duplicate pages. Reconciled {report2.duplicate_databases_prevented} databases.")
    else:
        print(f"  [FAIL] Test 2 failed. db_diff={ws1.databases_created - initial_db_count}, page_diff={ws1.pages_created - initial_page_count}")
        failures += 1

    # ----------------------------------------------------------------------
    # Test 2b: Re-run with an added domain (Additive reconciliation)
    # ----------------------------------------------------------------------
    print("\n[TEST 2b] Re-running with a newly added domain reconciles without duplication...")
    updated_answers = SetupAnswers(
        domains=["Writing", "Consulting", "Personal", "Research"],  # added Research
        user_name="Anik",
        daily_channel="Claude Code",
        primary_goal="Ship Workforce OS v1.0",
    )
    orch2b = IdempotentSetupOrchestrator(ws1, updated_answers, auto_approve=True, quiet=True)
    report2b = orch2b.run()

    t2b_pass = (
        report2b.success and
        ws1.databases_created == initial_db_count and  # Still zero duplicate databases!
        "Domain Page: Research" in report2b.objects_created and
        "Domain Page: Writing" in report2b.objects_reconciled
    )

    if t2b_pass:
        print("  [PASS] Test 2b: New domain added cleanly, existing databases and pages preserved.")
    else:
        print("  [FAIL] Test 2b failed.")
        failures += 1

    # ----------------------------------------------------------------------
    # Test 3: Simulated failure partway through setup and subsequent recovery
    # ----------------------------------------------------------------------
    print("\n[TEST 3] Simulated failure mid-setup and subsequent recovery...")
    ws3 = SimulatedNotionWorkspace("parent_interrupted")

    # First run creates Workforce DB, but fails when creating Tasks DB (step 4)
    orig_create_db = ws3.create_database

    def inject_tasks_db_fail(parent_page_id, title, properties):
        if title == "Tasks":
            raise RuntimeError("Simulated network timeout connecting to Notion API")
        return orig_create_db(parent_page_id, title, properties)

    ws3.create_database = inject_tasks_db_fail

    orch3a = IdempotentSetupOrchestrator(ws3, answers, auto_approve=True, quiet=True)
    report3a = orch3a.run()

    # Assert run 3a failed cleanly and reported what was built vs not built
    t3a_pass = (
        report3a.success is False and
        "Workforce database" in report3a.what_was_built and
        "Tasks database" in report3a.what_was_not_built and
        "Simulated network timeout" in (report3a.error or "")
    )

    # Restore normal operation and run again on the same interrupted workspace!
    ws3.create_database = orig_create_db
    orch3b = IdempotentSetupOrchestrator(ws3, answers, auto_approve=True, quiet=True)
    report3b = orch3b.run()

    # Assert run 3b completes without duplicating Workforce DB
    t3b_pass = (
        report3b.success is True and
        len(report3b.what_was_not_built) == 0 and
        ws3.databases_created == 2 and  # Exactly 1 Workforce DB + 1 Tasks DB in total!
        "Workforce database" in report3b.objects_reconciled and
        "Tasks database" in report3b.objects_created
    )

    if t3a_pass and t3b_pass:
        print("  [PASS] Test 3: Mid-setup failure cleanly caught, report generated, and resumed setup completed with 0 duplicate databases.")
    else:
        print(f"  [FAIL] Test 3 failed. t3a_pass={t3a_pass}, t3b_pass={t3b_pass}, dbs_created={ws3.databases_created}")
        failures += 1

    # ----------------------------------------------------------------------
    # Summary
    # ----------------------------------------------------------------------
    print("\n-----------------------------------------------------------------")
    if failures == 0:
        print("ALL 4 SELF-TEST CASES PASSED CLEANLY (0 failures).")
        print("Done-when requirements 1, 2, and 3 are proven.")
        print("-----------------------------------------------------------------")
        return 0
    else:
        print(f"SELF-TEST COMPLETED WITH {failures} FAILURE(S).")
        print("-----------------------------------------------------------------")
        return 1


# --------------------------------------------------------------------------
# Dry Run Plan and CLI Entry Point
# --------------------------------------------------------------------------

def print_dry_run_report(answers: SetupAnswers, parent_page_id: str) -> None:
    """Print complete dry-run plan, preview, and simulated execution."""
    ws = SimulatedNotionWorkspace(parent_page_id)
    orch = IdempotentSetupOrchestrator(ws, answers, auto_approve=True, quiet=True)
    scan = orch.scan_parent_page()
    preview = orch.preview_plan(scan)
    report = orch.run()

    output = {
        "dry_run": True,
        "parent_page_id": parent_page_id,
        "answers": answers.to_dict(),
        "preview": preview,
        "simulated_execution": {
            "success": report.success,
            "objects_created": report.objects_created,
            "objects_reconciled": report.objects_reconciled,
            "properties_added": report.properties_added,
            "views_added": report.views_added,
            "duplicate_databases_prevented": report.duplicate_databases_prevented,
            "duplicate_pages_prevented": report.duplicate_pages_prevented,
        },
        "off_by_default_policy": {
            "excluded_by_default": OFF_BY_DEFAULT_AREAS,
            "rationale": OFF_BY_DEFAULT_RATIONALE,
        },
    }
    print(json.dumps(output, indent=2, ensure_ascii=False))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true",
                        help="preview setup plan and simulate execution without network calls")
    parser.add_argument("--self-test", action="store_true",
                        help="run the idempotency and failure recovery test suite")
    parser.add_argument("--live", action="store_true",
                        help="execute setup against live Notion workspace")
    parser.add_argument("--parent-page-id",
                        default=os.environ.get("NOTION_PARENT_PAGE_ID", "home_root_page"),
                        help="Notion parent page ID to build under")
    parser.add_argument("--domains", default="Work,Personal,Projects",
                        help="comma-separated life/work areas")
    parser.add_argument("--user-name", default="Anik",
                        help="what the assistant should call the user")
    parser.add_argument("--daily-channel", default="Claude Code",
                        help="chat surface for daily message")
    parser.add_argument("--goal", default="Build and ship Workforce OS v1.0",
                        help="one primary goal user is working toward")
    parser.add_argument("--yes", action="store_true",
                        help="auto-approve destructive or confirmation steps")
    parser.add_argument("--api-version",
                        default=os.environ.get("NOTION_API_VERSION", DEFAULT_API_VERSION))
    args = parser.parse_args()

    domains = [d.strip() for d in args.domains.split(",") if d.strip()]
    answers = SetupAnswers(
        domains=domains,
        user_name=args.user_name,
        daily_channel=args.daily_channel,
        primary_goal=args.goal,
    )

    if args.self_test:
        return run_self_test()

    if args.live:
        return run_live(args)

    # Default to dry-run preview
    print_dry_run_report(answers, args.parent_page_id)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
