async def setup_test_data():
    await init_db()

    if hasattr(vector_db, "clear"):
        await vector_db.clear()

    async with get_connection() as conn:
        await conn.execute("DELETE FROM notes WHERE file_path = ?", ("/fake/path/test.md",))
        await conn.commit()

        # Create note only
        cursor = await conn.execute(
            """
            INSERT INTO notes
            (file_path, title, note_type, raw_content, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                "/fake/path/test.md",
                "Test Note",
                "markdown",
                "raw context",
                "2023-01-01",
                "2023-01-01",
            )
        )
        note_id = cursor.lastrowid
        await conn.commit()

    # Let ONE system own block creation
    block_ids = [101, 102, 103]
    contents = [
        "The quick brown fox jumps over the lazy dog.",
        "Artificial intelligence is transforming the world.",
        "Vector databases store embeddings for fast retrieval.",
    ]

    await add_blocks_to_vector_db(block_ids, contents)
