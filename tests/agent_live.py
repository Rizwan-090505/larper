"""
Regression test for the Gemini streaming path in PersonalManagerAgent.

This does NOT hit the network. It patches google.genai.Client with a fake
that mirrors the real SDK's shape exactly (google-genai==2.17.0):

    client.aio.models.generate_content_stream(...)

is an `async def` — calling it returns a *coroutine*, which must be
`await`-ed to obtain the actual `AsyncIterator[GenerateContentResponse]`.
`async for chunk in client.aio.models.generate_content_stream(...)`
(no await) raises:

    TypeError: 'async for' requires an object with __aiter__ method, got coroutine

That exception used to be swallowed by the broad `except Exception` in
`_run_gemini`, silently falling back to the local parser — which is why the
agent always said "set your Gemini key" even with a valid key configured.

This test uses the project's actual PersonalManagerAgent implementation
(src/agent/personal_manager.py) unmodified — only the transport
(genai.Client) is faked — so it will fail again if the await/async-for bug,
or the streaming callback wiring, ever regresses.

Run just this file:
    uv run pytest tests/test_agent_gemini.py -v
"""

from __future__ import annotations

import asyncio

import pytest

import google.genai as genai
from src.agent.personal_manager import PersonalManagerAgent


# ── Fakes that mirror the real google-genai response shape ────────────────


class _FakePart:
    def __init__(self, text=None, function_call=None, thought=False):
        self.text = text
        self.function_call = function_call
        self.thought = thought


class _FakeContent:
    def __init__(self, parts):
        self.parts = parts


class _FakeCandidate:
    def __init__(self, parts, finish_reason=""):
        self.content = _FakeContent(parts)
        self.finish_reason = finish_reason


class _FakeChunk:
    def __init__(self, parts, finish_reason=""):
        self.candidates = [_FakeCandidate(parts, finish_reason)]


async def _fake_text_stream(*words: str, finish_reason: str = "STOP"):
    for i, w in enumerate(words):
        fr = finish_reason if i == len(words) - 1 else ""
        yield _FakeChunk([_FakePart(text=w)], finish_reason=fr)
        await asyncio.sleep(0)


class _FakeAsyncModels:
    """Mimics google.genai.models.AsyncModels.generate_content_stream:
    an `async def` whose call must be awaited before it's iterable."""

    def __init__(self, script):
        self.call_count = 0
        self._script = script  # list of word-tuples, one per round

    async def generate_content_stream(self, *, model, contents, config=None):
        idx = min(self.call_count, len(self._script) - 1)
        words = self._script[idx]
        self.call_count += 1
        return _fake_text_stream(*words)


class _FakeAio:
    def __init__(self, models):
        self.models = models


class _FakeClient:
    """Drop-in replacement for genai.Client used inside personal_manager."""

    last_instance: "_FakeClient | None" = None

    def __init__(self, script, api_key=None):
        self.aio = _FakeAio(_FakeAsyncModels(script))
        _FakeClient.last_instance = self


def _install_fake_client(monkeypatch, script):
    def _factory(*, api_key=None):
        return _FakeClient(script, api_key=api_key)

    monkeypatch.setattr(genai, "Client", _factory)


# ── Tests ───────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_gemini_streams_and_returns_reply(monkeypatch):
    """A plain text-only reply (no tool calls) should stream chunk-by-chunk
    to stream_callback and produce a correct final AgentResult."""
    _install_fake_client(
        monkeypatch,
        script=[("Hello", " from", " Gemini", " (mocked).", "\n[intent:chat]")],
    )

    agent = PersonalManagerAgent()
    agent._api_key = "fake-key-present"  # simulate a configured key

    received: list[str] = []

    async def on_chunk(c: str) -> None:
        received.append(c)

    result = await agent.run("hi there", stream_callback=on_chunk)

    assert _FakeClient.last_instance.aio.models.call_count == 1
    assert received, "no chunks were streamed to stream_callback — streaming broken"
    assert "Gemini" in result.reply
    assert "[intent:" not in result.reply, "intent marker should be stripped"
    assert result.action.intent == "chat"


@pytest.mark.asyncio
async def test_gemini_falls_back_to_local_when_transport_broken(monkeypatch):
    """If generate_content_stream is called WITHOUT awaiting first (the
    original bug), the resulting TypeError must not crash the agent — it
    should fall back to the local parser AND record the real error instead
    of just blaming a missing key."""

    class _BrokenAsyncModels:
        call_count = 0

        def generate_content_stream(self, *, model, contents, config=None):
            # Returns a coroutine (this method is NOT `async def` here on
            # purpose) to simulate what happens if calling code forgets to
            # `await` a real (async def) generate_content_stream and tries
            # `async for` directly on it.
            _BrokenAsyncModels.call_count += 1

            async def _coro():
                return None

            return _coro()  # a coroutine object, not an async iterator

    class _BrokenAio:
        def __init__(self):
            self.models = _BrokenAsyncModels()

    class _BrokenClient:
        def __init__(self, api_key=None):
            self.aio = _BrokenAio()

    monkeypatch.setattr(genai, "Client", lambda **kw: _BrokenClient(**kw))

    agent = PersonalManagerAgent()
    agent._api_key = "fake-key-present"

    result = await agent.run("hi there")

    # Must not raise, must fall back, and must surface the real reason.
    assert result is not None
    assert agent._last_error, "the real transport error should be recorded"
    assert "coroutine" in agent._last_error.lower() or "TypeError" in agent._last_error


@pytest.mark.asyncio
async def test_gemini_agent_calls_tool_then_synthesizes(monkeypatch):
    """A round with a function_call should execute the tool, then a second
    streaming round should produce the final text — validating the
    multi-round tool-loop + streaming interplay."""
    fc = _FakePart(
        function_call=type(
            "FC", (), {"name": "search_notes", "args": {"query": "drone"}}
        )()
    )

    async def _round_1():
        yield _FakeChunk([fc], finish_reason="STOP")

    class _ToolThenTextModels:
        def __init__(self):
            self.call_count = 0

        async def generate_content_stream(self, *, model, contents, config=None):
            self.call_count += 1
            if self.call_count == 1:
                return _round_1()
            return _fake_text_stream("Found it.", "\n[intent:question]")

    class _Aio:
        def __init__(self):
            self.models = _ToolThenTextModels()

    class _Client:
        def __init__(self, api_key=None):
            self.aio = _Aio()

    monkeypatch.setattr(genai, "Client", lambda **kw: _Client(**kw))

    async def _fake_execute_tool(self, name, args):
        return [
            {
                "id": 1,
                "title": "drone note",
                "file_path": "pages/fyp/Droneresearch.md",
                "excerpt": "...",
            }
        ]

    monkeypatch.setattr(PersonalManagerAgent, "_execute_tool", _fake_execute_tool)

    agent = PersonalManagerAgent()
    agent._api_key = "fake-key-present"

    received: list[str] = []

    async def on_chunk(c: str) -> None:
        received.append(c)

    result = await agent.run("what do I know about drones?", stream_callback=on_chunk)

    assert result.tool_calls and result.tool_calls[0]["tool"] == "search_notes"
    assert "Found it." in result.reply
    assert received, "final synthesis round should have streamed text"


@pytest.mark.asyncio
async def test_gemini_preserves_thought_signature_on_function_call_replay(monkeypatch):
    """Regression test for: 400 INVALID_ARGUMENT 'Function call is missing a
    thought_signature in functionCall parts'.

    Gemini 3.x attaches a `thought_signature` to the Part that carries a
    `function_call`, and requires that exact signature to be echoed back
    verbatim when the call is replayed into conversation history on the
    next round. The original bug: the agent captured only
    `part.function_call` while streaming (discarding the rest of the Part,
    including `thought_signature`), then rebuilt a bare
    `Part(function_call=fc)` with no signature when appending the model's
    turn to `contents` — silently dropping it and triggering the API error
    on every question that needed a tool call, which fell back to the
    generic "closest match" local reply.

    This test asserts the exact Part object (thought_signature included)
    that the fake stream handed back is the same object propagated into the
    `contents` sent on the next round.
    """
    SIGNATURE = b"opaque-signature-bytes-xyz-1234"

    fc = _FakePart(
        function_call=type(
            "FC", (), {"name": "search_notes", "args": {"query": "drone"}}
        )()
    )
    fc.thought_signature = SIGNATURE  # what Gemini 3.x actually attaches

    async def _round_1():
        yield _FakeChunk([fc], finish_reason="STOP")

    class _Models:
        def __init__(self):
            self.call_count = 0
            self.seen_contents_round_2 = None

        async def generate_content_stream(self, *, model, contents, config=None):
            self.call_count += 1
            if self.call_count == 1:
                return _round_1()
            # Second round: the model's previous turn (containing the
            # function_call Part) must already be present in `contents`,
            # with its thought_signature intact.
            self.seen_contents_round_2 = list(contents)
            return _fake_text_stream("Found it.", "\n[intent:question]")

    class _Aio:
        def __init__(self, models):
            self.models = models

    class _Client:
        def __init__(self, models, api_key=None):
            self.aio = _Aio(models)

    models = _Models()
    monkeypatch.setattr(genai, "Client", lambda **kw: _Client(models, **kw))

    async def _fake_execute_tool(self, name, args):
        return [
            {
                "id": 1,
                "title": "drone note",
                "file_path": "pages/fyp/Droneresearch.md",
                "excerpt": "...",
            }
        ]

    monkeypatch.setattr(PersonalManagerAgent, "_execute_tool", _fake_execute_tool)

    agent = PersonalManagerAgent()
    agent._api_key = "fake-key-present"

    result = await agent.run("what do I know about drones?")

    assert models.call_count == 2
    assert models.seen_contents_round_2 is not None

    # Find the model-turn Content carrying the function_call and confirm the
    # thought_signature survived the round-trip unmodified.
    found_signature = None
    for content in models.seen_contents_round_2:
        if getattr(content, "role", None) != "model":
            continue
        for part in content.parts or []:
            if getattr(part, "function_call", None) is not None:
                found_signature = getattr(part, "thought_signature", None)

    assert found_signature == SIGNATURE, (
        "thought_signature was NOT preserved when replaying the function_call "
        "Part back into conversation history — this reproduces the "
        "'400 INVALID_ARGUMENT: Function call is missing a thought_signature' "
        "bug that caused the agent to silently fall back to the local "
        "'closest match' reply instead of a real conversational answer."
    )
    assert "Found it." in result.reply
