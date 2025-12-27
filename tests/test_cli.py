from pathlib import Path

from click.testing import CliRunner

from codex_transcripts import cli, generate_html


FIXTURE = Path(__file__).parent / "fixtures" / "session_current.jsonl"


def write_fixture(target):
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(FIXTURE.read_text(encoding="utf-8"), encoding="utf-8")


def test_generate_html_creates_pages(tmp_path):
    output_dir = tmp_path / "output"
    index_path = generate_html(FIXTURE, output_dir)

    assert index_path.exists()
    assert (output_dir / "page-001.html").exists()
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
    monkeypatch.setattr("codex_transcripts.questionary.select", fake_select)

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
