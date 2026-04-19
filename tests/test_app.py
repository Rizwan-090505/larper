import asyncio
import importlib
import os
import sqlite3
import sys
import unittest
from pathlib import Path

TEST_ENV = {
    "API_KEY": "test_api_key",
    "ACTIVE_FOLDER": "./test_data",
    "MODEL": "test_model",
    "DB_PATH": "./test_data/test_larper.db",
}


def reload_config(env: dict):
    for key, value in env.items():
        os.environ[key] = value

    if "config" in sys.modules:
        importlib.reload(sys.modules["config"])
    else:
        import config
        sys.modules["config"] = config

    return sys.modules["config"]


class TestLarper(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.root = Path(__file__).resolve().parents[1]
        self.test_data = self.root / "test_data"
        self.test_data.mkdir(exist_ok=True)

    def tearDown(self):
        # Clean up any test database files after each test
        db_path = self.test_data / "test_larper.db"
        if db_path.exists():
            db_path.unlink()

    def test_config_loads_env(self):
        config = reload_config(TEST_ENV)
        self.assertEqual(config.settings.API_KEY, TEST_ENV["API_KEY"])
        self.assertEqual(config.settings.ACTIVE_FOLDER, TEST_ENV["ACTIVE_FOLDER"])
        self.assertEqual(config.settings.MODEL, TEST_ENV["MODEL"])
        self.assertEqual(config.settings.DB_PATH, TEST_ENV["DB_PATH"])

    async def test_init_db_creates_tables(self):
        config = reload_config(TEST_ENV)
        import src.ingestion.db as db_module
        importlib.reload(db_module)

        await db_module.init_db()

        db_path = self.root / TEST_ENV["DB_PATH"]
        self.assertTrue(db_path.exists())

        with sqlite3.connect(db_path) as conn:
            cursor = conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
            tables = {row[0] for row in cursor.fetchall()}

        self.assertIn("notes", tables)
        self.assertIn("blocks", tables)
        self.assertIn("tasks", tables)
        self.assertIn("sync_log", tables)

    def test_parse_markdown_extracts_tasks_and_blocks(self):
        from src.ingestion.parser import parse_markdown

        sample = """# Test Title\n\n- [ ] Write tests due:2026-04-20\n- [x] Review code\n"""
        title, blocks, tasks = parse_markdown(Path("test.md"), sample)

        self.assertEqual(title, "Test Title")
        self.assertTrue(any(block["block_type"] == "task" for block in blocks))
        self.assertEqual(len(tasks), 2)
        self.assertEqual(tasks[0]["title"], "Write tests")
        self.assertEqual(tasks[0]["due_date"], "2026-04-20")
        self.assertEqual(tasks[1]["is_done"], 1)

    async def test_upsert_note_and_query_task(self):
        config = reload_config(TEST_ENV)
        import src.ingestion.db as db_module
        importlib.reload(db_module)

        await db_module.init_db()

        note_id = await db_module.upsert_note(
            file_path="./test_data/sample.md",
            title="Sample",
            note_type="page",
            raw_content="Hello world",
            event_type="created",
        )

        await db_module.insert_blocks(note_id, [
            {"block_type": "paragraph", "content": "Hello world", "level": None, "position": 0, "parent_block": None}
        ])

        db_path = self.root / TEST_ENV["DB_PATH"]
        with sqlite3.connect(db_path) as conn:
            cursor = conn.execute("SELECT id FROM blocks WHERE note_id=?", (note_id,))
            block_id = cursor.fetchone()[0]

        await db_module.insert_tasks(note_id, [
            {"block_id": block_id, "raw_text": "[ ] sample task", "title": "sample task", "is_done": 0, "due_date": None}
        ])

        with sqlite3.connect(db_path) as conn:
            cursor = conn.execute("SELECT COUNT(*) FROM notes")
            self.assertEqual(cursor.fetchone()[0], 1)
            cursor = conn.execute("SELECT COUNT(*) FROM tasks")
            self.assertEqual(cursor.fetchone()[0], 1)


if __name__ == "__main__":
    unittest.main()
