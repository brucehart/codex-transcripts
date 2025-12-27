from pathlib import Path

import click
import pytest

from codex_transcripts import (
    build_gist_description,
    build_gist_index_filename,
    build_gist_label,
    extract_gist_id,
    extract_github_repo,
    format_session_timestamp,
    inject_gist_preview_js,
    parse_session_file,
    stage_gist_files,
)


def load_fixture_session(name="session_current.jsonl"):
    fixture = Path(__file__).parent / "fixtures" / name
    return parse_session_file(fixture), fixture


def test_format_session_timestamp():
    assert format_session_timestamp("2025-01-01T00:00:00Z") == "2025-01-01 00:00"
    assert format_session_timestamp("not-a-time") == "not-a-time"
    assert format_session_timestamp(None) is None


def test_build_gist_label_description_filename():
    session, fixture = load_fixture_session()
    assert build_gist_label(session, fixture) == "2025-01-01 00:00 abc123"
    assert (
        build_gist_description(session, fixture)
        == "Codex transcript: 2025-01-01 00:00 abc123"
    )
    assert (
        build_gist_index_filename(session, fixture)
        == "codex-transcript-2025-01-01-00-00-abc123.html"
    )


def test_extract_github_repo_handles_api_urls():
    repo = extract_github_repo(
        "https://api.github.com/repos/simonw/claude-code-transcripts"
    )
    assert repo == "simonw/claude-code-transcripts"


def test_extract_gist_id():
    assert (
        extract_gist_id("https://gist.github.com/user/abc123def456")
        == "abc123def456"
    )
    assert extract_gist_id(None) is None


def test_inject_gist_preview_js_once(tmp_path):
    html_path = tmp_path / "index.html"
    html_path.write_text("<html><body>OK</body></html>", encoding="utf-8")
    inject_gist_preview_js(tmp_path)
    inject_gist_preview_js(tmp_path)
    content = html_path.read_text(encoding="utf-8")
    assert "gistpreview.github.io" in content
    assert content.count("<script>") == 1


def test_stage_gist_files_renames_index_and_rewrites_links(tmp_path):
    output_dir = tmp_path / "output"
    output_dir.mkdir()
    (output_dir / "index.html").write_text(
        '<a href="index.html">Index</a><a href="page-001.html">Page</a>',
        encoding="utf-8",
    )
    (output_dir / "page-001.html").write_text("Page 1", encoding="utf-8")

    staging_dir = tmp_path / "stage"
    staging_dir.mkdir()
    files, index_target, _ = stage_gist_files(
        output_dir,
        include_json=False,
        index_filename="session-abc.html",
        staging_dir=staging_dir,
    )

    assert index_target.name == "session-abc.html"
    assert index_target in files
    content = index_target.read_text(encoding="utf-8")
    assert 'href="session-abc.html"' in content
    assert "page-001.html" in content


def test_stage_gist_files_requires_index_html(tmp_path):
    output_dir = tmp_path / "output"
    output_dir.mkdir()
    (output_dir / "page-001.html").write_text("Page 1", encoding="utf-8")

    staging_dir = tmp_path / "stage"
    staging_dir.mkdir()
    with pytest.raises(click.ClickException, match="Missing index.html"):
        stage_gist_files(
            output_dir,
            include_json=False,
            index_filename="session-abc.html",
            staging_dir=staging_dir,
        )
