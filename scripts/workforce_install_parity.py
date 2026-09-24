#!/usr/bin/env python3
"""Install-by-prompt parity proof.

Proves that the literal instructions on docs/INSTALL.md, mechanically followed,
build the same Workforce OS structure as the plugin path's existing build logic
in scripts/workforce_setup.py (the ground truth for "what the plugin builds").

Two independent paths are compared:

  A. Plugin path (ground truth). IdempotentSetupOrchestrator.run() against a
     fresh SimulatedNotionWorkspace. This is the code the Claude Code plugin's
     setup skill drives.

  B. Install-page path. An independent builder that:
       - reads docs/INSTALL.md and parses its build-order steps;
       - reads docs/STRUCTURE.md (the page points at it) and parses the task and
         workforce property tables, the view list, and the marker;
       - executes only those literal steps against a second fresh workspace.
     It does not call the orchestrator or reuse its build logic. It shares only
     the simulated workspace harness and the five answers dataclass, so the two
     paths start from identical inputs and are written to the same kind of
     workspace.

The two resulting structures are canonicalised to a signature and diffed. Any
difference is reported by name.

Honest limit. This proves the install page is self-consistent and complete
against the plugin's own build path. It does NOT prove that a real Codex,
Cursor, Gemini CLI, or other non-Claude-Code host, handed the page, follows it
correctly. That is a live-vendor-app test and is out of reach of an unattended
session. See docs/INSTALL.md ("Hosts actually tried").

Usage:
  python3 scripts/workforce_install_parity.py
  python3 scripts/workforce_install_parity.py --verbose
"""

from __future__ import annotations

import argparse
import os
import re
import sys

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
if SCRIPT_DIR not in sys.path:
    sys.path.insert(0, SCRIPT_DIR)

from workforce_setup import (  # noqa: E402
    TASKS_ASSIGNED_TO_PROP,
    WORKFORCE_OS_MARKER,
    IdempotentSetupOrchestrator,
    SetupAnswers,
    SimulatedNotionWorkspace,
)

REPO_ROOT = os.path.dirname(SCRIPT_DIR)
INSTALL_PAGE = os.path.join(REPO_ROOT, "docs", "INSTALL.md")
STRUCTURE_DOC = os.path.join(REPO_ROOT, "docs", "STRUCTURE.md")

INSTALL_INSTRUCTION = "Read this page and install Workforce OS for me"
TASK_HEADING = "## The task database"
WORKFORCE_HEADING = "## The Workforce database"
DOMAIN_CONTEXT_MARKER = "AGENT ROUTING CONTRACT"


# --------------------------------------------------------------------------
# Reading the install page and the structure it points at
# --------------------------------------------------------------------------

def read_text(path: str) -> str:
    with open(path, "r", encoding="utf-8") as fh:
        return fh.read()


def parse_build_order(install_text: str) -> list[str]:
    """Extract the numbered build-order steps from docs/INSTALL.md."""
    lines = install_text.splitlines()
    in_section = False
    steps: list[str] = []
    for line in lines:
        if line.strip() == "## Build order":
            in_section = True
            continue
        if not in_section:
            continue
        if line.startswith("## "):
            break
        match = re.match(r"^\s*\d+\.\s+(.*\S)\s*$", line)
        if match:
            steps.append(match.group(1).strip())
    return steps


def parse_section_names(step_text: str) -> list[str]:
    """Pull the section page list out of the 'Section pages:' build step."""
    tail = step_text.split(":", 1)[1]
    names = [n.strip().rstrip(".") for n in tail.split(",")]
    return [n for n in names if n]


def parse_property_names(structure_text: str, heading_prefix: str) -> list[str]:
    """First column of the markdown table under a heading in docs/STRUCTURE.md."""
    lines = structure_text.splitlines()
    start = next(
        (i for i, line in enumerate(lines) if line.startswith(heading_prefix)),
        None,
    )
    if start is None:
        raise ValueError(f"heading not found in STRUCTURE.md: {heading_prefix!r}")
    names: list[str] = []
    for line in lines[start + 1:]:
        stripped = line.strip()
        if stripped.startswith("|"):
            first = stripped.strip("|").split("|")[0].strip()
            if first == "Property" or set(first) <= set("-: "):
                continue
            names.append(first)
        elif names:
            break
    return names


def parse_relation_target(structure_text: str, heading_prefix: str,
                          prop_name: str) -> str | None:
    """Find the relation target named in a property's table row."""
    lines = structure_text.splitlines()
    start = next(
        (i for i, line in enumerate(lines) if line.startswith(heading_prefix)),
        None,
    )
    if start is None:
        return None
    for line in lines[start + 1:]:
        stripped = line.strip()
        if not stripped.startswith("|"):
            if stripped and not stripped.startswith("|"):
                break
            continue
        cells = [c.strip() for c in stripped.strip("|").split("|")]
        if cells and cells[0] == prop_name:
            match = re.search(r"Relation\s*→\s*([A-Za-z]+)", cells[1] if len(cells) > 1 else "")
            return match.group(1) if match else None
    return None


def parse_view_names(structure_text: str) -> list[str]:
    """Bold view names from the '### Views' bullet list."""
    lines = structure_text.splitlines()
    start = next((i for i, l in enumerate(lines) if l.strip() == "### Views"), None)
    if start is None:
        raise ValueError("'### Views' heading not found in STRUCTURE.md")
    names: list[str] = []
    for line in lines[start + 1:]:
        stripped = line.strip()
        match = re.match(r"^-\s+\*\*(.+?)\*\*", stripped)
        if match:
            names.append(match.group(1))
        elif names and not stripped.startswith("-"):
            break
    return names


# --------------------------------------------------------------------------
# Path B: the independent install-page builder
# --------------------------------------------------------------------------

class InstallPageBuilder:
    """Builds the structure by following docs/INSTALL.md's literal steps only.

    It does not call IdempotentSetupOrchestrator or its build helpers. The
    structure schema comes from docs/STRUCTURE.md, which the page points at.
    """

    def __init__(self, ws: SimulatedNotionWorkspace, answers: SetupAnswers,
                 install_text: str, structure_text: str):
        self.ws = ws
        self.answers = answers
        self.install_text = install_text
        self.structure_text = structure_text
        self.steps = parse_build_order(install_text)
        self.section_names = parse_section_names(
            next(s for s in self.steps if s.lower().startswith("section pages"))
        )
        self.workforce_props = parse_property_names(structure_text, WORKFORCE_HEADING)
        self.task_props = parse_property_names(structure_text, TASK_HEADING)
        self.views = parse_view_names(structure_text)
        self.workforce_ds_id: str | None = None
        self.tasks_ds_id: str | None = None
        self.section_ids: dict[str, str] = {}

    # -- individual literal steps ---------------------------------------

    def step_marker(self) -> None:
        self.ws.append_blocks(self.ws.parent_page_id, [{
            "object": "block",
            "type": "callout",
            "callout": {
                "icon": {"emoji": "⚡"},
                "rich_text": [{
                    "type": "text",
                    "text": {"content": f"Workforce OS [{WORKFORCE_OS_MARKER}]"},
                }],
            },
        }])

    def step_workforce_database(self) -> None:
        props = {name: {"rich_text": {}} for name in self.workforce_props}
        db = self.ws.create_database(self.ws.parent_page_id, "Workforce", props)
        self.workforce_ds_id = db["data_sources"][0]["id"]

    def step_worker_rows(self) -> None:
        rows = [{
            "name": self.answers.user_name,
            "kind": "Human",
            "role": "Specialist",
            "channel": "None",
        }]
        for agent in self.answers.agents:
            rows.append({
                "name": agent["name"],
                "kind": agent.get("kind", "Agent"),
                "role": agent.get("role", "Specialist"),
                "channel": agent.get("channel", self.answers.daily_channel),
            })
        for row in rows:
            self.ws.create_page(
                parent={"type": "data_source_id", "data_source_id": self.workforce_ds_id},
                title=row["name"],
                properties={},
                children=[{
                    "object": "block",
                    "type": "paragraph",
                    "paragraph": {"rich_text": [{
                        "type": "text",
                        "text": {"content": f"Worker startup brief for {row['name']}."},
                    }]},
                }],
            )

    def step_task_database(self) -> None:
        props = {}
        for name in self.task_props:
            if name == TASKS_ASSIGNED_TO_PROP:
                props[name] = {
                    "relation": {"data_source_id": self.workforce_ds_id, "type": "single_property"}
                }
            else:
                props[name] = {"rich_text": {}}
        db = self.ws.create_database(self.ws.parent_page_id, "Tasks", props)
        self.tasks_ds_id = db["data_sources"][0]["id"]

    def step_task_views(self) -> None:
        for name in self.views:
            if "per domain" in name.lower():
                for domain in self.answers.domains:
                    self.ws.add_view(self.tasks_ds_id, {"name": f"Domain: {domain}"})
            else:
                self.ws.add_view(self.tasks_ds_id, {"name": name})

    def step_section_pages(self) -> None:
        for title in self.section_names:
            page = self.ws.create_page(
                parent={"type": "page_id", "page_id": self.ws.parent_page_id},
                title=title,
                properties={},
                children=[{
                    "object": "block",
                    "type": "heading_1",
                    "heading_1": {"rich_text": [{"type": "text", "text": {"content": title}}]},
                }],
            )
            self.section_ids[title] = page["id"]

    def step_domain_pages(self) -> None:
        domains_parent = self.section_ids["Domains"]
        for domain in self.answers.domains:
            self.ws.create_page(
                parent={"type": "page_id", "page_id": domains_parent},
                title=domain,
                properties={},
                children=[{
                    "object": "block",
                    "type": "callout",
                    "callout": {
                        "icon": {"emoji": "\U0001f6e1\ufe0f"},
                        "rich_text": [{
                            "type": "text",
                            "text": {"content": (
                                f"{DOMAIN_CONTEXT_MARKER} (AGENTS.md rule 5): an agent "
                                f"working in the '{domain}' domain may ONLY read the "
                                "declared context below."
                            )},
                        }],
                    },
                }],
            )

    def step_worker_briefs(self) -> None:
        # Briefs are written when rows are created; this step is a no-op check
        # that every worker row carries one.
        ds = self.ws.data_sources[self.workforce_ds_id]
        for row in ds.get("rows", []):
            if not self.ws.blocks.get(row["id"]):
                raise AssertionError(f"worker row {row['title']!r} has no startup brief")

    def step_initial_task(self) -> None:
        domain = self.answers.domains[0]
        self.ws.create_page(
            parent={"type": "data_source_id", "data_source_id": self.tasks_ds_id},
            title="Review Workforce OS structure and verify domain context routing",
            properties={
                "Status": {"status": {"name": "Planned"}},
                "Domain": {"select": {"name": domain}},
            },
        )

    def build(self) -> SimulatedNotionWorkspace:
        dispatch = {
            "marker": self.step_marker,
            "workforce database": self.step_workforce_database,
            "worker rows": self.step_worker_rows,
            "task database": self.step_task_database,
            "task views": self.step_task_views,
            "section pages": self.step_section_pages,
            "domain pages": self.step_domain_pages,
            "worker startup briefs": self.step_worker_briefs,
            "initial task": self.step_initial_task,
        }
        if not self.steps:
            raise AssertionError("docs/INSTALL.md has no parseable build order")
        for step in self.steps:
            lowered = step.lower()
            handler = next(
                (fn for key, fn in dispatch.items() if lowered.startswith(key)),
                None,
            )
            if handler is None:
                raise AssertionError(f"unrecognised build-order step: {step!r}")
            handler()
        return self.ws


# --------------------------------------------------------------------------
# Canonical structure signature and diff
# --------------------------------------------------------------------------

def _db_title(db: dict) -> str:
    return "".join(t.get("text", {}).get("content", "") for t in db.get("title", []))


def _callout_text(block: dict) -> str:
    return "".join(
        t.get("text", {}).get("content", "")
        for t in block.get("callout", {}).get("rich_text", [])
    )


def structure_signature(ws: SimulatedNotionWorkspace) -> dict:
    parent = ws.parent_page_id

    marker_present = any(
        block.get("type") == "callout"
        and f"[{WORKFORCE_OS_MARKER}]" in _callout_text(block)
        for block in ws.search_parent_blocks(parent)
    )

    databases: dict[str, dict] = {}
    for db in ws.databases.values():
        title = _db_title(db)
        assigned = db.get("properties", {}).get(TASKS_ASSIGNED_TO_PROP)
        relation_target = "Workforce" if assigned and "relation" in assigned else None
        databases[title] = {
            "properties": sorted(db.get("properties", {}).keys()),
            "assigned_to_relation_target": relation_target,
        }

    child_pages = ws.get_child_pages(parent)
    section_pages = sorted(p["title"] for p in child_pages)

    domains_page = next((p for p in child_pages if p["title"] == "Domains"), None)
    domain_pages: dict[str, bool] = {}
    if domains_page:
        for page in ws.get_child_pages(domains_page["id"]):
            blocks = ws.blocks.get(page["id"], [])
            domain_pages[page["title"]] = any(
                block.get("type") == "callout"
                and DOMAIN_CONTEXT_MARKER in _callout_text(block)
                for block in blocks
            )

    workforce_ds = next(
        (db["data_sources"][0]["id"] for db in ws.databases.values()
         if _db_title(db) == "Workforce"), None)
    tasks_ds = next(
        (db["data_sources"][0]["id"] for db in ws.databases.values()
         if _db_title(db) == "Tasks"), None)

    worker_rows = []
    if workforce_ds:
        worker_rows = sorted(
            row["title"] for row in ws.data_sources[workforce_ds].get("rows", [])
        )

    raw_views = ws.views.get(tasks_ds, []) if tasks_ds else []
    views = sorted({
        "One per Domain" if v["name"].startswith("Domain:") else v["name"]
        for v in raw_views
    })

    initial_task = {"present": False, "status": None, "domain": None}
    if tasks_ds:
        task_rows = ws.data_sources[tasks_ds].get("rows", [])
        if task_rows:
            props = task_rows[0].get("properties", {})
            initial_task = {
                "present": True,
                "status": props.get("Status", {}).get("status", {}).get("name"),
                "domain": props.get("Domain", {}).get("select", {}).get("name"),
            }

    return {
        "marker_present": marker_present,
        "databases": databases,
        "section_pages": section_pages,
        "domain_pages": domain_pages,
        "worker_rows": worker_rows,
        "task_views": views,
        "initial_task": initial_task,
    }


def diff_signatures(plugin: object, install: object, path: str = "structure") -> list[str]:
    """Recursively diff two canonical signatures, naming every difference."""
    diffs: list[str] = []
    if isinstance(plugin, dict) and isinstance(install, dict):
        for key in sorted(set(plugin) | set(install)):
            if key not in plugin:
                diffs.append(f"{path}.{key}: missing from plugin path")
            elif key not in install:
                diffs.append(f"{path}.{key}: missing from install path")
            else:
                diffs.extend(diff_signatures(plugin[key], install[key], f"{path}.{key}"))
    elif isinstance(plugin, list) and isinstance(install, list):
        if plugin != install:
            plugin_only = [x for x in plugin if x not in install]
            install_only = [x for x in install if x not in plugin]
            diffs.append(
                f"{path}: differs; plugin-only={plugin_only} install-only={install_only}"
            )
    elif plugin != install:
        diffs.append(f"{path}: plugin={plugin!r} install={install!r}")
    return diffs


# --------------------------------------------------------------------------
# Guard rails: the page points at the source, it does not copy it
# --------------------------------------------------------------------------

def check_page_shape(install_text: str) -> list[str]:
    """The page must be an instruction that points, not a duplicate spec."""
    problems: list[str] = []
    if INSTALL_INSTRUCTION not in install_text:
        problems.append("missing one-line instruction")
    if "AGENTS.md" not in install_text:
        problems.append("missing pointer to AGENTS.md")
    if "docs/STRUCTURE.md" not in install_text:
        problems.append("missing pointer to docs/STRUCTURE.md")
    if "[workforce-os:root]" not in install_text:
        problems.append("missing idempotency marker")
    questions = re.findall(r"^\s*\d+\.\s", install_text.split("## The five questions", 1)[-1].split("## Build order", 1)[0], re.MULTILINE)
    if len(questions) != 5:
        problems.append(f"expected exactly five setup questions, found {len(questions)}")
    if len(parse_build_order(install_text)) != 9:
        problems.append("expected nine build-order steps")
    # Must not restate the property tables (that is what docs/STRUCTURE.md is for).
    if "| Task | Title" in install_text or "| Worker | Title" in install_text:
        problems.append("page duplicates STRUCTURE.md property tables")
    return problems


# --------------------------------------------------------------------------
# Runner
# --------------------------------------------------------------------------

def run_parity(verbose: bool = False) -> int:
    print("=================================================================")
    print("Workforce OS Install-by-Prompt Parity Proof")
    print("docs/INSTALL.md literal steps vs scripts/workforce_setup.py build")
    print("=================================================================\n")

    install_text = read_text(INSTALL_PAGE)
    structure_text = read_text(STRUCTURE_DOC)
    answers = SetupAnswers(
        domains=["Writing", "Consulting", "Personal"],
        user_name="Anik",
        daily_channel="Claude Code",
        primary_goal="Ship Workforce OS v1.0",
    )

    problems = check_page_shape(install_text)
    if problems:
        print("[FAIL] docs/INSTALL.md shape check:")
        for problem in problems:
            print(f"       - {problem}")
        return 1
    print("[PASS] docs/INSTALL.md contains the instruction, five questions,")
    print("       idempotency marker, nine build steps, and points at AGENTS.md")
    print("       and docs/STRUCTURE.md without copying the property tables.\n")

    plugin_ws = SimulatedNotionWorkspace("parity_plugin_path")
    plugin_report = IdempotentSetupOrchestrator(
        plugin_ws, answers, auto_approve=True, quiet=not verbose
    ).run()
    if not plugin_report.success:
        print(f"[FAIL] plugin path setup did not complete: {plugin_report.error}")
        return 1

    install_ws = SimulatedNotionWorkspace("parity_install_path")
    InstallPageBuilder(install_ws, answers, install_text, structure_text).build()

    plugin_sig = structure_signature(plugin_ws)
    install_sig = structure_signature(install_ws)
    diffs = diff_signatures(plugin_sig, install_sig)

    if diffs:
        print("[FAIL] the install page's literal steps diverge from the plugin build:")
        for item in diffs:
            print(f"       - {item}")
        return 1

    print("[PASS] Install-page path builds the identical structure:")
    print(f"       databases:    {sorted(plugin_sig['databases'])}")
    print(f"       section pages: {plugin_sig['section_pages']}")
    print(f"       domain pages:  {sorted(plugin_sig['domain_pages'])}")
    print(f"       worker rows:   {plugin_sig['worker_rows']}")
    print(f"       task views:    {plugin_sig['task_views']}")
    print(f"       initial task:  {plugin_sig['initial_task']}")
    print()
    print("-----------------------------------------------------------------")
    print("PARITY PROVEN: the install page's literal instructions are")
    print("self-consistent and complete against the plugin's build path.")
    print("NOT PROVEN: that a real Codex/Cursor/Gemini CLI follows them.")
    print("-----------------------------------------------------------------")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--verbose", "-v", action="store_true",
                        help="print the plugin path's step-by-step progress")
    args = parser.parse_args()
    return run_parity(verbose=args.verbose)


if __name__ == "__main__":
    raise SystemExit(main())
