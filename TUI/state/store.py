from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional
import uuid


@dataclass
class Item:
    id: str
    text: str
    file: str
    created_at: datetime
    time: Optional[str] = None

    def is_event(self) -> bool:
        return self.time is not None


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

    def set_current_file(self, filename: str):
        self._current_file = filename
        if filename not in self._files:
            self._files[filename] = []
        if filename not in self._notes:
            self._notes.append(filename)

    def add_item(self, text: str, time: Optional[str] = None) -> Optional[Item]:
        if not self._current_file:
            return None
        item = Item(
            id=str(uuid.uuid4())[:8],
            text=text,
            file=self._current_file,
            created_at=datetime.now(),
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

    def get_todos(self) -> list[Item]:
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
        if filename not in self._notes:
            self._notes.append(filename)
        if filename not in self._files:
            self._files[filename] = []


store = Store()