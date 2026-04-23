import pytest
from src.ingestion.parser.patterns import TASK_PATTERN, DUE_DATE_PATTERN

def test_task_pattern():
    # Valid done tasks
    assert TASK_PATTERN.match("- [x] text").group(1) == "x"
    assert TASK_PATTERN.match("* [X] text").group(1) == "X"
    assert TASK_PATTERN.match("[v] text").group(1) == "v"
    assert TASK_PATTERN.match("[V] Some task").group(1) == "V"
    assert TASK_PATTERN.match("[-] In progress").group(1) == "-"
    assert TASK_PATTERN.match("[~] cancelled").group(1) == "~"
    
    # Valid open tasks
    m = TASK_PATTERN.match("[ ] Open task")
    assert m is not None
    assert m.group(1) == "" or m.group(1).isspace()

    # Weird spacing
    assert TASK_PATTERN.match("[  ] Open task").group(1) == ""
    assert TASK_PATTERN.match("[ x ] text").group(1) == "x"

    # TODOs
    assert TASK_PATTERN.match("TODO Buy milk").group(2) == "Buy milk"
    assert TASK_PATTERN.match("Todo: Buy milk").group(2) == "Buy milk"
    assert TASK_PATTERN.match("TODO : Buy milk").group(2) == "Buy milk"

    # Negative test
    assert not TASK_PATTERN.match("Just normal text")
    assert not TASK_PATTERN.match("-[ ] Not at start")

def test_due_date_pattern():
    assert DUE_DATE_PATTERN.search("Task due: 2026-04-22").group(1) == "2026-04-22"
    assert DUE_DATE_PATTERN.search("Task @due 2026/04/22").group(1) == "2026/04/22"

from src.ingestion.parser.extractors import _extract_task_meta

def test_extract_task_meta():
    res1 = _extract_task_meta("content", "Buy milk @due 2026-04-22 [!]", "x", 1)
    assert res1['is_done'] == 1
    assert res1['due_date'] == "2026-04-22"
    assert res1['priority'] == "high"
    assert res1['title'] == "Buy milk"

    res2 = _extract_task_meta("content", "Watch movie TODO: get popcorn #fun", None, 2)
    assert res2['is_done'] == 0
    assert res2['tags'] == "fun"
    assert res2['title'] == "Watch movie TODO: get popcorn"

if __name__ == "__main__":
    test_task_pattern()
    test_due_date_pattern()
    test_extract_task_meta()
    print("ALL TESTS PASSED")
