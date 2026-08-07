"""
Search tool helpers used by the agent and TUI.

graph_expand now calls the real _graph_expand_scores from retrieval.py so
all three expansion strategies (parent/child blocks, [[wikilinks]], shared
#tags) are exercised, then enriches and returns the results.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Dict, List, Set

from config import settings
from src.rag.enhanced_retrieval import search_and_enrich_blocks
from src.ingestion.db.blocks import get_enriched_blocks_data
from src.ingestion.db.connection import get_connection

TOKEN_RE = re.compile(r"[a-z0-9][a-z0-9_-]*", re.IGNORECASE)


# ---------------------------------------------------------------------------
# Path helpers
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# Search functions
# ---------------------------------------------------------------------------


async def bm25_search(query: str, k: int | None = None) -> List[Dict[str, Any]]:
    """Approximate BM25 via hybrid retrieval."""
    k = k or settings.RAG_DEFAULT_K
    return normalize_result_paths(await search_and_enrich_blocks(query, k=k))


async def hybrid_search(query: str, k: int | None = None) -> List[Dict[str, Any]]:
    """Hybrid DB/vector search with filesystem fallback for unindexed notes."""
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

    results = [
        {
            "id": row["id"],
            "content": row["content"],
            "title": row["title"],
            "file_path": _display_path(row["file_path"]),
        }
        for row in rows
    ]
    return results or await filesystem_search(query, k=k)


async def filesystem_search(query: str, k: int | None = None) -> List[Dict[str, Any]]:
    """Search markdown files directly under ACTIVE_FOLDER."""
    k = k or settings.RAG_DEFAULT_K
    tokens = [t.lower() for t in TOKEN_RE.findall(query)]
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
        hit_count = sum(1 for t in tokens if t in haystack)
        if not hit_count:
            continue

        first_line = next(
            (ln.strip("# ").strip() for ln in content.splitlines() if ln.strip()),
            fp.stem,
        )
        score = hit_count / max(len(tokens), 1)
        matches.append(
            (
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
            )
        )

    matches.sort(key=lambda item: (item[0], item[1]), reverse=True)
    return [item for _, _, item in matches[:k]]


async def tag_search(tag: str, k: int | None = None) -> List[Dict[str, Any]]:
    """Search blocks by #tag."""
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
        {
            "id": r["id"],
            "content": r["content"],
            "title": r["title"],
            "file_path": _display_path(r["file_path"]),
        }
        for r in rows
    ]


async def ref_search(ref_title: str, k: int | None = None) -> List[Dict[str, Any]]:
    """Search block references by target title or [[reference]]."""
    k = k or settings.RAG_DEFAULT_K
    if not ref_title:
        return []
    ref_title = ref_title.strip("[]").strip()
    q = f"%{ref_title.lower()}%"
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
        {
            "target_title": r["target_title"],
            "content": r["content"],
            "title": r["title"],
            "file_path": _display_path(r["file_path"]),
        }
        for r in rows
    ]


async def graph_expand(
    seed_block_ids: Set[int], k: int | None = None
) -> List[Dict[str, Any]]:
    """
    Graph-expand from seed block IDs.

    Uses all three graph signals from retrieval.py:
      1. Parent / child blocks
      2. [[wikilink]] references
      3. Shared #tags

    Additionally queries the hierarchical DB for file-path-segment neighbours.
    Returns enriched block dicts for the discovered neighbours.
    """
    from src.rag.retrieval import _graph_expand_scores
    from src.rag.multi_hierarchical import get_hierarchical_db

    k = k or settings.RAG_DEFAULT_K
    if not seed_block_ids:
        return []

    # DB-level graph expansion
    graph_sc = await _graph_expand_scores(seed_block_ids)

    # Hierarchical path-segment expansion: find blocks in same "folder domain"
    hier_db = get_hierarchical_db()
    seed_nodes: set[str] = set()
    for bid in seed_block_ids:
        seed_nodes.update(hier_db.graph_nodes_for_block(bid))

    if seed_nodes:
        for bid, meta in hier_db._meta.items():
            if bid in seed_block_ids:
                continue
            block_nodes = set(hier_db.graph_nodes_for_block(bid))
            overlap = seed_nodes & block_nodes
            if overlap:
                # weight by number of shared path segments
                boost = len(overlap) * 0.2
                graph_sc[bid] = graph_sc.get(bid, 0.0) + boost

    if not graph_sc:
        return []

    ranked_ids = sorted(graph_sc.keys(), key=lambda b: graph_sc[b], reverse=True)[:k]
    enriched = await get_enriched_blocks_data(ranked_ids)

    results = []
    for bid in ranked_ids:
        data = enriched.get(bid)
        if data:
            data["graph_score"] = graph_sc[bid]
            results.append(data)

    return normalize_result_paths(results)
