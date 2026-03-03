import json

from codex_transcripts import generate_html


def _write_session(path, repo_url, commit_hash, commit_message, user_text):
    lines = [
        json.dumps(
            {
                "timestamp": "2025-01-01T00:00:00Z",
                "type": "session_meta",
                "payload": {
                    "id": "abc123",
                    "timestamp": "2025-01-01T00:00:00Z",
                    "git": {"repository_url": repo_url, "branch": "main"},
                },
            }
        ),
        json.dumps(
            {
                "timestamp": "2025-01-01T00:00:01Z",
                "type": "response_item",
                "payload": {
                    "type": "message",
                    "role": "user",
                    "content": [{"type": "input_text", "text": user_text}],
                },
            }
        ),
        json.dumps(
            {
                "timestamp": "2025-01-01T00:00:02Z",
                "type": "response_item",
                "payload": {
                    "type": "function_call",
                    "name": "shell",
                    "call_id": "call-1",
                    "arguments": {"command": "echo hi"},
                },
            }
        ),
        json.dumps(
            {
                "timestamp": "2025-01-01T00:00:03Z",
                "type": "response_item",
                "payload": {
                    "type": "function_call_output",
                    "call_id": "call-1",
                    "output": f"[main {commit_hash}] {commit_message}",
                },
            }
        ),
    ]
    path.write_text("\n".join(lines), encoding="utf-8")


def test_generate_html_writes_search_index(tmp_path):
    session_file = tmp_path / "session.jsonl"
    _write_session(
        session_file,
        repo_url="https://github.com/example/repo",
        commit_hash="abcdef1",
        commit_message="first commit",
        user_text="Searchable user text",
    )

    output_dir = tmp_path / "output"
    generate_html(session_file, output_dir)

    search_index_path = output_dir / "search-index.json"
    assert search_index_path.exists()

    payload = json.loads(search_index_path.read_text(encoding="utf-8"))
    assert "items" in payload
    assert any("Searchable user text" in item["text"] for item in payload["items"])


def test_generate_html_repo_context_does_not_leak_between_runs(tmp_path):
    session_one = tmp_path / "session-one.jsonl"
    session_two = tmp_path / "session-two.jsonl"

    _write_session(
        session_one,
        repo_url="https://github.com/one/repo",
        commit_hash="abcdef1",
        commit_message="first commit",
        user_text="first session",
    )
    _write_session(
        session_two,
        repo_url="https://github.com/two/repo",
        commit_hash="deadbee",
        commit_message="second commit",
        user_text="second session",
    )

    out_one = tmp_path / "out-one"
    out_two = tmp_path / "out-two"
    generate_html(session_one, out_one)
    generate_html(session_two, out_two)

    first_content = (out_one / "index.html").read_text(encoding="utf-8")
    second_content = (out_two / "index.html").read_text(encoding="utf-8")

    assert "https://github.com/one/repo/commit/abcdef1" in first_content
    assert "https://github.com/two/repo/commit/deadbee" in second_content
    assert "https://github.com/two/repo/commit/deadbee" not in first_content
