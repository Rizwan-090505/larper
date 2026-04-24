import re

TASK_PATTERN = re.compile(
    r'''
    ^\s*
    (?:[*\-]\s+)?
    (?:
        \[\s*([xXvV\-\~_\!\?]?)\s*\]
        |
        TODO\s*:?\s*
    )
    \s*(.+)
    ''',
    re.IGNORECASE | re.VERBOSE
)

DATE_ISO = re.compile(r'\b(\d{4}[-/]\d{2}[-/]\d{2})\b')

DATE_SLASH = re.compile(r'\b(\d{1,2}[-/]\d{1,2}[-/]\d{4})\b')

DATE_ENGLISH = re.compile(
    r'\b('
    r'(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|'
    r'Jul(?:y)?|Aug(?:ust)?|Sep(?:tember)?|Oct(?:ober)?|Nov(?:ember)?|'
    r'Dec(?:ember)?)'
    r'\s+\d{1,2},?\s*\d{4}'
    r')\b',
    re.IGNORECASE
)

DATE_RANGE = re.compile(
    r'(\d{4}[-/]\d{2}[-/]\d{2})\s*(?:to|\-|until|through)\s*(\d{4}[-/]\d{2}[-/]\d{2})',
    re.IGNORECASE
)

TIME_PATTERN = re.compile(
    r'\b(\d{1,2}:\d{2}\s*(?:AM|PM|am|pm)?)\b'
)

TIME_RANGE = re.compile(
    r'\b(\d{1,2}:\d{2}\s*(?:AM|PM|am|pm)?)\s*[-–to]+\s*'
    r'(\d{1,2}:\d{2}\s*(?:AM|PM|am|pm)?)\b',
    re.IGNORECASE
)

PRIORITY_PATTERN = re.compile(r'\[([!?]{1,3})\]')

# FIXED: removed \p{L} (not supported by Python re)
TAG_PATTERN = re.compile(r'(?<![\[\`])#([\w\-]+)', re.UNICODE)

RECURRENCE_PATTERN = re.compile(
    r'\b('
    r'every\s+(?:day|week|month|year|weekday|weekend|'
    r'\d+\s+(?:days?|weeks?|months?|years?))'
    r'|daily|weekly|monthly|yearly|biweekly|'
    r'every\s+other\s+(?:day|week|month|year)'
    r')\b',
    re.IGNORECASE
)

LINK_PATTERN = re.compile(r'\[\[([^\[\]]+?)\]\]')

DUE_DATE_PATTERN = re.compile(
    r'(?:due:|@due)\s*(\d{4}[-/]\d{2}[-/]\d{2})',
    re.IGNORECASE
)

START_DATE_PATTERN = re.compile(
    r'@start\s*(\d{4}[-/]\d{2}[-/]\d{2})',
    re.IGNORECASE
)
