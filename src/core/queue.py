import asyncio
from typing import Final
from .events import FileEvent

event_queue: Final[asyncio.Queue[FileEvent]] = asyncio.Queue()
