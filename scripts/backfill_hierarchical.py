# scripts/backfill_hierarchical.py
import asyncio
from src.ingestion.db.connection import get_connection
from src.rag.multi_hierarchical import get_hierarchical_db


async def backfill():
    print("Loading existing blocks from DB...")
    async with get_connection() as conn:
        cursor = await conn.execute("""
            SELECT b.id, b.content, b.note_id, n.title, n.file_path
            FROM blocks b
            JOIN notes n ON b.note_id = n.id
            WHERE n.deleted_at IS NULL
            ORDER BY n.id
        """)
        rows = await cursor.fetchall()

    print(f"Found {len(rows)} blocks. Building hierarchical indexes...")
    hier = get_hierarchical_db()

    # Process in batches of 100 to avoid memory spikes
    BATCH = 100
    for i in range(0, len(rows), BATCH):
        batch = rows[i : i + BATCH]
        await hier.add_hierarchical_embeddings(
            block_ids=[r["id"] for r in batch],
            contents=[r["content"] for r in batch],
            note_ids=[r["note_id"] for r in batch],
            titles=[r["title"] for r in batch],
            file_paths=[r["file_path"] for r in batch],
        )
        print(f"  {min(i + BATCH, len(rows))}/{len(rows)}")

    print(f"Done. {hier.size} blocks indexed.")


asyncio.run(backfill())
