import re
from collections import defaultdict
from datetime import datetime, timedelta
from typing import List, Dict, Any

from src.ingestion.db.blocks import get_enriched_blocks_data
from src.ingestion.db.connection import get_connection
from src.rag.vector_db import search_similar_blocks, VectorDB


TOKEN_RE = re.compile(r"[a-z0-9][a-z0-9_-]*", re.IGNORECASE)
TAG_RE = re.compile(r"(?<![\[`])#([\w-]+)")
ISO_DATE_RE = re.compile(r"\b\d{4}-\d{2}-\d{2}\b")


async def search_and_enrich_blocks(
    query: str, k: int = 5, db: VectorDB | None = None
) -> List[Dict[str, Any]]:
    """
    Hybrid RAG search.

    Signals:
    - embedding similarity from FAISS
    - keyword overlap against block content/note title
    - tag matches from #tags and plain tag words
    - temporal matches against task dates and block text dates
    - graph expansion through parents, children, references, and shared tags
    """
    if not query.strip() or k <= 0:
        return []

    scores: dict[int, dict[str, float]] = defaultdict(lambda: defaultdict(float))

    vector_results = await search_similar_blocks(query, k=max(k * 3, 10), db=db)
    for block_id, score in vector_results:
        scores[block_id]["embedding"] = max(scores[block_id]["embedding"], float(score))

    lexical = await _keyword_and_tag_scores(query, limit=max(k * 5, 25))
    for block_id, signal_scores in lexical.items():
        for signal, score in signal_scores.items():
            scores[block_id][signal] += score

    temporal = await _temporal_scores(query)
    for block_id, score in temporal.items():
        scores[block_id]["temporal"] += score

    graph_scores = await _graph_expand_scores(set(scores.keys()))
    for block_id, score in graph_scores.items():
        scores[block_id]["graph"] += score

    if not scores:
        return []

    ranked = sorted(
        scores.items(),
        key=lambda item: _weighted_score(item[1]),
        reverse=True,
    )
    block_ids = [block_id for block_id, _ in ranked[: max(k * 2, k)]]
    enriched_data = await get_enriched_blocks_data(block_ids)

    enriched_results = []
    for block_id, signal_scores in ranked:
        if len(enriched_results) >= k:
            break
        data = enriched_data.get(block_id)
        if not data:
            continue
        total = _weighted_score(signal_scores)
        data["similarity_score"] = total
        data["hybrid_score"] = total
        data["score_breakdown"] = dict(signal_scores)
        enriched_results.append(data)

    return enriched_results


def _weighted_score(signal_scores: dict[str, float]) -> float:
    return (
        signal_scores.get("embedding", 0.0) * 0.55
        + signal_scores.get("keyword", 0.0) * 0.20
        + signal_scores.get("tag", 0.0) * 0.15
        + signal_scores.get("temporal", 0.0) * 0.15
        + signal_scores.get("graph", 0.0) * 0.10
    )


async def _keyword_and_tag_scores(query: str, limit: int) -> dict[int, dict[str, float]]:
    tokens = [token.lower() for token in TOKEN_RE.findall(query) if len(token) > 2]
    tags = [tag.lower() for tag in TAG_RE.findall(query)]
    scores: dict[int, dict[str, float]] = defaultdict(lambda: defaultdict(float))

    if not tokens and not tags:
        return scores

    async with get_connection() as conn:
        cursor = await conn.execute(
            """
            SELECT b.id, b.content, n.title, GROUP_CONCAT(bt.tag, ',') AS tags
            FROM blocks b
            JOIN notes n ON b.note_id = n.id
            LEFT JOIN block_tags bt ON bt.block_id = b.id
            WHERE n.deleted_at IS NULL
            GROUP BY b.id
            ORDER BY n.updated_at DESC, b.position ASC
            LIMIT ?
            """,
            (limit,),
        )
        rows = await cursor.fetchall()

    for row in rows:
        content = f"{row['title']} {row['content']}".lower()
        row_tags = {tag.lower() for tag in (row["tags"] or "").split(",") if tag}
        if tokens:
            overlap = sum(1 for token in tokens if token in content)
            if overlap:
                scores[row["id"]]["keyword"] = overlap / max(len(tokens), 1)
        tag_matches = set(tags) & row_tags if tags else set(tokens) & row_tags
        if tag_matches:
            scores[row["id"]]["tag"] = len(tag_matches) / max(len(tags) or len(tokens), 1)

    return scores


async def _temporal_scores(query: str) -> dict[int, float]:
    target_dates = _extract_query_dates(query)
    if not target_dates:
        return {}

    scores: dict[int, float] = defaultdict(float)
    async with get_connection() as conn:
        cursor = await conn.execute(
            """
            SELECT b.id, b.content, t.due_date, t.start_date
            FROM blocks b
            JOIN notes n ON b.note_id = n.id
            LEFT JOIN tasks t ON t.block_id = b.id AND t.is_deleted = 0
            WHERE n.deleted_at IS NULL
            """
        )
        rows = await cursor.fetchall()

    for row in rows:
        candidates = set(ISO_DATE_RE.findall(row["content"] or ""))
        if row["due_date"]:
            candidates.add(row["due_date"])
        if row["start_date"]:
            candidates.add(row["start_date"])
        if candidates & target_dates:
            scores[row["id"]] = 1.0

    return scores


async def _graph_expand_scores(seed_block_ids: set[int]) -> dict[int, float]:
    if not seed_block_ids:
        return {}

    scores: dict[int, float] = defaultdict(float)
    placeholders = ",".join("?" * len(seed_block_ids))
    params = list(seed_block_ids)

    async with get_connection() as conn:
        cursor = await conn.execute(
            f"""
            SELECT id FROM blocks
            WHERE parent_block IN ({placeholders})
               OR id IN (SELECT parent_block FROM blocks WHERE id IN ({placeholders}) AND parent_block IS NOT NULL)
            """,
            params + params,
        )
        for row in await cursor.fetchall():
            if row["id"] not in seed_block_ids:
                scores[row["id"]] += 0.5

        cursor = await conn.execute(
            f"""
            SELECT target_block_id AS id FROM block_references
            WHERE source_block_id IN ({placeholders}) AND target_block_id IS NOT NULL
            UNION
            SELECT source_block_id AS id FROM block_references
            WHERE target_block_id IN ({placeholders})
            """,
            params + params,
        )
        for row in await cursor.fetchall():
            if row["id"] not in seed_block_ids:
                scores[row["id"]] += 0.7

        cursor = await conn.execute(
            f"""
            SELECT DISTINCT bt2.block_id AS id
            FROM block_tags bt1
            JOIN block_tags bt2 ON LOWER(bt1.tag) = LOWER(bt2.tag)
            WHERE bt1.block_id IN ({placeholders})
            """,
            params,
        )
        for row in await cursor.fetchall():
            if row["id"] not in seed_block_ids:
                scores[row["id"]] += 0.3

    return scores


def _extract_query_dates(query: str) -> set[str]:
    dates = set(ISO_DATE_RE.findall(query))
    now = datetime.now()
    lower = query.lower()
    if "today" in lower:
        dates.add(now.date().isoformat())
    if "tomorrow" in lower:
        dates.add((now.date() + timedelta(days=1)).isoformat())
    if "yesterday" in lower:
        dates.add((now.date() - timedelta(days=1)).isoformat())

    try:
        from dateparser.search import search_dates

        matches = search_dates(
            query,
            settings={"RELATIVE_BASE": now, "PREFER_DATES_FROM": "future"},
        )
    except Exception:
        matches = None

    if matches:
        for _, parsed in matches:
            dates.add(parsed.date().isoformat())

    return dates
