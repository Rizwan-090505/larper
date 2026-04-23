import re
from typing import Dict, Any, Optional
from src.ingestion.parser.patterns import (
    DATE_RANGE, DATE_ISO, DATE_SLASH, DATE_ENGLISH,
    TIME_RANGE, TIME_PATTERN, DUE_DATE_PATTERN, START_DATE_PATTERN,
    PRIORITY_PATTERN, TAG_PATTERN, RECURRENCE_PATTERN
)

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
        meta['date_start'] = dr.group(1).replace('/', '-')
        meta['date_end'] = dr.group(2).replace('/', '-')
    else:
        dates = DATE_ISO.findall(content) or DATE_SLASH.findall(content)
        en = DATE_ENGLISH.findall(content)
        if dates:
            meta['date'] = dates[0].replace('/', '-')
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

def _extract_task_meta(content: str, task_text: str, checkbox_val: Optional[str],
                       block_id: int) -> Dict[str, Any]:
    """Build a task dict with all extracted metadata."""
    is_done = 0
    if checkbox_val:
        v = checkbox_val.lower()
        if v in ('x', 'v'):
            is_done = 1

    # Due date
    due_match = DUE_DATE_PATTERN.search(task_text)
    due_date = due_match.group(1).replace('/', '-') if due_match else None

    # Start date
    start_match = START_DATE_PATTERN.search(task_text)
    start_date = start_match.group(1).replace('/', '-') if start_match else None

    # Priority
    pri_match = PRIORITY_PATTERN.search(task_text)
    priority = None
    if pri_match:
        val = pri_match.group(1)
        priority = 'high' if '!' in val else 'medium'

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
