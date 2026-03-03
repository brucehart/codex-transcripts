from pathlib import Path

import pytest

from codex_transcripts import generate_batch_html, scan_all_sessions
import codex_transcripts.archive as archive_module


FIXTURE = Path(__file__).parent / "fixtures" / "session_current.jsonl"


def write_fixture(target: Path):
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(FIXTURE.read_text(encoding="utf-8"), encoding="utf-8")


def test_scan_all_sessions_skips_bad_files(tmp_path):
    sessions_dir = tmp_path / "sessions"
    write_fixture(sessions_dir / "2025" / "12" / "24" / "run-good.jsonl")
    bad_file = sessions_dir / "2025" / "12" / "24" / "run-bad.jsonl"
    bad_file.parent.mkdir(parents=True, exist_ok=True)
    bad_file.write_text("{not json}\n", encoding="utf-8")

    projects, scan_failures = scan_all_sessions(sessions_dir, skip_bad_files=True)

    assert len(projects) == 1
    assert len(projects[0]["sessions"]) == 1
    assert len(scan_failures) == 1
    assert scan_failures[0]["path"].endswith("run-bad.jsonl")


def test_scan_all_sessions_strict_raises_on_bad_files(tmp_path):
    sessions_dir = tmp_path / "sessions"
    bad_file = sessions_dir / "2025" / "12" / "24" / "run-bad.jsonl"
    bad_file.parent.mkdir(parents=True, exist_ok=True)
    bad_file.write_text("{not json}\n", encoding="utf-8")

    with pytest.raises(RuntimeError, match="Failed to parse session file"):
        scan_all_sessions(sessions_dir, skip_bad_files=False)


def test_generate_batch_html_excludes_failed_session_links(tmp_path, monkeypatch):
    sessions_dir = tmp_path / "sessions"
    write_fixture(sessions_dir / "2025" / "12" / "24" / "run-a.jsonl")
    write_fixture(sessions_dir / "2025" / "12" / "24" / "run-b.jsonl")

    original_generate = archive_module.generate_html_from_session

    def fake_generate_html_from_session(session, output_dir, **kwargs):
        source_path = Path(kwargs["source_path"])
        if source_path.stem == "run-b":
            raise ValueError("boom")
        return original_generate(session, output_dir, **kwargs)

    monkeypatch.setattr(
        archive_module, "generate_html_from_session", fake_generate_html_from_session
    )

    output_dir = tmp_path / "archive"
    stats = generate_batch_html(sessions_dir, output_dir, include_json=False)

    assert stats["total_sessions"] == 1
    assert len(stats["failed_sessions"]) == 1

    project_index = (output_dir / "example-repo" / "index.html").read_text(
        encoding="utf-8"
    )
    assert 'href="run-a/index.html"' in project_index
    assert 'href="run-b/index.html"' not in project_index
    assert "run-b" in project_index
    assert "boom" in project_index


def test_generate_batch_html_incremental_skips_unchanged_sessions(tmp_path, monkeypatch):
    sessions_dir = tmp_path / "sessions"
    write_fixture(sessions_dir / "2025" / "12" / "24" / "run-a.jsonl")

    output_dir = tmp_path / "archive"
    first_stats = generate_batch_html(sessions_dir, output_dir, incremental=True)
    assert first_stats["total_sessions"] == 1
    assert first_stats["skipped_sessions"] == 0

    def should_not_render(*args, **kwargs):
        raise RuntimeError("renderer should not run for unchanged sessions")

    monkeypatch.setattr(archive_module, "generate_html_from_session", should_not_render)

    second_stats = generate_batch_html(sessions_dir, output_dir, incremental=True)
    assert second_stats["total_sessions"] == 1
    assert second_stats["skipped_sessions"] == 1
    assert second_stats["failed_sessions"] == []


def test_generate_batch_html_master_index_contains_filter_controls(tmp_path):
    sessions_dir = tmp_path / "sessions"
    write_fixture(sessions_dir / "2025" / "12" / "24" / "run-a.jsonl")

    output_dir = tmp_path / "archive"
    generate_batch_html(sessions_dir, output_dir)

    master_index = (output_dir / "index.html").read_text(encoding="utf-8")
    assert "filter-tool" in master_index
    assert "archive-session-item" in master_index
