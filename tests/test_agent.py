from datetime import datetime

from src.agent import PersonalManagerAgent


def test_local_agent_parses_relative_task_date():
    agent = PersonalManagerAgent()
    action = agent._parse_locally(
        "remind me to renew passport tomorrow #admin",
        datetime(2026, 8, 3, 9, 0),
    )

    assert action.intent == "task"
    assert action.text == "renew passport"
    assert action.date == "2026-08-04"
    assert action.tags == ["admin"]


def test_local_agent_parses_event_time():
    agent = PersonalManagerAgent()
    action = agent._parse_locally(
        "meeting with Sam tomorrow at 14:30 #work",
        datetime(2026, 8, 3, 9, 0),
    )

    assert action.intent == "event"
    assert action.date == "2026-08-04"
    assert action.time == "14:30"
    assert action.tags == ["work"]
