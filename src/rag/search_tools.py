from __future__ import annotations

import re
from pathlib import Path
from typing import List, Dict, Any, Set
from config import settings
from src.rag.retrieval import search_and_enrich_blocks
from src.ingestion.db.blocks import get_enriched_blocks_data
from src.ingestion.db.connection import get_connection


TOKEN_RE = re.compile(r"[a-z0-9][a-z0-9_-]*", re.IGNORECASE)


def _active_folder() -> Path:
    return Path(settings.ACTIVE_FOLDER).resolve()


def _display_path(file_path: str) -> str:
    path = Path(str(file_path).strip("\"'"))
    try:
        return path.resolve().relative_to(_active_folder()).as_posix()
    except (ValueError, OSError):
        return path.as_posix()


def normalize_result_paths(results: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    normalized = []
    for result in results:
        item = dict(result)
        if item.get("file_path"):
            item["file_path"] = _display_path(item["file_path"])
        if item.get("file"):
            item["file"] = _display_path(item["file"])
        normalized.append(item)
    return normalized

async def bm25_search(query: str, k: int | None = None) -> List[Dict[str, Any]]:
    """Approximate BM25 via existing hybrid retrieval (placeholder)."""
    k = k or settings.RAG_DEFAULT_K
    return normalize_result_paths(await search_and_enrich_blocks(query, k=k))


async def hybrid_search(query: str, k: int | None = None) -> List[Dict[str, Any]]:
    """Hybrid DB/vector search with a filesystem fallback for unindexed notes."""
    k = k or settings.RAG_DEFAULT_K
    try:
        results = await search_and_enrich_blocks(query, k=k)
    except Exception:
        results = []
    normalized = normalize_result_paths(results)
    if normalized:
        return normalized
    return await filesystem_search(query, k=k)


async def fzf_search(query: str, k: int | None = None) -> List[Dict[str, Any]]:
    """Simple fuzzy substring search across note titles and block content."""
    k = k or settings.RAG_DEFAULT_K
    if not query or not query.strip():
        return []

    q = f"%{query.strip().lower()}%"
    results = []
    try:
        async with get_connection() as conn:
            cursor = await conn.execute(
                """
                SELECT b.id, b.content, n.title, n.file_path
                FROM blocks b
                JOIN notes n ON b.note_id = n.id
                WHERE n.deleted_at IS NULL
                  AND (LOWER(b.content) LIKE ? OR LOWER(n.title) LIKE ? OR LOWER(n.file_path) LIKE ?)
                ORDER BY n.updated_at DESC
                LIMIT ?
                """,
                (q, q, q, k),
            )
            rows = await cursor.fetchall()
    except Exception:
        rows = []

    for row in rows:
        results.append({
            "id": row["id"],
            "content": row["content"],
            "title": row["title"],
            "file_path": _display_path(row["file_path"]),
        })

    return results or await filesystem_search(query, k=k)


async def filesystem_search(query: str, k: int | None = None) -> List[Dict[str, Any]]:
    """Search markdown files directly under ACTIVE_FOLDER."""
    k = k or settings.RAG_DEFAULT_K
    tokens = [token.lower() for token in TOKEN_RE.findall(query)]
    if not tokens:
        return []

    matches: list[tuple[float, float, Dict[str, Any]]] = []
    folder = _active_folder()
    for fp in folder.rglob("*.md"):
        try:
            rel = fp.relative_to(folder)
        except ValueError:
            continue
        if any(part.startswith(".") for part in rel.parts):
            continue
        try:
            content = fp.read_text(encoding="utf-8", errors="replace")
            stat = fp.stat()
        except OSError:
            continue

        haystack = f"{rel.as_posix()} {fp.stem} {content}".lower()
        hit_count = sum(1 for token in tokens if token in haystack)
        if not hit_count:
            continue

        first_line = next((line.strip("# ").strip() for line in content.splitlines() if line.strip()), fp.stem)
        score = hit_count / max(len(tokens), 1)
        matches.append((
            score,
            stat.st_mtime,
            {
                "id": rel.as_posix(),
                "content": content,
                "title": first_line or fp.stem,
                "file_path": rel.as_posix(),
                "hybrid_score": score,
                "similarity_score": score,
            },
        ))

    matches.sort(key=lambda item: (item[0], item[1]), reverse=True)
    return [item for _, _, item in matches[:k]]


async def tag_search(tag: str, k: int | None = None) -> List[Dict[str, Any]]:
    """Search blocks by tag (#tag)."""
    k = k or settings.RAG_DEFAULT_K
    if not tag:
        return []
    tag = tag.lstrip("#").lower()
    async with get_connection() as conn:
        cursor = await conn.execute(
            """
            SELECT b.id, b.content, n.title, n.file_path
            FROM block_tags bt
            JOIN blocks b ON bt.block_id = b.id
            JOIN notes n ON b.note_id = n.id
            WHERE LOWER(bt.tag) = ? AND n.deleted_at IS NULL
            ORDER BY n.updated_at DESC
            LIMIT ?
            """,
            (tag, k),
        )
        rows = await cursor.fetchall()

    return [
        {"id": r["id"], "content": r["content"], "title": r["title"], "file_path": _display_path(r["file_path"])}
        for r in rows
    ]


async def ref_search(ref_title: str, k: int | None = None) -> List[Dict[str, Any]]:
    """Search block references by target title or [[reference]]."""
    k = k or settings.RAG_DEFAULT_K
    if not ref_title:
        return []
    q = f"%{ref_title.strip().lower()}%"
    async with get_connection() as conn:
        cursor = await conn.execute(
            """
            SELECT br.target_title, b.content, n.title, n.file_path
            FROM block_references br
            LEFT JOIN blocks b ON br.target_block_id = b.id
            JOIN notes n ON br.target_note_id = n.id
            WHERE LOWER(br.target_title) LIKE ?
            LIMIT ?
            """,
            (q, k),
        )
        rows = await cursor.fetchall()

    return [
        {"target_title": r["target_title"], "content": r["content"], "title": r["title"], "file_path": _display_path(r["file_path"])}
        for r in rows
    ]


async def graph_expand(seed_block_ids: Set[int], k: int | None = None) -> List[Dict[str, Any]]:
    """Return graph-expanded related blocks using retrieval internals."""
    k = k or settings.RAG_DEFAULT_K
    if not seed_block_ids:
        return []
    # Use the existing retrieval functions to get candidate ids via vector search
    # then call get_enriched_blocks_data for final payload
    # For simplicity, map seed_block_ids to list and request enriched data for neighbors
    enriched = await get_enriched_blocks_data(list(seed_block_ids))
    # Flatten and return up to k entries from enriched
    results = list(enriched.values())[:k]
    return normalize_result_paths(results)
