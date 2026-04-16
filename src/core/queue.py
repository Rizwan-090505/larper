import asyncio
from typing import Final
from .events import FileEvent, ParseEvent

event_queue: Final[asyncio.Queue[FileEvent]] = asyncio.Queue()
parser_queue: Final[asyncio.Queue[ParseEvent]] = asyncio.Queue()
