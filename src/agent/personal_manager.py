from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal

from config import settings
from src.rag.retrieval import search_and_enrich_blocks


Intent = Literal["task", "event", "note", "question"]


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


class PersonalManagerAgent:
    """Local-first personal manager agent with optional OpenRouter parsing."""

    _task_re = re.compile(
        r"^(?:add\s+)?(?:todo|task|remind me to|remember to|i need to)\s+(.+)$",
        re.IGNORECASE,
    )
    _event_re = re.compile(
        r"^(?:add\s+)?(?:event|meeting|appointment|call)\s+(.+)$",
        re.IGNORECASE,
    )
    _question_re = re.compile(r"^(?:\?|ask|search|find|what|when|where|who|why|how)\b", re.IGNORECASE)
    _time_re = re.compile(r"\b(\d{1,2})(?::(\d{2}))?\s*(am|pm)?\b", re.IGNORECASE)

    async def run(self, message: str, *, now: datetime | None = None) -> AgentResult:
        now = now or datetime.now()
        context = await search_and_enrich_blocks(message, k=6)
        action = await self._parse(message, now=now, context=context)

        if action.intent == "question":
            reply = await self._answer(message, context)
        elif action.intent == "task":
            due = f" due {action.date}" if action.date else ""
            reply = f"Task captured: {action.text}{due}"
        elif action.intent == "event":
            when = " ".join(part for part in [action.date, action.time] if part)
            reply = f"Event captured: {action.text}" + (f" at {when}" if when else "")
        else:
            reply = "Note saved."

        return AgentResult(action=action, reply=reply, context=context)

    async def _parse(
        self,
        message: str,
        *,
        now: datetime,
        context: list[dict[str, Any]],
    ) -> AgentAction:
        llm_action = await self._parse_with_openrouter(message, now=now, context=context)
        if llm_action:
            return llm_action
        return self._parse_locally(message, now)

    def _parse_locally(self, message: str, now: datetime) -> AgentAction:
        text = message.strip()
        tags = re.findall(r"(?<![\[`])#([\w-]+)", text)
        date, time = self._extract_datetime(text, now)

        task = self._task_re.match(text)
        event = self._event_re.match(text)

        if self._question_re.match(text) or text.endswith("?"):
            intent: Intent = "question"
            body = text
        elif event or (time and any(word in text.lower() for word in ("meet", "call", "appointment", "event"))):
            intent = "event"
            body = event.group(1).strip() if event else text
        elif task or any(word in text.lower() for word in ("todo", "remind", "due ", "need to")):
            intent = "task"
            body = task.group(1).strip() if task else text
        else:
            intent = "note"
            body = text

        body = self._strip_datetime_noise(body)
        return AgentAction(intent=intent, text=body, date=date, time=time, tags=tags)

    async def _parse_with_openrouter(
        self,
        message: str,
        *,
        now: datetime,
        context: list[dict[str, Any]],
    ) -> AgentAction | None:
        api_key = settings.OPENROUTER_API_KEY or settings.API_KEY
        if not api_key:
            return None

        try:
            from langchain_openrouter import ChatOpenRouter
        except Exception:
            return None

        model = settings.OPENROUTER_MODEL or settings.MODEL
        llm = ChatOpenRouter(
            model=model,
            api_key=api_key,
            base_url=settings.OPENROUTER_API_BASE,
            temperature=0,
            max_retries=1,
            app_title="LARPer Personal Manager",
        )

        context_lines = [
            f"- {hit.get('title')}: {hit.get('content')}"
            for hit in context[:5]
            if hit.get("content")
        ]
        prompt = (
            "Parse this personal-manager input into compact JSON with keys "
            "intent(task,event,note,question), text, date(YYYY-MM-DD|null), "
            "time(HH:MM|null), tags(array). Use the current date for relative dates. "
            f"Current date: {now.date().isoformat()}.\n"
            f"Known context:\n{chr(10).join(context_lines) or '- none'}\n"
            f"Input: {message}"
        )

        try:
            response = await llm.ainvoke(prompt)
            data = json.loads(self._json_payload(str(response.content)))
            intent = data.get("intent")
            if intent not in {"task", "event", "note", "question"}:
                return None
            return AgentAction(
                intent=intent,
                text=str(data.get("text") or message).strip(),
                date=data.get("date") or None,
                time=data.get("time") or None,
                tags=[str(tag) for tag in data.get("tags", [])],
            )
        except Exception:
            return None

    async def _answer(self, message: str, context: list[dict[str, Any]]) -> str:
        if not context:
            return "I could not find anything relevant in your local notes."

        api_key = settings.OPENROUTER_API_KEY or settings.API_KEY
        if api_key:
            try:
                from langchain_openrouter import ChatOpenRouter

                llm = ChatOpenRouter(
                    model=settings.OPENROUTER_MODEL or settings.MODEL,
                    api_key=api_key,
                    base_url=settings.OPENROUTER_API_BASE,
                    temperature=0.2,
                    max_retries=1,
                    app_title="LARPer Personal Manager",
                )
                context_text = "\n".join(
                    f"[{i}] {hit.get('title')} ({hit.get('file_path')}): {hit.get('content')}"
                    for i, hit in enumerate(context[:6], 1)
                )
                response = await llm.ainvoke(
                    "Answer from these local notes only. Be concise.\n"
                    f"Question: {message}\nContext:\n{context_text}"
                )
                return str(response.content).strip()
            except Exception:
                pass

        top = context[0]
        return f"Best match: {top.get('content')} ({top.get('title')})"

    def _extract_datetime(self, text: str, now: datetime) -> tuple[str | None, str | None]:
        lower = text.lower()
        explicit_time = self._extract_time(text)
        if "tomorrow" in lower:
            from datetime import timedelta

            return (now.date() + timedelta(days=1)).isoformat(), explicit_time
        if "today" in lower or "tonight" in lower:
            return now.date().isoformat(), explicit_time
        if "yesterday" in lower:
            from datetime import timedelta

            return (now.date() - timedelta(days=1)).isoformat(), explicit_time

        try:
            from dateparser.search import search_dates

            matches = search_dates(
                text,
                settings={
                    "RELATIVE_BASE": now,
                    "PREFER_DATES_FROM": "future",
                    "RETURN_AS_TIMEZONE_AWARE": False,
                },
            )
        except Exception:
            matches = None

        if matches:
            _, parsed = matches[0]
            parsed_time = explicit_time or (parsed.strftime("%H:%M") if self._time_re.search(text) else None)
            return parsed.date().isoformat(), parsed_time

        return None, explicit_time

    def _extract_time(self, text: str) -> str | None:
        match = self._time_re.search(text)
        if not match:
            return None
        hour = int(match.group(1))
        minute = int(match.group(2) or "0")
        meridiem = (match.group(3) or "").lower()
        if meridiem == "pm" and hour < 12:
            hour += 12
        if meridiem == "am" and hour == 12:
            hour = 0
        if hour > 23 or minute > 59:
            return None
        return f"{hour:02d}:{minute:02d}"

    def _strip_datetime_noise(self, text: str) -> str:
        text = re.sub(r"\b(today|tomorrow|tonight|next week|next month)\b", "", text, flags=re.I)
        text = re.sub(r"\b(?:at|on|by|due)\s+\d{1,2}(?::\d{2})?\s*(?:am|pm)?\b", "", text, flags=re.I)
        text = re.sub(r"(?<![\[`])#[\w-]+", "", text)
        return re.sub(r"\s{2,}", " ", text).strip(" ,.-")

    def _json_payload(self, content: str) -> str:
        content = content.strip()
        fenced = re.search(r"```(?:json)?\s*(.*?)```", content, re.DOTALL | re.IGNORECASE)
        if fenced:
            return fenced.group(1).strip()
        start = content.find("{")
        end = content.rfind("}")
        if start != -1 and end != -1 and end > start:
            return content[start : end + 1]
        return content
