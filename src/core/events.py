from dataclasses import dataclass
from pathlib import Path
from typing import Literal


@dataclass(slots=True)
class FileEvent:
    path: Path
    event_type: Literal["created", "modified", "deleted"]
