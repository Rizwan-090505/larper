import json
import re
import asyncio
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal
from dotenv import load_dotenv

from config import settings
from src.rag.enhanced_retrieval import search_and_enrich_blocks
from google import genai
from google.genai import types

load_dotenv()

_THINKING_RE = re.compile(r"<thinking>.*?</thinking>", re.DOTALL | re.IGNORECASE)

Intent = Literal["task", "event", "note", "question", "chat"]

GEMINI_MODEL = settings.GEMINI_MODEL if hasattr(settings, "GEMINI_MODEL") else "gemini-2.0-flash"

# How many turns of conversation to keep in memory
MAX_HISTORY = 20


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


# ─── Tool schemas for Claude tool use ────────────────────────────────────────

TOOLS = [
    types.Tool(
        function_declarations=[
            types.FunctionDeclaration(
                name="search_notes",
                description="Search the user's personal knowledge base (notes, journals, tasks). Use this before answering any question about the user's life, work, or plans. This is a hybrid search combining semantic similarity, keywords, and temporal relevance.",
                parameters=types.Schema(
                    type=types.Type.OBJECT,
                    properties={
                        "query": types.Schema(type=types.Type.STRING, description="Natural language search query"),
                        "k": types.Schema(type=types.Type.INTEGER, description="Number of results (default 6)"),
                    },
                    required=["query"],
                ),
            ),
            types.FunctionDeclaration(
                name="tag_search",
                description="Search notes by a specific #tag.",
                parameters=types.Schema(
                    type=types.Type.OBJECT,
                    properties={
                        "tag": types.Schema(type=types.Type.STRING, description="Tag name (with or without #)"),
                    },
                    required=["tag"],
                ),
            ),
            types.FunctionDeclaration(
                name="fuzzy_search",
                description="Fuzzy search across note titles and content. Good for finding specific terms or phrases.",
                parameters=types.Schema(
                    type=types.Type.OBJECT,
                    properties={
                        "query": types.Schema(type=types.Type.STRING, description="Search term for fuzzy matching"),
                        "k": types.Schema(type=types.Type.INTEGER, description="Number of results (default 6)"),
                    },
                    required=["query"],
                ),
            ),
            types.FunctionDeclaration(
                name="reference_search",
                description="Search for notes that reference other notes via [[links]].",
                parameters=types.Schema(
                    type=types.Type.OBJECT,
                    properties={
                        "reference": types.Schema(type=types.Type.STRING, description="Reference text or note title"),
                        "k": types.Schema(type=types.Type.INTEGER, description="Number of results (default 6)"),
                    },
                    required=["reference"],
                ),
            ),
            types.FunctionDeclaration(
                name="graph_expansion",
                description="Find notes related to given note IDs through semantic connections.",
                parameters=types.Schema(
                    type=types.Type.OBJECT,
                    properties={
                        "note_ids": types.Schema(type=types.Type.ARRAY, description="List of note IDs to expand from", items=types.Schema(type=types.Type.INTEGER)),
                        "k": types.Schema(type=types.Type.INTEGER, description="Number of related notes to return (default 6)"),
                    },
                    required=["note_ids"],
                ),
            ),
        ]
    )
]

SYSTEM_PROMPT = """\
You are LARPer, an autonomous personal knowledge assistant embedded in a terminal note-taking app.
You help the user manage their notes, tasks, and journals with full access to their knowledge base.

Today is {date}.

# AUTONOMY & TOOL USAGE
You have access to multiple search tools. Use them proactively:
1. search_notes: Default hybrid search (semantic + keyword + temporal). Use for general queries.
2. tag_search: When user mentions a #tag or asks about specific categories.
3. fuzzy_search: When looking for specific terms, names, or exact phrases.
4. reference_search: When user mentions [[links]] or asks about connections between notes.
5. graph_expansion: When you have note IDs and want to find related content.

You are encouraged to use multiple tools in sequence for complex queries. For example:
- First search_notes for general context
- Then tag_search for specific categories
- Then reference_search to explore connections

# RESPONSE GUIDELINES
- Be concise but thorough. Replies should be helpful and actionable.
- When you find relevant notes, mention specific filenames (e.g., "journals/2026-08-04.md") so they become clickable.
- For questions: Answer based on search results, cite sources, and suggest follow-up questions.
- For tasks/events: Confirm capture briefly and mention any relevant existing notes.
- For notes: Confirm saved and connect to related existing content.

# SEARCH STRATEGY
- Always search before answering questions about the user's knowledge.
- If initial search yields little, try different tools or reformulate the query.
- Combine results from multiple tools for comprehensive answers.
- Use graph_expansion to explore connections when you have starting points.

# FILE REFERENCES
Always write file paths exactly as they appear in search results (e.g., "journals/2026-08-04.md") so the UI can make them clickable links.

IMPORTANT: At the very end of every reply, on its own line, output EXACTLY one of these intent markers:
[intent:task]    — user wants to capture a to-do / reminder / task
[intent:event]   — user is logging a meeting, appointment, or event  
[intent:question]— user is asking a question about their notes / knowledge
[intent:note]    — user wants to save a note or thought
[intent:chat]    — general conversation, no specific capture needed
Do NOT explain the marker. Just append it silently.
"""


class PersonalManagerAgent:
    """
    Conversational agent using Claude (claude-sonnet-4-6) via Anthropic API.
    Maintains conversation history across turns. Uses tool_use for RAG search.
    Falls back to local regex parser if API key is missing.
    """

    def __init__(self):
        self._history: list[dict] = []  # [{role, content}]
        self._api_key: str = self._find_api_key()
        self._search_tools_loaded = False

    def _find_api_key(self) -> str:
        """Find any available Gemini API key from env/config."""
        import os
        return (
            os.environ.get("GEMINI_API_KEY", "")
            or getattr(settings, "GEMINI_API_KEY", "")
            or ""
        )

    # ── Public entry point ────────────────────────────────────────────────────

    async def run(self, message: str, *, now: datetime | None = None) -> AgentResult:
        now = now or datetime.now()

        if self._api_key:
            result = await self._run_gemini(message, now=now)
            if result:
                return result

        # Fallback: local parser + RAG
        return await self._run_local(message, now=now)

    # ── Claude agentic loop ───────────────────────────────────────────────────

    async def _run_gemini(self, message: str, *, now: datetime) -> AgentResult | None:
        # Add user message to history
        self._history.append({"role": "user", "parts": [types.Part.from_text(text=message)]})
        if len(self._history) > MAX_HISTORY:
            self._history = self._history[-MAX_HISTORY:]

        system = SYSTEM_PROMPT.format(date=now.date().isoformat())
        tool_calls_log: list[dict] = []
        final_text = ""

        contents = []
        for msg in self._history:
            contents.append(types.Content(role=msg["role"], parts=msg["parts"]))

        client = genai.Client(api_key=self._api_key)

        try:
            for _iteration in range(5):  # agentic loop
                config = types.GenerateContentConfig(
                    system_instruction=system,
                    tools=TOOLS,
                    temperature=0.7,
                )
                
                resp = await client.aio.models.generate_content(
                    model=GEMINI_MODEL,
                    contents=contents,
                    config=config
                )

                if not resp.candidates:
                    return None

                candidate = resp.candidates[0]
                message_parts = candidate.content.parts
                
                # Collect text — skip thinking/thought parts
                text_parts = []
                for p in message_parts:
                    # Skip dedicated thought parts (Gemini thinking models)
                    if getattr(p, "thought", False):
                        continue
                    if p.text:
                        # Strip any <thinking>…</thinking> blocks embedded in text
                        cleaned = _THINKING_RE.sub("", p.text).strip()
                        if cleaned:
                            text_parts.append(cleaned)
                
                if text_parts:
                    final_text = "\n".join(text_parts).strip()

                function_calls = [p.function_call for p in message_parts if p.function_call]
                
                if not function_calls:
                    break
                    
                contents.append(candidate.content)

                # Execute tools
                tool_results_parts = []
                for fc in function_calls:
                    tool_name = fc.name
                    tool_input = type(fc.args).to_dict(fc.args) if hasattr(fc.args, 'to_dict') else dict(fc.args)
                    if not isinstance(tool_input, dict):
                        try:
                            tool_input = dict(fc.args)
                        except:
                            tool_input = getattr(fc, "args", {})
                            
                    tool_calls_log.append({"tool": tool_name, "args": tool_input})

                    result_data = await self._execute_tool(tool_name, tool_input)
                    
                    tool_results_parts.append(
                        types.Part.from_function_response(
                            name=tool_name,
                            response={"result": result_data}
                        )
                    )

                contents.append(types.Content(role="user", parts=tool_results_parts))

        except Exception as exc:
            return None

        if not final_text:
            return None

        # Extract [intent:xxx] tag that the model appends
        _INTENT_RE = re.compile(r"\[intent:(task|event|note|question|chat)\]", re.IGNORECASE)
        ai_intent: Intent | None = None
        m = _INTENT_RE.search(final_text)
        if m:
            ai_intent = m.group(1).lower()  # type: ignore[assignment]
            # Strip the tag (and any trailing whitespace/newline) from the reply
            final_text = _INTENT_RE.sub("", final_text).rstrip()

        # Add assistant reply (without the tag) to persistent history
        self._history.append({"role": "model", "parts": [types.Part.from_text(text=final_text)]})

        action = self._infer_action(message, now)
        # Override locally-inferred intent with the AI's explicit intent
        if ai_intent:
            action.intent = ai_intent
        return AgentResult(
            action=action,
            reply=final_text,
            tool_calls=tool_calls_log,
        )

    async def _execute_tool(self, name: str, args: dict) -> Any:
        try:
            from src.rag import search_tools
            
            if name == "search_notes":
                results = await search_and_enrich_blocks(
                    args.get("query", ""), k=int(args.get("k", 6))
                )
                results = search_tools.normalize_result_paths(results)
                return [
                    {
                        "title": r.get("title", ""),
                        "file": r.get("file_path", ""),
                        "file_path": r.get("file_path", ""),
                        "excerpt": (r.get("content") or "")[:300],
                    }
                    for r in results[:6]
                ]
            elif name == "tag_search":
                results = await search_tools.tag_search(args.get("tag", ""), k=int(args.get("k", 6)))
                return [
                    {
                        "title": r.get("title", ""),
                        "file": r.get("file_path", ""),
                        "file_path": r.get("file_path", ""),
                        "excerpt": (r.get("content") or "")[:300],
                    }
                    for r in results[:6]
                ]
            elif name == "fuzzy_search":
                results = await search_tools.fzf_search(args.get("query", ""), k=int(args.get("k", 6)))
                return [
                    {
                        "title": r.get("title", ""),
                        "file": r.get("file_path", ""),
                        "file_path": r.get("file_path", ""),
                        "excerpt": (r.get("content") or "")[:300],
                    }
                    for r in results[:6]
                ]
            elif name == "reference_search":
                results = await search_tools.ref_search(args.get("reference", ""), k=int(args.get("k", 6)))
                return [
                    {
                        "title": r.get("title", ""),
                        "file": r.get("file_path", ""),
                        "file_path": r.get("file_path", ""),
                        "target_title": r.get("target_title", ""),
                        "excerpt": (r.get("content") or "")[:300],
                    }
                    for r in results[:6]
                ]
            elif name == "graph_expansion":
                note_ids = args.get("note_ids", [])
                if isinstance(note_ids, list):
                    note_id_set = set(note_ids)
                    results = await search_tools.graph_expand(note_id_set, k=int(args.get("k", 6)))
                    return [
                        {
                            "title": r.get("title", ""),
                            "file": r.get("file_path", ""),
                            "file_path": r.get("file_path", ""),
                            "excerpt": (r.get("content") or "")[:300],
                        }
                        for r in results[:6]
                    ]
        except Exception as exc:
            return {"error": str(exc)}
        return {"error": f"unknown tool: {name}"}

    # ── Local fallback ────────────────────────────────────────────────────────

    async def _run_local(self, message: str, *, now: datetime) -> AgentResult:
        context = []
        try:
            context = await search_and_enrich_blocks(message, k=4)
            from src.rag import search_tools
            context = search_tools.normalize_result_paths(context)
        except Exception:
            pass

        action = self._infer_action(message, now)

        if action.intent == "question":
            if context:
                top = context[0]
                reply = (
                    f"Best match from your notes ({top.get('title', '')}): "
                    f"{(top.get('content') or '')[:200]}"
                )
            else:
                reply = "No matching notes found. (Set GEMINI_API_KEY in .env for full AI responses.)"
        elif action.intent == "task":
            due = f" due {action.date}" if action.date else ""
            reply = f"Task captured: {action.text}{due}"
        elif action.intent == "event":
            when = " ".join(p for p in [action.date, action.time] if p)
            reply = f"Event noted: {action.text}" + (f" at {when}" if when else "")
        else:
            reply = "Note saved."

        return AgentResult(action=action, reply=reply, context=context)

    def _parse_locally(self, message: str, now: datetime) -> AgentAction:
        """Backward-compatible alias used by older tests."""
        return self._infer_action(message, now)

    # ── Intent inference (used for UI actions, not for the reply) ────────────

    _task_re = re.compile(
        r"^(?:add\s+)?(?:todo|task|remind me to|remember to|i need to)\s+(.+)$",
        re.IGNORECASE,
    )
    _event_re = re.compile(
        r"^(?:add\s+)?(?:event|meeting|appointment|call)\s+(.+)$",
        re.IGNORECASE,
    )
    _question_re = re.compile(
        r"^(?:\?|ask|search|find|what|when|where|who|why|how)\b", re.IGNORECASE
    )
    _time_re = re.compile(r"\b(\d{1,2})(?::(\d{2}))?\s*(am|pm)?\b", re.IGNORECASE)

    def _infer_action(self, message: str, now: datetime) -> AgentAction:
        text = message.strip()
        tags = re.findall(r"(?<![\[`])#([\w-]+)", text)
        date, time = self._extract_datetime(text, now)

        task_m = self._task_re.match(text)
        event_m = self._event_re.match(text)

        if self._question_re.match(text) or text.endswith("?"):
            intent: Intent = "question"
            body = text
        elif event_m or (time and any(w in text.lower() for w in ("meet", "call", "appointment", "event"))):
            intent = "event"
            body = event_m.group(1).strip() if event_m else text
        elif task_m or any(w in text.lower() for w in ("todo", "remind", "due ", "need to")):
            intent = "task"
            body = task_m.group(1).strip() if task_m else text
        else:
            intent = "chat"
            body = text

        return AgentAction(intent=intent, text=self._clean(body), date=date, time=time, tags=tags)

    def _extract_datetime(self, text: str, now: datetime) -> tuple[str | None, str | None]:
        lower = text.lower()
        t = self._extract_time(text)
        if "tomorrow" in lower:
            from datetime import timedelta
            return (now.date() + timedelta(days=1)).isoformat(), t
        if "today" in lower or "tonight" in lower:
            return now.date().isoformat(), t
        if "yesterday" in lower:
            from datetime import timedelta
            return (now.date() - timedelta(days=1)).isoformat(), t
        try:
            from dateparser.search import search_dates
            matches = search_dates(text, settings={"RELATIVE_BASE": now, "PREFER_DATES_FROM": "future"})
            if matches:
                _, parsed = matches[0]
                return parsed.date().isoformat(), t or (parsed.strftime("%H:%M") if self._time_re.search(text) else None)
        except Exception:
            pass
        return None, t

    def _extract_time(self, text: str) -> str | None:
        m = self._time_re.search(text)
        if not m:
            return None
        h, mi = int(m.group(1)), int(m.group(2) or "0")
        mer = (m.group(3) or "").lower()
        if mer == "pm" and h < 12:
            h += 12
        if mer == "am" and h == 12:
            h = 0
        return f"{h:02d}:{mi:02d}" if h <= 23 and mi <= 59 else None

    def _clean(self, text: str) -> str:
        text = re.sub(r"\b(today|tomorrow|tonight|next week|next month)\b", "", text, flags=re.I)
        text = re.sub(r"\b(?:at|on|by|due)\s+\d{1,2}(?::\d{2})?\s*(?:am|pm)?\b", "", text, flags=re.I)
        text = re.sub(r"(?<![\[`])#[\w-]+", "", text)
        return re.sub(r"\s{2,}", " ", text).strip(" ,.-")
