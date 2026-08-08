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


def _resolve_to_abs(file_path: str) -> Path:
    """Resolve a user-supplied path (relative or absolute) to an absolute Path."""
    p = Path(file_path)
    if p.is_absolute():
        return p.resolve()
    return (_active_folder() / p).resolve()


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


# ---------------------------------------------------------------------------
# get_note  — fetch raw file content with optional line-range slicing
# ---------------------------------------------------------------------------


async def get_note(
    file_path: str,
    start_line: int | None = None,
    end_line: int | None = None,
) -> Dict[str, Any]:
    """
    Return the raw content of a note file, optionally sliced to [start_line, end_line].

    Lines are 1-indexed and inclusive.  The DB is used to surface note metadata
    (id, title, updated_at); if the note isn't in the DB yet we still read the
    file and return what we can.

    Returns a dict with keys:
        file_path, title, note_id, total_lines,
        start_line, end_line, content, blocks
    where ``blocks`` is a list of block dicts that fall inside the requested
    line range (empty when no range is given).
    """
    abs_path = _resolve_to_abs(file_path)
    rel_path = _display_path(str(abs_path))

    # ── Read raw file ─────────────────────────────────────────────────────────
    if not abs_path.exists():
        return {"error": f"File not found: {rel_path}"}

    try:
        raw = abs_path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        return {"error": f"Cannot read file: {exc}"}

    lines = raw.splitlines()
    total = len(lines)

    # Normalise line range (1-indexed, inclusive)
    sl = max(1, start_line) if start_line is not None else 1
    el = min(total, end_line) if end_line is not None else total

    sliced_lines = lines[sl - 1 : el]
    sliced_content = "\n".join(sliced_lines)

    # ── DB metadata ───────────────────────────────────────────────────────────
    note_id: int | None = None
    title: str = abs_path.stem
    updated_at: str | None = None
    matching_blocks: list[dict] = []

    try:
        async with get_connection() as conn:
            cursor = await conn.execute(
                "SELECT id, title, updated_at FROM notes WHERE file_path=? AND deleted_at IS NULL",
                (str(abs_path),),
            )
            row = await cursor.fetchone()
            if row:
                note_id = row["id"]
                title = row["title"]
                updated_at = row["updated_at"]

            # Return blocks that overlap with the requested line range
            if note_id is not None and (start_line is not None or end_line is not None):
                b_cursor = await conn.execute(
                    """
                    SELECT id, block_type, content, position, level, parent_block
                    FROM blocks
                    WHERE note_id = ? AND position >= ? AND position < ?
                    ORDER BY position
                    """,
                    (note_id, sl - 1, el),  # position is 0-indexed in DB
                )
                b_rows = await b_cursor.fetchall()
                matching_blocks = [dict(r) for r in b_rows]
    except Exception:
        pass  # DB unavailable — still return file content

    return {
        "file_path": rel_path,
        "note_id": note_id,
        "title": title,
        "updated_at": updated_at,
        "total_lines": total,
        "start_line": sl,
        "end_line": el,
        "content": sliced_content,
        "blocks": matching_blocks,
    }


# ---------------------------------------------------------------------------
# backtrack  — which notes reference THIS note / block
# ---------------------------------------------------------------------------


async def backtrack(
    file_path: str | None = None,
    block_id: int | None = None,
    k: int | None = None,
) -> List[Dict[str, Any]]:
    """
    Find all notes that reference the given note (by file_path) or block (by block_id)
    via [[wikilinks]] stored in block_references.

    Provide at least one of file_path or block_id.

    Returns a list of dicts:
        source_file, source_title, source_block_id,
        source_block_content, reference_type, target_title
    """
    k = k or settings.RAG_DEFAULT_K

    if file_path is None and block_id is None:
        return [{"error": "Provide file_path or block_id"}]

    abs_path: str | None = None
    if file_path is not None:
        abs_path = str(_resolve_to_abs(file_path))

    results: list[dict] = []

    try:
        async with get_connection() as conn:
            if block_id is not None:
                # Back-links to a specific block
                cursor = await conn.execute(
                    """
                    SELECT
                        src_n.file_path  AS source_file,
                        src_n.title      AS source_title,
                        br.source_block_id,
                        src_b.content    AS source_block_content,
                        br.reference_type,
                        br.target_title
                    FROM block_references br
                    JOIN blocks src_b ON br.source_block_id = src_b.id
                    JOIN notes  src_n ON src_b.note_id = src_n.id
                    WHERE br.target_block_id = ?
                      AND src_n.deleted_at IS NULL
                    LIMIT ?
                    """,
                    (block_id, k),
                )
                rows = await cursor.fetchall()
                results.extend(dict(r) for r in rows)

            if abs_path is not None:
                # Back-links to the whole note (any block inside it)
                # First resolve the note id
                n_cursor = await conn.execute(
                    "SELECT id, title FROM notes WHERE file_path=? AND deleted_at IS NULL",
                    (abs_path,),
                )
                note_row = await n_cursor.fetchone()
                if note_row:
                    target_note_id = note_row["id"]
                    cursor = await conn.execute(
                        """
                        SELECT
                            src_n.file_path  AS source_file,
                            src_n.title      AS source_title,
                            br.source_block_id,
                            src_b.content    AS source_block_content,
                            br.reference_type,
                            br.target_title
                        FROM block_references br
                        JOIN blocks src_b ON br.source_block_id = src_b.id
                        JOIN notes  src_n ON src_b.note_id = src_n.id
                        WHERE br.target_note_id = ?
                          AND src_n.deleted_at IS NULL
                        LIMIT ?
                        """,
                        (target_note_id, k),
                    )
                    rows = await cursor.fetchall()
                    for r in rows:
                        d = dict(r)
                        # De-duplicate: skip if we already have an entry for
                        # this source_block_id from the block-level query above
                        if not any(
                            x["source_block_id"] == d["source_block_id"]
                            for x in results
                        ):
                            results.append(d)
                else:
                    # Note not in DB — try matching by title-based wikilinks
                    stem = Path(abs_path).stem
                    cursor = await conn.execute(
                        """
                        SELECT
                            src_n.file_path  AS source_file,
                            src_n.title      AS source_title,
                            br.source_block_id,
                            src_b.content    AS source_block_content,
                            br.reference_type,
                            br.target_title
                        FROM block_references br
                        JOIN blocks src_b ON br.source_block_id = src_b.id
                        JOIN notes  src_n ON src_b.note_id = src_n.id
                        WHERE LOWER(br.target_title) = LOWER(?)
                          AND src_n.deleted_at IS NULL
                        LIMIT ?
                        """,
                        (stem, k),
                    )
                    rows = await cursor.fetchall()
                    results.extend(dict(r) for r in rows)

    except Exception as exc:
        return [{"error": str(exc)}]

    # Normalise paths
    for item in results:
        if item.get("source_file"):
            item["source_file"] = _display_path(item["source_file"])

    return results[:k]


# ---------------------------------------------------------------------------
# get_todos  — fetch tasks from DB with natural-language metadata
# ---------------------------------------------------------------------------

_PRIORITY_LABELS = {"high": "🔴 high", "medium": "🟡 medium", "low": "🟢 low"}


def _humanise_task(row: dict) -> dict:
    """Convert a raw tasks DB row into a clean, agent-friendly dict."""
    tags_raw = row.get("tags") or ""
    tags = [t.strip() for t in tags_raw.split(",") if t.strip()] if tags_raw else []

    priority_raw = (row.get("priority") or "").lower()
    priority = _PRIORITY_LABELS.get(priority_raw, priority_raw or None)

    return {
        "id": row["id"],
        "title": row["title"],
        "raw_text": row["raw_text"],
        "is_done": bool(row["is_done"]),
        "due_date": row["due_date"],
        "start_date": row.get("start_date"),
        "priority": priority,
        "tags": tags,
        "recurrence": row.get("recurrence"),
        "file_path": _display_path(row["file_path"]) if row.get("file_path") else None,
        "note_title": row.get("note_title"),
        "sync_status": row.get("sync_status"),
    }


async def get_todos(
    filter_done: bool | None = None,
    tag: str | None = None,
    due_before: str | None = None,
    due_after: str | None = None,
    priority: str | None = None,
    file_path: str | None = None,
    k: int | None = None,
) -> List[Dict[str, Any]]:
    """
    Fetch tasks from the DB, mirroring the same natural-language metadata
    understanding used during ingestion (due dates, priorities, tags,
    recurrence, start dates).

    Parameters
    ----------
    filter_done  : True → only done, False → only pending, None → both
    tag          : filter by a single tag (without #)
    due_before   : ISO date string — return tasks due on or before this date
    due_after    : ISO date string — return tasks due on or after this date
    priority     : 'high' | 'medium' | 'low'
    file_path    : restrict to tasks from this file (relative or absolute)
    k            : max results (default RAG_DEFAULT_K)
    """
    k = k or settings.RAG_DEFAULT_K

    conditions: list[str] = ["t.is_deleted = 0", "n.deleted_at IS NULL"]
    params: list[Any] = []

    if filter_done is True:
        conditions.append("t.is_done = 1")
    elif filter_done is False:
        conditions.append("t.is_done = 0")

    if priority:
        conditions.append("LOWER(t.priority) = LOWER(?)")
        params.append(priority.lower())

    if due_before:
        conditions.append("t.due_date IS NOT NULL AND t.due_date <= ?")
        params.append(due_before)

    if due_after:
        conditions.append("t.due_date IS NOT NULL AND t.due_date >= ?")
        params.append(due_after)

    if file_path:
        abs_p = str(_resolve_to_abs(file_path))
        conditions.append("n.file_path = ?")
        params.append(abs_p)

    if tag:
        tag_clean = tag.lstrip("#").lower()
        conditions.append(
            "(LOWER(t.tags) LIKE ? OR EXISTS ("
            "  SELECT 1 FROM block_tags bt"
            "  WHERE bt.block_id = t.block_id AND LOWER(bt.tag) = ?"
            "))"
        )
        params.append(f"%{tag_clean}%")
        params.append(tag_clean)

    where = " AND ".join(conditions)
    params.append(k)

    sql = f"""
        SELECT
            t.id, t.raw_text, t.title, t.is_done,
            t.due_date, t.start_date, t.priority,
            t.tags, t.recurrence, t.sync_status,
            n.file_path, n.title AS note_title
        FROM tasks t
        JOIN notes n ON t.note_id = n.id
        WHERE {where}
        ORDER BY
            CASE WHEN t.due_date IS NULL THEN 1 ELSE 0 END,
            t.due_date ASC,
            CASE LOWER(t.priority) WHEN 'high' THEN 0 WHEN 'medium' THEN 1 ELSE 2 END,
            t.id DESC
        LIMIT ?
    """

    try:
        async with get_connection() as conn:
            cursor = await conn.execute(sql, params)
            rows = await cursor.fetchall()
    except Exception as exc:
        return [{"error": str(exc)}]

    return [_humanise_task(dict(r)) for r in rows]
