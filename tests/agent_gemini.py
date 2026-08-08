"""
Live smoke test: actually calls Gemini using your configured GEMINI_API_KEY
and GEMINI_MODEL, through the real PersonalManagerAgent — no mocks.

This talks to the real network (generativelanguage.googleapis.com), so it
can't run inside network-restricted sandboxes. Run it yourself:

    uv run python scripts/test_gemini_live.py

Exit code 0 means Gemini replied successfully and streaming worked.
Any other outcome prints the real error/response so you can see exactly
what's wrong (bad key, bad model name, network/firewall, etc.) instead of
the generic "set GEMINI_API_KEY" fallback message.
"""

from __future__ import annotations

import asyncio
import os
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv

load_dotenv()

from config import settings
from src.agent.personal_manager import PersonalManagerAgent


async def main() -> int:
    api_key = os.environ.get("GEMINI_API_KEY") or getattr(
        settings, "GEMINI_API_KEY", ""
    )
    model = os.environ.get("GEMINI_MODEL") or getattr(settings, "GEMINI_MODEL", "")

    print(f"GEMINI_API_KEY set : {'yes (' + api_key[:6] + '…)' if api_key else 'NO'}")
    print(f"GEMINI_MODEL       : {model or '(default)'}")
    print("-" * 60)

    if not api_key:
        print("FAIL: no GEMINI_API_KEY found in environment/.env — nothing to test.")
        return 1

    agent = PersonalManagerAgent()
    if not agent._api_key:
        print(
            "FAIL: agent could not locate an API key via its own lookup "
            "(_find_api_key) even though one exists in the environment. "
            "This itself would be a bug worth reporting."
        )
        return 1

    print("Sending a test message to Gemini and streaming the reply…\n")

    chunks: list[str] = []

    async def on_chunk(text: str) -> None:
        chunks.append(text)
        print(text, end="", flush=True)

    try:
        result = await agent.run(
            "Say hello in exactly one short sentence, no notes lookup needed.",
            now=datetime.now(),
            stream_callback=on_chunk,
        )
    except Exception as exc:  # pragma: no cover - diagnostic path
        print(f"\n\nFAIL: agent.run() raised an exception: {type(exc).__name__}: {exc}")
        return 1

    print("\n" + "-" * 60)

    if not chunks:
        print(
            "FAIL: no chunks were streamed to stream_callback — streaming is broken "
            "even if a final reply came back."
        )

    if agent._last_error:
        print(
            f"NOTE: agent recorded an internal error during the run: {agent._last_error}"
        )

    if result is None:
        print("FAIL: agent.run() returned None.")
        return 1

    print(f"Final reply   : {result.reply!r}")
    print(f"Detected intent: {result.action.intent}")
    print(f"Tool calls made: {[t['tool'] for t in result.tool_calls]}")

    # Heuristic: if we ended up with the local-fallback wording, Gemini
    # never actually answered even though a key is configured.
    fallback_markers = (
        "Set GEMINI_API_KEY",
        "AI mode failed",
        "AI mode is unavailable",
        "I couldn't find anything about that in your notes.",
    )
    if any(m in result.reply for m in fallback_markers) and not chunks:
        print("\nFAIL: got the LOCAL FALLBACK reply, not a real Gemini response.")
        print(
            "This means _run_gemini failed. Check the logged error above/agent._last_error."
        )
        return 1

    if not chunks:
        print("\nFAIL: got a reply but streaming produced zero chunks.")
        return 1

    print("\nPASS: received a real streamed reply from Gemini.")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
