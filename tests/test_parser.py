from pathlib import Path

from codex_transcripts import parse_session_file, resolve_project_key, get_session_summary


def test_parse_current_session():
    fixture = Path(__file__).parent / "fixtures" / "session_current.jsonl"
    session = parse_session_file(fixture)

    assert session.session_id == "abc123"
    assert session.cwd == "/tmp/project"
    assert session.instructions == "System instructions"
    assert session.git["branch"] == "main"
    assert len(session.entries) == 4


def test_project_key_from_git():
    fixture = Path(__file__).parent / "fixtures" / "session_current.jsonl"
    session = parse_session_file(fixture)

    project_key, display_name = resolve_project_key(session)
    assert project_key == "example/repo"
    assert display_name == "example/repo"


def test_summary_from_user_message():
    fixture = Path(__file__).parent / "fixtures" / "session_current.jsonl"
    summary = get_session_summary(fixture)
    assert summary == "Hello"
