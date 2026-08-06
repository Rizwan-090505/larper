from src.TUI.state.store import store


def test_normalize_journal_aliases():
    assert store.normalize_note_path("journals/2026-08-06", default_dir="pages") == "journals/2026-08-06.md"
    assert store.normalize_note_path("journal/2026-08-06", default_dir="pages") == "journals/2026-08-06.md"
    assert store.normalize_note_path("pages/journal/2026-08-06", default_dir="pages") == "journals/2026-08-06.md"
    assert store.normalize_note_path("pages/journals/2026-08-06", default_dir="pages") == "journals/2026-08-06.md"
    assert store.normalize_note_path("2026-08-06", default_dir="pages") == "pages/2026-08-06.md"
    assert store.normalize_note_path("pages/2026-08-06", default_dir="pages") == "pages/2026-08-06.md"
