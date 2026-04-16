#!/usr/bin/env python3
import asyncio
import traceback
from pathlib import Path
from typing import List, Dict, Tuple, Any

from markdown_it import MarkdownIt
from mdit_py_plugins.front_matter import front_matter_plugin
import re
from src.core.queue import parser_queue
from src.core.events import ParseEvent

TASK_PATTERN = re.compile(r'^(?:\[([ xX])\]|TODO)\s+(.+)')
DUE_DATE_PATTERN = re.compile(r'(?:due:|@due)\s*(\d{4}-\d{2}-\d{2})', re.IGNORECASE)

def parse_markdown(path: Path, raw_content: str) -> Tuple[str, List[Dict[str, Any]], List[Dict[str, Any]]]:
    try:
        md = MarkdownIt().use(front_matter_plugin)
        tokens = md.parse(raw_content)

        title = path.stem
        blocks: List[Dict[str, Any]] = []
        tasks: List[Dict[str, Any]] = []

        stack = []  # [(level, block_id)]
        block_id = 0

        in_list_item = False
        in_heading = False

        i = 0
        while i < len(tokens):
            token = tokens[i]

            if getattr(token, "type", "") == "front_matter":
                i += 1
                continue

            if getattr(token, "type", "") == "list_item_open":
                in_list_item = True
            elif getattr(token, "type", "") == "list_item_close":
                in_list_item = False
            elif getattr(token, "type", "") == "heading_open":
                in_heading = True
                # Extract title safely
                if i + 1 < len(tokens) and getattr(tokens[i + 1], "type", "") == "inline":
                    content = getattr(tokens[i + 1], "content", "").strip()
                    if content:
                        title = content
            elif getattr(token, "type", "") == "heading_close":
                in_heading = False

            if getattr(token, "type", "") == "inline":
                content = getattr(token, "content", "").strip()
                if not content:
                    i += 1
                    continue

                if in_list_item:
                    block_type = "list"
                elif in_heading:
                    block_type = "heading"
                else:
                    block_type = "paragraph"

                # Task Detection
                task_match = TASK_PATTERN.match(content)
                if task_match:
                    block_type = "task"
                    checkbox_val = task_match.group(1)
                    task_text = task_match.group(2).strip()

                    is_done = 1 if checkbox_val and checkbox_val.lower() == 'x' else 0

                    due_date_match = DUE_DATE_PATTERN.search(task_text)
                    due_date = due_date_match.group(1) if due_date_match else None

                    clean_title = DUE_DATE_PATTERN.sub('', task_text).strip()

                    tasks.append({
                        "raw_text": content,
                        "title": clean_title,
                        "is_done": is_done,
                        "due_date": due_date,
                        "block_id": block_id
                    })

                level = getattr(token, "level", 0)

                while stack and stack[-1][0] >= level:
                    stack.pop()

                parent_block = stack[-1][1] if stack else None

                t_map = getattr(token, "map", None)
                position = t_map[0] if t_map and isinstance(t_map, (list, tuple)) and len(t_map) > 0 else 0

                blocks.append({
                    "id": block_id,
                    "block_type": block_type,
                    "content": content,
                    "position": position,
                    "parent_block": parent_block
                })

                stack.append((level, block_id))
                block_id += 1

            i += 1

        return title, blocks, tasks

    except Exception as e:
        print(f"--> [ERROR] Markdown parsing failed for {path}: {e}")
        traceback.print_exc()
        return path.stem, [], []

async def parser_worker() -> None:
    """Consumes ParseEvents from parser_queue and processes them."""
    while True:
        try:
            event: ParseEvent = await parser_queue.get()
            title, blocks, tasks = parse_markdown(event.path, event.raw_content)

            # --- MOCK DB OUTPUT START ---
            print(f"\n{'='*50}")
            print(f"🛠️  MOCK DB ACTION: UPSERT NOTE ({event.event_type.upper()})")
            print(f"File Path: {event.path}")
            print(f"Title: {title}")
            print(f"Type: {event.note_type}")

            print(f"\n🧩 EXTRACTED BLOCKS ({len(blocks)} total):")
            for b in blocks:
                # Provide a safer get for indenting, defaulting to empty string
                indent = "  " * (b.get('level', 0) or 0)
                parent_info = f" (Parent Pos: {b['parent_block']})" if b['parent_block'] is not None else ""
                print(f"{indent}- [Pos {b['position']}] {b['block_type'].upper()}{parent_info}: {b['content'][:60]}...")

            print(f"\n✅ EXTRACTED TASKS ({len(tasks)} total):")
            for t in tasks:
                status = "[x]" if t['is_done'] else "[ ]"
                due = f" (Due: {t['due_date']})" if t['due_date'] else ""
                print(f"  {status} {t['title']}{due}")

            print(f"{'='*50}\n")
            # --- MOCK DB OUTPUT END ---

        except Exception as e:
            print(f"--> [ERROR] Parser worker failed: {e}")
        finally:
            parser_queue.task_done()
