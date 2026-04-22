#!/usr/bin/env python3
"""
Markdown parser — extracts blocks, tasks, events, and references
with proper heading-based parent hierarchy and nested list support.
"""
import asyncio
import traceback
from pathlib import Path
from typing import List, Dict, Tuple, Any, Optional

from markdown_it import MarkdownIt
from mdit_py_plugins.front_matter import front_matter_plugin
import re

from src.core.queue import parser_queue
from src.core.events import ParseEvent
from src.ingestion.db import upsert_note, insert_blocks, insert_tasks, insert_references

# ---------------------------------------------------------------------------
# Regex patterns
# ---------------------------------------------------------------------------

# Tasks: "[ ] text", "[x] text", "[X] text", "TODO text"
TASK_PATTERN = re.compile(r'^(?:\[([ xX])\]|TODO)\s+(.+)')

# Due date:  "due: 2026-04-22" or "@due 2026-04-22"
DUE_DATE_PATTERN = re.compile(r'(?:due:|@due)\s*(\d{4}-\d{2}-\d{2})', re.I)

# Start date: "@start 2026-04-22"
START_DATE_PATTERN = re.compile(r'@start\s*(\d{4}-\d{2}-\d{2})', re.I)

# Priority:  "[!]" → high,  "[?]" → medium   (anywhere in text)
PRIORITY_PATTERN = re.compile(r'\[([!?])\]')

# Inline tags:  #tag  (must NOT be inside a link)
TAG_PATTERN = re.compile(r'(?<!\[)#([A-Za-z][\w-]*)')

# Recurrence: "every day", "every week", "daily", "weekly", "monthly"
RECURRENCE_PATTERN = re.compile(
    r'\b(every\s+(?:day|week|month|year)|daily|weekly|monthly|yearly)\b', re.I
)

# Wikilinks: [[target]] or [[target#block]]
LINK_PATTERN = re.compile(r'\[\[([^\]]+)\]\]')

# ---------------------------------------------------------------------------
# Event detection patterns
# ---------------------------------------------------------------------------

# ISO date: 2026-04-22
DATE_ISO = re.compile(r'\b(\d{4}-\d{2}-\d{2})\b')

# Slash date: 22/04/2026  or  04/22/2026
DATE_SLASH = re.compile(r'\b(\d{1,2}/\d{1,2}/\d{4})\b')

# English date: "April 22, 2026" or "Apr 22 2026"
DATE_ENGLISH = re.compile(
    r'\b((?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?'
    r'|Jul(?:y)?|Aug(?:ust)?|Sep(?:tember)?|Oct(?:ober)?|Nov(?:ember)?'
    r'|Dec(?:ember)?)\s+\d{1,2},?\s*\d{4})\b', re.I
)

# Time: "10:00 AM", "14:30", "2:00pm"
TIME_PATTERN = re.compile(r'\b(\d{1,2}:\d{2}\s*(?:AM|PM|am|pm)?)\b')

# Time range: "10:00-11:00" or "10:00 AM - 2:00 PM"
TIME_RANGE = re.compile(
    r'\b(\d{1,2}:\d{2}\s*(?:AM|PM|am|pm)?)\s*[-–]\s*(\d{1,2}:\d{2}\s*(?:AM|PM|am|pm)?)\b'
)

# Date range: "2026-04-22 to 2026-04-25"
DATE_RANGE = re.compile(r'(\d{4}-\d{2}-\d{2})\s+to\s+(\d{4}-\d{2}-\d{2})', re.I)


# ---------------------------------------------------------------------------
# Core parser
# ---------------------------------------------------------------------------

def _extract_heading_level(tag: str) -> Optional[int]:
    """Extract numeric heading level from tag like 'h1', 'h2', etc."""
    if tag and tag.startswith('h') and len(tag) == 2 and tag[1].isdigit():
        return int(tag[1])
    return None


def _detect_event(content: str) -> Optional[Dict[str, Any]]:
    """Check if content contains event-like patterns. Returns metadata or None."""
    meta: Dict[str, Any] = {}

    dr = DATE_RANGE.search(content)
    if dr:
        meta['date_start'] = dr.group(1)
        meta['date_end'] = dr.group(2)
    else:
        dates = DATE_ISO.findall(content) or DATE_SLASH.findall(content)
        en = DATE_ENGLISH.findall(content)
        if dates:
            meta['date'] = dates[0]
        elif en:
            meta['date'] = en[0]

    tr = TIME_RANGE.search(content)
    if tr:
        meta['time_start'] = tr.group(1).strip()
        meta['time_end'] = tr.group(2).strip()
    else:
        ts = TIME_PATTERN.findall(content)
        if ts:
            meta['time'] = ts[0].strip()

    return meta if meta else None


def _extract_task_meta(content: str, task_text: str, checkbox_val: str,
                       block_id: int) -> Dict[str, Any]:
    """Build a task dict with all extracted metadata."""
    is_done = 1 if checkbox_val and checkbox_val.lower() == 'x' else 0

    # Due date
    due_match = DUE_DATE_PATTERN.search(task_text)
    due_date = due_match.group(1) if due_match else None

    # Start date
    start_match = START_DATE_PATTERN.search(task_text)
    start_date = start_match.group(1) if start_match else None

    # Priority
    pri_match = PRIORITY_PATTERN.search(task_text)
    priority = None
    if pri_match:
        priority = 'high' if pri_match.group(1) == '!' else 'medium'

    # Tags
    tags_list = TAG_PATTERN.findall(task_text)
    tags = ','.join(tags_list) if tags_list else None

    # Recurrence
    rec_match = RECURRENCE_PATTERN.search(task_text)
    recurrence = rec_match.group(1).lower() if rec_match else None

    # Clean title — strip metadata markers
    clean = task_text
    for pat in (DUE_DATE_PATTERN, START_DATE_PATTERN, PRIORITY_PATTERN,
                RECURRENCE_PATTERN):
        clean = pat.sub('', clean)
    # Remove tags from title
    clean = TAG_PATTERN.sub('', clean).strip()
    # Collapse whitespace
    clean = re.sub(r'\s{2,}', ' ', clean).strip()

    return {
        'raw_text': content,
        'title': clean,
        'is_done': is_done,
        'due_date': due_date,
        'start_date': start_date,
        'priority': priority,
        'tags': tags,
        'recurrence': recurrence,
        'block_id': block_id,
    }


def parse_markdown(path: Path, raw_content: str
                   ) -> Tuple[str, List[Dict], List[Dict], List[Dict]]:
    """
    Parse markdown into (title, blocks, tasks, references).

    Parent hierarchy logic:
    - Headings build a section stack (h1 > h2 > h3 …).
      A heading's parent is the last heading with a *smaller* level number.
    - Non-heading blocks (paragraphs, lists) inherit the current
      innermost heading as their parent.
    - Nested list items inherit the surrounding list item as parent.
    """
    try:
        md = MarkdownIt().use(front_matter_plugin)
        tokens = md.parse(raw_content)

        title = path.stem
        blocks: List[Dict[str, Any]] = []
        tasks: List[Dict[str, Any]] = []
        references: List[Dict[str, Any]] = []

        # Heading section stack: [(heading_level, block_id)]
        heading_stack: List[Tuple[int, int]] = []

        # List nesting stack: [block_id of enclosing list_item inline]
        list_item_stack: List[int] = []
        # Depth counter for list_item nesting
        list_depth = 0

        block_id = 0
        in_list_item = False
        in_heading = False
        current_heading_tag: Optional[str] = None

        i = 0
        while i < len(tokens):
            tok = tokens[i]
            ttype = getattr(tok, 'type', '')

            # Skip front matter
            if ttype == 'front_matter':
                i += 1
                continue

            # ---- list item open/close tracking ----
            if ttype == 'list_item_open':
                list_depth += 1
                in_list_item = True
            elif ttype == 'list_item_close':
                list_depth -= 1
                in_list_item = list_depth > 0
                if list_item_stack:
                    list_item_stack.pop()

            # ---- heading open/close tracking ----
            elif ttype == 'heading_open':
                in_heading = True
                current_heading_tag = getattr(tok, 'tag', None)
                # Capture title from first heading, only if it's currently the fallback path.stem
                if title == path.stem and i + 1 < len(tokens) and getattr(tokens[i + 1], 'type', '') == 'inline':
                    c = getattr(tokens[i + 1], 'content', '').strip()
                    if c:
                        title = c
            elif ttype == 'heading_close':
                in_heading = False
                current_heading_tag = None

            # ---- process inline tokens (actual content) ----
            if ttype == 'inline':
                content = getattr(tok, 'content', '').strip()
                if not content:
                    i += 1
                    continue

                # --- determine block_type ---
                block_type = 'paragraph'
                if in_heading:
                    block_type = 'heading'
                elif in_list_item:
                    block_type = 'list'

                # Task detection
                task_match = TASK_PATTERN.match(content)
                if task_match:
                    block_type = 'task'

                # Event detection (only if not already a task)
                event_meta = None
                if block_type not in ('task',):
                    event_meta = _detect_event(content)
                    if event_meta:
                        block_type = 'event'

                # --- compute parent_block ---
                if in_heading:
                    hlevel = _extract_heading_level(current_heading_tag)
                    # Pop heading stack until we find a level < this one
                    while heading_stack and heading_stack[-1][0] >= (hlevel or 99):
                        heading_stack.pop()
                    parent_block = heading_stack[-1][1] if heading_stack else None
                elif in_list_item and list_item_stack:
                    # Nested list items → parent is enclosing list item
                    parent_block = list_item_stack[-1]
                else:
                    # Regular block → parent is current innermost heading
                    parent_block = heading_stack[-1][1] if heading_stack else None

                # Position
                t_map = getattr(tok, 'map', None)
                position = (t_map[0] if t_map and isinstance(t_map, (list, tuple))
                            and len(t_map) > 0 else 0)

                # Heading level for heading blocks
                level = _extract_heading_level(current_heading_tag) if in_heading else list_depth

                blocks.append({
                    'id': block_id,
                    'block_type': block_type,
                    'content': content,
                    'level': level,
                    'position': position,
                    'parent_block': parent_block,
                })

                # If this is a heading, push onto heading stack
                if in_heading and current_heading_tag:
                    hlevel = _extract_heading_level(current_heading_tag)
                    if hlevel:
                        heading_stack.append((hlevel, block_id))

                # If this is a list item, push onto list_item_stack
                if in_list_item:
                    list_item_stack.append(block_id)

                # --- extract task metadata ---
                if task_match:
                    tasks.append(_extract_task_meta(
                        content, task_match.group(2).strip(),
                        task_match.group(1), block_id,
                    ))

                # --- extract references ---
                for lm in LINK_PATTERN.finditer(content):
                    link_target = lm.group(1).strip()
                    if '#' in link_target:
                        tgt_title, tgt_block = link_target.split('#', 1)
                        tgt_title = tgt_title.strip()
                        tgt_block = tgt_block.strip()
                    else:
                        tgt_title = link_target
                        tgt_block = None
                    references.append({
                        'source_block_id': block_id,
                        'target_title': tgt_title,
                        'target_block': tgt_block,
                        'reference_type': 'link',
                    })

                block_id += 1

            i += 1

        return title, blocks, tasks, references

    except Exception as e:
        print(f"--> [ERROR] Markdown parsing failed for {path}: {e}")
        traceback.print_exc()
        return path.stem, [], [], []


# ---------------------------------------------------------------------------
# Reference resolver & worker
# ---------------------------------------------------------------------------

from src.ingestion.sync_worker import sync_trigger


async def _resolve_references(references: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Resolve target_title to target_note_id and optionally target_block_id."""
    from src.ingestion.db import get_connection

    resolved = []
    for ref in references:
        target_title = ref['target_title']
        target_block = ref.get('target_block')

        async with get_connection() as conn:
            cursor = await conn.execute(
                "SELECT id FROM notes WHERE title=? AND deleted_at IS NULL",
                (target_title,)
            )
            note_row = await cursor.fetchone()

            if note_row:
                target_note_id = note_row['id']
                target_block_id = None

                if target_block:
                    cursor = await conn.execute(
                        "SELECT id FROM blocks WHERE note_id=? AND content LIKE ?",
                        (target_note_id, f"%{target_block}%")
                    )
                    block_row = await cursor.fetchone()
                    if block_row:
                        target_block_id = block_row['id']

                resolved.append({
                    'source_block_id': ref['source_block_id'],
                    'target_note_id': target_note_id,
                    'target_block_id': target_block_id,
                    'target_title': target_title,
                    'reference_type': ref.get('reference_type', 'link'),
                })

    return resolved


async def parser_worker() -> None:
    """Consumes ParseEvents from parser_queue and processes them."""
    while True:
        try:
            event: ParseEvent = await parser_queue.get()
            title, blocks, tasks, references = parse_markdown(event.path, event.raw_content)

            note_id = await upsert_note(event.path, title, event.note_type,
                                        event.raw_content, event.event_type)
            await insert_blocks(note_id, blocks)
            await insert_tasks(note_id, tasks)

            if references:
                resolved_refs = await _resolve_references(references)
                if resolved_refs:
                    await insert_references(note_id, resolved_refs)

            sync_trigger.set()
            print(f"Processed {event.event_type}: {event.path} (ID: {note_id})")

        except Exception as e:
            print(f"--> [ERROR] Parser worker failed: {e}")
        finally:
            parser_queue.task_done()
