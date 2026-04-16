from dataclasses import dataclass
from pathlib import Path
from typing import Literal


@dataclass(slots=True)
class FileEvent:
    path: Path
    event_type: Literal["created", "modified", "deleted"]

@dataclass(slots=True)
class ParseEvent:
    path: Path
    raw_content: str
    note_type: str
    event_type: str
