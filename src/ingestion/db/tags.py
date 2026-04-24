from src.ingestion.db.connection import get_connection

async def insert_block_tags(block_ids: list[int], block_tags: list[dict]) -> None:
    """Insert hashtags associated with each block."""
    async with get_connection() as conn:
        for bt in block_tags:
            local_id = bt['block_id']
            if local_id < len(block_ids):
                db_id = block_ids[local_id]
                tag = bt['tag']
                await conn.execute("""
                    INSERT INTO block_tags (block_id, tag)
                    VALUES (?, ?)
                """, (db_id, tag))
        await conn.commit()
    print(f"--> [DB] Inserted {len(block_tags)} block tags")
