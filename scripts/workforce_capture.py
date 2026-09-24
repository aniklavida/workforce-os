#!/usr/bin/env python3
"""Workforce OS capture, structuring, idempotency, and assignment routing.

Architecture context:
  Workforce OS ships NO RUNTIME (locked decision in docs/ARCHITECTURE.md).
  In live use, rough messages are transformed into structured tasks by
  whichever connected agent runs commands/capture.md, using its own reasoning
  against AGENTS.md.

  This module provides:
  1. The deterministic fixture stand-in for documented capture examples
     (AGENTS.md section 2 and skills/workforce-operate/SKILL.md).
  2. The mechanical idempotency harness: verifying that repeating an identical
     capture against a workspace produces ZERO duplicate rows and ZERO
     repeated rounds of chat questions.
  3. Strict assignment routing through the shared three-layer permission gate
     in workforce_permission.py (can_assign and assignment_blockers).
  4. Nonexistent specialist handling: plainly stating when no active specialist
     covers a domain and strictly refusing to fall back to the Assistant or
     silently complete the task.

Usage:
  python3 scripts/workforce_capture.py --self-test
  python3 scripts/workforce_capture.py --dry-run
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass, field
from datetime import datetime, timezone
import os
import sys
from typing import Any, Callable

# Ensure script directory is on sys.path
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
if SCRIPT_DIR not in sys.path:
    sys.path.insert(0, SCRIPT_DIR)

import workforce_permission


@dataclass
class CaptureResult:
    """Outcome of an idempotent capture attempt."""

    task: dict[str, Any]
    created: bool
    duplicate_detected: bool
    questions_asked: list[str]
    explanation: str
    ordering_trace: list[str] = field(default_factory=list)


@dataclass
class AssignmentResult:
    """Outcome of routing a captured task to an assignable worker."""

    assigned: bool
    worker_name: str | None
    reason: str
    task: dict[str, Any]
    blockers_evaluated: dict[str, list[str]] = field(default_factory=dict)


def capture_and_structure_thought(
    raw_message: str,
    available_domains: list[str],
    user_name: str = "Anik",
    current_date: str = "2026-09-24",
) -> dict[str, Any]:
    """Transform rough user input into a structured task record under AGENTS.md rule 2.

    Fixture-only stand-in for agent reasoning over documented examples.
    """
    clean = raw_message.strip()
    lower = clean.lower()

    # Documented capture example 1: AGENTS.md section 2
    if "telegram" in lower or "amazon" in lower:
        task_title = "Apply for an Amazon Associates affiliate account"
        next_action = "Apply for an Amazon Associates affiliate account; add eBay and Etsy once approved."
        done_when = "Amazon affiliate approved and able to generate links."
        domain = "Writing" if "Writing" in available_domains else available_domains[0]
        priority = "High"
    # Documented capture example 2: skills/workforce-operate/SKILL.md
    elif "company registration" in lower:
        task_title = "Register the company"
        next_action = "Confirm the registration fee and start the filing"
        done_when = "Registration certificate in hand"
        domain = "Consulting" if "Consulting" in available_domains else available_domains[0]
        priority = "High"
    else:
        task_title = clean.capitalize()
        next_action = f"Clarify initial step and execute {task_title}"
        done_when = f"Completion criteria met for {task_title}"
        domain = available_domains[0] if available_domains else "Unassigned"
        priority = "Medium"

    return {
        "Task": task_title,
        "Next Action": next_action,
        "Done When": done_when,
        "Domain": domain,
        "Priority": priority,
        "Status": "Planned",
        "Type": "Task",
        "Start Date": current_date,
        "Due Date": None,
        "Notes": "",  # User only — agents never write here
        "Agent Notes": f"[{current_date}] Assistant: Structured rough thought into actionable task without manual field editing.",
    }


def capture_thought_idempotent(
    raw_message: str,
    tasks_database: list[dict[str, Any]],
    chat_history: list[str] | None = None,
    available_domains: list[str] | None = None,
    user_name: str = "Anik",
    current_date: str = "2026-09-24",
    candidate_questions: list[str] | None = None,
) -> CaptureResult:
    """Capture a rough thought idempotently into the tasks database.

    Enforces:
      1. Idempotency check: if thought was already captured, 0 duplicate rows
         and 0 repeated questions are produced.
      2. Ordering discipline: create-first (initial row created immediately),
         complete-second (inferred fields completed afterwards).
      3. Communication channel: questions live in chat, never in Notion fields.
      4. Question bundling: 1-3 short questions asked at most, never repeated.
      5. User notes invariant: 'Notes' is strictly user-only; agents write to
         'Agent Notes'.
    """
    clean = raw_message.strip()
    domains = available_domains or ["Writing", "Consulting", "Personal"]

    # 1. Deduplication check against existing tasks in workspace
    for existing_task in tasks_database:
        raw_source = existing_task.get("_raw_thought")
        agent_notes = existing_task.get("Agent Notes") or ""
        captured_marker = f"Captured thought: {clean}"

        if raw_source == clean or captured_marker in agent_notes:
            return CaptureResult(
                task=existing_task,
                created=False,
                duplicate_detected=True,
                questions_asked=[],
                explanation=(
                    f"Thought {clean!r} is already captured; zero duplicate rows created "
                    f"and zero repeated questions asked."
                ),
                ordering_trace=["check_existing", "duplicate_detected"],
            )

    # 2. Create-first: create row immediately with whatever was given
    ordering_trace = ["check_existing", "create_first"]
    initial_row: dict[str, Any] = {
        "Task": clean,
        "Status": "Planned",
        "Domain": None,
        "Notes": "",  # Strictly user only
        "Agent Notes": f"[{current_date}] Captured thought: {clean}",
        "_raw_thought": clean,
        "_stage": "create_first",
    }

    # 3. Infer what you safely can
    ordering_trace.append("infer_structured_values")
    structured = capture_and_structure_thought(
        clean,
        domains,
        user_name=user_name,
        current_date=current_date,
    )

    # 4. Clarification questions in chat (never in Notion)
    questions_to_ask: list[str] = []
    if candidate_questions:
        # Bundle 1 to 3 short questions (AGENTS.md rule 4)
        for q in candidate_questions[:3]:
            q_clean = q.strip()
            if chat_history is not None:
                if q_clean not in chat_history:
                    questions_to_ask.append(q_clean)
                    chat_history.append(q_clean)
            else:
                questions_to_ask.append(q_clean)

    # 5. Complete-second: populate inferred fields onto the created row
    ordering_trace.append("complete_second")
    initial_row.update(structured)
    initial_row["_raw_thought"] = clean
    initial_row["_stage"] = "completed"
    initial_row["Notes"] = ""  # Enforce note boundary invariant

    tasks_database.append(initial_row)

    return CaptureResult(
        task=initial_row,
        created=True,
        duplicate_detected=False,
        questions_asked=questions_to_ask,
        explanation=f"New thought captured as structured task '{initial_row['Task']}'.",
        ordering_trace=ordering_trace,
    )


def assign_captured_task(
    task: dict[str, Any],
    available_workers: list[dict[str, Any]],
    chat_messages: list[str] | None = None,
) -> AssignmentResult:
    """Route a captured task to an eligible worker through the shared assignment gate.

    Enforces:
      1. Task readiness check: Next action, Done When, and Domain must be known.
      2. Role separation: Assistant and Advisor never perform specialist execution work.
         Assistant assigns; Specialist executes.
      3. Shared permission gate: Every candidate specialist is evaluated strictly
         using workforce_permission.can_assign and assignment_blockers.
      4. Sensitive Profile domain: Requires explicit, loggable grant.
      5. No-specialist-exists path: If no active worker passes the gate, state so
         plainly in chat and offer to add a Worker row. Never assign to Assistant.
         Never quietly do the work itself.
    """
    task_title = task.get("Task") or task.get("title") or "Untitled task"
    task_domain = task.get("Domain") or task.get("domain")
    next_action = task.get("Next Action")
    done_when = task.get("Done When")

    # 1. Task readiness check (commands/assign.md step 1)
    if not task_title or not task_domain or not next_action or not done_when:
        reason = (
            f"Task '{task_title}' is not assignable yet: definition incomplete "
            f"(domain={bool(task_domain)}, next_action={bool(next_action)}, done_when={bool(done_when)})."
        )
        if chat_messages is not None:
            chat_messages.append(reason)
        return AssignmentResult(
            assigned=False,
            worker_name=None,
            reason=reason,
            task=task,
        )

    # 2. Evaluate candidates using the shared assignment gate from workforce_permission.py
    blockers_evaluated: dict[str, list[str]] = {}
    eligible_specialists: list[dict[str, Any]] = []

    for worker in available_workers:
        w_name = worker.get("worker") or worker.get("name") or "Unknown"
        w_role = worker.get("role", "Specialist")

        # Assistant and Advisor never do specialist work (AGENTS.md section 6)
        if w_role in ("Assistant", "Advisor"):
            blockers_evaluated[w_name] = [
                f"role is {w_role!r}; {w_role} never performs specialist execution work"
            ]
            continue

        # Invoke shared assignment gate from workforce_permission
        blockers = list(workforce_permission.assignment_blockers(worker, task_domain))

        # Check Profile domain loggable grant if task is in Profile domain
        if task_domain == "Profile" and not workforce_permission.is_profile_domain_granted(worker):
            blockers.append(
                "Profile domain requires an explicit, loggable grant with named author and stated reason"
            )

        blockers_evaluated[w_name] = blockers

        if not blockers:
            eligible_specialists.append(worker)

    # 3. Handle when no specialist exists (commands/assign.md line 15)
    if not eligible_specialists:
        plain_reason = (
            f"No specialist exists for domain '{task_domain}'. "
            f"Work remains unassigned in queue. Offer to add a Worker row from Notion. "
            f"Do not assign it to the assistant. Do not quietly do it yourself."
        )
        if chat_messages is not None:
            chat_messages.append(plain_reason)

        task["Assigned To"] = None
        task["Status"] = "Planned"  # Strictly never quietly started or completed

        return AssignmentResult(
            assigned=False,
            worker_name=None,
            reason=plain_reason,
            task=task,
            blockers_evaluated=blockers_evaluated,
        )

    # 4. Assign to eligible specialist
    chosen_worker = eligible_specialists[0]
    chosen_name = chosen_worker.get("worker") or chosen_worker.get("name") or "Unknown"
    task["Assigned To"] = chosen_name
    task["Agent Notes"] = workforce_permission.append_agent_note(
        task.get("Agent Notes"),
        "Assistant",
        f"Assigned to {chosen_name} ({chosen_worker.get('role', 'Specialist')})",
    )

    success_msg = f"Task '{task_title}' assigned to worker '{chosen_name}'."
    if chat_messages is not None:
        chat_messages.append(success_msg)

    return AssignmentResult(
        assigned=True,
        worker_name=chosen_name,
        reason=success_msg,
        task=task,
        blockers_evaluated=blockers_evaluated,
    )


# --------------------------------------------------------------------------
# Named Tests
# --------------------------------------------------------------------------

def test_capture_idempotency_zero_duplicate_rows_and_zero_repeated_questions() -> tuple[bool, str]:
    """Test idempotency: a repeated identical capture produces 0 duplicate rows and 0 repeated questions."""
    tasks_db: list[dict[str, Any]] = []
    chat_history: list[str] = []
    raw_message = "the telegram deal thing — think amazon approval comes first"
    clarifications = ["Confirm preferred affiliate link formats?"]

    # First capture: creates task, asks clarification question in chat
    res1 = capture_thought_idempotent(
        raw_message,
        tasks_db,
        chat_history=chat_history,
        candidate_questions=clarifications,
    )

    if not res1.created:
        return False, "Initial capture failed: task was not created"
    if len(tasks_db) != 1:
        return False, f"Expected 1 task in database after first capture, got {len(tasks_db)}"
    if len(res1.questions_asked) != 1:
        return False, f"Expected 1 question asked on first capture, got {len(res1.questions_asked)}"
    if res1.ordering_trace != ["check_existing", "create_first", "infer_structured_values", "complete_second"]:
        return False, f"Create-first, complete-second ordering violated: {res1.ordering_trace}"
    if res1.task.get("Notes") != "":
        return False, "User-only Notes field was modified by agent"

    # Second capture: identical message against fixture workspace with existing task
    res2 = capture_thought_idempotent(
        raw_message,
        tasks_db,
        chat_history=chat_history,
        candidate_questions=clarifications,
    )

    if res2.created:
        return False, "Idempotency broken: second capture created a duplicate task"
    if not res2.duplicate_detected:
        return False, "Idempotency broken: duplicate capture was not detected"
    if len(tasks_db) != 1:
        return False, f"Idempotency broken: expected 1 task in database, found {len(tasks_db)}"
    if len(res2.questions_asked) != 0:
        return False, (
            f"Idempotency broken: expected 0 repeated questions, got {len(res2.questions_asked)}: "
            f"{res2.questions_asked}"
        )
    if len(chat_history) != 1:
        return False, f"Idempotency broken: chat history duplicated questions, found {len(chat_history)}"

    return True, (
        "Re-running capture on identical message produced 0 duplicate rows and 0 repeated questions; "
        "ordering strictly verified as create-first, complete-second."
    )


def test_assignment_routes_through_shared_permission_gate() -> tuple[bool, str]:
    """Test that assignment in the fixture path strictly routes through workforce_permission.py."""
    from workforce_schema import agent_worker, human_worker
    from workforce_permission import grant_domain

    workers = [
        agent_worker("Alice", ["Writing"], status="Active"),
        agent_worker("Bob", ["Writing"], status="Paused"),
        agent_worker("Charlie", []),
        agent_worker("Dave", ["Consulting"], status="Active"),
        human_worker("Anik", ["Writing"]),
    ]

    target_domain = "Writing"
    task = {
        "Task": "Draft whitepaper introduction",
        "Next Action": "Write outline section 1",
        "Done When": "Outline approved",
        "Domain": target_domain,
        "Status": "Planned",
    }

    # Verify that assignment helper evaluates candidates using the exact shared blockers
    res = assign_captured_task(task, workers)
    if not res.assigned or res.worker_name != "Alice":
        return False, f"Expected Alice to be assigned, got {res.worker_name} (assigned={res.assigned})"

    for w in workers:
        w_name = w["worker"]
        shared_blockers = workforce_permission.assignment_blockers(w, target_domain)
        evaluated_blockers = res.blockers_evaluated.get(w_name)
        if evaluated_blockers != shared_blockers:
            return False, (
                f"Gate drift detected for worker '{w_name}': fixture evaluated {evaluated_blockers}, "
                f"shared assignment_blockers returned {shared_blockers}"
            )

    # Prove that the helper actually calls assignment_blockers by verifying invocation
    called_workers: list[str] = []
    orig_blockers = workforce_permission.assignment_blockers

    def spy_blockers(worker: dict, domain: str) -> list[str]:
        called_workers.append(worker.get("worker") or worker.get("name") or "")
        return orig_blockers(worker, domain)

    try:
        workforce_permission.assignment_blockers = spy_blockers
        res_spy = assign_captured_task(copy_task := dict(task), workers)
        if not called_workers:
            return False, "Fixture assignment path bypassed workforce_permission.assignment_blockers"
    finally:
        workforce_permission.assignment_blockers = orig_blockers

    return True, (
        "Assignment in fixture path strictly invokes and honors shared assignment_blockers "
        "from workforce_permission; zero logic drift across all candidate states."
    )


def test_nonexistent_specialist_states_plainly_and_refuses_assistant_fallback() -> tuple[bool, str]:
    """Test that when no specialist exists, the failure is stated plainly and Assistant is never assigned."""
    from workforce_schema import agent_worker, assistant_worker

    # Workspace with an Assistant and a Specialist for Writing, but NO specialist for Engineering
    workers = [
        assistant_worker("GeneralAssistant", domains=["Engineering", "Writing", "Consulting"]),
        agent_worker("WritingSpecialist", domains=["Writing"], status="Active"),
    ]

    engineering_task = {
        "Task": "Build database schema migration script",
        "Next Action": "Write idempotent SQL migration",
        "Done When": "Migration script verified against test database",
        "Domain": "Engineering",
        "Status": "Planned",
    }

    chat_messages: list[str] = []
    res = assign_captured_task(engineering_task, workers, chat_messages=chat_messages)

    if res.assigned:
        return False, f"Task was assigned when no specialist existed: {res.worker_name}"

    if engineering_task.get("Assigned To") is not None:
        return False, (
            f"Assigned To must be None when no specialist exists, got {engineering_task.get('Assigned To')}"
        )

    if engineering_task.get("Status") != "Planned":
        return False, (
            f"Task Status must remain 'Planned' (never quietly started or done), got {engineering_task.get('Status')}"
        )

    if "No specialist exists for domain 'Engineering'" not in res.reason:
        return False, (
            f"Reason did not plainly state that no specialist exists: {res.reason}"
        )

    if not any("No specialist exists for domain 'Engineering'" in msg for msg in chat_messages):
        return False, "Plain statement was not communicated in chat messages"

    if "Do not assign it to the assistant" not in res.reason:
        return False, "Reason failed to cite assistant non-fallback rule"

    return True, (
        "Nonexistent specialist plainly reported; task remains unassigned in queue and "
        "is strictly never assigned to Assistant or quietly completed."
    )


# --------------------------------------------------------------------------
# Self-Test Runner & CLI
# --------------------------------------------------------------------------

def run_self_test() -> int:
    """Run self-tests proving capture idempotency and assignment gate integration."""
    print("=================================================================")
    print("Running Workforce OS Capture & Assignment Self-Tests...")
    print("=================================================================\n")

    cases = [
        ("Capture idempotency (0 duplicate rows, 0 repeated questions)", test_capture_idempotency_zero_duplicate_rows_and_zero_repeated_questions),
        ("Assignment routes strictly through shared permission gate", test_assignment_routes_through_shared_permission_gate),
        ("Nonexistent specialist states plainly & refuses Assistant assignment", test_nonexistent_specialist_states_plainly_and_refuses_assistant_fallback),
    ]

    failures = 0
    for name, test_fn in cases:
        ok, msg = test_fn()
        if ok:
            print(f"  [PASS] {name}: {msg}\n")
        else:
            print(f"  [FAIL] {name}: {msg}\n")
            failures += 1

    print("-----------------------------------------------------------------")
    if failures == 0:
        print(f"ALL {len(cases)} CAPTURE & ASSIGNMENT SELF-TEST CASES PASSED CLEANLY (0 failures).")
        print("Idempotency, shared gate integration, and specialist boundaries proven.")
        print("-----------------------------------------------------------------")
        return 0
    else:
        print(f"CAPTURE SUITE FAILED WITH {failures} FAILURE(S).")
        print("-----------------------------------------------------------------")
        return 1


def dry_run_preview() -> dict[str, Any]:
    """Produce a dry-run preview of capture idempotency and assignment routing."""
    tasks_db: list[dict[str, Any]] = []
    chat_log: list[str] = []

    res1 = capture_thought_idempotent(
        "the telegram deal thing — think amazon approval comes first",
        tasks_db,
        chat_history=chat_log,
        candidate_questions=["Clarify affiliate commission tier?"],
    )

    res2 = capture_thought_idempotent(
        "the telegram deal thing — think amazon approval comes first",
        tasks_db,
        chat_history=chat_log,
        candidate_questions=["Clarify affiliate commission tier?"],
    )

    from workforce_schema import agent_worker, assistant_worker
    workers = [
        assistant_worker("OrchestratorAssistant", domains=["Writing", "Personal"]),
        agent_worker("AffiliateSpecialist", domains=["Writing"], status="Active"),
    ]
    assign_res = assign_captured_task(res1.task, workers, chat_messages=chat_log)

    return {
        "initial_capture_created": res1.created,
        "second_capture_created": res2.created,
        "duplicate_detected": res2.duplicate_detected,
        "tasks_in_database": len(tasks_db),
        "questions_in_chat": len(chat_log),
        "assigned_to": assign_res.worker_name,
        "assignment_status": assign_res.reason,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Workforce OS capture & assignment harness")
    parser.add_argument("--self-test", action="store_true", help="Run capture & assignment self-tests")
    parser.add_argument("--dry-run", action="store_true", help="Preview idempotent capture and assignment")
    args = parser.parse_args()

    if args.self_test:
        return run_self_test()

    if args.dry_run:
        preview = dry_run_preview()
        import json
        print(json.dumps(preview, indent=2))
        return 0

    parser.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())
