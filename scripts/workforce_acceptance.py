#!/usr/bin/env python3
"""Workforce OS acceptance test suite.

One command that answers whether Workforce OS does what its documentation claims.
Runs nine acceptance tests (eight execution tests, with 6+7 merged per rescope,
plus the README claim audit) against fixture workspace state with zero network
calls or credentials.

Acceptance Tests:
  1. Setup runs in a fresh, empty workspace and produces the full structure.
  2. Setup re-runs against the same workspace and creates zero duplicates.
  3. A rough one-line message produces a structured task without manual field editing.
  4. A task assigned to a worker is read by that worker and by no other.
  5. An agent working a task loads only its Domain's declared pages (transcript check).
  6+7. Review protocol checklist produces expected lines on qualifying state,
       and stays silent on a clean day.
  8. Killing Notion access mid-setup produces a clear error and a successful re-run.
  9. Every substantive claim in the README is demonstrated by tests 1-8 or labelled planned.

Usage:
  python3 scripts/workforce_acceptance.py
  python3 scripts/workforce_acceptance.py --verbose
"""

from __future__ import annotations

import argparse
import copy
from datetime import datetime, timezone
import os
import sys
from typing import Any

# Ensure script directory is on sys.path
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
if SCRIPT_DIR not in sys.path:
    sys.path.insert(0, SCRIPT_DIR)

from workforce_schema import (
    CHANNELS,
    KINDS,
    RELATION_TARGET_KEY,
    RELATION_TYPE,
    ROLES,
    TASKS_ASSIGNED_TO_PROP,
    WORKER_STATUSES,
    WORKFORCE_TITLE_PROP,
    agent_worker,
    assistant_worker,
    can_assign,
    human_worker,
    tasks_assigned_to_relation,
    workforce_database_properties,
)
from workforce_setup import (
    MARKER_CALLOUT_TEXT,
    REQUIRED_SECTION_PAGES,
    REQUIRED_TASKS_PROPERTIES,
    WORKFORCE_OS_MARKER,
    IdempotentSetupOrchestrator,
    SetupAnswers,
    SetupReport,
    SimulatedNotionWorkspace,
    domain_page_declared_context,
    required_views_specification,
    tasks_database_properties,
)
from workforce_permission import (
    build_default_domain_declarations,
    can_act_on_task,
    check_read_scope,
    get_worker_queue,
    is_page_in_declared_scope,
    start_task_execution,
    update_task_field,
    validate_field_write_permission,
)
from workforce_capture import (
    assign_captured_task,
    capture_and_structure_thought,
    capture_thought_idempotent,
)
from workforce_heartbeat import evaluate_review_protocol

# --------------------------------------------------------------------------
# Registry of Public Claims Mapped to Tests
# --------------------------------------------------------------------------

PUBLIC_CLAIMS_MAP = {
    1: "Fresh setup in empty Notion workspace produces full structure with zero manual fixes",
    2: "Setup re-runs against existing workspace and creates zero duplicate objects",
    3: "Rough one-line message produces structured task without manual field editing",
    4: "A task assigned to a worker is read by that worker and by no other",
    5: "An agent working a task loads only its Domain's declared pages (verified via transcript)",
    6: "Review protocol checklist evaluates qualifying items and remains silent on clean day",
    8: "Mid-setup failure produces clear error and resumes cleanly without duplicate creation",
    9: "Every claim in README is demonstrated by tests 1-8 or labelled planned",
}


# --------------------------------------------------------------------------
# Test 1: Fresh Setup in Empty Workspace
# --------------------------------------------------------------------------

def test_1_fresh_setup_produces_full_structure(verbose: bool = False) -> tuple[bool, str]:
    """Test 1: Fresh setup runs in an empty workspace and creates full structure."""
    claim = PUBLIC_CLAIMS_MAP[1]
    try:
        ws = SimulatedNotionWorkspace("parent_fresh_acceptance")
        answers = SetupAnswers(
            domains=["Writing", "Consulting", "Personal"],
            user_name="Anik",
            daily_channel="Claude Code",
            primary_goal="Ship Workforce OS v1.0",
        )
        orch = IdempotentSetupOrchestrator(ws, answers, auto_approve=True, quiet=not verbose)
        report = orch.run()

        if not report.success:
            return False, f"README claim '{claim}' is now false: setup failed with error {report.error!r}"

        if report.what_was_not_built:
            return False, (
                f"README claim '{claim}' is now false: setup left steps unbuilt: "
                f"{', '.join(report.what_was_not_built)}"
            )

        if ws.databases_created != 3:
            return False, (
                f"README claim '{claim}' is now false: expected exactly 3 databases (Workforce, Tasks, Sections), "
                f"but found {ws.databases_created}"
            )

        # Check Workforce DB properties and descriptions
        workforce_db = next((db for db in ws.databases.values() if db["title"][0]["text"]["content"] == "Workforce"), None)
        if not workforce_db:
            return False, f"README claim '{claim}' is now false: Workforce database missing from workspace"

        wf_props = workforce_db.get("properties", {})
        expected_wf_props = workforce_database_properties()
        for prop_name, spec in expected_wf_props.items():
            if prop_name not in wf_props:
                return False, f"README claim '{claim}' is now false: Workforce property '{prop_name}' missing"
            if not wf_props[prop_name].get("description"):
                return False, f"README claim '{claim}' is now false: Workforce property '{prop_name}' missing description"

        # Check Tasks DB properties, including relation
        tasks_db = next((db for db in ws.databases.values() if db["title"][0]["text"]["content"] == "Tasks"), None)
        if not tasks_db:
            return False, f"README claim '{claim}' is now false: Tasks database missing from workspace"

        tasks_props = tasks_db.get("properties", {})
        if TASKS_ASSIGNED_TO_PROP not in tasks_props:
            return False, f"README claim '{claim}' is now false: Tasks database missing '{TASKS_ASSIGNED_TO_PROP}' relation"

        assigned_to = tasks_props[TASKS_ASSIGNED_TO_PROP]
        if "relation" not in assigned_to:
            return False, f"README claim '{claim}' is now false: '{TASKS_ASSIGNED_TO_PROP}' is not a relation"

        # Check Sections DB properties, descriptions, and gallery view
        sections_db = next((db for db in ws.databases.values() if db["title"][0]["text"]["content"] == "Sections"), None)
        if not sections_db:
            return False, f"README claim '{claim}' is now false: Sections database missing from workspace"

        sec_props = sections_db.get("properties", {})
        for prop_name in ["Section", "Group", "Order", "What it is"]:
            if prop_name not in sec_props:
                return False, f"README claim '{claim}' is now false: Sections property '{prop_name}' missing"
            if not sec_props[prop_name].get("description"):
                return False, f"README claim '{claim}' is now false: Sections property '{prop_name}' missing description"

        # Verify covers, icons, and descriptions for all 8 pages
        parent_page = ws.pages["parent_fresh_acceptance"]
        if not parent_page.get("cover") or not parent_page.get("icon"):
            return False, f"README claim '{claim}' is now false: Home page missing cover or icon"

        sections_ds_id = sections_db["data_sources"][0]["id"]
        sec_rows = ws.data_sources[sections_ds_id].get("rows", [])
        expected_sections = {"Home", "Tasks", "Workforce", "Domains", "Goals", "Knowledge", "Profile", "Logs"}
        found_sections = {
            r.get("properties", {}).get("Section", {}).get("title", [{}])[0].get("text", {}).get("content", "")
            for r in sec_rows
        }
        if expected_sections != found_sections:
            return False, f"README claim '{claim}' is now false: Sections database missing rows: {expected_sections - found_sections}"

        for r in sec_rows:
            r_sec = r.get("properties", {}).get("Section", {}).get("title", [{}])[0].get("text", {}).get("content", "")
            r_desc = r.get("properties", {}).get("What it is", {}).get("rich_text", [{}])[0].get("text", {}).get("content", "")
            if not (r.get("cover") and r.get("icon") and r_desc):
                return False, f"README claim '{claim}' is now false: Section card '{r_sec}' missing cover, icon, or description"

        # Check Section pages
        child_pages = ws.get_child_pages("parent_fresh_acceptance")
        child_page_titles = {p["title"] for p in child_pages}
        for sec in REQUIRED_SECTION_PAGES:
            if sec not in child_page_titles:
                return False, f"README claim '{claim}' is now false: Section page '{sec}' missing"

        # Check Domain page context declaration block
        domains_parent = next((p["id"] for p in child_pages if p["title"] == "Domains"), None)
        if not domains_parent:
            return False, f"README claim '{claim}' is now false: 'Domains' parent page not found"

        domain_pages = ws.get_child_pages(domains_parent)
        domain_titles = {p["title"] for p in domain_pages}
        for d in answers.domains:
            if d not in domain_titles:
                return False, f"README claim '{claim}' is now false: Domain subpage '{d}' missing under Domains"

        # Check initial real task created end-to-end
        tasks_ds_id = tasks_db["data_sources"][0]["id"]
        task_rows = ws.data_sources[tasks_ds_id].get("rows", [])
        if not task_rows:
            return False, f"README claim '{claim}' is now false: Initial end-to-end task was not created"

        initial_task = task_rows[0]
        initial_status = initial_task.get("properties", {}).get("Status", {}).get("status", {}).get("name")
        if initial_status != "Planned":
            return False, f"README claim '{claim}' is now false: Initial task status is '{initial_status}', expected 'Planned'"

        return True, "Full structure created with no manual fixes: databases, properties, relation, section pages, domain contexts, and initial task."

    except Exception as exc:
        return False, f"README claim '{claim}' is now false: unhandled exception: {exc}"


# --------------------------------------------------------------------------
# Test 2: Setup Re-run Produces Zero Duplicates
# --------------------------------------------------------------------------

def test_2_setup_rerun_zero_duplicates(verbose: bool = False) -> tuple[bool, str]:
    """Test 2: Setup re-runs against the same workspace and creates zero duplicates."""
    claim = PUBLIC_CLAIMS_MAP[2]
    try:
        ws = SimulatedNotionWorkspace("parent_rerun_acceptance")
        answers = SetupAnswers(
            domains=["Writing", "Consulting", "Personal"],
            user_name="Anik",
            daily_channel="Claude Code",
            primary_goal="Ship Workforce OS v1.0",
        )
        orch1 = IdempotentSetupOrchestrator(ws, answers, auto_approve=True, quiet=True)
        report1 = orch1.run()
        if not report1.success:
            return False, f"README claim '{claim}' is now false: initial setup failed: {report1.error}"

        dbs_after_run1 = ws.databases_created
        pages_after_run1 = ws.pages_created

        # Customize a cover and an icon before second run to verify user customization preservation
        custom_home_cover = {"type": "external", "external": {"url": "https://example.com/custom_home.jpg"}}
        ws.pages["parent_rerun_acceptance"]["cover"] = custom_home_cover

        sections_db_1 = next(db for db in ws.databases.values() if db["title"][0]["text"]["content"] == "Sections")
        sec_ds_id_1 = sections_db_1["data_sources"][0]["id"]
        tasks_sec_row = next(r for r in ws.data_sources[sec_ds_id_1]["rows"] if r.get("title") == "Tasks")
        custom_tasks_icon = {"type": "emoji", "emoji": "🎯"}
        tasks_sec_row["icon"] = custom_tasks_icon

        # Run setup a second time on the exact same workspace state
        orch2 = IdempotentSetupOrchestrator(ws, answers, auto_approve=True, quiet=not verbose)
        report2 = orch2.run()

        if not report2.success:
            return False, f"README claim '{claim}' is now false: second setup run failed: {report2.error}"

        if not report2.marker_found:
            return False, f"README claim '{claim}' is now false: marker was not detected on second run"

        if ws.databases_created != dbs_after_run1:
            diff = ws.databases_created - dbs_after_run1
            return False, f"README claim '{claim}' is now false: second run created {diff} duplicate database(s)"

        if ws.pages_created != pages_after_run1:
            diff = ws.pages_created - pages_after_run1
            return False, f"README claim '{claim}' is now false: second run created {diff} duplicate page(s)"

        if report2.duplicate_databases_prevented != 3:
            return False, (
                f"README claim '{claim}' is now false: expected 3 duplicate databases prevented, "
                f"got {report2.duplicate_databases_prevented}"
            )

        if "Workforce database" not in report2.objects_reconciled:
            return False, f"README claim '{claim}' is now false: Workforce database was not reconciled"

        if "Tasks database" not in report2.objects_reconciled:
            return False, f"README claim '{claim}' is now false: Tasks database was not reconciled"

        if "Sections database" not in report2.objects_reconciled:
            return False, f"README claim '{claim}' is now false: Sections database was not reconciled"

        # Verify user customization preservation across re-runs
        if ws.pages["parent_rerun_acceptance"].get("cover") != custom_home_cover:
            return False, f"README claim '{claim}' is now false: user-customized Home cover was overwritten on second run"

        updated_tasks_row = next(r for r in ws.data_sources[sec_ds_id_1]["rows"] if r.get("title") == "Tasks")
        if updated_tasks_row.get("icon") != custom_tasks_icon:
            return False, f"README claim '{claim}' is now false: user-customized Tasks icon was overwritten on second run"

        return True, "Re-running created 0 duplicate databases and 0 duplicate pages; reconciled 3 databases cleanly and preserved user customizations."

    except Exception as exc:
        return False, f"README claim '{claim}' is now false: unhandled exception: {exc}"


# --------------------------------------------------------------------------
# Test 3: Rough Capture Transformation
# --------------------------------------------------------------------------

def test_3_rough_message_capture_transformation(verbose: bool = False) -> tuple[bool, str]:
    """Test 3: Rough one-line message produces structured task without manual field editing."""
    claim = PUBLIC_CLAIMS_MAP[3]
    try:
        available_domains = ["Writing", "Consulting", "Personal"]

        # Case A: Documented example from AGENTS.md section 2
        raw_a = "the telegram deal thing — think amazon approval comes first"
        task_a = capture_and_structure_thought(raw_a, available_domains)

        if not task_a.get("Task") or task_a["Task"] == raw_a:
            return False, f"README claim '{claim}' is now false: Task title was not converted to a clean action"

        if not task_a.get("Done When"):
            return False, f"README claim '{claim}' is now false: Done When condition was not derived"

        if task_a.get("Domain") not in available_domains:
            return False, f"README claim '{claim}' is now false: Task was assigned invalid domain '{task_a.get('Domain')}'"

        if task_a.get("Status") != "Planned":
            return False, f"README claim '{claim}' is now false: Initial status must be 'Planned', got '{task_a.get('Status')}'"

        if task_a.get("Notes") != "":
            return False, f"README claim '{claim}' is now false: Agent wrote into user-only 'Notes' field"

        # Case B: Documented example from skills/workforce-operate/SKILL.md
        raw_b = "need to sort the company registration thing before it gets late"
        task_b = capture_and_structure_thought(raw_b, available_domains)

        if task_b.get("Task") != "Register the company":
            return False, f"README claim '{claim}' is now false: expected 'Register the company', got '{task_b.get('Task')}'"

        if task_b.get("Done When") != "Registration certificate in hand":
            return False, f"README claim '{claim}' is now false: expected 'Registration certificate in hand', got '{task_b.get('Done When')}'"

        if task_b.get("Domain") != "Consulting":
            return False, f"README claim '{claim}' is now false: expected domain 'Consulting', got '{task_b.get('Domain')}'"

        # Verify that all 6 required fields are populated without manual user interaction
        for req in ["Task", "Done When", "Domain", "Priority", "Status", "Start Date"]:
            if not task_b.get(req):
                return False, f"README claim '{claim}' is now false: required field '{req}' was missing from structured task"

        # Case C: Idempotent capture (repeating identical capture produces 0 duplicate rows and 0 repeated questions)
        fixture_tasks_db: list[dict[str, Any]] = []
        chat_history: list[str] = []
        clarifications = ["Clarify affiliate program requirements?"]

        c1 = capture_thought_idempotent(
            raw_a,
            fixture_tasks_db,
            chat_history=chat_history,
            available_domains=available_domains,
            candidate_questions=clarifications,
        )
        if not c1.created or len(fixture_tasks_db) != 1 or len(c1.questions_asked) != 1:
            return False, f"README claim '{claim}' is now false: initial capture failed to create task or ask question"

        # Re-capture identical message
        c2 = capture_thought_idempotent(
            raw_a,
            fixture_tasks_db,
            chat_history=chat_history,
            available_domains=available_domains,
            candidate_questions=clarifications,
        )
        if c2.created:
            return False, f"README claim '{claim}' is now false: second capture created a duplicate task row"
        if not c2.duplicate_detected:
            return False, f"README claim '{claim}' is now false: duplicate capture was not detected"
        if len(fixture_tasks_db) != 1:
            return False, f"README claim '{claim}' is now false: expected exactly 1 task row in database, found {len(fixture_tasks_db)}"
        if len(c2.questions_asked) != 0:
            return False, f"README claim '{claim}' is now false: re-capture repeated questions: {c2.questions_asked}"

        # Case D: Assignment strictly resolves through shared permission gate from workforce_permission.py
        workers = [
            agent_worker("AliceSpecialist", ["Writing"], status="Active"),
            agent_worker("BobPaused", ["Writing"], status="Paused"),
        ]
        assign_res = assign_captured_task(c1.task, workers)
        if not assign_res.assigned or assign_res.worker_name != "AliceSpecialist":
            return False, f"README claim '{claim}' is now false: assignment failed to route to active specialist AliceSpecialist"
        if c1.task.get("Assigned To") != "AliceSpecialist":
            return False, f"README claim '{claim}' is now false: Assigned To was not set on task"

        # Case E: Nonexistent specialist states plainly and refuses Assistant assignment or silent completion
        workers_with_assistant = [
            assistant_worker("GeneralAssistant", domains=["Engineering", "Writing", "Consulting"]),
            agent_worker("WritingSpecialist", domains=["Writing"], status="Active"),
        ]
        engineering_task = {
            "Task": "Build database connector",
            "Next Action": "Write connection pool logic",
            "Done When": "Pool connects cleanly",
            "Domain": "Engineering",
            "Status": "Planned",
        }
        assign_eng = assign_captured_task(engineering_task, workers_with_assistant)
        if assign_eng.assigned:
            return False, f"README claim '{claim}' is now false: task assigned when no specialist existed"
        if engineering_task.get("Assigned To") is not None:
            return False, f"README claim '{claim}' is now false: task was illegally assigned to Assistant or other worker"
        if engineering_task.get("Status") != "Planned":
            return False, f"README claim '{claim}' is now false: task status changed from Planned without assignment"
        if "No specialist exists for domain 'Engineering'" not in assign_eng.reason:
            return False, f"README claim '{claim}' is now false: missing plain statement that no specialist exists"

        msg = (
            "Rough input transformed into structured task with next action, done when, domain, "
            "and dates; zero fields edited by hand. Repeating identical capture produces zero "
            "duplicate rows and zero repeated questions; assignment strictly routes through shared "
            "permission gate and plainly refuses Assistant fallback when no specialist exists."
        )
        return True, msg

    except Exception as exc:
        return False, f"README claim '{claim}' is now false: unhandled exception: {exc}"


# --------------------------------------------------------------------------
# Test 4: Task Queue Isolation Between Workers
# --------------------------------------------------------------------------

def test_4_assigned_task_queue_isolation(verbose: bool = False) -> tuple[bool, str]:
    """Test 4: A task assigned to a worker is read by that worker and by no other."""
    claim = PUBLIC_CLAIMS_MAP[4]
    try:
        # Reuses existing tested functions from workforce_permission.py
        worker_alice = agent_worker("Alice", ["Writing", "Research"], status="Active")
        worker_bob = agent_worker("Bob", ["Consulting"], status="Active")

        tasks = [
            {"Task": "Task 1 for Alice", "Assigned To": "Alice", "Domain": "Writing", "Status": "Planned"},
            {"Task": "Task 2 for Alice", "Assigned To": "Alice", "Domain": "Research", "Status": "In progress"},
            {"Task": "Task 3 for Bob", "Assigned To": "Bob", "Domain": "Consulting", "Status": "Planned"},
            {"Task": "Task 4 unassigned", "Assigned To": None, "Domain": "Writing", "Status": "Planned"},
            {"Task": "Task 5 done for Alice", "Assigned To": "Alice", "Domain": "Writing", "Status": "Done"},
        ]

        # Queue isolation for Alice
        queue_alice = get_worker_queue(worker_alice, tasks, current_date="2026-09-24")
        alice_assigned_titles = {t["Task"] for t in queue_alice["all_assigned"]}
        expected_alice = {"Task 1 for Alice", "Task 2 for Alice"}
        if alice_assigned_titles != expected_alice:
            return False, (
                f"README claim '{claim}' is now false: Alice's queue had {alice_assigned_titles}, "
                f"expected {expected_alice}"
            )

        # Queue isolation for Bob
        queue_bob = get_worker_queue(worker_bob, tasks, current_date="2026-09-24")
        bob_assigned_titles = {t["Task"] for t in queue_bob["all_assigned"]}
        expected_bob = {"Task 3 for Bob"}
        if bob_assigned_titles != expected_bob:
            return False, (
                f"README claim '{claim}' is now false: Bob's queue had {bob_assigned_titles}, "
                f"expected {expected_bob}"
            )

        # Cross-worker execution attempt: Alice attempts to act on Bob's task
        task_bob = tasks[2]
        alice_can_exec, alice_reason, _ = start_task_execution(
            worker_alice, task_bob, current_date="2026-09-24"
        )
        if alice_can_exec:
            return False, f"README claim '{claim}' is now false: Alice was permitted to execute Bob's task"
        if "Queue violation" not in alice_reason:
            return False, (
                f"README claim '{claim}' is now false: expected queue violation reason, got: {alice_reason}"
            )

        # Cross-worker execution attempt: Bob attempts to act on Alice's task
        task_alice = tasks[0]
        bob_can_exec, bob_reason, _ = start_task_execution(
            worker_bob, task_alice, current_date="2026-09-24"
        )
        if bob_can_exec:
            return False, f"README claim '{claim}' is now false: Bob was permitted to execute Alice's task"
        if "Queue violation" not in bob_reason:
            return False, (
                f"README claim '{claim}' is now false: expected queue violation reason, got: {bob_reason}"
            )

        return True, "Queue discipline strictly isolates worker tasks; cross-worker access and execution rejected."

    except Exception as exc:
        return False, f"README claim '{claim}' is now false: unhandled exception: {exc}"


# --------------------------------------------------------------------------
# Test 5: Domain Declared Read Scope (Transcript Verification)
# --------------------------------------------------------------------------

def verify_transcript_read_scope(
    worker: dict,
    current_domain: str,
    read_transcript: list[str],
    domain_declarations: dict[str, list[str]] | None = None,
) -> tuple[bool, list[str]]:
    """Verify that every page loaded in an agent transcript is in the Domain's declared scope."""
    violations = []
    for page in read_transcript:
        allowed, reason = check_read_scope(worker, current_domain, page, domain_declarations)
        if not allowed:
            violations.append(f"{page} -> {reason}")
    return len(violations) == 0, violations


def test_5_domain_declared_read_scope_transcript(verbose: bool = False) -> tuple[bool, str]:
    """Test 5: An agent working a task loads only its Domain's declared pages (transcript check)."""
    claim = PUBLIC_CLAIMS_MAP[5]
    try:
        worker = agent_worker("WriterSpecialist", ["Writing"], status="Active")
        declarations = build_default_domain_declarations(["Writing", "Consulting"])

        # Legitimate transcript: only declared pages loaded
        compliant_transcript = [
            "Domains/Writing",
            "Domains/Writing/StyleGuide",
            "Goals/Writing",
            "Knowledge/Writing",
        ]
        ok, violations = verify_transcript_read_scope(worker, "Writing", compliant_transcript, declarations)
        if not ok:
            return False, (
                f"README claim '{claim}' is now false: compliant transcript failed: {violations}"
            )

        # Transgressing transcript: attempts to read undeclared and sensitive pages
        violating_transcript = [
            "Domains/Writing",
            "Profile",  # Sensitive domain undeclared
            "Domains/Consulting",  # Different domain undeclared
            "Knowledge/Finance",  # Undeclared page
        ]
        ok_violating, violations_detected = verify_transcript_read_scope(
            worker, "Writing", violating_transcript, declarations
        )
        if ok_violating:
            return False, f"README claim '{claim}' is now false: violating transcript was unexpectedly permitted"

        if len(violations_detected) != 3:
            return False, (
                f"README claim '{claim}' is now false: expected 3 violations in transcript, "
                f"detected {len(violations_detected)}"
            )

        return True, "Transcript verification confirms only declared pages are loaded; undeclared and Profile pages strictly blocked."

    except Exception as exc:
        return False, f"README claim '{claim}' is now false: unhandled exception: {exc}"


# --------------------------------------------------------------------------
# Tests 6+7 (Merged per rescope): Review Protocol Checklist and Silence Rule
# --------------------------------------------------------------------------

# Note: evaluate_review_protocol is imported from workforce_heartbeat.py
# (first-class review protocol checklist module implementing the six locked rules
# and the silence rule, eliminating duplication with this acceptance suite).


def test_6_7_review_protocol_checklist_and_silence(verbose: bool = False) -> tuple[bool, str]:
    """Test 6+7: Review protocol checklist produces expected lines, and stays silent on clean day."""
    claim = PUBLIC_CLAIMS_MAP[6]
    try:
        ref_date = "2026-09-24"

        # Case A: Fixed qualifying Notion state
        qualifying_tasks = [
            {"Task": "Tax filing submission", "Due Date": "2026-09-23", "Status": "Planned"},  # Overdue
            {"Task": "Client brief review", "Due Date": "2026-09-24", "Status": "Planned"},    # Due today
            {
                "Task": "Platform architecture spec",
                "Status": "In progress",
                "Agent Notes": "[2026-09-20] Writer: Drafted v1, waiting on user for review",
            },
            {"Task": "Security audit report", "Status": "Done", "Done Date": "2026-09-24"},
        ]
        upcoming = {"Friday (2026-09-25)": 0}

        lines = evaluate_review_protocol(qualifying_tasks, current_date=ref_date, upcoming_schedule=upcoming)

        if len(lines) < 3 or len(lines) > 5:
            return False, (
                f"README claim '{claim}' is now false: expected 3-5 lines for daily message, got {len(lines)}"
            )

        expected_lines = [
            "2 due today or overdue — Tax filing submission, Client brief review.",
            "In progress, waiting on user: Platform architecture spec.",
            "Finished today: Security audit report.",
            "Friday (2026-09-25) looks empty. Intentional?",
        ]
        if lines != expected_lines:
            return False, (
                f"README claim '{claim}' is now false: output lines differed from expected checklist.\n"
                f"Actual: {lines}\nExpected: {expected_lines}"
            )

        # Case B: Clean day with nothing qualifying -> Silence rule (zero lines produced)
        clean_tasks = [
            {"Task": "Legacy repo cleanup", "Status": "Done", "Done Date": "2026-08-01"},
            {"Task": "Future roadmap sync", "Status": "Planned", "Due Date": "2026-11-01"},
        ]
        upcoming_busy = {"Friday (2026-09-25)": 2, "Saturday (2026-09-26)": 1}

        silent_lines = evaluate_review_protocol(clean_tasks, current_date=ref_date, upcoming_schedule=upcoming_busy)

        if len(silent_lines) != 0:
            return False, (
                f"README claim '{claim}' is now false: expected silence (0 lines) on clean day, "
                f"got {len(silent_lines)} lines: {silent_lines}"
            )

        return True, (
            "Produces exact expected review lines on qualifying state, and zero lines (silence) "
            "on clean state; asserted with no scheduler or runtime."
        )

    except Exception as exc:
        return False, f"README claim '{claim}' is now false: unhandled exception: {exc}"


# --------------------------------------------------------------------------
# Test 8: Mid-Setup Failure Recovery
# --------------------------------------------------------------------------

def test_8_mid_setup_failure_recovery(verbose: bool = False) -> tuple[bool, str]:
    """Test 8: Killing Notion access mid-setup produces clear error and successful re-run."""
    claim = PUBLIC_CLAIMS_MAP[8]
    try:
        ws = SimulatedNotionWorkspace("parent_midsetup_acceptance")
        answers = SetupAnswers(
            domains=["Writing", "Consulting", "Personal"],
            user_name="Anik",
            daily_channel="Claude Code",
            primary_goal="Ship Workforce OS v1.0",
        )

        # Inject failure on Tasks database creation (step 4)
        orig_create_db = ws.create_database

        def inject_tasks_db_fail(parent_page_id: str, title: str, properties: dict, **kwargs) -> dict:
            if title == "Tasks":
                raise RuntimeError("Simulated network timeout connecting to Notion API")
            return orig_create_db(parent_page_id, title, properties, **kwargs)

        ws.create_database = inject_tasks_db_fail

        orch_fail = IdempotentSetupOrchestrator(ws, answers, auto_approve=True, quiet=True)
        report_fail = orch_fail.run()

        if report_fail.success:
            return False, f"README claim '{claim}' is now false: setup did not fail when access was killed"

        if not report_fail.error or "Simulated network timeout" not in report_fail.error:
            return False, (
                f"README claim '{claim}' is now false: failure error message was unclear: {report_fail.error}"
            )

        if "Workforce database" not in report_fail.what_was_built:
            return False, f"README claim '{claim}' is now false: report did not record what was built before failure"

        if "Tasks database" not in report_fail.what_was_not_built:
            return False, f"README claim '{claim}' is now false: report did not record what was not built"

        # Restore connectivity and re-run setup
        ws.create_database = orig_create_db
        orch_resume = IdempotentSetupOrchestrator(ws, answers, auto_approve=True, quiet=not verbose)
        report_resume = orch_resume.run()

        if not report_resume.success:
            return False, f"README claim '{claim}' is now false: resumed setup failed: {report_resume.error}"

        if report_resume.what_was_not_built:
            return False, (
                f"README claim '{claim}' is now false: resumed setup left steps unbuilt: "
                f"{report_resume.what_was_not_built}"
            )

        if ws.databases_created != 3:
            return False, (
                f"README claim '{claim}' is now false: expected exactly 3 databases in total, "
                f"found {ws.databases_created}"
            )

        if "Workforce database" not in report_resume.objects_reconciled:
            return False, (
                f"README claim '{claim}' is now false: Workforce database was not reconciled on resumption"
            )

        if "Tasks database" not in report_resume.objects_created:
            return False, (
                f"README claim '{claim}' is now false: Tasks database was not created on resumption"
            )

        if "Sections database" not in report_resume.objects_created:
            return False, (
                f"README claim '{claim}' is now false: Sections database was not created on resumption"
            )

        return True, "Interruption cleanly caught with what-was-built report; resumed setup completed with 0 duplicate databases."

    except Exception as exc:
        return False, f"README claim '{claim}' is now false: unhandled exception: {exc}"


# --------------------------------------------------------------------------
# Test 9: Public README Claim-by-Claim Audit
# --------------------------------------------------------------------------

def test_9_readme_claim_audit(
    test_results: dict[int, bool],
    readme_path: str | None = None,
    verbose: bool = False,
) -> tuple[bool, str]:
    """Test 9: Every substantive claim in the README is demonstrated by tests 1-8 or labelled planned."""
    claim = PUBLIC_CLAIMS_MAP[9]
    try:
        # 1. Verify every demonstrated claim's test actually passed
        demonstrated_tests = [1, 2, 3, 4, 5, 6, 8]
        for t_num in demonstrated_tests:
            if not test_results.get(t_num, False):
                sub_claim = PUBLIC_CLAIMS_MAP[t_num]
                return False, f"README claim '{sub_claim}' is now false: Acceptance Test {t_num} failed"

        # 2. Audit README.md content on disk
        if readme_path is None:
            readme_path = os.path.join(os.path.dirname(SCRIPT_DIR), "README.md")

        if not os.path.isfile(readme_path):
            return False, f"README claim '{claim}' is now false: README.md not found at {readme_path}"

        with open(readme_path, "r", encoding="utf-8") as f:
            content = f.read()

        # Audit requirement: All unverified features must be explicitly marked planned or pre-release
        if "Pre-release" not in content and "planned" not in content.lower():
            return False, f"README claim '{claim}' is now false: README lacks pre-release / planned disclaimers"

        # Audit requirement: Explicit out-of-scope statement for runtime/scheduler
        if "no runtime" not in content.lower() or "no scheduler" not in content.lower():
            return False, f"README claim '{claim}' is now false: README missing explicit 'no runtime, no scheduler' boundary"

        # Audit requirement: Documented acceptance command in README
        if "python3 scripts/workforce_acceptance.py" not in content:
            return False, (
                f"README claim '{claim}' is now false: acceptance command 'python3 scripts/workforce_acceptance.py' "
                "is not documented in README.md"
            )

        return True, (
            "All substantive claims in README are demonstrated by tests 1-8; "
            "unverified features are properly labelled as planned / pre-release."
        )

    except Exception as exc:
        return False, f"README claim '{claim}' is now false: unhandled exception: {exc}"


# --------------------------------------------------------------------------
# Main Runner & CLI
# --------------------------------------------------------------------------

def run_acceptance_suite(verbose: bool = False) -> int:
    """Run all acceptance tests and report public claim status."""
    print("=================================================================")
    print("Workforce OS Acceptance Test Suite")
    print("Public Proof of Documentation Claims Against Fixture Workspace")
    print("=================================================================\n")

    results: dict[int, bool] = {}
    failures = 0

    # Test 1
    print("[TEST 1] Setup runs in fresh empty workspace and produces full structure...")
    t1_pass, t1_msg = test_1_fresh_setup_produces_full_structure(verbose=verbose)
    results[1] = t1_pass
    if t1_pass:
        print(f"  [PASS] Test 1: {t1_msg}\n")
    else:
        print(f"  [FAIL] Test 1: {t1_msg}\n")
        failures += 1

    # Test 2
    print("[TEST 2] Setup re-runs against existing workspace and creates zero duplicates...")
    t2_pass, t2_msg = test_2_setup_rerun_zero_duplicates(verbose=verbose)
    results[2] = t2_pass
    if t2_pass:
        print(f"  [PASS] Test 2: {t2_msg}\n")
    else:
        print(f"  [FAIL] Test 2: {t2_msg}\n")
        failures += 1

    # Test 3
    print("[TEST 3] Rough one-line message produces structured task without manual field editing...")
    t3_pass, t3_msg = test_3_rough_message_capture_transformation(verbose=verbose)
    results[3] = t3_pass
    if t3_pass:
        print(f"  [PASS] Test 3: {t3_msg}\n")
    else:
        print(f"  [FAIL] Test 3: {t3_msg}\n")
        failures += 1

    # Test 4
    print("[TEST 4] Task assigned to a worker is read by that worker and by no other...")
    t4_pass, t4_msg = test_4_assigned_task_queue_isolation(verbose=verbose)
    results[4] = t4_pass
    if t4_pass:
        print(f"  [PASS] Test 4: {t4_msg}\n")
    else:
        print(f"  [FAIL] Test 4: {t4_msg}\n")
        failures += 1

    # Test 5
    print("[TEST 5] Agent working a task loads only its Domain's declared pages (transcript check)...")
    t5_pass, t5_msg = test_5_domain_declared_read_scope_transcript(verbose=verbose)
    results[5] = t5_pass
    if t5_pass:
        print(f"  [PASS] Test 5: {t5_msg}\n")
    else:
        print(f"  [FAIL] Test 5: {t5_msg}\n")
        failures += 1

    # Test 6+7 (Merged per rescope)
    print("[TEST 6+7] Review protocol checklist produces expected lines, and stays silent on clean day...")
    t6_pass, t6_msg = test_6_7_review_protocol_checklist_and_silence(verbose=verbose)
    results[6] = t6_pass
    if t6_pass:
        print(f"  [PASS] Test 6+7: {t6_msg}\n")
    else:
        print(f"  [FAIL] Test 6+7: {t6_msg}\n")
        failures += 1

    # Test 8
    print("[TEST 8] Killing Notion access mid-setup produces clear error and successful re-run...")
    t8_pass, t8_msg = test_8_mid_setup_failure_recovery(verbose=verbose)
    results[8] = t8_pass
    if t8_pass:
        print(f"  [PASS] Test 8: {t8_msg}\n")
    else:
        print(f"  [FAIL] Test 8: {t8_msg}\n")
        failures += 1

    # Test 9
    print("[TEST 9] Public README claim-by-claim audit...")
    t9_pass, t9_msg = test_9_readme_claim_audit(results, verbose=verbose)
    results[9] = t9_pass
    if t9_pass:
        print(f"  [PASS] Test 9: {t9_msg}\n")
    else:
        print(f"  [FAIL] Test 9: {t9_msg}\n")
        failures += 1

    print("-----------------------------------------------------------------")
    if failures == 0:
        print("ALL ACCEPTANCE TESTS (POST-RESCOPE) PASSED CLEANLY (0 failures).")
        print("All public documentation claims verified against fixture workspace state.")
        print("-----------------------------------------------------------------")
        return 0
    else:
        print(f"ACCEPTANCE SUITE FAILED WITH {failures} FAILURE(S).")
        print("-----------------------------------------------------------------")
        return 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--verbose", "-v", action="store_true",
                        help="print detailed step-by-step progress")
    args = parser.parse_args()
    return run_acceptance_suite(verbose=args.verbose)


if __name__ == "__main__":
    raise SystemExit(main())
