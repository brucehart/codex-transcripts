from pathlib import Path

import pytest

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


def test_event_msg_duplicate_user_message_is_suppressed(tmp_path):
    session_file = tmp_path / "session.jsonl"
    session_file.write_text(
        "\n".join(
            [
                '{"timestamp":"2025-01-01T00:00:00Z","type":"session_meta","payload":{"id":"abc123","timestamp":"2025-01-01T00:00:00Z"}}',
                '{"timestamp":"2025-01-01T00:00:01Z","type":"response_item","payload":{"type":"message","role":"user","content":[{"type":"input_text","text":"Hello"}]}}',
                '{"timestamp":"2025-01-01T00:00:01Z","type":"event_msg","payload":{"type":"user_message","message":"Hello"}}',
            ]
        ),
        encoding="utf-8",
    )

    session = parse_session_file(session_file)
    user_messages = [
        entry
        for entry in session.entries
        if entry.entry_type == "message" and entry.role == "user"
    ]
    assert len(user_messages) == 1


def test_event_msg_duplicate_user_message_with_different_timestamp_is_suppressed(tmp_path):
    session_file = tmp_path / "session.jsonl"
    session_file.write_text(
        "\n".join(
            [
                '{"timestamp":"2025-01-01T00:00:00Z","type":"session_meta","payload":{"id":"abc123","timestamp":"2025-01-01T00:00:00Z"}}',
                '{"timestamp":"2025-01-01T00:00:01Z","type":"response_item","payload":{"type":"message","role":"user","content":[{"type":"input_text","text":"Hello"}]}}',
                '{"timestamp":"2025-01-01T00:00:02Z","type":"event_msg","payload":{"type":"user_message","message":"Hello"}}',
            ]
        ),
        encoding="utf-8",
    )

    session = parse_session_file(session_file)
    user_messages = [
        entry
        for entry in session.entries
        if entry.entry_type == "message" and entry.role == "user"
    ]
    assert len(user_messages) == 1


def test_legacy_format_is_still_supported(tmp_path):
    session_file = tmp_path / "legacy.jsonl"
    session_file.write_text(
        "\n".join(
            [
                '{"id":"legacy-1","timestamp":"2025-01-01T00:00:00Z","git":{"repository_url":"https://github.com/example/repo"}}',
                '{"type":"message","timestamp":"2025-01-01T00:00:01Z","role":"user","content":[{"text":"Legacy hello"}]}',
                '{"type":"function_call","timestamp":"2025-01-01T00:00:02Z","name":"shell","call_id":"c1","arguments":"{\\"command\\":\\"echo hi\\"}"}',
                '{"type":"function_call_output","timestamp":"2025-01-01T00:00:03Z","call_id":"c1","output":"ok"}',
            ]
        ),
        encoding="utf-8",
    )

    session = parse_session_file(session_file)

    assert session.session_id == "legacy-1"
    assert any(
        entry.entry_type == "tool_call" and entry.tool_name == "shell"
        for entry in session.entries
    )
    assert any(entry.entry_type == "tool_output" for entry in session.entries)


def test_parse_session_records_invalid_json_rows_in_non_strict_mode(tmp_path):
    session_file = tmp_path / "session.jsonl"
    session_file.write_text(
        "\n".join(
            [
                '{"timestamp":"2025-01-01T00:00:00Z","type":"session_meta","payload":{"id":"abc123"}}',
                "{not valid json}",
                '{"timestamp":"2025-01-01T00:00:01Z","type":"response_item","payload":{"type":"message","role":"user","content":[{"type":"input_text","text":"Hello"}]}}',
            ]
        ),
        encoding="utf-8",
    )

    session = parse_session_file(session_file)
    assert session.invalid_json_rows == 1
    assert session.invalid_json_line_numbers == [2]
    assert any(
        entry.entry_type == "message" and entry.role == "user" and entry.content == "Hello"
        for entry in session.entries
    )


def test_parse_session_strict_rows_raises_with_line_number(tmp_path):
    session_file = tmp_path / "session.jsonl"
    session_file.write_text(
        "\n".join(
            [
                '{"timestamp":"2025-01-01T00:00:00Z","type":"session_meta","payload":{"id":"abc123"}}',
                "{not valid json}",
            ]
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="line 2"):
        parse_session_file(session_file, strict_rows=True)


def test_instruction_fragment_message_is_not_collapsed(tmp_path):
    session_file = tmp_path / "session.jsonl"
    session_file.write_text(
        "\n".join(
            [
                '{"timestamp":"2025-01-01T00:00:00Z","type":"session_meta","payload":{"id":"abc123","instructions":"Always run tests before deploying."}}',
                '{"timestamp":"2025-01-01T00:00:01Z","type":"response_item","payload":{"type":"message","role":"user","content":[{"type":"input_text","text":"Reminder: Always run tests before deploying, then open a PR."}]}}',
            ]
        ),
        encoding="utf-8",
    )

    session = parse_session_file(session_file)
    user_messages = [
        entry
        for entry in session.entries
        if entry.entry_type == "message" and entry.role == "user"
    ]
    assert len(user_messages) == 1
    assert not user_messages[0].content.startswith("System instructions repeated.")


def test_instruction_exact_repeat_is_collapsed(tmp_path):
    session_file = tmp_path / "session.jsonl"
    session_file.write_text(
        "\n".join(
            [
                '{"timestamp":"2025-01-01T00:00:00Z","type":"session_meta","payload":{"id":"abc123","instructions":"Always run tests before deploying."}}',
                '{"timestamp":"2025-01-01T00:00:01Z","type":"response_item","payload":{"type":"message","role":"user","content":[{"type":"input_text","text":"Always run tests before deploying."}]}}',
            ]
        ),
        encoding="utf-8",
    )

    session = parse_session_file(session_file)
    user_messages = [
        entry
        for entry in session.entries
        if entry.entry_type == "message" and entry.role == "user"
    ]
    assert len(user_messages) == 1
    assert user_messages[0].content.startswith("System instructions repeated.")
