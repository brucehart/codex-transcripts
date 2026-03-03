import importlib
from pathlib import Path

from click.testing import CliRunner

from codex_transcripts import (
    build_local_session_label,
    cli,
    generate_html,
    get_session_summary,
    parse_session_file,
)


FIXTURE = Path(__file__).parent / "fixtures" / "session_current.jsonl"


def write_fixture(target):
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(FIXTURE.read_text(encoding="utf-8"), encoding="utf-8")


def test_generate_html_creates_pages(tmp_path):
    output_dir = tmp_path / "output"
    index_path = generate_html(FIXTURE, output_dir)

    assert index_path.exists()
    assert (output_dir / "page-001.html").exists()
    assert (output_dir / "search-index.json").exists()
    content = index_path.read_text(encoding="utf-8")
    assert "Codex transcript" in content
    assert "Hello" in content


def test_json_cli_generates_output(tmp_path):
    output_dir = tmp_path / "output"
    runner = CliRunner()

    result = runner.invoke(
        cli,
        ["json", str(FIXTURE), "-o", str(output_dir)],
    )

    assert result.exit_code == 0, result.output
    assert (output_dir / "index.html").exists()


def test_local_cli_generates_output(tmp_path, monkeypatch):
    sessions_dir = tmp_path / ".codex" / "sessions" / "2025" / "12" / "24"
    session_file = sessions_dir / "run-local.jsonl"
    write_fixture(session_file)

    class DummySelect:
        def __init__(self, value):
            self.value = value

        def ask(self):
            return self.value

    def fake_select(*args, **kwargs):
        return DummySelect(session_file)

    monkeypatch.setenv("HOME", str(tmp_path))
    cli_module = importlib.import_module("codex_transcripts.cli")
    monkeypatch.setattr(cli_module.questionary, "select", fake_select)

    output_dir = tmp_path / "output"
    runner = CliRunner()
    result = runner.invoke(cli, ["local", "-o", str(output_dir)])

    assert result.exit_code == 0, result.output
    assert (output_dir / "index.html").exists()


def test_all_cli_generates_archive(tmp_path):
    sessions_dir = tmp_path / "sessions"
    write_fixture(sessions_dir / "2025" / "12" / "24" / "run-a.jsonl")
    write_fixture(sessions_dir / "2025" / "12" / "25" / "run-b.jsonl")

    output_dir = tmp_path / "archive"
    runner = CliRunner()
    result = runner.invoke(
        cli,
        ["all", "-s", str(sessions_dir), "-o", str(output_dir), "-q"],
    )

    assert result.exit_code == 0, result.output
    assert (output_dir / "index.html").exists()
    project_dir = output_dir / "example-repo"
    assert (project_dir / "index.html").exists()
    assert (project_dir / "run-a" / "index.html").exists()
    assert (project_dir / "run-b" / "index.html").exists()


def test_build_local_session_label_includes_repo():
    session = parse_session_file(FIXTURE)
    summary = get_session_summary(FIXTURE)
    label = build_local_session_label(session, summary, max_length=80)
    assert label.startswith("example/repo — Hello")


def test_cli_help_lists_serve_command():
    runner = CliRunner()
    result = runner.invoke(cli, ["--help"])
    assert result.exit_code == 0, result.output
    assert "serve" in result.output


def test_json_cli_writes_exports_and_stats(tmp_path):
    output_dir = tmp_path / "output"
    runner = CliRunner()
    result = runner.invoke(
        cli,
        [
            "json",
            str(FIXTURE),
            "-o",
            str(output_dir),
            "--markdown",
            "--txt",
            "--stats-json",
            "--theme",
            "compact",
        ],
    )

    assert result.exit_code == 0, result.output
    assert (output_dir / "index.html").exists()
    assert (output_dir / "transcript.md").exists()
    assert (output_dir / "transcript.txt").exists()
    assert (output_dir / "stats.json").exists()
    assert (output_dir / "assets" / "theme.css").exists()


def test_diff_cli_generates_report(tmp_path):
    output_dir = tmp_path / "diff"
    runner = CliRunner()
    result = runner.invoke(
        cli,
        [
            "diff",
            str(FIXTURE),
            str(FIXTURE),
            "-o",
            str(output_dir),
        ],
    )

    assert result.exit_code == 0, result.output
    assert (output_dir / "index.html").exists()
    assert (output_dir / "diff.json").exists()


def test_json_cli_warns_on_skipped_malformed_rows(tmp_path):
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

    output_dir = tmp_path / "output"
    runner = CliRunner()
    result = runner.invoke(
        cli,
        ["json", str(session_file), "-o", str(output_dir)],
    )

    assert result.exit_code == 0, result.output
    assert "Warning: skipped 1 malformed JSON row(s)" in result.output
    assert (output_dir / "index.html").exists()


def test_json_cli_strict_rows_fails_on_malformed_input(tmp_path):
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

    output_dir = tmp_path / "output"
    runner = CliRunner()
    result = runner.invoke(
        cli,
        ["json", str(session_file), "-o", str(output_dir), "--strict-rows"],
    )

    assert result.exit_code != 0
    assert "Invalid JSON row at line 2" in result.output


def test_json_cli_redaction_is_consistent_across_all_outputs(tmp_path):
    session_file = tmp_path / "session.jsonl"
    session_file.write_text(
        "\n".join(
            [
                '{"timestamp":"2025-01-01T00:00:00Z","type":"session_meta","payload":{"id":"abc123"}}',
                '{"timestamp":"2025-01-01T00:00:01Z","type":"response_item","payload":{"type":"message","role":"user","content":[{"type":"input_text","text":"Contact me at user@example.com"}]}}',
            ]
        ),
        encoding="utf-8",
    )

    output_dir = tmp_path / "output"
    runner = CliRunner()
    result = runner.invoke(
        cli,
        [
            "json",
            str(session_file),
            "-o",
            str(output_dir),
            "--markdown",
            "--txt",
            "--redact-pattern",
            r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}",
        ],
    )

    assert result.exit_code == 0, result.output
    page_content = (output_dir / "page-001.html").read_text(encoding="utf-8")
    index_content = (output_dir / "index.html").read_text(encoding="utf-8")
    search_content = (output_dir / "search-index.json").read_text(encoding="utf-8")
    md_content = (output_dir / "transcript.md").read_text(encoding="utf-8")
    txt_content = (output_dir / "transcript.txt").read_text(encoding="utf-8")

    for content in (page_content, index_content, search_content, md_content, txt_content):
        assert "user@example.com" not in content
        assert "[REDACTED]" in content
