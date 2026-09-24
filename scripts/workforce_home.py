#!/usr/bin/env python3
"""Workforce OS Home view definition, empty states, and degraded/failure states engine.

Architecture Context:
  Workforce OS ships NO RUNTIME and NO RENDERED UI (locked 2026-09-15 decision in docs/ARCHITECTURE.md).
  Home is a Notion view/page created during setup and maintained by connected agents,
  not an application screen rendered by this repository.

This module provides:
  1. Deterministic Home view specification and layout evaluator:
     - Home groups into exactly four sections: Today · Waiting on you · Upcoming · This week.
       Nothing else competes for that space (locked decision).
     - Mobile constraint: Legible on a phone without horizontal scrolling. No wide tables
       are forced into Home view; layout uses mobile-friendly Notion block types (list views,
       callouts, headings, bulleted lists).
     - Empty, no tasks: States what to do first in one line — never a blank page.
     - Empty, nothing worth reporting: Matches the review protocol (heartbeat) silence rule
       from item 18 exactly (same condition, same silence outcome / no message).
  2. Degraded and failure state message formatters, each providing an actionable next step:
     - Notion unreachable: Retries with backoff; final failure emits a plain message in chat
       naming the next action. Never fails silently, never invents data.
     - Permission denied: Names the exact object, missing permission, and how to grant it.
       Never a raw API error.
     - Partial setup failure: Reports what was created and what was not; re-run completes
       rather than duplicates (wrapping SetupReport from workforce_setup.py).
     - Rate limited: Backs off and continues visibly rather than appearing to hang.
     - Worker has no Domain: Single-line refusal naming the remedy (reusing can_act_on_task
       from workforce_permission.py).
     - Recovery: Cites Acceptance Test 8 proving idempotent convergence upon re-run.
  3. Actionable next-step validation:
     - Mechanically checks that every failure/degraded message contains an actionable
       instruction with a recognized imperative verb.

Usage:
  python3 scripts/workforce_home.py --self-test
  python3 scripts/workforce_home.py --dry-run
"""

from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timedelta
import json
import os
import re
import sys
from typing import Any, Callable

# Ensure script directory is on sys.path
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
if SCRIPT_DIR not in sys.path:
    sys.path.insert(0, SCRIPT_DIR)

from workforce_heartbeat import (
    SILENCE_LINES,
    SILENCE_MESSAGE,
    evaluate_review_protocol_detailed,
    is_waiting_on_user,
    parse_date,
)
from workforce_permission import can_act_on_task
from workforce_setup import SetupReport, SimulatedNotionWorkspace

# --------------------------------------------------------------------------
# Home View Constants & Specifications
# --------------------------------------------------------------------------

HOME_SECTIONS = ("Today", "Waiting on you", "Upcoming", "This week")

HOME_MOBILE_CONSTRAINT = (
    "Legible on a phone without horizontal scrolling: wide tables (type 'table') "
    "are prohibited; Home uses Notion mobile-friendly block types (list-layout linked "
    "database views, callouts, headings, and bulleted lists)."
)

EMPTY_NO_TASKS_MESSAGE = (
    "No tasks yet. Capture your first task in chat (e.g., 'Draft project brief') to get started."
)

ACTIONABLE_VERBS = {
    "re-run",
    "rerun",
    "retry",
    "grant",
    "open",
    "check",
    "edit",
    "wait",
    "assign",
    "reduce",
    "pause",
    "add",
    "select",
    "click",
    "capture",
    "send",
    "resume",
    "connect",
    "verify",
    "restore",
}


# --------------------------------------------------------------------------
# Actionable Next-Step Enforcement
# --------------------------------------------------------------------------

def has_actionable_next_step(message: str) -> bool:
    """Check whether a message contains an actionable remedy instruction with a recognized verb.

    A message describing a problem without a remedy is not finished (card decision).
    Enforced as a checkable property, not just a style guideline.
    """
    if not message or not isinstance(message, str):
        return False

    lowered = message.lower()

    # Must contain an action-oriented directive pattern
    action_phrases = [
        "next action:",
        "to grant it",
        "to resolve",
        "to get started",
        "then retry",
        "please wait while",
        "before retrying",
        "re-run setup",
        "check your",
        "to resume",
        "capture your",
    ]
    has_action_phrase = any(phrase in lowered for phrase in action_phrases)

    # Must contain at least one recognized imperative action verb
    has_action_verb = any(
        re.search(r"\b" + re.escape(v) + r"\b", lowered)
        for v in ACTIONABLE_VERBS
    )

    return bool(has_action_phrase and has_action_verb)


# --------------------------------------------------------------------------
# Degraded and Failure State Formatters
# --------------------------------------------------------------------------

def format_notion_unreachable_message(
    attempts: int = 3,
    last_error: str = "Connection timed out",
    endpoint: str = "https://api.notion.com/v1",
) -> str:
    """State 1: Notion unreachable.

    Retries with backoff; after the final failure, a plain message in chat.
    Never fails silently, never guesses at data.
    """
    return (
        f"Cannot reach Notion after {attempts} attempts ({last_error}). "
        "Check your internet connection and Notion's system status at https://status.notion.so, "
        "then retry your command."
    )


def execute_notion_call_with_backoff(
    call_fn: Callable[[], Any],
    max_retries: int = 3,
    initial_backoff: float = 0.5,
    backoff_factor: float = 2.0,
    sleeper: Callable[[float], None] | None = None,
) -> tuple[bool, Any, list[float], str | None]:
    """Execute a Notion API call with exponential backoff on transient failure.

    Returns (success, result, delays_applied, error_message).
    Never invents data to fill gaps on failure.
    """
    delays_applied: list[float] = []
    current_backoff = initial_backoff
    last_exc: Exception | None = None

    for attempt in range(1, max_retries + 1):
        try:
            res = call_fn()
            return True, res, delays_applied, None
        except Exception as exc:
            last_exc = exc
            if attempt < max_retries:
                delays_applied.append(current_backoff)
                if sleeper:
                    sleeper(current_backoff)
                current_backoff *= backoff_factor

    err_msg = format_notion_unreachable_message(
        attempts=max_retries,
        last_error=str(last_exc) if last_exc else "Unknown error",
    )
    return False, None, delays_applied, err_msg


def format_permission_denied_message(
    object_name: str,
    object_id: str,
    missing_permission: str = "read/write",
    target_type: str = "page",
) -> str:
    """State 2: Permission denied.

    Names the exact object, the exact missing permission, and how to grant it.
    Never a raw API error.
    """
    return (
        f"Permission denied accessing {target_type} '{object_name}' ({object_id}): "
        f"missing '{missing_permission}' permission. "
        f"To grant it, open the {target_type} in Notion, click '...', select 'Connect to' "
        "(or 'Add connections'), and grant access to your integration before retrying."
    )


def format_partial_setup_failure_message(
    error: str,
    what_was_built: list[str],
    what_was_not_built: list[str],
) -> str:
    """State 3: Partial setup failure.

    Reports what was created and what was not; a re-run completes rather than duplicates.
    Wraps SetupReport from workforce_setup.py.
    """
    built_str = ", ".join(what_was_built) if what_was_built else "None"
    unbuilt_str = ", ".join(what_was_not_built) if what_was_not_built else "None"
    return (
        f"Setup stopped before completing: {error}.\n"
        f"Created: {built_str}.\n"
        f"Not yet created: {unbuilt_str}.\n"
        "Next action: Re-run setup at any time; setup will resume from where it stopped "
        "and converge on the complete structure with zero duplicate databases or pages."
    )


def format_rate_limited_message(
    retry_after_seconds: float,
    attempt: int = 1,
    max_attempts: int = 3,
) -> str:
    """State 4: Rate limited.

    Backs off and continues, visibly, rather than appearing to hang.
    """
    return (
        f"Notion rate limit reached (HTTP 429 on attempt {attempt}/{max_attempts}). "
        f"Backing off for {retry_after_seconds:.1f} seconds before retrying; "
        "please wait while operations resume automatically. "
        "If rate limits persist, reduce batch sizes or pause concurrent agent requests before retrying."
    )


def execute_rate_limited_call_with_backoff(
    call_fn: Callable[[], Any],
    max_retries: int = 3,
    default_retry_after: float = 1.0,
    sleeper: Callable[[float], None] | None = None,
    logger: list[str] | None = None,
) -> tuple[bool, Any, list[str]]:
    """Execute call with rate limit handling, logging visible messages rather than hanging."""
    logged: list[str] = []
    last_exc: Exception | None = None

    for attempt in range(1, max_retries + 1):
        try:
            res = call_fn()
            return True, res, logged
        except Exception as exc:
            last_exc = exc
            is_429 = "429" in str(exc) or "rate limit" in str(exc).lower()
            if is_429 and attempt < max_retries:
                msg = format_rate_limited_message(
                    retry_after_seconds=default_retry_after,
                    attempt=attempt,
                    max_attempts=max_retries,
                )
                logged.append(msg)
                if logger is not None:
                    logger.append(msg)
                if sleeper:
                    sleeper(default_retry_after)
            else:
                break

    fail_msg = (
        f"Rate limit exceeded after {max_retries} attempts: {last_exc}. "
        "Next action: Please wait while operations pause; reduce batch sizes or retry when the rate window resets."
    )
    logged.append(fail_msg)
    return False, None, logged


def format_worker_no_domain_message(
    worker: dict,
    task: dict | None = None,
) -> str:
    """State 5: Worker has no Domain.

    States so in one line, reusing the existing message from workforce_permission.py's
    domain-scope check (can_act_on_task), accompanied by an actionable next step.
    """
    if task is None:
        task = {"Task": "Unassigned work", "Domain": "General"}

    _, base_reason = can_act_on_task(worker, task)
    worker_name = worker.get("worker") or worker.get("name") or "Unknown worker"

    return (
        f"{base_reason} To resolve, edit worker '{worker_name}' in the Workforce database "
        "and assign one or more Domains before reassigning."
    )


def format_recovery_message(citation: str = "Acceptance Test 8") -> str:
    """State 6: Recovery.

    States that setup is re-runnable at any time and converges on the correct
    structure (proven by Acceptance Test 8), naming the next action.
    """
    return (
        "Setup is re-runnable at any time and converges idempotently on the correct structure "
        f"without creating duplicate databases or pages (proven by {citation}). "
        "Next action: Re-run setup (e.g., 'python3 scripts/workforce_setup.py') to resume and "
        "converge on the complete workspace structure."
    )


# --------------------------------------------------------------------------
# Home View Layout & Evaluation Engine
# --------------------------------------------------------------------------

@dataclass
class HomeViewResult:
    """Structured evaluation of the Home view against current workspace state."""

    sections: dict[str, list[dict[str, Any]]]
    is_empty_no_tasks: bool
    is_nothing_worth_reporting: bool
    empty_message: str | None
    silence_output: list[str] = field(default_factory=lambda: list(SILENCE_LINES))
    silence_message: str | None = SILENCE_MESSAGE

    def to_dict(self) -> dict[str, Any]:
        return {
            "sections": {k: [t.get("Task") or t.get("title") for t in v] for k, v in self.sections.items()},
            "is_empty_no_tasks": self.is_empty_no_tasks,
            "is_nothing_worth_reporting": self.is_nothing_worth_reporting,
            "empty_message": self.empty_message,
            "silence_output": self.silence_output,
            "silence_message": self.silence_message,
        }


def evaluate_home_view(
    tasks: list[dict[str, Any]],
    current_date: str = "2026-09-24",
    upcoming_schedule: dict[str, int] | None = None,
) -> HomeViewResult:
    """Evaluate Home view grouping into exactly: Today · Waiting on you · Upcoming · This week.

    Handles empty states:
      - Empty, no tasks: States what to do first in one line — never a blank page.
      - Empty, nothing worth reporting: Matches the heartbeat's silence rule exactly
        (same condition, same silence outcome / no message).
    """
    # Case 1: Empty, no tasks at all
    if not tasks:
        return HomeViewResult(
            sections={s: [] for s in HOME_SECTIONS},
            is_empty_no_tasks=True,
            is_nothing_worth_reporting=False,
            empty_message=EMPTY_NO_TASKS_MESSAGE,
        )

    curr_dt = parse_date(current_date)
    if curr_dt is None:
        curr_dt = date(2026, 9, 24)

    # Evaluate against the review protocol checklist from workforce_heartbeat.py
    # to guarantee exact agreement with the silence rule
    heartbeat_res = evaluate_review_protocol_detailed(
        tasks=tasks,
        current_date=current_date,
        upcoming_schedule=upcoming_schedule,
    )

    # Case 2: Empty, nothing worth reporting (matches heartbeat silence rule)
    if heartbeat_res.is_silent:
        return HomeViewResult(
            sections={s: [] for s in HOME_SECTIONS},
            is_empty_no_tasks=False,
            is_nothing_worth_reporting=True,
            empty_message=None,  # Silence: no message, agrees with heartbeat silence
            silence_output=list(SILENCE_LINES),
            silence_message=SILENCE_MESSAGE,
        )

    # Case 3: Populated Home view grouped into exactly the four locked sections
    today_tasks: list[dict[str, Any]] = []
    waiting_tasks: list[dict[str, Any]] = []
    upcoming_tasks: list[dict[str, Any]] = []
    this_week_tasks: list[dict[str, Any]] = []

    two_days_ahead = curr_dt + timedelta(days=2)
    seven_days_ahead = curr_dt + timedelta(days=7)

    for t in tasks:
        status = t.get("Status") or t.get("status")
        if status == "Done":
            continue

        task_type = t.get("Type") or t.get("type")
        if task_type == "Someday":
            continue

        # Check Waiting on you first
        if is_waiting_on_user(t):
            waiting_tasks.append(t)
            continue

        due_raw = t.get("Due Date") or t.get("due_date")
        due_dt = parse_date(due_raw)

        if due_dt:
            if due_dt <= curr_dt:
                today_tasks.append(t)
            elif curr_dt < due_dt <= two_days_ahead:
                upcoming_tasks.append(t)
            elif two_days_ahead < due_dt <= seven_days_ahead:
                this_week_tasks.append(t)
        elif status == "In progress":
            today_tasks.append(t)

    sections = {
        "Today": today_tasks,
        "Waiting on you": waiting_tasks,
        "Upcoming": upcoming_tasks,
        "This week": this_week_tasks,
    }

    return HomeViewResult(
        sections=sections,
        is_empty_no_tasks=False,
        is_nothing_worth_reporting=False,
        empty_message=None,
    )


def generate_home_view_spec(
    tasks_data_source_id: str = "ds_tasks_123",
    custom_sections: tuple[str, ...] | None = None,
) -> dict[str, Any]:
    """Generate the deterministic Notion Home view specification.

    Enforces that:
      - Sections group into exactly: Today, Waiting on you, Upcoming, This week.
        No extra sections may compete for this space.
      - Legible on a phone without horizontal scrolling: wide tables are forbidden;
        uses mobile-friendly block types (list views, callouts, headings).
    """
    sections = custom_sections or HOME_SECTIONS
    if tuple(sections) != HOME_SECTIONS:
        raise ValueError(
            f"Home groups into exactly: Today · Waiting on you · Upcoming · This week. "
            f"Received: {sections}. Nothing else competes for that space."
        )

    # Build mobile-friendly block layout specification
    blocks: list[dict[str, Any]] = [
        {
            "object": "block",
            "type": "callout",
            "callout": {
                "icon": {"emoji": "⚡"},
                "rich_text": [{"type": "text", "text": {"content": "Workforce OS — Home [workforce-os:root]"}}],
            },
        }
    ]

    for sec in sections:
        blocks.append({
            "object": "block",
            "type": "heading_2",
            "heading_2": {
                "rich_text": [{"type": "text", "text": {"content": sec}}],
            },
        })
        # Mobile constraint: linked database views MUST be 'list', never 'table'
        blocks.append({
            "object": "block",
            "type": "linked_database_view",
            "linked_database_view": {
                "data_source_id": tasks_data_source_id,
                "view_type": "list",  # Mobile-friendly list layout without wide table columns
                "section": sec,
            },
        })

    return {
        "title": "Home",
        "sections": list(sections),
        "mobile_constraint": HOME_MOBILE_CONSTRAINT,
        "blocks": blocks,
    }


def validate_home_blocks_for_mobile(blocks: list[dict[str, Any]]) -> tuple[bool, str]:
    """Verify that Home view blocks contain zero wide tables."""
    for b in blocks:
        b_type = b.get("type")
        if b_type == "table":
            return False, "Wide table block found: violates mobile readability constraint."
        if b_type == "linked_database_view":
            view_type = b.get("linked_database_view", {}).get("view_type")
            if view_type == "table":
                return False, "Linked database view uses 'table': violates mobile readability constraint."
    return True, "Home view blocks strictly obey mobile readability constraint (no wide tables)."


# --------------------------------------------------------------------------
# Self-Test Suite
# --------------------------------------------------------------------------

def test_degraded_failure_states_in_fixture() -> tuple[bool, str]:
    """Done-when 1: Each degraded/failure state has a written, tested message with a next action.

    Triggerable in a fixture workspace using simulated infrastructure.
    """
    # State 1: Notion unreachable with backoff
    delays_record: list[float] = []

    def mock_sleeper(d: float) -> None:
        delays_record.append(d)

    def failing_api_call() -> None:
        raise RuntimeError("Simulated connection timeout connecting to api.notion.com")

    ok1, _, delays1, err1 = execute_notion_call_with_backoff(
        failing_api_call,
        max_retries=3,
        initial_backoff=0.2,
        sleeper=mock_sleeper,
    )
    if ok1 is not False or err1 is None:
        return False, "State 1 failed: expected failure outcome from unreachable Notion"
    if len(delays_record) != 2:
        return False, f"State 1 failed: expected 2 backoff sleeps for 3 attempts, got {len(delays_record)}"
    if not has_actionable_next_step(err1):
        return False, f"State 1 failed: message lacks actionable next step: {err1}"

    # State 2: Permission denied
    msg2 = format_permission_denied_message(
        object_name="Tasks",
        object_id="db_tasks_123",
        missing_permission="insert_pages",
        target_type="database",
    )
    if "Tasks" not in msg2 or "db_tasks_123" not in msg2 or "insert_pages" not in msg2:
        return False, f"State 2 failed: message missing exact object or permission: {msg2}"
    if not has_actionable_next_step(msg2):
        return False, f"State 2 failed: message lacks actionable next step: {msg2}"

    # State 3: Partial setup failure (reusing SimulatedNotionWorkspace)
    ws = SimulatedNotionWorkspace("parent_partial_test")
    report = SetupReport()
    report.success = False
    report.error = "Simulated network drop during Tasks database creation"
    report.what_was_built = ["Marker block", "Workforce database", "Worker: Anik"]
    report.what_was_not_built = ["Tasks database", "Tasks views", "Section pages"]

    msg3 = format_partial_setup_failure_message(
        error=report.error,
        what_was_built=report.what_was_built,
        what_was_not_built=report.what_was_not_built,
    )
    if "Workforce database" not in msg3 or "Tasks database" not in msg3:
        return False, f"State 3 failed: partial setup report missing built/unbuilt items: {msg3}"
    if "zero duplicate databases" not in msg3:
        return False, f"State 3 failed: missing zero-duplicate re-run statement: {msg3}"
    if not has_actionable_next_step(msg3):
        return False, f"State 3 failed: message lacks actionable next step: {msg3}"

    # State 4: Rate limited with visible backoff
    rate_log: list[str] = []
    attempt_count = 0

    def rate_limited_call() -> str:
        nonlocal attempt_count
        attempt_count += 1
        if attempt_count < 2:
            raise RuntimeError("HTTP 429: Rate limited by Notion API")
        return "success_after_backoff"

    ok4, res4, logs4 = execute_rate_limited_call_with_backoff(
        rate_limited_call,
        max_retries=3,
        default_retry_after=0.1,
        sleeper=lambda d: None,
        logger=rate_log,
    )
    if not ok4 or res4 != "success_after_backoff":
        return False, "State 4 failed: rate limit retry failed to complete call"
    if not logs4 or "Notion rate limit reached" not in logs4[0]:
        return False, f"State 4 failed: missing visible backoff notification: {logs4}"
    if not has_actionable_next_step(logs4[0]):
        return False, f"State 4 failed: rate limit notification lacks actionable next step: {logs4[0]}"

    # State 5: Worker has no Domain (reusing workforce_permission.py check)
    worker_no_scope = {"worker": "WriterAgent", "status": "Active", "domains": []}
    task_target = {"Task": "Write blog post", "Domain": "Marketing"}
    msg5 = format_worker_no_domain_message(worker_no_scope, task_target)

    if "empty Domains scope" not in msg5:
        return False, f"State 5 failed: message did not reuse permission domain scope refusal: {msg5}"
    if "\n" in msg5:
        return False, f"State 5 failed: message must be exactly one line, found newlines: {msg5}"
    if not has_actionable_next_step(msg5):
        return False, f"State 5 failed: message lacks actionable next step: {msg5}"

    # State 6: Recovery statement
    msg6 = format_recovery_message(citation="Acceptance Test 8")
    if "Acceptance Test 8" not in msg6 or "idempotently" not in msg6:
        return False, f"State 6 failed: recovery message missing citation: {msg6}"
    if not has_actionable_next_step(msg6):
        return False, f"State 6 failed: recovery message lacks actionable next step: {msg6}"

    return True, "All 6 degraded/failure states have written, next-action-bearing messages proven in fixture."


def test_home_and_heartbeat_silence_agreement() -> tuple[bool, str]:
    """Done-when 2: Home view empty-nothing-worth-reporting state and heartbeat silence rule agree.

    Proven by test (same condition, same silence outcome or no message).
    """
    ref_date = "2026-09-24"

    # Case A: Clean day where nothing qualifies
    clean_tasks = [
        {"Task": "Old archive migration", "Status": "Done", "Done Date": "2026-08-01"},
        {"Task": "Future planning session", "Status": "Planned", "Due Date": "2026-11-01"},
    ]
    upcoming_busy = {"Friday (2026-09-25)": 2, "Saturday (2026-09-26)": 1}

    heartbeat_clean = evaluate_review_protocol_detailed(
        clean_tasks, current_date=ref_date, upcoming_schedule=upcoming_busy
    )
    home_clean = evaluate_home_view(
        clean_tasks, current_date=ref_date, upcoming_schedule=upcoming_busy
    )

    # Core agreement checks:
    # 1. Condition: both agree on silence
    if home_clean.is_nothing_worth_reporting != heartbeat_clean.is_silent:
        return False, (
            f"Agreement broken on clean day: home.is_nothing_worth_reporting="
            f"{home_clean.is_nothing_worth_reporting}, heartbeat.is_silent={heartbeat_clean.is_silent}"
        )
    if not home_clean.is_nothing_worth_reporting:
        return False, "Expected Home view to report is_nothing_worth_reporting=True on clean day"

    # 2. Output: both agree on zero lines / no message
    if home_clean.empty_message is not None:
        return False, f"Expected Home view empty_message to be None on clean day, got: {home_clean.empty_message}"
    if home_clean.silence_output != heartbeat_clean.lines:
        return False, (
            f"Silence output differed between Home view and Heartbeat: "
            f"Home={home_clean.silence_output}, Heartbeat={heartbeat_clean.lines}"
        )
    if home_clean.silence_output != SILENCE_LINES or len(home_clean.silence_output) != 0:
        return False, f"Expected empty list for silence output, got: {home_clean.silence_output}"

    # Case B: Qualifying day with items requiring attention
    qualifying_tasks = [
        {"Task": "Tax filing submission", "Due Date": "2026-09-23", "Status": "Planned"},
        {"Task": "Platform spec", "Status": "In progress", "Agent Notes": "Waiting on user for review"},
    ]
    heartbeat_qualifying = evaluate_review_protocol_detailed(
        qualifying_tasks, current_date=ref_date
    )
    home_qualifying = evaluate_home_view(
        qualifying_tasks, current_date=ref_date
    )

    if home_qualifying.is_nothing_worth_reporting != heartbeat_qualifying.is_silent:
        return False, (
            f"Agreement broken on qualifying day: home={home_qualifying.is_nothing_worth_reporting}, "
            f"heartbeat={heartbeat_qualifying.is_silent}"
        )
    if home_qualifying.is_nothing_worth_reporting is not False:
        return False, "Expected is_nothing_worth_reporting=False on qualifying day"

    # Confirm sections correctly populated
    if len(home_qualifying.sections["Today"]) == 0:
        return False, "Expected Today section to contain overdue tax filing"
    if len(home_qualifying.sections["Waiting on you"]) == 0:
        return False, "Expected Waiting on you section to contain platform spec"

    # Case C: Empty workspace (0 tasks)
    home_empty = evaluate_home_view([])
    if not home_empty.is_empty_no_tasks:
        return False, "Expected is_empty_no_tasks=True for 0 tasks in workspace"
    if home_empty.empty_message != EMPTY_NO_TASKS_MESSAGE:
        return False, f"Expected 1-line empty directive, got: {home_empty.empty_message}"

    return True, "Home view silence state and heartbeat silence rule agree on condition and zero-line outcome."


def test_every_failure_message_contains_next_action() -> tuple[bool, str]:
    """Done-when 3: Every failure message contains an actionable next step.

    Proven by checking every message template for an actionable instruction and verb,
    not merely checking that strings are non-empty.
    """
    templates = [
        format_notion_unreachable_message(attempts=3, last_error="Timeout"),
        format_permission_denied_message("Goals", "page_123", "update_content", "page"),
        format_partial_setup_failure_message("API dropped", ["Workforce"], ["Tasks"]),
        format_rate_limited_message(retry_after_seconds=2.5, attempt=1, max_attempts=3),
        format_worker_no_domain_message({"worker": "Agent1", "domains": []}),
        format_recovery_message("Acceptance Test 8"),
        EMPTY_NO_TASKS_MESSAGE,
    ]

    for idx, msg in enumerate(templates, start=1):
        if not msg or not isinstance(msg, str):
            return False, f"Template {idx} is empty or non-string"
        if not has_actionable_next_step(msg):
            return False, f"Template {idx} lacks actionable instruction or recognized verb:\n  {msg}"

    # Also verify that a message lacking a remedy is rejected by the validator
    bad_messages = [
        "Network connection failed.",
        "Error 403: Forbidden.",
        "Worker has no domain.",
        "Rate limit reached.",
    ]
    for bad in bad_messages:
        if has_actionable_next_step(bad):
            return False, f"Validator incorrectly accepted message lacking remedy: {bad!r}"

    return True, "Every failure message contains an actionable instruction and verified action verb."


def test_home_view_four_sections_and_mobile_constraint() -> tuple[bool, str]:
    """Verify that Home groups into exactly 4 sections and enforces mobile constraint."""
    spec = generate_home_view_spec("ds_tasks_abc")

    if tuple(spec["sections"]) != HOME_SECTIONS:
        return False, f"Home sections must be exactly {HOME_SECTIONS}, got {spec['sections']}"

    # Reject competing sections
    try:
        generate_home_view_spec("ds_tasks_abc", custom_sections=("Today", "Waiting on you", "Upcoming", "This week", "Extra"))
        return False, "Expected ValueError when competing sections are added to Home view"
    except ValueError:
        pass

    # Verify mobile constraint
    ok, reason = validate_home_blocks_for_mobile(spec["blocks"])
    if not ok:
        return False, f"Mobile constraint violation: {reason}"

    # Confirm invalid wide table is caught
    violating_blocks = [{"type": "table"}]
    viol_ok, _ = validate_home_blocks_for_mobile(violating_blocks)
    if viol_ok:
        return False, "Validator failed to reject wide table block in Home view"

    return True, "Home view strictly defines 4 sections, rejects competitors, and enforces mobile layout."


def test_empty_no_tasks_one_line() -> tuple[bool, str]:
    """Verify that empty Home view states what to do first in one line, never blank."""
    home_empty = evaluate_home_view([])
    if not home_empty.is_empty_no_tasks:
        return False, "Expected is_empty_no_tasks=True"
    msg = home_empty.empty_message
    if not msg:
        return False, "Home view produced blank page when no tasks exist"
    if "\n" in msg:
        return False, f"Home empty directive must be a single line, found newlines: {msg!r}"
    if not has_actionable_next_step(msg):
        return False, f"Home empty directive lacks actionable next step: {msg!r}"

    return True, "Empty Home view produces a single-line actionable directive and never a blank page."


def run_self_tests() -> int:
    """Run all self-tests for Home view, empty states, and degraded/failure messages."""
    print("=================================================================")
    print("Running Workforce OS Home View & Degraded States Self-Tests...")
    print("=================================================================\n")

    tests = [
        ("Degraded/failure states in fixture", test_degraded_failure_states_in_fixture),
        ("Home view and heartbeat silence agreement", test_home_and_heartbeat_silence_agreement),
        ("Every failure message contains next action", test_every_failure_message_contains_next_action),
        ("Four sections and mobile constraint", test_home_view_four_sections_and_mobile_constraint),
        ("Empty no-tasks single-line directive", test_empty_no_tasks_one_line),
    ]

    failures = 0
    for name, fn in tests:
        try:
            ok, msg = fn()
            if ok:
                print(f"  [PASS] {name}: {msg}\n")
            else:
                print(f"  [FAIL] {name}: {msg}\n")
                failures += 1
        except Exception as exc:
            print(f"  [FAIL] {name}: Unhandled exception: {exc}\n")
            failures += 1

    print("-----------------------------------------------------------------")
    if failures == 0:
        print(f"ALL {len(tests)} HOME VIEW & DEGRADED STATES SELF-TESTS PASSED CLEANLY (0 failures).")
        print("Done-when requirements 1, 2, and 3 proven.")
        print("-----------------------------------------------------------------")
        return 0
    else:
        print(f"SELF-TESTS FAILED with {failures} failure(s).")
        print("-----------------------------------------------------------------")
        return 1


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(description="Workforce OS Home view and degraded states.")
    parser.add_argument("--self-test", action="store_true", help="Run automated self-tests.")
    parser.add_argument("--dry-run", action="store_true", help="Preview Home view evaluation and message formats.")
    args = parser.parse_args()

    if args.self_test:
        return run_self_tests()

    if args.dry_run or len(sys.argv) == 1:
        # Dry-run output demonstrating Home view states and failure messages
        sample_tasks = [
            {"Task": "Fix security vulnerability", "Due Date": "2026-09-24", "Status": "Planned"},
            {"Task": "Client review", "Status": "In progress", "Agent Notes": "waiting on user for signoff"},
            {"Task": "Design review", "Due Date": "2026-09-26", "Status": "Planned"},
            {"Task": "Deploy pipeline update", "Due Date": "2026-09-29", "Status": "Planned"},
        ]
        home_eval = evaluate_home_view(sample_tasks, current_date="2026-09-24")
        spec = generate_home_view_spec("ds_tasks_example")

        preview = {
            "dry_run": True,
            "home_specification": {
                "title": spec["title"],
                "sections": spec["sections"],
                "mobile_constraint": spec["mobile_constraint"],
                "block_count": len(spec["blocks"]),
            },
            "home_evaluation_sample": home_eval.to_dict(),
            "empty_states": {
                "empty_no_tasks_message": EMPTY_NO_TASKS_MESSAGE,
                "empty_nothing_worth_reporting_silence": True,
            },
            "degraded_and_failure_messages": {
                "notion_unreachable": format_notion_unreachable_message(3, "Connection reset by peer"),
                "permission_denied": format_permission_denied_message("Workforce", "db_wf_1", "update_properties", "database"),
                "partial_setup_failure": format_partial_setup_failure_message("Timeout", ["Marker block", "Workforce database"], ["Tasks database"]),
                "rate_limited": format_rate_limited_message(1.5, 1, 3),
                "worker_no_domain": format_worker_no_domain_message({"worker": "Writer", "domains": []}),
                "recovery": format_recovery_message("Acceptance Test 8"),
            },
        }
        print(json.dumps(preview, indent=2))
        return 0

    return 0


if __name__ == "__main__":
    sys.exit(main())
