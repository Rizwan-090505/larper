from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional
import sys
import os
import uuid

# Load ACTIVE_FOLDER from config.py
_root = Path(__file__).resolve().parents[3]
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))

from config import settings
ACTIVE_FOLDER = Path(settings.ACTIVE_FOLDER).resolve()

# Import database connection for task loading
from src.ingestion.db.connection import get_connection


@dataclass
class Item:
    id: str
    text: str
    file: str
    created_at: datetime
    date: Optional[str] = None
    time: Optional[str] = None

    def is_event(self) -> bool:
        return self.time is not None or self.date is not None


@dataclass
class NoteContent:
    id: str
    text: str
    file: str
    created_at: datetime


class Store:
    def __init__(self):
        self._items: dict[str, Item] = {}
        self._note_contents: dict[str, list[NoteContent]] = {}
        self._files: dict[str, list[str]] = {}
        self._current_file: Optional[str] = None
        self._notes: list[str] = []

    def get_current_file(self) -> Optional[str]:
        return self._current_file

    def normalize_note_path(self, filepath: str | Path, *, default_dir: str = "pages") -> str:
        """Return a safe, active-folder-relative markdown path."""
        raw = str(filepath).strip().strip("\"'")
        if not raw:
            raise ValueError("empty note path")

        path = Path(raw).expanduser()
        if path.is_absolute():
            try:
                rel = path.resolve().relative_to(self.get_active_folder())
            except ValueError as exc:
                raise ValueError(f"note path is outside active folder: {path}") from exc
        else:
            rel = path

        if rel.suffix.lower() != ".md":
            rel = rel.with_suffix(".md")

        # Normalize journal directory aliases so singular paths like
        # journal/2026-08-06 and pages/journal/2026-08-06 map to the
        # canonical journals/ namespace.
        if rel.parts:
            first = rel.parts[0].lower()
            second = rel.parts[1].lower() if len(rel.parts) > 1 else ""
            if first == "journal":
                rel = Path("journals", *rel.parts[1:])
            elif first == "pages" and second in ("journal", "journals"):
                rel = Path("journals", *rel.parts[2:])

        if default_dir == "pages" and (len(rel.parts) == 1 or rel.parts[0] not in ("pages", "journals")):
            rel = Path("pages") / rel
        elif len(rel.parts) == 1 and default_dir:
            rel = Path(default_dir) / rel

        if any(part in ("", ".", "..") for part in rel.parts):
            raise ValueError(f"invalid note path: {filepath}")

        return rel.as_posix()

    def resolve_note_path(self, filepath: str | Path, *, default_dir: str = "pages") -> Path:
        return self.get_active_folder() / self.normalize_note_path(
            filepath, default_dir=default_dir
        )

    def find_note_path(self, reference: str | Path) -> Path:
        """Resolve a note reference from agent/UI text to an existing path if possible."""
        raw = str(reference).strip().strip("\"'")
        if not raw:
            raise ValueError("empty note reference")

        path = Path(raw).expanduser()
        active_folder = self.get_active_folder()

        if path.is_absolute():
            return path.resolve()

        rel = path if path.suffix.lower() == ".md" else path.with_suffix(".md")
        direct = active_folder / rel
        if direct.exists():
            return direct

        candidates = []
        for fp in active_folder.rglob(rel.name):
            if not fp.is_file() or fp.suffix.lower() != ".md":
                continue
            try:
                rel_parts = fp.relative_to(active_folder).parts
            except ValueError:
                continue
            if any(part.startswith(".") for part in rel_parts):
                continue
            if len(rel.parts) == 1 or fp.as_posix().endswith(rel.as_posix()):
                candidates.append(fp)

        if candidates:
            candidates.sort(key=lambda fp: (len(fp.relative_to(active_folder).parts), str(fp)))
            return candidates[0]

        return active_folder / self.normalize_note_path(rel, default_dir="pages")

    def set_current_file(self, filename: str):
        if not filename:
            self._current_file = None
            return
        self._current_file = self.normalize_note_path(filename, default_dir="")
        if self._current_file not in self._files:
            self._files[self._current_file] = []
        if self._current_file not in self._notes:
            self._notes.append(self._current_file)

    def clear_current_file(self):
        self._current_file = None

    def add_item(
        self,
        text: str,
        time: Optional[str] = None,
        date: Optional[str] = None,
    ) -> Optional[Item]:
        if not self._current_file:
            return None
        item = Item(
            id=str(uuid.uuid4())[:8],
            text=text,
            file=self._current_file,
            created_at=datetime.now(),
            date=date,
            time=time,
        )
        self._items[item.id] = item
        self._files.setdefault(self._current_file, []).append(item.id)
        return item

    def add_note_content(self, text: str) -> Optional[NoteContent]:
        if not self._current_file:
            return None
        nc = NoteContent(
            id=str(uuid.uuid4())[:8],
            text=text,
            file=self._current_file,
            created_at=datetime.now(),
        )
        self._note_contents.setdefault(self._current_file, []).append(nc)
        return nc

    async def get_all_tasks_from_db(self) -> list[Item]:
        """Load all incomplete tasks from database."""
        try:
            async with get_connection() as conn:
                cursor = await conn.execute("""
                    SELECT t.title, t.due_date, n.file_path
                    FROM tasks t
                    JOIN notes n ON t.note_id = n.id
                    WHERE t.is_done = 0 AND t.is_deleted = 0
                    ORDER BY 
                        CASE WHEN t.due_date IS NULL THEN 1 ELSE 0 END,
                        t.due_date,
                        t.title
                """)
                rows = await cursor.fetchall()
                
                tasks = []
                for row in rows:
                    task = Item(
                        id=str(uuid.uuid4())[:8],
                        text=row['title'],
                        file=row['file_path'],
                        created_at=datetime.now(),
                        date=row['due_date']
                    )
                    tasks.append(task)
                return tasks
        except Exception:
            return []

    def get_todos(self) -> list[Item]:
        """Get tasks from current file (compatibility)."""
        if not self._current_file:
            return []
        return [
            self._items[iid]
            for iid in self._files.get(self._current_file, [])
            if not self._items[iid].is_event()
        ]

    def get_events(self) -> list[Item]:
        if not self._current_file:
            return []
        return [
            self._items[iid]
            for iid in self._files.get(self._current_file, [])
            if self._items[iid].is_event()
        ]

    def get_notes(self) -> list[str]:
        return list(self._notes)

    def get_note_contents(self, filename: str) -> list[NoteContent]:
        return self._note_contents.get(filename, [])

    def get_file_content(self, filename: str) -> list[Item]:
        return [self._items[iid] for iid in self._files.get(filename, [])]

    def add_note_file(self, filename: str):
        filename = self.normalize_note_path(filename, default_dir="")
        if filename not in self._notes:
            self._notes.append(filename)
        if filename not in self._files:
            self._files[filename] = []

    def remove_note_file(self, filename: str):
        try:
            filename = self.normalize_note_path(filename, default_dir="")
        except ValueError:
            filename = str(filename)
        if filename in self._notes:
            self._notes.remove(filename)
        self._files.pop(filename, None)
        self._note_contents.pop(filename, None)
        if self._current_file == filename:
            self._current_file = None

    # ─── Disk Save ────────────────────────────────────────────────────────────

    def _ensure_dir(self, subdir: str) -> Path:
        target = ACTIVE_FOLDER / subdir
        target.mkdir(parents=True, exist_ok=True)
        return target

    def save_note_to_disk(self, content: str, subdir: str, filename: str) -> Path:
        target_dir = self._ensure_dir(subdir)
        filepath = target_dir / filename
        filepath.write_text(content, encoding="utf-8")
        self.add_note_file(str(Path(subdir) / filename))
        return filepath

    def append_line_to_current_file(self, line: str, subdir: str = "journals") -> Optional[Path]:
        if not self._current_file:
            return None
        filepath = self.get_active_folder() / self._current_file
        filepath.parent.mkdir(parents=True, exist_ok=True)
        existing = filepath.read_text(encoding="utf-8") if filepath.exists() else ""
        separator = "" if existing.endswith("\n") or not existing else "\n"
        filepath.write_text(f"{existing}{separator}{line}\n", encoding="utf-8")
        self.add_note_file(str(filepath.relative_to(self.get_active_folder())))
        return filepath

    def get_active_folder(self) -> Path:
        return ACTIVE_FOLDER


store = Store()
