import re

# Tasks: "[ ] text", "[x] text", "[v] text", "TODO text", "TODO: text"
# Supports leading spacing, `- ` or `* ` usually handled by MarkdownIt but sometimes raw
TASK_PATTERN = re.compile(r'^\s*(?:[*\-]\s+)?(?:\[\s*([xXvV\-\~_]?)\s*\]|TODO\s*:?)\s+(.+)', re.IGNORECASE)

# Due date: "due: 2026-04-22" or "@due 2026/04/22"
DUE_DATE_PATTERN = re.compile(r'(?:due:|@due)\s*(\d{4}[-/]\d{2}[-/]\d{2})', re.I)

# Start date: "@start 2026-04-22"
START_DATE_PATTERN = re.compile(r'@start\s*(\d{4}[-/]\d{2}[-/]\d{2})', re.I)

# Priority: "[!]" -> high, "[?]" -> medium, "[!!]" -> high etc.
PRIORITY_PATTERN = re.compile(r'\[([!?]+)\]')

# Inline tags: #tag (must NOT be inside a link)
TAG_PATTERN = re.compile(r'(?<!\[)#([A-Za-z][\w-]*)')

# Recurrence: "every day", "daily", etc.
RECURRENCE_PATTERN = re.compile(
    r'\b(every\s+(?:day|week|month|year)|daily|weekly|monthly|yearly)\b', re.I
)

# Wikilinks: [[target]] or [[target#block]]
LINK_PATTERN = re.compile(r'\[\[([^\]]+)\]\]')

# ---------------------------------------------------------------------------
# Event detection patterns
# ---------------------------------------------------------------------------

# ISO date: 2026-04-22 or 2026/04/22
DATE_ISO = re.compile(r'\b(\d{4}[-/]\d{2}[-/]\d{2})\b')

# Slash date: 22/04/2026 or 04/22/2026
DATE_SLASH = re.compile(r'\b(\d{1,2}[-/]\d{1,2}[-/]\d{4})\b')

# English date
DATE_ENGLISH = re.compile(
    r'\b((?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?'
    r'|Jul(?:y)?|Aug(?:ust)?|Sep(?:tember)?|Oct(?:ober)?|Nov(?:ember)?'
    r'|Dec(?:ember)?)\s+\d{1,2},?\s*\d{4})\b', re.I
)

# Time: "10:00 AM", "14:30"
TIME_PATTERN = re.compile(r'\b(\d{1,2}:\d{2}\s*(?:AM|PM|am|pm)?)\b')

# Time range: "10:00-11:00"
TIME_RANGE = re.compile(
    r'\b(\d{1,2}:\d{2}\s*(?:AM|PM|am|pm)?)\s*[-–]\s*(\d{1,2}:\d{2}\s*(?:AM|PM|am|pm)?)\b'
)

# Date range: "2026-04-22 to 2026-04-25"
DATE_RANGE = re.compile(r'(\d{4}[-/]\d{2}[-/]\d{2})\s+to\s+(\d{4}[-/]\d{2}[-/]\d{2})', re.I)
