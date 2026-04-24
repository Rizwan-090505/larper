from src.ingestion.db.connection import get_connection

async def insert_block_tags(block_ids: list[int], block_tags: list[dict]) -> None:
    """Insert hashtags associated with each block.

    block_tags entries must have block_id already set to the real SQLite rowid
    (remapping from parser-local indices is done in the worker before this call).
    block_ids is kept as a parameter for the DELETE step only.
    """
    async with get_connection() as conn:
        # Clear existing tags for these blocks before re-inserting
        if block_ids:
            placeholders = ",".join("?" * len(block_ids))
            await conn.execute(
                f"DELETE FROM block_tags WHERE block_id IN ({placeholders})",
                block_ids,
            )
        for bt in block_tags:
            db_id = bt['block_id']
            if db_id is None:
                continue
            tag = bt['tag']
            await conn.execute("""
                INSERT INTO block_tags (block_id, tag)
                VALUES (?, ?)
            """, (db_id, tag))
        await conn.commit()
    print(f"--> [DB] Inserted {len(block_tags)} block tags")
