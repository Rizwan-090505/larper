"""
PersonalManagerAgent
=====================
Conversational agent backed by Gemini with an agentic RAG loop.

Key behaviours
──────────────
1. ALWAYS searches the knowledge base before answering knowledge questions.
   The agent may call tools multiple times (up to MAX_TOOL_ROUNDS) to gather
   enough evidence.

2. If search yields nothing relevant the agent says "I don't know / I couldn't
   find anything" rather than hallucinating an answer.

3. Chat messages typed into the input bar are NEVER saved as notes.
   Only explicit "note" intents (detected by the AI itself) trigger saving.
   The TUI enforces this too, but the agent makes it explicit via intent tags.

4. Full multi-tool set exposed to the model:
     search_notes      – hybrid RAG (embedding + keyword + temporal + graph)
     tag_search        – search by #tag
     fuzzy_search      – substring / fuzzy match
     reference_search  – [[wikilink]] lookup
     graph_expansion   – expand from block IDs through graph edges
     get_note          – read a note file (with optional line range)
     backtrack         – which notes reference this note / block
     get_todos         – fetch tasks with full metadata understanding
"""

from __future__ import annotations

import json
import logging
import re
import asyncio
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal

from dotenv import load_dotenv
from google import genai
from google.genai import types

from config import settings
from src.rag.enhanced_retrieval import search_and_enrich_blocks

load_dotenv()

log = logging.getLogger(__name__)

# ── Constants ─────────────────────────────────────────────────────────────────

_THINKING_RE = re.compile(r"<thinking>.*?</thinking>", re.DOTALL | re.IGNORECASE)
_INTENT_RE = re.compile(r"\[intent:(task|event|note|question|chat)\]", re.IGNORECASE)
_IDONTKNOW_RE = re.compile(
    r"\b(i (don'?t|do not|couldn'?t|could not) (know|find|locate|see)|"
    r"no (relevant|matching|related) (notes?|results?|information|content)|"
    r"nothing (found|relevant|matching)|"
    r"couldn'?t find (any|anything|relevant))\b",
    re.IGNORECASE,
)

GEMINI_MODEL = getattr(settings, "GEMINI_MODEL", "gemini-2.0-flash")
MAX_HISTORY = 20  # conversation turns to keep
MAX_TOOL_ROUNDS = 5  # max agentic search iterations per user message
MAX_OUTPUT_TOKENS = 4096  # explicit cap so replies can't inherit a tiny API default
MAX_CONTINUATIONS = 2  # extra rounds to finish a reply cut off by MAX_TOKENS

Intent = Literal["task", "event", "note", "question", "chat"]


# ── Data classes ──────────────────────────────────────────────────────────────


@dataclass
class AgentAction:
    intent: Intent
    text: str
    date: str | None = None
    time: str | None = None
    tags: list[str] = field(default_factory=list)


@dataclass
class AgentResult:
    action: AgentAction
    reply: str
    context: list[dict[str, Any]] = field(default_factory=list)
    tool_calls: list[dict[str, Any]] = field(default_factory=list)


# ── Tool schemas ──────────────────────────────────────────────────────────────

_TOOLS = [
    types.Tool(
        function_declarations=[
            types.FunctionDeclaration(
                name="search_notes",
                description=(
                    "Search the user's personal knowledge base (notes, journals, tasks). "
                    "MUST be called before answering any question about the user's life, "
                    "work, plans, ideas, or anything that might be in their notes. "
                    "Combines semantic similarity, keywords, temporal relevance, and graph "
                    "connections. Call this first; use other tools to refine."
                ),
                parameters=types.Schema(
                    type=types.Type.OBJECT,
                    properties={
                        "query": types.Schema(
                            type=types.Type.STRING,
                            description="Natural language search query",
                        ),
                        "k": types.Schema(
                            type=types.Type.INTEGER,
                            description="Number of results (default 6, max 12)",
                        ),
                    },
                    required=["query"],
                ),
            ),
            types.FunctionDeclaration(
                name="tag_search",
                description=(
                    "Search notes by a specific #tag. "
                    "Use when the user mentions a hashtag or asks about a category/topic "
                    "they habitually tag."
                ),
                parameters=types.Schema(
                    type=types.Type.OBJECT,
                    properties={
                        "tag": types.Schema(
                            type=types.Type.STRING,
                            description="Tag name (with or without #)",
                        ),
                        "k": types.Schema(
                            type=types.Type.INTEGER,
                            description="Number of results (default 6)",
                        ),
                    },
                    required=["tag"],
                ),
            ),
            types.FunctionDeclaration(
                name="fuzzy_search",
                description=(
                    "Fuzzy / substring search across note titles and content. "
                    "Good for finding specific names, exact phrases, or file names."
                ),
                parameters=types.Schema(
                    type=types.Type.OBJECT,
                    properties={
                        "query": types.Schema(
                            type=types.Type.STRING,
                            description="Search term for fuzzy matching",
                        ),
                        "k": types.Schema(
                            type=types.Type.INTEGER,
                            description="Number of results (default 6)",
                        ),
                    },
                    required=["query"],
                ),
            ),
            types.FunctionDeclaration(
                name="reference_search",
                description=(
                    "Search for notes that reference other notes via [[wikilinks]]. "
                    "Use when the user asks about connections, links, or a specific note "
                    "title they may have linked from elsewhere."
                ),
                parameters=types.Schema(
                    type=types.Type.OBJECT,
                    properties={
                        "reference": types.Schema(
                            type=types.Type.STRING,
                            description="Reference text or note title",
                        ),
                        "k": types.Schema(
                            type=types.Type.INTEGER,
                            description="Number of results (default 6)",
                        ),
                    },
                    required=["reference"],
                ),
            ),
            types.FunctionDeclaration(
                name="graph_expansion",
                description=(
                    "Expand from known block IDs through the knowledge graph "
                    "(parent/child blocks, [[wikilinks]], shared #tags, file-path proximity). "
                    "Use after search_notes when you have result IDs and want to find "
                    "closely related content not caught by the initial search. "
                    "Also use after get_note to explore what links out from a note."
                ),
                parameters=types.Schema(
                    type=types.Type.OBJECT,
                    properties={
                        "note_ids": types.Schema(
                            type=types.Type.ARRAY,
                            description="List of block IDs returned by previous searches or get_note",
                            items=types.Schema(type=types.Type.INTEGER),
                        ),
                        "k": types.Schema(
                            type=types.Type.INTEGER,
                            description="Number of related notes (default 6)",
                        ),
                    },
                    required=["note_ids"],
                ),
            ),
            types.FunctionDeclaration(
                name="get_note",
                description=(
                    "Read the full raw content of a specific note file, optionally "
                    "limited to a line range. Use when you need to see the exact text of "
                    "a note rather than search-result excerpts — e.g. when the user asks "
                    "'show me my drone research note' or 'what's on lines 5-20 of meeting4aug.md'. "
                    "Returns content, metadata, and the DB blocks that fall in the line range."
                ),
                parameters=types.Schema(
                    type=types.Type.OBJECT,
                    properties={
                        "file_path": types.Schema(
                            type=types.Type.STRING,
                            description=(
                                "Relative path to the note file from the vault root, "
                                "e.g. 'pages/fyp/Droneresearch.md' or 'journals/2026-08-07.md'"
                            ),
                        ),
                        "start_line": types.Schema(
                            type=types.Type.INTEGER,
                            description="First line to return (1-indexed, inclusive). Omit for start of file.",
                        ),
                        "end_line": types.Schema(
                            type=types.Type.INTEGER,
                            description="Last line to return (1-indexed, inclusive). Omit for end of file.",
                        ),
                    },
                    required=["file_path"],
                ),
            ),
            types.FunctionDeclaration(
                name="backtrack",
                description=(
                    "Find all notes that reference (link back to) a given note or block "
                    "via [[wikilinks]]. Use when the user asks 'what links to X?', "
                    "'what references my drone note?', or 'where is this mentioned?'. "
                    "Provide file_path to find all back-links to a whole note, "
                    "or block_id to find back-links to a specific block."
                ),
                parameters=types.Schema(
                    type=types.Type.OBJECT,
                    properties={
                        "file_path": types.Schema(
                            type=types.Type.STRING,
                            description=(
                                "Relative path of the note to find back-links for, "
                                "e.g. 'pages/fyp/Droneresearch.md'"
                            ),
                        ),
                        "block_id": types.Schema(
                            type=types.Type.INTEGER,
                            description="Block ID to find back-links for (from a previous search result)",
                        ),
                        "k": types.Schema(
                            type=types.Type.INTEGER,
                            description="Max number of back-links to return (default 6)",
                        ),
                    },
                ),
            ),
            types.FunctionDeclaration(
                name="get_todos",
                description=(
                    "Fetch tasks / to-dos from the database with full natural-language "
                    "metadata: due dates, priorities, tags, recurrence, start dates. "
                    "Use for any question about tasks, todos, what needs to be done, "
                    "what's overdue, upcoming deadlines, or specific priority items. "
                    "All filters are optional — omit to get all pending tasks."
                ),
                parameters=types.Schema(
                    type=types.Type.OBJECT,
                    properties={
                        "filter_done": types.Schema(
                            type=types.Type.BOOLEAN,
                            description=(
                                "true → only completed tasks, "
                                "false → only pending tasks, "
                                "omit → both"
                            ),
                        ),
                        "tag": types.Schema(
                            type=types.Type.STRING,
                            description="Filter by tag (without #)",
                        ),
                        "due_before": types.Schema(
                            type=types.Type.STRING,
                            description="ISO date (YYYY-MM-DD) — tasks due on or before this date",
                        ),
                        "due_after": types.Schema(
                            type=types.Type.STRING,
                            description="ISO date (YYYY-MM-DD) — tasks due on or after this date",
                        ),
                        "priority": types.Schema(
                            type=types.Type.STRING,
                            description="'high', 'medium', or 'low'",
                        ),
                        "file_path": types.Schema(
                            type=types.Type.STRING,
                            description="Restrict to tasks from a specific file",
                        ),
                        "k": types.Schema(
                            type=types.Type.INTEGER,
                            description="Max results (default 6)",
                        ),
                    },
                ),
            ),
        ]
    )
]

# ── System prompt ─────────────────────────────────────────────────────────────

_SYSTEM_PROMPT = """\
You are LARPer, an autonomous personal knowledge assistant embedded in a terminal note-taking app.
Today is {date}.

# CORE RULE — SEARCH BEFORE YOU ANSWER
You MUST call search_notes (or another search tool) before answering ANY question about:
  • the user's notes, journals, tasks, or ideas
  • their projects, meetings, plans, or research
  • anything they might have written down

NEVER answer knowledge questions from memory — always check the notes first.

If after searching you find no relevant information, respond honestly:
  "I couldn't find anything about that in your notes."
  or "I don't know — there's nothing relevant in your knowledge base."
Do NOT make up an answer or guess.

# TOOL STRATEGY
You may call multiple tools per turn to build a complete picture:
  1. search_notes        — default hybrid search; start here
  2. tag_search          — when a #tag is mentioned or relevant
  3. fuzzy_search        — for specific names, phrases, or file titles
  4. reference_search    — for [[wikilink]] targets
  5. graph_expansion     — to explore related content once you have block IDs;
                           also use after get_note to follow links outward
  6. get_note            — to read the FULL content of a specific file, or a
                           precise line range (use when excerpts aren't enough)
  7. backtrack           — to find all notes that reference a given note/block
                           (the "who links here?" query)
  8. get_todos           — to fetch tasks with metadata (due date, priority, tags,
                           recurrence); prefer this over search_notes for task questions

Use graph_expansion when the initial results are thin; it expands through
parent/child blocks, [[links]], shared #tags, and file-path segments.

Use get_note when the user asks to "show", "read", or "open" a specific file,
or when search excerpts are clearly incomplete.

Use backtrack when the user asks what links TO a note, or wants to understand
the reverse graph — "what references X?".

Use get_todos for any question about pending work, deadlines, priorities, or
what tasks are overdue. It applies the same natural-language date and metadata
understanding as the ingestion pipeline.

# WHAT NOT TO CAPTURE
Chat conversation, your questions, and general dialogue are NEVER saved as notes.
Only content the user explicitly asks to save or that is obviously a personal note/task/event
should produce [intent:note], [intent:task], or [intent:event].

# RESPONSE STYLE
• Be concise and direct.
• Always cite sources: mention exact file paths like journals/2026-08-06.md so the UI
  can make them clickable.
• For questions: answer from search results, cite files, offer follow-up.
• For tasks/events: confirm capture briefly.

# INTENT MARKER (required, silent)
End every reply with EXACTLY one of these on its own line — no explanation:
  [intent:task]      user wants a to-do / reminder
  [intent:event]     meeting, appointment, or calendar item
  [intent:question]  user asked a question (never auto-save)
  [intent:note]      user explicitly wants to save a note or thought
  [intent:chat]      general chat — never auto-save
"""


# ── Agent ─────────────────────────────────────────────────────────────────────


class PersonalManagerAgent:
    """
    Conversational agent with agentic RAG loop.
    • Uses Gemini for the LLM backend.
    • Falls back to local regex parser if no API key is configured.
    • Maintains multi-turn history (MAX_HISTORY turns).
    """

    def __init__(self) -> None:
        self._history: list[dict] = []
        self._api_key: str = self._find_api_key()
        self._last_error: str = ""

    def _find_api_key(self) -> str:
        import os

        return (
            os.environ.get("GEMINI_API_KEY", "")
            or getattr(settings, "GEMINI_API_KEY", "")
            or ""
        )

    # ── Public ────────────────────────────────────────────────────────────────

    async def run(
        self,
        message: str,
        *,
        now: datetime | None = None,
        stream_callback=None,
    ) -> AgentResult:
        """Run the agent.

        Args:
            message: User message text.
            now: Override the current datetime (useful for tests).
            stream_callback: Optional async callable(str) that receives each
                text chunk as it arrives from the model, enabling incremental
                display in the TUI.  Called with an empty string ``""`` once
                all tool rounds are done and the final synthesis has started.
        """
        now = now or datetime.now()
        self._last_error = ""
        if self._api_key:
            result = await self._run_gemini(
                message, now=now, stream_callback=stream_callback
            )
            if result:
                return result
        return await self._run_local(message, now=now)

    # ── Gemini agentic loop ───────────────────────────────────────────────────

    async def _run_gemini(
        self, message: str, *, now: datetime, stream_callback=None
    ) -> AgentResult | None:
        # Append user message
        self._history.append(
            {
                "role": "user",
                "parts": [types.Part.from_text(text=message)],
            }
        )
        if len(self._history) > MAX_HISTORY:
            self._history = self._history[-MAX_HISTORY:]

        system = _SYSTEM_PROMPT.format(date=now.date().isoformat())
        tool_log: list[dict] = []
        final_text: str = ""

        contents = [
            types.Content(role=m["role"], parts=m["parts"]) for m in self._history
        ]

        client = genai.Client(api_key=self._api_key)
        exhausted_with_pending_calls = False

        try:
            for _round in range(MAX_TOOL_ROUNDS):
                config = types.GenerateContentConfig(
                    system_instruction=system,
                    tools=_TOOLS,
                    temperature=0.4,  # lower temp → more faithful to retrieved content
                    max_output_tokens=MAX_OUTPUT_TOKENS,
                )

                # Stream every round.  For tool-calling rounds the function_call
                # parts are small and arrive quickly; we collect them all before
                # executing tools.  For the final text-only round the stream lets
                # the TUI display tokens as they arrive.
                round_text_chunks: list[str] = []
                fn_call_parts: list = []  # whole Part objects (preserves thought_signature)
                candidate = None
                finish_reason = ""

                stream = await client.aio.models.generate_content_stream(
                    model=GEMINI_MODEL,
                    contents=contents,
                    config=config,
                )
                async for chunk in stream:
                    if not chunk.candidates:
                        continue
                    candidate = chunk.candidates[0]
                    finish_reason = str(getattr(candidate, "finish_reason", "") or "")
                    for p in candidate.content.parts or []:
                        if getattr(p, "thought", False):
                            continue
                        if p.function_call:
                            # Keep the WHOLE Part, not just .function_call.
                            # Gemini 3.x attaches a `thought_signature` to the
                            # Part alongside the function_call, and requires
                            # that same signature to be echoed back verbatim
                            # when the call is replayed into conversation
                            # history on the next round. Dropping it (as
                            # `Part(function_call=fc)` did before) causes:
                            #   400 INVALID_ARGUMENT: Function call is missing
                            #   a thought_signature in functionCall parts.
                            fn_call_parts.append(p)
                        elif p.text:
                            cleaned = _THINKING_RE.sub("", p.text)
                            if cleaned:
                                round_text_chunks.append(cleaned)
                                # Only stream text to UI when there are no
                                # pending tool calls (i.e. this is a text round).
                                # We don't know yet whether fn_calls will follow,
                                # so we buffer and flush below.

                if candidate is None:
                    log.warning("Gemini returned no candidates (round %d)", _round)
                    self._last_error = "Gemini returned no candidates (possible safety block or invalid request)."
                    return None

                if round_text_chunks:
                    round_text = "".join(round_text_chunks).strip()
                    if round_text:
                        final_text = round_text

                if "MAX_TOKENS" in finish_reason.upper() and not fn_call_parts:
                    log.warning(
                        "Gemini reply truncated by MAX_TOKENS (round %d, %d chars so "
                        "far) — requesting continuation.",
                        _round,
                        len(final_text),
                    )
                    final_text = await self._continue_truncated_reply(
                        client,
                        system,
                        contents,
                        candidate,
                        final_text,
                        stream_callback=stream_callback,
                    )

                if not fn_call_parts:
                    # Final text-only round — deliver all collected text to the
                    # stream_callback now (chunks were buffered above to avoid
                    # sending partial text before we knew tool calls were absent).
                    if stream_callback and final_text:
                        await stream_callback(final_text)
                    exhausted_with_pending_calls = False
                    break

                # There are tool calls — reconstruct a Content from streamed parts
                # so we can append it to the conversation. Function-call parts
                # are re-used as-is (see comment above) to preserve thought_signature.
                from google.genai import types as _gtypes

                model_parts = []
                if round_text_chunks:
                    model_parts.append(
                        _gtypes.Part.from_text(text="".join(round_text_chunks))
                    )
                model_parts.extend(fn_call_parts)
                model_content = _gtypes.Content(role="model", parts=model_parts)

                # Append model turn with function calls
                contents.append(model_content)

                # Execute tools
                tool_result_parts = []
                for p in fn_call_parts:
                    fc = p.function_call
                    name = fc.name
                    args = self._coerce_args(fc.args)
                    tool_log.append({"tool": name, "args": args})

                    result_data = await self._execute_tool(name, args)
                    tool_result_parts.append(
                        types.Part.from_function_response(
                            name=name,
                            response={"result": result_data},
                        )
                    )

                contents.append(types.Content(role="user", parts=tool_result_parts))
                exhausted_with_pending_calls = True

            if exhausted_with_pending_calls or not final_text:
                log.warning(
                    "Gemini agent hit MAX_TOOL_ROUNDS=%d without a final answer "
                    "(tools called: %d) — forcing a text-only synthesis round.",
                    MAX_TOOL_ROUNDS,
                    len(tool_log),
                )
                contents.append(
                    types.Content(
                        role="user",
                        parts=[
                            types.Part.from_text(
                                text=(
                                    "Stop calling tools now. Using only the results "
                                    "already gathered above, give your final answer "
                                    "to my original question, citing file paths. "
                                    "End with the required [intent:...] marker."
                                )
                            )
                        ],
                    )
                )
                final_config = types.GenerateContentConfig(
                    system_instruction=system,
                    temperature=0.4,
                    max_output_tokens=MAX_OUTPUT_TOKENS,
                )

                # ── Streaming synthesis round ─────────────────────────────────
                # Use generate_content_stream so text arrives in the TUI
                # chunk-by-chunk rather than all at once after a long wait.
                streamed_chunks: list[str] = []
                fin_candidate = None
                fin_stream = await client.aio.models.generate_content_stream(
                    model=GEMINI_MODEL,
                    contents=contents,
                    config=final_config,
                )
                async for chunk in fin_stream:
                    if not chunk.candidates:
                        continue
                    fin_candidate = chunk.candidates[0]
                    for p in fin_candidate.content.parts or []:
                        if getattr(p, "thought", False):
                            continue
                        if p.text:
                            cleaned = _THINKING_RE.sub("", p.text)
                            if cleaned:
                                streamed_chunks.append(cleaned)
                                if stream_callback:
                                    await stream_callback(cleaned)

                if streamed_chunks:
                    final_text = "".join(streamed_chunks).strip()

                if fin_candidate is not None and (
                    "MAX_TOKENS"
                    in str(getattr(fin_candidate, "finish_reason", "") or "").upper()
                ):
                    log.warning(
                        "Forced-synthesis reply also truncated by MAX_TOKENS — "
                        "requesting continuation."
                    )
                    final_text = await self._continue_truncated_reply(
                        client,
                        system,
                        contents,
                        fin_candidate,
                        final_text,
                        stream_callback=stream_callback,
                    )

        except Exception as exc:
            log.exception("Gemini call failed")
            self._last_error = f"{type(exc).__name__}: {exc}"
            return None

        if not final_text:
            log.warning(
                "Gemini agent produced no final text after %d tool calls — "
                "falling back to local parser.",
                len(tool_log),
            )
            self._last_error = (
                f"Gemini produced no final text after {len(tool_log)} tool call(s)."
            )
            return None

        # Extract + strip intent marker
        intent: Intent | None = None
        m = _INTENT_RE.search(final_text)
        if m:
            intent = m.group(1).lower()  # type: ignore[assignment]
            final_text = _INTENT_RE.sub("", final_text).rstrip()

        # Persist assistant reply
        self._history.append(
            {
                "role": "model",
                "parts": [types.Part.from_text(text=final_text)],
            }
        )

        action = self._infer_action(message, now)
        if intent:
            action.intent = intent

        # Safety: chat / question must never trigger note-saving
        if action.intent in ("chat", "question"):
            pass

        return AgentResult(
            action=action,
            reply=final_text,
            tool_calls=tool_log,
        )

    # ── Truncation recovery ───────────────────────────────────────────────────

    async def _continue_truncated_reply(
        self,
        client: "genai.Client",
        system: str,
        contents: list,
        candidate,
        partial_text: str,
        *,
        stream_callback=None,
    ) -> str:
        accumulated = partial_text
        convo = list(contents) + [candidate.content]

        for _ in range(MAX_CONTINUATIONS):
            convo.append(
                types.Content(
                    role="user",
                    parts=[
                        types.Part.from_text(
                            text=(
                                "Your previous reply was cut off before it finished. "
                                "Continue exactly where you left off — do not repeat "
                                "anything already said, do not restart the answer. "
                                "End with the required [intent:...] marker once complete."
                            )
                        )
                    ],
                )
            )
            cont_candidate = None
            streamed_chunks: list[str] = []
            try:
                cont_stream = await client.aio.models.generate_content_stream(
                    model=GEMINI_MODEL,
                    contents=convo,
                    config=types.GenerateContentConfig(
                        system_instruction=system,
                        temperature=0.4,
                        max_output_tokens=MAX_OUTPUT_TOKENS,
                    ),
                )
                async for chunk in cont_stream:
                    if not chunk.candidates:
                        continue
                    cont_candidate = chunk.candidates[0]
                    for p in cont_candidate.content.parts or []:
                        if getattr(p, "thought", False):
                            continue
                        if p.text:
                            cleaned = _THINKING_RE.sub("", p.text)
                            if cleaned:
                                streamed_chunks.append(cleaned)
                                if stream_callback:
                                    await stream_callback(cleaned)
            except Exception:
                log.exception("Continuation call failed")
                break

            chunk_text = "".join(streamed_chunks).strip()
            if chunk_text:
                accumulated = f"{accumulated}\n{chunk_text}"

            if cont_candidate is not None:
                # Rebuild a synthetic Content so we can append it to convo
                convo.append(
                    types.Content(
                        role="model",
                        parts=[types.Part.from_text(text=chunk_text)],
                    )
                )
                if (
                    "MAX_TOKENS"
                    not in str(
                        getattr(cont_candidate, "finish_reason", "") or ""
                    ).upper()
                ):
                    break
                log.warning(
                    "Continuation still truncated by MAX_TOKENS — trying again."
                )
            else:
                break

        return accumulated

    # ── Tool execution ────────────────────────────────────────────────────────

    @staticmethod
    def _coerce_args(raw) -> dict:
        """Normalise Gemini's args object to a plain dict."""
        if isinstance(raw, dict):
            return raw
        try:
            return dict(raw)
        except Exception:
            return {}

    async def _execute_tool(self, name: str, args: dict) -> Any:
        try:
            from src.rag import search_tools

            if name == "search_notes":
                results = await search_and_enrich_blocks(
                    args.get("query", ""), k=int(args.get("k", 6))
                )
                results = search_tools.normalize_result_paths(results)
                return self._format_results(results)

            elif name == "tag_search":
                results = await search_tools.tag_search(
                    args.get("tag", ""), k=int(args.get("k", 6))
                )
                return self._format_results(results)

            elif name == "fuzzy_search":
                results = await search_tools.fzf_search(
                    args.get("query", ""), k=int(args.get("k", 6))
                )
                return self._format_results(results)

            elif name == "reference_search":
                results = await search_tools.ref_search(
                    args.get("reference", ""), k=int(args.get("k", 6))
                )
                return self._format_results(results, extra_key="target_title")

            elif name == "graph_expansion":
                ids = args.get("note_ids", [])
                if isinstance(ids, list) and ids:
                    results = await search_tools.graph_expand(
                        set(int(i) for i in ids),
                        k=int(args.get("k", 6)),
                    )
                    return self._format_results(results)
                return []

            elif name == "get_note":
                result = await search_tools.get_note(
                    file_path=args.get("file_path", ""),
                    start_line=args.get("start_line"),
                    end_line=args.get("end_line"),
                )
                return result

            elif name == "backtrack":
                results = await search_tools.backtrack(
                    file_path=args.get("file_path"),
                    block_id=args.get("block_id"),
                    k=int(args.get("k", 6)),
                )
                return results

            elif name == "get_todos":
                filter_done = args.get("filter_done")
                # Gemini may send filter_done as a string
                if isinstance(filter_done, str):
                    filter_done = filter_done.lower() == "true"
                results = await search_tools.get_todos(
                    filter_done=filter_done,
                    tag=args.get("tag"),
                    due_before=args.get("due_before"),
                    due_after=args.get("due_after"),
                    priority=args.get("priority"),
                    file_path=args.get("file_path"),
                    k=int(args.get("k", 6)),
                )
                return results

        except Exception as exc:
            log.warning("Tool %s failed: %s", name, exc)
            return {"error": str(exc)}

        return {"error": f"unknown tool: {name}"}

    @staticmethod
    def _format_results(
        results: list[dict],
        extra_key: str | None = None,
    ) -> list[dict]:
        out = []
        for r in results[:8]:
            item = {
                "id": r.get("id", ""),
                "title": r.get("title", ""),
                "file": r.get("file_path", ""),
                "file_path": r.get("file_path", ""),
                "excerpt": (r.get("content") or "")[:400],
            }
            if extra_key and r.get(extra_key):
                item[extra_key] = r[extra_key]
            out.append(item)
        return out

    # ── Local fallback (no API key) ───────────────────────────────────────────

    async def _run_local(self, message: str, *, now: datetime) -> AgentResult:
        context: list[dict] = []
        try:
            context = await search_and_enrich_blocks(message, k=4)
            from src.rag import search_tools

            context = search_tools.normalize_result_paths(context)
        except Exception:
            pass

        action = self._infer_action(message, now)

        # Build a note about *why* we're in local-only mode, so the message
        # doesn't misleadingly tell the user to "set" a key that is already
        # set — if a key is present but the call still failed, surface the
        # real reason instead.
        if self._api_key and self._last_error:
            ai_note = f"(AI mode failed: {self._last_error})"
        elif self._api_key:
            ai_note = "(AI mode is unavailable right now — check logs for details.)"
        else:
            ai_note = "(Set GEMINI_API_KEY in .env for full AI responses.)"

        if action.intent == "question":
            if context:
                top = context[0]
                reply = (
                    f"Best match from your notes ({top.get('title', '')}): "
                    f"{(top.get('content') or '')[:200]}"
                )
            else:
                reply = f"I couldn't find anything about that in your notes. {ai_note}"
        elif action.intent == "task":
            due = f" due {action.date}" if action.date else ""
            reply = f"Task captured: {action.text}{due}"
        elif action.intent == "event":
            when = " ".join(p for p in [action.date, action.time] if p)
            reply = f"Event noted: {action.text}" + (f" at {when}" if when else "")
        elif action.intent == "note":
            reply = "Note saved."
        else:
            reply = "Got it."

        return AgentResult(action=action, reply=reply, context=context)

    # ── Intent inference ──────────────────────────────────────────────────────

    _task_re = re.compile(
        r"^(?:add\s+)?(?:todo|task|remind me to|remember to|i need to)\s+(.+)$",
        re.IGNORECASE,
    )
    _event_re = re.compile(
        r"^(?:add\s+)?(?:event|meeting|appointment|call)\s+(.+)$",
        re.IGNORECASE,
    )
    _question_re = re.compile(
        r"^(?:\?|ask|search|find|what|when|where|who|why|how)\b",
        re.IGNORECASE,
    )
    _note_re = re.compile(
        r"^(?:note|save|write|log|record|capture)\b",
        re.IGNORECASE,
    )
    _time_re = re.compile(r"\b(\d{1,2})(?:(:(\d{2}))?)\s*(am|pm)?\b", re.IGNORECASE)

    def _infer_action(self, message: str, now: datetime) -> AgentAction:
        text = message.strip()
        tags = re.findall(r"(?<![\[`])#([\w-]+)", text)
        date, time = self._extract_datetime(text, now)

        task_m = self._task_re.match(text)
        event_m = self._event_re.match(text)

        if self._question_re.match(text) or text.endswith("?"):
            intent: Intent = "question"
            body = text
        elif event_m or (
            time
            and any(w in text.lower() for w in ("meet", "call", "appointment", "event"))
        ):
            intent = "event"
            body = event_m.group(1).strip() if event_m else text
        elif task_m or any(
            w in text.lower() for w in ("todo", "remind", "due ", "need to")
        ):
            intent = "task"
            body = task_m.group(1).strip() if task_m else text
        elif self._note_re.match(text):
            intent = "note"
            body = text
        else:
            intent = "chat"
            body = text

        return AgentAction(
            intent=intent,
            text=self._clean(body),
            date=date,
            time=time,
            tags=tags,
        )

    def _extract_datetime(
        self, text: str, now: datetime
    ) -> tuple[str | None, str | None]:
        from datetime import timedelta

        lower = text.lower()
        t = self._extract_time(text)
        if "tomorrow" in lower:
            return (now.date() + timedelta(days=1)).isoformat(), t
        if "today" in lower or "tonight" in lower:
            return now.date().isoformat(), t
        if "yesterday" in lower:
            return (now.date() - timedelta(days=1)).isoformat(), t
        try:
            from dateparser.search import search_dates

            matches = search_dates(
                text,
                settings={"RELATIVE_BASE": now, "PREFER_DATES_FROM": "future"},
            )
            if matches:
                _, parsed = matches[0]
                return (
                    parsed.date().isoformat(),
                    t
                    or (
                        parsed.strftime("%H:%M") if self._time_re.search(text) else None
                    ),
                )
        except Exception:
            pass
        return None, t

    def _extract_time(self, text: str) -> str | None:
        m = self._time_re.search(text)
        if not m:
            return None
        h, mi = int(m.group(1)), int(m.group(3) or "0")
        mer = (m.group(4) or "").lower()
        if mer == "pm" and h < 12:
            h += 12
        if mer == "am" and h == 12:
            h = 0
        return f"{h:02d}:{mi:02d}" if h <= 23 and mi <= 59 else None

    def _clean(self, text: str) -> str:
        text = re.sub(
            r"\b(today|tomorrow|tonight|next week|next month)\b", "", text, flags=re.I
        )
        text = re.sub(
            r"\b(?:at|on|by|due)\s+\d{1,2}(?::\d{2})?\s*(?:am|pm)?\b",
            "",
            text,
            flags=re.I,
        )
        text = re.sub(r"(?<![\[`])#[\w-]+", "", text)
        return re.sub(r"\s{2,}", " ", text).strip(" ,.-")

    # ── Backward-compat ───────────────────────────────────────────────────────

    def _parse_locally(self, message: str, now: datetime) -> AgentAction:
        return self._infer_action(message, now)
