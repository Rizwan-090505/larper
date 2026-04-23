import traceback
from pathlib import Path
from typing import List, Dict, Tuple, Any, Optional

from markdown_it import MarkdownIt
from mdit_py_plugins.front_matter import front_matter_plugin

from src.ingestion.parser.patterns import TASK_PATTERN, LINK_PATTERN
from src.ingestion.parser.extractors import _extract_heading_level, _detect_event, _extract_task_meta

def parse_markdown(path: Path, raw_content: str
                   ) -> Tuple[str, List[Dict], List[Dict], List[Dict]]:
    """
    Parse markdown into (title, blocks, tasks, references).
    Parent hierarchy logic:
    - Headings build a section stack (h1 > h2 > h3 …).
      A heading's parent is the last heading with a *smaller* level number.
    - Non-heading blocks (paragraphs, lists) inherit the current innermost heading as parent.
    - Nested list items inherit the surrounding list item as parent.
    """
    try:
        md = MarkdownIt().use(front_matter_plugin)
        tokens = md.parse(raw_content)

        title = path.stem
        blocks: List[Dict[str, Any]] = []
        tasks: List[Dict[str, Any]] = []
        references: List[Dict[str, Any]] = []

        heading_stack: List[Tuple[int, int]] = []
        list_item_stack: List[int] = []
        list_depth = 0

        block_id = 0
        in_list_item = False
        in_heading = False
        current_heading_tag: Optional[str] = None

        i = 0
        while i < len(tokens):
            tok = tokens[i]
            ttype = getattr(tok, 'type', '')

            if ttype == 'front_matter':
                i += 1
                continue

            if ttype == 'list_item_open':
                list_depth += 1
                in_list_item = True
            elif ttype == 'list_item_close':
                list_depth -= 1
                in_list_item = list_depth > 0
                if list_item_stack:
                    list_item_stack.pop()
            elif ttype == 'heading_open':
                in_heading = True
                current_heading_tag = getattr(tok, 'tag', None)
                if title == path.stem and i + 1 < len(tokens) and getattr(tokens[i + 1], 'type', '') == 'inline':
                    c = getattr(tokens[i + 1], 'content', '').strip()
                    if c:
                        title = c
            elif ttype == 'heading_close':
                in_heading = False
                current_heading_tag = None

            if ttype == 'inline':
                content = getattr(tok, 'content', '').strip()
                if not content:
                    i += 1
                    continue

                block_type = 'paragraph'
                if in_heading:
                    block_type = 'heading'
                elif in_list_item:
                    block_type = 'list'

                task_match = TASK_PATTERN.match(content)
                if task_match:
                    block_type = 'task'

                event_meta = None
                if block_type not in ('task',):
                    event_meta = _detect_event(content)
                    if event_meta:
                        block_type = 'event'

                if in_heading:
                    hlevel = _extract_heading_level(current_heading_tag)
                    while heading_stack and heading_stack[-1][0] >= (hlevel or 99):
                        heading_stack.pop()
                    parent_block = heading_stack[-1][1] if heading_stack else None
                elif in_list_item and list_item_stack:
                    parent_block = list_item_stack[-1]
                else:
                    parent_block = heading_stack[-1][1] if heading_stack else None

                t_map = getattr(tok, 'map', None)
                position = (t_map[0] if t_map and isinstance(t_map, (list, tuple))
                            and len(t_map) > 0 else 0)

                level = _extract_heading_level(current_heading_tag) if in_heading else list_depth

                blocks.append({
                    'id': block_id,
                    'block_type': block_type,
                    'content': content,
                    'level': level,
                    'position': position,
                    'parent_block': parent_block,
                })

                if in_heading and current_heading_tag:
                    hlevel = _extract_heading_level(current_heading_tag)
                    if hlevel:
                        heading_stack.append((hlevel, block_id))

                if in_list_item:
                    list_item_stack.append(block_id)

                if task_match:
                    tasks.append(_extract_task_meta(
                        content, task_match.group(2).strip(),
                        task_match.group(1), block_id,
                    ))

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
