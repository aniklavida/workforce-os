# Notion round-trip and rate-limit observations

This document records what happens when a task row is written to Notion with
varied formatting and read back, and how Notion's rate limit behaves. It exists
so that `skills/workforce-setup` and the rest of the protocol only promise
formatting fidelity the API actually delivers.

The measuring instrument is [`scripts/notion_roundtrip_proof.py`](../scripts/notion_roundtrip_proof.py).

## Run status

**NOT YET EXECUTED AGAINST A LIVE WORKSPACE.**

At the time this document was committed, no `NOTION_TOKEN` or
`NOTION_DATA_SOURCE_ID` was available in the authoring environment, so the live
run was not performed and **no live fidelity or rate-limit numbers are claimed
here**. The script itself was executed in `--dry-run` mode to prove it runs and
to print the exact request plan; that output is reproduced below. The tables
further down are the report format the script emits and the documented
expectations that the live run should confirm or correct.

Do not promote the expectations below into claims about tested behaviour. Run
the script once against a real workspace and paste its output over the
placeholder tables.

## How to run it once

1. Create an internal integration in Notion and give it access to the task
   database (or use the OAuth token from the remote MCP if the agent exposes
   one). Store the secret outside the repository.
2. Find the task **data source id** (not the database id). With the remote MCP,
   inspect the database object returned to the agent; with the REST API,
   `GET /v1/databases/{database_id}` returns the database's `data_sources`, and
   `GET /v1/data_sources/{data_source_id}` confirms the schema. Do not reuse a
   `database_id` where a `data_source_id` is required.
3. Export both values for one shell session and run the script:

   ```sh
   export NOTION_TOKEN=ntn_...            # never commit this
   export NOTION_DATA_SOURCE_ID=...
   python3 scripts/notion_roundtrip_proof.py --burst 20 \
       --out docs/NOTION_ROUNDTRIP.md
   ```

4. The script creates one row titled `Round-trip probe <timestamp>` with the
   note "Safe to delete", reads it back, then records the result. Delete the
   row afterwards. The report is written to `docs/NOTION_ROUNDTRIP.md`; commit
   that, with the run timestamp filled in.

### Dry-run output (actually executed, no network)

`python3 scripts/notion_roundtrip_proof.py --dry-run` printed a plan with
16 probe blocks created in a single `POST /pages` request, a paginated
`GET /blocks/{page_id}/children?page_size=100` read, a paginated
`POST /data_sources/{data_source_id}/query` read, and a burst of small reads to
observe rate limiting.

## What the script writes

The task page body carries these formatting primitives, one per row of the
fidelity table:

| # | Block |
|---|---|
| 0 | `heading_1` |
| 1 | `heading_2` with mixed bold/italic rich text |
| 2 | paragraph with bold, italic, strikethrough, underline, code, red text, yellow background |
| 3 | paragraph with a hyperlink |
| 4 | paragraph containing an inline newline |
| 5 | paragraph with leading and trailing spaces |
| 6 | `bulleted_list_item` |
| 7 | `numbered_list_item` |
| 8 | `to_do` checked |
| 9 | `to_do` unchecked |
| 10 | `quote` |
| 11 | `callout` with emoji icon and blue background |
| 12 | `code` with language and caption |
| 13 | `divider` |
| 14 | `toggle` with a nested paragraph child |
| 15 | `heading_3` with `is_toggleable` |

The script compares the written rich text, annotations (bold, italic,
strikethrough, underline, code, colour), links, `checked`, `language`,
`callout.icon`, `callout.color` and `is_toggleable`, and recurses one level
into `toggle` children. A verdict is one of `PRESERVED`, `ALTERED` or `LOST`.

## Documented expectations (to be confirmed live)

Notion's API exposes a defined set of block types and rich-text annotations, and
some Notion-editor features have no API representation. That leads to the
following expectations, which the live run should confirm or correct:

| Feature | Expected result | Why |
|---|---|---|
| Supported block types (headings, lists, to-do, quote, callout, code, divider, toggle) | PRESERVED | All are first-class API block types |
| `bold`/`italic`/`strikethrough`/`underline`/`code`/`color` annotations | PRESERVED | Part of the rich-text `annotations` object |
| Hyperlink on a text run | PRESERVED | Stored as `text.link.url` |
| Callout icon and colour | PRESERVED | `callout.icon` and `callout.color` are returned |
| Code block language and caption | PRESERVED | `code.language`, `code.caption` are returned |
| Toggle's nested child block | PRESERVED, but needs a second paginated read | `has_children` is true; children are not inlined |
| Numbered list start value | ALTERED/LOST | The API stores list items, not a starting number |
| Text alignment | ALTERED/LOST | Paragraph alignment is not exposed by the API |
| Inline newline inside one paragraph | ALTERED/LOST | Newlines can be split into separate blocks or dropped |
| Leading/trailing whitespace | ALTERED | Rich text is normalised on write |
| Block types with no API model (synced blocks, table of contents, template buttons) | LOST/UNSUPPORTED | Returned as `unsupported` or absent |

## Fidelity results (paste the live report here)

_Not run. Replace this section with the `## Formatting round-trip` table the
script emits._

## Rate-limit results (paste the live report here)

_Not run. Replace this section with the `## Rate-limit behaviour` block the
script emits: burst size, 429 count, first 429 index, Retry-After values, and
latency min/mean/max._
