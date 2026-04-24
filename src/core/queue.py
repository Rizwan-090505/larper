import asyncio
from typing import Final
from .events import FileEvent, ParseEvent
import logging
import asyncio

# Setup logging for queue events (append to same logfile as watchdog)
logging.basicConfig(
	filename="watchdog.log",
	filemode="a",
	format="%(asctime)s %(levelname)s %(message)s",
	level=logging.INFO
)

class LoggingQueue(asyncio.Queue):
	async def put(self, item):
		logging.info(f"Queue PUT: {item}")
		return await super().put(item)

	async def get(self):
		item = await super().get()
		logging.info(f"Queue GET: {item}")
		return item

event_queue: Final[LoggingQueue] = LoggingQueue()
parser_queue: Final[LoggingQueue] = LoggingQueue()

