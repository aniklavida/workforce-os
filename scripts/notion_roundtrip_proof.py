#!/usr/bin/env python3
"""Throwaway proof script for Workforce OS Notion connectivity.

It does three things against the Notion REST API and writes the raw
observations as a Markdown report:

  1. Writes one real task row into a task data source, with a page body that
     carries every formatting primitive the Workforce OS schema cares about
     (headings, annotations, lists, to-dos, quote, callout, code, divider,
     toggle, colour, link, inline newline). It then reads the page back and
     records exactly which formatting survived the round-trip.
  2. Reads the data source and the page's children using cursor pagination and
     a page_size of 100. Nothing here fans out one request per row.
  3. Measures the observed rate-limit behaviour with a controlled burst of
     small sequential reads: count of 200s before the first 429, the
     Retry-After header if present, and request latency.

This file is a measurement instrument, not product code. It is not imported by
anything. Run it once against a real workspace, paste the report into
docs/NOTION_ROUNDTRIP.md, and delete it if the report is all that is needed.

Credentials are never committed. Supply them through the environment:

    NOTION_TOKEN           internal integration secret (starts with "ntn_")
    NOTION_DATA_SOURCE_ID  the task data source id from the Notion URL / API
    NOTION_API_VERSION     optional, defaults to 2025-09-03

The current Notion API makes the data source the primary abstraction. A page is
created with parent.type = "data_source_id", and database queries are addressed
to /v1/data_sources/{id}/query. There is no database_id in this script.

Dry run (no network, no credentials, proves the request plan and batching):

    python3 scripts/notion_roundtrip_proof.py --dry-run

Live run, writing the report to stdout:

    NOTION_TOKEN=... NOTION_DATA_SOURCE_ID=... \\
        python3 scripts/notion_roundtrip_proof.py --burst 20
"""

from __future__ import annotations

import argparse
import json
import os
import statistics
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone

API_BASE = "https://api.notion.com/v1"
DEFAULT_API_VERSION = "2025-09-03"
PAGE_SIZE = 100  # Notion's maximum; every read below uses it.


# --------------------------------------------------------------------------
# HTTP client with rate-limit accounting
# --------------------------------------------------------------------------


class NotionError(RuntimeError):
    pass


class NotionClient:
    def __init__(self, token: str, api_version: str, dry_run: bool = False,
                 max_retries: int = 3):
        self.token = token
        self.api_version = api_version
        self.dry_run = dry_run
        self.max_retries = max_retries
        self.calls: list[dict] = []

    def _headers(self) -> dict:
        return {
            "Authorization": f"Bearer {self.token}",
            "Notion-Version": self.api_version,
            "Content-Type": "application/json",
        }

    def request(self, method: str, path: str, body: dict | None = None,
                purpose: str = "") -> dict:
        if self.dry_run:
            self.calls.append({"method": method, "path": path,
                               "purpose": purpose, "dry_run": True})
            return {"dry_run": True, "method": method, "path": path}

        url = f"{API_BASE}{path}"
        data = json.dumps(body).encode("utf-8") if body is not None else None
        attempt = 0
        while True:
            attempt += 1
            started = time.monotonic()
            req = urllib.request.Request(url, data=data, method=method,
                                         headers=self._headers())
            status = None
            retry_after = None
            header_retry = None
            error_text = ""
            try:
                with urllib.request.urlopen(req, timeout=60) as resp:
                    status = resp.status
                    header_retry = resp.headers.get("Retry-After")
                    payload = json.loads(resp.read().decode("utf-8"))
            except urllib.error.HTTPError as exc:
                status = exc.code
                header_retry = exc.headers.get("Retry-After")
                error_text = exc.read().decode("utf-8", "replace")
                payload = None
            elapsed = time.monotonic() - started
            record = {
                "method": method,
                "path": path,
                "purpose": purpose,
                "status": status,
                "seconds": round(elapsed, 4),
                "retry_after": header_retry,
                "attempt": attempt,
            }
            self.calls.append(record)

            if status is not None and 200 <= status < 300:
                return payload if payload is not None else {}

            if status == 429 and attempt <= self.max_retries:
                if header_retry is not None:
                    retry_after = float(header_retry)
                else:
                    retry_after = min(2 ** attempt, 8)
                time.sleep(retry_after)
                continue

            raise NotionError(
                f"{method} {path} -> HTTP {status}: {error_text[:400]}"
            )

    # -- pagination ---------------------------------------------------------

    def get_page_children(self, block_id: str) -> list[dict]:
        """Return every child block, cursor-paginated, never one page at once."""
        results: list[dict] = []
        cursor = None
        pages = 0
        while True:
            path = f"/blocks/{block_id}/children?page_size={PAGE_SIZE}"
            if cursor:
                path += f"&start_cursor={cursor}"
            payload = self.request("GET", path,
                                   purpose="read page children (paginated)")
            pages += 1
            results.extend(payload.get("results", []))
            if not payload.get("has_more"):
                break
            cursor = payload.get("next_cursor")
        self.last_child_pages = pages
        return results

    def query_data_source(self, data_source_id: str,
                          page_filter: dict | None = None) -> list[dict]:
        """Query a data source with cursor pagination and page_size=100."""
        results: list[dict] = []
        cursor = None
        pages = 0
        while True:
            body: dict = {"page_size": PAGE_SIZE}
            if page_filter:
                body["filter"] = page_filter
            if cursor:
                body["start_cursor"] = cursor
            payload = self.request(
                "POST", f"/data_sources/{data_source_id}/query", body,
                purpose="query data source (paginated)")
            pages += 1
            results.extend(payload.get("results", []))
            if not payload.get("has_more"):
                break
            cursor = payload.get("next_cursor")
        self.last_query_pages = pages
        return results


# --------------------------------------------------------------------------
# The formatting probe page
# --------------------------------------------------------------------------


def rich(content: str, **annotations) -> dict:
    return {
        "type": "text",
        "text": {"content": content},
        "annotations": {
            "bold": annotations.get("bold", False),
            "italic": annotations.get("italic", False),
            "strikethrough": annotations.get("strikethrough", False),
            "underline": annotations.get("underline", False),
            "code": annotations.get("code", False),
            "color": annotations.get("color", "default"),
        },
    }


def paragraph(rich_text: list[dict], children: list[dict] | None = None) -> dict:
    block = {"object": "block", "type": "paragraph",
             "paragraph": {"rich_text": rich_text}}
    if children:
        block["paragraph"]["children"] = children
    return block


def build_probe_children() -> list[dict]:
    """The block set written to the task page body.

    Each entry is a documented formatting primitive. The comparison pass below
    reports which ones survive a write -> read-back round-trip.
    """
    return [
        {"object": "block", "type": "heading_1",
         "heading_1": {"rich_text": [rich("Round-trip fidelity probe")]}},
        {"object": "block", "type": "heading_2",
         "heading_2": {"rich_text": [
             rich("Heading with "),
             rich("bold", bold=True),
             rich(" and "),
             rich("italic", italic=True),
         ]}},
        {"object": "block", "type": "paragraph",
         "paragraph": {"rich_text": [
             rich("mixed: "),
             rich("bold", bold=True),
             rich(" / "),
             rich("italic", italic=True),
             rich(" / "),
             rich("strike", strikethrough=True),
             rich(" / "),
             rich("underline", underline=True),
             rich(" / "),
             rich("code", code=True),
             rich(" / "),
             rich("red", color="red"),
             rich(" / "),
             rich("highlight", color="yellow_background"),
         ]}},
        {"object": "block", "type": "paragraph",
         "paragraph": {"rich_text": [
             rich("a link: "),
             {"type": "text",
              "text": {"content": "example", "link": {"url": "https://example.com"}},
              "annotations": {"bold": False, "italic": False,
                              "strikethrough": False, "underline": False,
                              "code": False, "color": "default"}},
         ]}},
        {"object": "block", "type": "paragraph",
         "paragraph": {"rich_text": [
             rich("line one\nline two")]}},
        {"object": "block", "type": "paragraph",
         "paragraph": {"rich_text": [rich("  leading and trailing  ")]}},
        {"object": "block", "type": "bulleted_list_item",
         "bulleted_list_item": {"rich_text": [rich("bullet parent")]}},
        {"object": "block", "type": "numbered_list_item",
         "numbered_list_item": {"rich_text": [rich("number one")]}},
        {"object": "block", "type": "to_do",
         "to_do": {"rich_text": [rich("done item")], "checked": True}},
        {"object": "block", "type": "to_do",
         "to_do": {"rich_text": [rich("open item")], "checked": False}},
        {"object": "block", "type": "quote",
         "quote": {"rich_text": [rich("a quoted line")]}},
        {"object": "block", "type": "callout",
         "callout": {"rich_text": [rich("callout body", bold=True)],
                     "icon": {"type": "emoji", "emoji": "🔥"},
                     "color": "blue_background"}},
        {"object": "block", "type": "code",
         "code": {"rich_text": [rich("print('hello')")],
                  "language": "python",
                  "caption": [rich("code caption")]}},
        {"object": "block", "type": "divider", "divider": {}},
        {"object": "block", "type": "toggle",
         "toggle": {"rich_text": [rich("toggle parent")],
                    "children": [paragraph([rich("toggle child")])]}},
        {"object": "block", "type": "heading_3",
         "heading_3": {"rich_text": [rich("toggleable heading")],
                       "is_toggleable": True}},
    ]


def child_marker(block: dict) -> str:
    """A short human label for a block, for the report."""
    block_type = block.get("type", "?")
    payload = block.get(block_type, {})
    if isinstance(payload, dict):
        text = payload.get("rich_text")
        if text:
            return f"{block_type}: {plain(text)[:48]!r}"
    return block_type


def plain(rich_text: list[dict]) -> str:
    return "".join(run.get("plain_text", "") for run in rich_text)


def annotation_set(rich_text: list[dict]) -> list[dict]:
    out = []
    for run in rich_text:
        ann = run.get("annotations", {})
        out.append({
            "text": run.get("plain_text", ""),
            "bold": ann.get("bold", False),
            "italic": ann.get("italic", False),
            "strikethrough": ann.get("strikethrough", False),
            "underline": ann.get("underline", False),
            "code": ann.get("code", False),
            "color": ann.get("color", "default"),
            "link": (run.get("text", {}) or {}).get("link"),
        })
    return out


def compare_probe(written: dict, observed: dict | None) -> tuple[str, str, str]:
    """Return (verdict, written_summary, observed_summary) for one block."""
    if observed is None:
        return ("LOST", child_marker(written), "not returned by the API")
    if observed.get("type") != written.get("type"):
        return ("ALTERED", child_marker(written),
                f"type changed to {observed.get('type')}")

    w_type = written.get("type")
    w_payload = written.get(w_type, {})
    o_payload = observed.get(w_type, {})
    w_text = w_payload.get("rich_text") if isinstance(w_payload, dict) else None
    o_text = o_payload.get("rich_text") if isinstance(o_payload, dict) else None

    if w_text is not None and o_text is not None:
        w_ann = annotation_set(w_text)
        o_ann = annotation_set(o_text)
        if w_ann != o_ann:
            return ("ALTERED", json.dumps(w_ann, ensure_ascii=False),
                    json.dumps(o_ann, ensure_ascii=False))

    for key in ("checked", "language", "color", "is_toggleable"):
        if isinstance(w_payload, dict) and key in w_payload:
            if w_payload.get(key) != o_payload.get(key):
                return ("ALTERED", f"{key}={w_payload.get(key)!r}",
                        f"{key}={o_payload.get(key)!r}")
    if isinstance(w_payload, dict) and "icon" in w_payload:
        if w_payload.get("icon") != o_payload.get("icon"):
            return ("ALTERED", f"icon={w_payload.get('icon')!r}",
                    f"icon={o_payload.get('icon')!r}")

    return ("PRESERVED", child_marker(written), child_marker(observed))


# --------------------------------------------------------------------------
# Rate-limit burst
# --------------------------------------------------------------------------


def measure_rate_limit(client: NotionClient, read_block_id: str,
                       burst: int) -> dict:
    """Issue `burst` small sequential reads and summarise the response stream.

    Notion documents an average of about three requests per second. This does
    not try to defeat the limit; it records how the limit presents itself
    (status codes and Retry-After) and the latency profile.
    """
    latencies: list[float] = []
    statuses: list[int] = []
    retry_afters: list[str] = []
    first_429_after: int | None = None
    for i in range(burst):
        try:
            client.request("GET", f"/blocks/{read_block_id}",
                           purpose="rate-limit burst read")
        except NotionError:
            pass
        record = client.calls[-1]
        statuses.append(record["status"])
        latencies.append(record["seconds"])
        if record["retry_after"] is not None:
            retry_afters.append(str(record["retry_after"]))
        if record["status"] == 429 and first_429_after is None:
            first_429_after = i
    return {
        "burst": burst,
        "statuses": statuses,
        "count_429": statuses.count(429),
        "first_429_at_request": first_429_after,
        "retry_after_values": sorted(set(retry_afters)),
        "latency_seconds": {
            "min": round(min(latencies), 4) if latencies else None,
            "mean": round(statistics.mean(latencies), 4) if latencies else None,
            "max": round(max(latencies), 4) if latencies else None,
        },
    }


# --------------------------------------------------------------------------
# Report
# --------------------------------------------------------------------------


def markdown_report(report: dict) -> str:
    lines: list[str] = []
    lines.append("# Notion round-trip and rate-limit observations")
    lines.append("")
    lines.append(f"- Generated: {report['generated_at']}")
    lines.append(f"- API version: `{report['api_version']}`")
    lines.append(f"- Data source: `{report.get('data_source_id') or '(not set)'}`")
    lines.append(f"- Created task page: "
                 f"`{report.get('created_page_id') or '(not created)'}`")
    lines.append("")

    lines.append("## Pagination evidence")
    lines.append("")
    lines.append(f"- Child read pages fetched (page_size={PAGE_SIZE}): "
                 f"{report.get('child_pages')}")
    lines.append(f"- Data source query pages fetched (page_size={PAGE_SIZE}): "
                 f"{report.get('query_pages')}")
    lines.append(f"- Task rows returned by the data source query: "
                 f"{report.get('query_rows')}")
    lines.append("")

    lines.append("## Formatting round-trip")
    lines.append("")
    lines.append("| # | Written block | Verdict | Written | Observed |")
    lines.append("|---|---|---|---|---|")
    for row in report.get("fidelity", []):
        lines.append(
            f"| {row['index']} | `{row['block']}` | **{row['verdict']}** | "
            f"`{row['written']}` | `{row['observed']}` |")
    lines.append("")
    lines.append(f"Verdict counts: {report.get('verdict_counts')}")
    lines.append("")

    lines.append("## Rate-limit behaviour")
    lines.append("")
    rl = report.get("rate_limit") or {}
    if rl:
        lines.append(f"- Burst size: {rl['burst']} sequential reads")
        lines.append(f"- 429 responses: {rl['count_429']}")
        lines.append(f"- First 429 at request index: {rl['first_429_at_request']}")
        lines.append(f"- Retry-After values seen: {rl['retry_after_values']}")
        lines.append(f"- Latency seconds: {rl['latency_seconds']}")
    else:
        lines.append("- Not measured.")
    lines.append("")
    return "\n".join(lines)


def dry_run_plan(args) -> dict:
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "api_version": args.api_version,
        "dry_run": True,
        "note": "No network calls. This is the request plan the live run executes.",
        "steps": [
            f"GET /data_sources/{{data_source_id}} (schema discovery, "
            f"api version {args.api_version})",
            "POST /pages with parent.type=data_source_id, one batch of "
            f"{len(build_probe_children())} child blocks (single request, "
            f"limit is {PAGE_SIZE})",
            f"GET /blocks/{{page_id}}/children?page_size={PAGE_SIZE} then loop "
            "start_cursor until has_more=false (paginated read)",
            f"POST /data_sources/{{data_source_id}}/query with page_size="
            f"{PAGE_SIZE}, loop start_cursor (paginated, batched read)",
            f"GET /blocks/{{page_id}} x {args.burst} sequential reads to "
            "observe 429 / Retry-After",
        ],
        "batching_rule": (
            "No per-row fan-out: page_size=100 and cursor pagination on every "
            "read; all probe blocks created in one page-create request."),
        "env_required_for_live_run": [
            "NOTION_TOKEN", "NOTION_DATA_SOURCE_ID"],
    }


def resolve_title_property(schema: dict) -> str | None:
    for name, prop in (schema.get("properties") or {}).items():
        if prop.get("type") == "title":
            return name
    return "Task"


def live_run(args) -> dict:
    token = os.environ.get("NOTION_TOKEN")
    data_source_id = os.environ.get("NOTION_DATA_SOURCE_ID")
    if not token or not data_source_id:
        print(
            "Missing credentials. Set NOTION_TOKEN and NOTION_DATA_SOURCE_ID, "
            "then re-run. Nothing was sent.",
            file=sys.stderr)
        sys.exit(2)

    client = NotionClient(token, args.api_version)
    report: dict = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "api_version": args.api_version,
        "data_source_id": data_source_id,
    }

    schema = client.request(
        "GET", f"/data_sources/{data_source_id}",
        purpose="data source schema discovery")
    title_prop = resolve_title_property(schema)
    title = f"Round-trip probe {datetime.now(timezone.utc):%Y-%m-%d %H:%M:%S}"

    properties: dict = {
        title_prop: {"title": [rich(title)]},
        "Notes": {"rich_text": [rich(
            "Written by scripts/notion_roundtrip_proof.py. Safe to delete.")]},
    }
    # Only send select/status properties the schema actually has.
    schema_props = schema.get("properties") or {}
    for name, value in (("Status", "Planned"), ("Priority", "Low")):
        if name in schema_props:
            prop_type = schema_props[name].get("type")
            if prop_type == "status":
                properties[name] = {"status": {"name": value}}
            elif prop_type == "select":
                properties[name] = {"select": {"name": value}}

    children = build_probe_children()
    page = client.request(
        "POST", "/pages",
        {
            "parent": {"type": "data_source_id",
                       "data_source_id": data_source_id},
            "properties": properties,
            "children": children,
        },
        purpose=f"create task row + all {len(children)} blocks in one request")
    page_id = page.get("id")
    report["created_page_id"] = page_id
    report["title"] = title

    # -- paginated read of the page body --------------------------------
    observed_top = client.get_page_children(page_id)
    report["child_pages"] = getattr(client, "last_child_pages", None)

    # Recursively read nested children (toggle) so the comparison is complete.
    nested: dict[str, list[dict]] = {}
    for block in observed_top:
        if block.get("has_children"):
            nested[block["id"]] = client.get_page_children(block["id"])

    fid = []
    for i, written in enumerate(children):
        observed = observed_top[i] if i < len(observed_top) else None
        verdict, w_sum, o_sum = compare_probe(written, observed)
        fid.append({
            "index": i,
            "block": written.get("type"),
            "verdict": verdict,
            "written": w_sum,
            "observed": o_sum,
        })
    # Toggle child survival.
    toggle = next((b for b in observed_top if b.get("type") == "toggle"), None)
    if toggle:
        kids = nested.get(toggle["id"], [])
        fid.append({
            "index": "toggle-child",
            "block": "paragraph (nested)",
            "verdict": "PRESERVED" if kids else "LOST",
            "written": "toggle child",
            "observed": child_marker(kids[0]) if kids else "not returned",
        })
    report["fidelity"] = fid
    counts: dict[str, int] = {}
    for row in fid:
        counts[row["verdict"]] = counts.get(row["verdict"], 0) + 1
    report["verdict_counts"] = counts

    # -- paginated data source query ------------------------------------
    rows = client.query_data_source(data_source_id)
    report["query_pages"] = getattr(client, "last_query_pages", None)
    report["query_rows"] = len(rows)

    # -- rate-limit burst -----------------------------------------------
    report["rate_limit"] = measure_rate_limit(
        client, page_id, args.burst)
    report["call_count"] = len(client.calls)
    report["retries_after_429"] = sum(
        1 for c in client.calls if c.get("attempt", 1) > 1)
    report["generated_at"] = datetime.now(timezone.utc).isoformat()
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true",
                        help="print the request plan without any network call")
    parser.add_argument("--burst", type=int, default=20,
                        help="sequential reads used to observe rate limiting")
    parser.add_argument("--api-version", default=os.environ.get(
        "NOTION_API_VERSION", DEFAULT_API_VERSION))
    parser.add_argument("--out", help="write the Markdown report to this path")
    parser.add_argument("--json", action="store_true",
                        help="print the raw report as JSON")
    args = parser.parse_args()

    if args.dry_run:
        report = dry_run_plan(args)
        output = json.dumps(report, indent=2, ensure_ascii=False)
    else:
        report = live_run(args)
        output = (json.dumps(report, indent=2, ensure_ascii=False)
                  if args.json else markdown_report(report))

    if args.out:
        with open(args.out, "w", encoding="utf-8") as handle:
            handle.write(output if output.endswith("\n") else output + "\n")
        print(f"wrote {args.out}")
    else:
        print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
