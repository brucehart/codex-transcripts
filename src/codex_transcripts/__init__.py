"""Convert Codex session JSONL to clean, mobile-friendly HTML pages with pagination."""

from .archive import (
    build_local_session_label,
    find_all_sessions,
    find_local_session_records,
    find_local_sessions,
    generate_batch_html,
    get_session_summary,
    resolve_project_key,
    scan_all_sessions,
)
from .cli import cli
from .common import extract_github_repo, format_session_timestamp, open_or_print_url, slugify
from .gist import (
    build_gist_description,
    build_gist_index_filename,
    build_gist_label,
    create_gist_from_output,
    extract_gist_id,
    inject_gist_preview_js,
    stage_gist_files,
)
from .parser import Entry, SessionData, get_session_summary_from_session, parse_session_file
from .renderer import (
    CSS,
    JS,
    SearchMode,
    generate_html,
    generate_html_from_session,
    get_template,
    make_msg_id,
    render_markdown_text,
    sanitize_html,
)


def main() -> None:
    cli()


__all__ = [
    "CSS",
    "Entry",
    "JS",
    "SearchMode",
    "SessionData",
    "build_gist_description",
    "build_gist_index_filename",
    "build_gist_label",
    "build_local_session_label",
    "cli",
    "create_gist_from_output",
    "extract_gist_id",
    "extract_github_repo",
    "find_all_sessions",
    "find_local_session_records",
    "find_local_sessions",
    "format_session_timestamp",
    "generate_batch_html",
    "generate_html",
    "generate_html_from_session",
    "get_session_summary",
    "get_session_summary_from_session",
    "get_template",
    "inject_gist_preview_js",
    "main",
    "make_msg_id",
    "open_or_print_url",
    "parse_session_file",
    "render_markdown_text",
    "resolve_project_key",
    "sanitize_html",
    "scan_all_sessions",
    "slugify",
    "stage_gist_files",
]
