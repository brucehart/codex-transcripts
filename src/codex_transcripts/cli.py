"""CLI entrypoints for codex-transcripts."""

from __future__ import annotations

import functools
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from datetime import datetime
from pathlib import Path
import tempfile

import click
from click_default_group import DefaultGroup
import questionary

from .archive import (
    build_local_session_label,
    find_local_session_records,
    generate_batch_html,
    resolve_project_key,
)
from .common import open_or_print_url
from .exporters import write_transcript_exports
from .gist import (
    build_gist_description,
    build_gist_index_filename,
    create_gist_from_output,
)
from .parser import SessionData, parse_session_file
from .redaction import available_redaction_presets, redact_session_data, resolve_redaction_patterns
from .renderer import SearchMode, generate_html_from_session
from .session_diff import generate_diff_report
from .stats import build_stats_report, collect_session_metrics, write_stats_report


def _resolve_output_dir(output: str | None, output_auto: bool, source_stem: str) -> tuple[Path, bool]:
    auto_open = output is None and not output_auto
    if output_auto:
        parent_dir = Path(output) if output else Path(".")
        resolved_output = parent_dir / source_stem
    elif output is None:
        resolved_output = Path(tempfile.gettempdir()) / f"codex-session-{source_stem}"
    else:
        resolved_output = Path(output)
    return resolved_output, auto_open


def _resolve_search_mode(search_mode: str) -> SearchMode:
    normalized = search_mode.lower()
    if normalized not in {"inline", "external", "auto"}:
        raise click.ClickException(f"Invalid search mode: {search_mode}")
    return normalized  # type: ignore[return-value]


def _write_stats_if_requested(
    write_stats: bool,
    output_dir: Path,
    sessions: list[dict],
) -> Path | None:
    if not write_stats:
        return None
    report = build_stats_report(sessions)
    return write_stats_report(report, output_dir / "stats.json")


def _render_single_session_output(
    *,
    session: SessionData,
    source_path: Path,
    output_dir: Path,
    include_json: bool,
    search_mode: SearchMode,
    theme: str | None,
    redact_patterns: tuple[str, ...],
    markdown_enabled: bool,
    text_enabled: bool,
    pdf_enabled: bool,
    write_stats: bool,
) -> tuple[Path, Path | None]:
    session_for_output = (
        redact_session_data(session, redact_patterns) if redact_patterns else session
    )

    index_path = generate_html_from_session(
        session_for_output,
        output_dir,
        source_path=source_path,
        include_json=include_json,
        search_mode=search_mode,
        theme=theme,
    )

    if markdown_enabled or text_enabled or pdf_enabled:
        try:
            write_transcript_exports(
                session_for_output,
                output_dir,
                markdown_enabled=markdown_enabled,
                text_enabled=text_enabled,
                pdf_enabled=pdf_enabled,
            )
        except RuntimeError as exc:
            raise click.ClickException(str(exc)) from exc

    stats_path = _write_stats_if_requested(
        write_stats,
        output_dir,
        [collect_session_metrics(session_for_output, source_path=source_path)],
    )
    return index_path, stats_path


@click.group(cls=DefaultGroup, default="local", default_if_no_args=True)
@click.version_option(None, "-v", "--version", package_name="codex-transcripts")
def cli():
    """Convert Codex session JSONL to mobile-friendly HTML pages."""


@cli.command("local")
@click.option(
    "-o",
    "--output",
    type=click.Path(),
    help="Output directory. If not specified, writes to temp dir and opens in browser.",
)
@click.option(
    "-a",
    "--output-auto",
    is_flag=True,
    help="Auto-name output subdirectory based on session filename.",
)
@click.option(
    "--json",
    "include_json",
    is_flag=True,
    help="Include the original JSONL session file in the output directory.",
)
@click.option(
    "--gist",
    "create_gist",
    is_flag=True,
    help="Create a GitHub gist from the generated HTML and output a preview URL.",
)
@click.option(
    "--gist-public",
    "gist_public",
    is_flag=True,
    help="Create a public GitHub gist (default: secret). Implies --gist.",
)
@click.option(
    "--open",
    "open_browser",
    is_flag=True,
    help="Open the generated index.html in your default browser (default if no -o specified).",
)
@click.option(
    "--search-mode",
    type=click.Choice(["inline", "external", "auto"], case_sensitive=False),
    default="auto",
    show_default=True,
    help="How to embed transcript search data in index.html.",
)
@click.option(
    "--theme",
    type=str,
    default="default",
    show_default=True,
    help="Theme name (`default`, `compact`, `high-contrast`) or custom CSS file path.",
)
@click.option(
    "--markdown",
    "markdown_enabled",
    is_flag=True,
    help="Also export transcript as Markdown (transcript.md).",
)
@click.option(
    "--txt",
    "text_enabled",
    is_flag=True,
    help="Also export transcript as plain text (transcript.txt).",
)
@click.option(
    "--pdf",
    "pdf_enabled",
    is_flag=True,
    help="Also export transcript as PDF (transcript.pdf, requires optional `weasyprint`).",
)
@click.option(
    "--stats-json",
    "write_stats",
    is_flag=True,
    help="Write stats report JSON (`stats.json`).",
)
@click.option(
    "--redact",
    "redact_enabled",
    is_flag=True,
    help="Enable built-in redaction defaults (emails + tokens).",
)
@click.option(
    "--redact-preset",
    "redact_presets",
    type=click.Choice(available_redaction_presets(), case_sensitive=False),
    multiple=True,
    help="Apply named redaction presets. Repeatable.",
)
@click.option(
    "--redact-pattern",
    "redact_patterns",
    multiple=True,
    help="Regex pattern to redact from rendered/exported output. Repeatable.",
)
@click.option(
    "--limit",
    default=10,
    help="Maximum number of sessions to show (default: 10)",
)
def local_cmd(
    output,
    output_auto,
    include_json,
    create_gist,
    gist_public,
    open_browser,
    search_mode,
    theme,
    markdown_enabled,
    text_enabled,
    pdf_enabled,
    write_stats,
    redact_enabled,
    redact_presets,
    redact_patterns,
    limit,
):
    """Select and convert a local Codex session to HTML."""
    sessions_folder = Path.home() / ".codex" / "sessions"
    if not sessions_folder.exists():
        click.echo(f"Sessions folder not found: {sessions_folder}")
        click.echo("No local Codex sessions available.")
        return

    click.echo("Loading local sessions...")
    records = find_local_session_records(sessions_folder, limit=limit)
    if not records:
        click.echo("No local sessions found.")
        return

    choices = []
    record_by_path: dict[Path, SessionData] = {}
    for record in records:
        filepath = record.path
        mod_time = datetime.fromtimestamp(record.mtime)
        size_kb = record.size / 1024
        date_str = mod_time.strftime("%Y-%m-%d %H:%M")
        display_summary = build_local_session_label(record.session, record.summary, max_length=80)
        display = f"{date_str}  {size_kb:5.0f} KB  {display_summary}"
        choices.append(questionary.Choice(title=display, value=filepath))
        record_by_path[filepath] = record.session

    selected = questionary.select("Select a session to convert:", choices=choices).ask()
    if selected is None:
        click.echo("No session selected.")
        return

    session_file = Path(selected)
    output_dir, auto_open = _resolve_output_dir(output, output_auto, session_file.stem)
    resolved_redaction_patterns = resolve_redaction_patterns(
        redact_enabled,
        redact_presets,
        redact_patterns,
    )
    selected_session = record_by_path.get(session_file) or parse_session_file(session_file)
    index_path, stats_path = _render_single_session_output(
        session=selected_session,
        source_path=session_file,
        output_dir=output_dir,
        include_json=include_json,
        search_mode=_resolve_search_mode(search_mode),
        theme=theme,
        redact_patterns=resolved_redaction_patterns,
        markdown_enabled=markdown_enabled,
        text_enabled=text_enabled,
        pdf_enabled=pdf_enabled,
        write_stats=write_stats,
    )

    click.echo(f"Output: {output_dir.resolve()}")
    if stats_path:
        click.echo(f"Stats: {stats_path.resolve()}")

    if create_gist or gist_public:
        description = build_gist_description(selected_session, session_file)
        index_filename = build_gist_index_filename(selected_session, session_file)
        click.echo("Creating GitHub gist...")
        gist_url, preview_url = create_gist_from_output(
            output_dir,
            description,
            public=gist_public,
            include_json=include_json,
            index_filename=index_filename,
        )
        if gist_url:
            click.echo(f"Gist: {gist_url}")
        else:
            click.echo("Gist created, but no URL was returned.")
        if preview_url:
            click.echo(f"Preview: {preview_url}")

    if open_browser or auto_open:
        open_or_print_url(index_path.resolve().as_uri())


@cli.command("json")
@click.argument("json_file", type=click.Path(exists=True))
@click.option(
    "-o",
    "--output",
    type=click.Path(),
    help="Output directory. If not specified, writes to temp dir and opens in browser.",
)
@click.option(
    "-a",
    "--output-auto",
    is_flag=True,
    help="Auto-name output subdirectory based on filename.",
)
@click.option(
    "--json",
    "include_json",
    is_flag=True,
    help="Include the original JSONL session file in the output directory.",
)
@click.option(
    "--gist",
    "create_gist",
    is_flag=True,
    help="Create a GitHub gist from the generated HTML and output a preview URL.",
)
@click.option(
    "--gist-public",
    "gist_public",
    is_flag=True,
    help="Create a public GitHub gist (default: secret). Implies --gist.",
)
@click.option(
    "--open",
    "open_browser",
    is_flag=True,
    help="Open the generated index.html in your default browser (default if no -o specified).",
)
@click.option(
    "--search-mode",
    type=click.Choice(["inline", "external", "auto"], case_sensitive=False),
    default="auto",
    show_default=True,
    help="How to embed transcript search data in index.html.",
)
@click.option(
    "--theme",
    type=str,
    default="default",
    show_default=True,
    help="Theme name (`default`, `compact`, `high-contrast`) or custom CSS file path.",
)
@click.option(
    "--markdown",
    "markdown_enabled",
    is_flag=True,
    help="Also export transcript as Markdown (transcript.md).",
)
@click.option(
    "--txt",
    "text_enabled",
    is_flag=True,
    help="Also export transcript as plain text (transcript.txt).",
)
@click.option(
    "--pdf",
    "pdf_enabled",
    is_flag=True,
    help="Also export transcript as PDF (transcript.pdf, requires optional `weasyprint`).",
)
@click.option(
    "--stats-json",
    "write_stats",
    is_flag=True,
    help="Write stats report JSON (`stats.json`).",
)
@click.option(
    "--redact",
    "redact_enabled",
    is_flag=True,
    help="Enable built-in redaction defaults (emails + tokens).",
)
@click.option(
    "--redact-preset",
    "redact_presets",
    type=click.Choice(available_redaction_presets(), case_sensitive=False),
    multiple=True,
    help="Apply named redaction presets. Repeatable.",
)
@click.option(
    "--redact-pattern",
    "redact_patterns",
    multiple=True,
    help="Regex pattern to redact from rendered/exported output. Repeatable.",
)
def json_cmd(
    json_file,
    output,
    output_auto,
    include_json,
    create_gist,
    gist_public,
    open_browser,
    search_mode,
    theme,
    markdown_enabled,
    text_enabled,
    pdf_enabled,
    write_stats,
    redact_enabled,
    redact_presets,
    redact_patterns,
):
    """Convert a Codex session JSONL file to HTML."""
    json_path = Path(json_file)
    output_dir, auto_open = _resolve_output_dir(output, output_auto, json_path.stem)
    resolved_redaction_patterns = resolve_redaction_patterns(
        redact_enabled,
        redact_presets,
        redact_patterns,
    )
    session = parse_session_file(json_path)
    index_path, stats_path = _render_single_session_output(
        session=session,
        source_path=json_path,
        output_dir=output_dir,
        include_json=include_json,
        search_mode=_resolve_search_mode(search_mode),
        theme=theme,
        redact_patterns=resolved_redaction_patterns,
        markdown_enabled=markdown_enabled,
        text_enabled=text_enabled,
        pdf_enabled=pdf_enabled,
        write_stats=write_stats,
    )

    click.echo(f"Output: {output_dir.resolve()}")
    if stats_path:
        click.echo(f"Stats: {stats_path.resolve()}")

    if create_gist or gist_public:
        description = build_gist_description(session, json_path)
        index_filename = build_gist_index_filename(session, json_path)
        click.echo("Creating GitHub gist...")
        gist_url, preview_url = create_gist_from_output(
            output_dir,
            description,
            public=gist_public,
            include_json=include_json,
            index_filename=index_filename,
        )
        if gist_url:
            click.echo(f"Gist: {gist_url}")
        else:
            click.echo("Gist created, but no URL was returned.")
        if preview_url:
            click.echo(f"Preview: {preview_url}")

    if open_browser or auto_open:
        open_or_print_url(index_path.resolve().as_uri())


@cli.command("all")
@click.option(
    "-s",
    "--source",
    type=click.Path(exists=True),
    help="Source directory containing Codex sessions (default: ~/.codex/sessions).",
)
@click.option(
    "-o",
    "--output",
    type=click.Path(),
    default="./codex-archive",
    help="Output directory for the archive (default: ./codex-archive).",
)
@click.option(
    "--json",
    "include_json",
    is_flag=True,
    help="Include original JSONL session files alongside HTML.",
)
@click.option(
    "--open",
    "open_browser",
    is_flag=True,
    help="Open the generated archive in your default browser.",
)
@click.option(
    "-q",
    "--quiet",
    is_flag=True,
    help="Suppress all output except errors.",
)
@click.option(
    "--skip-bad-files/--no-skip-bad-files",
    default=True,
    show_default=True,
    help="Skip malformed session files during archive scanning.",
)
@click.option(
    "--strict",
    is_flag=True,
    help="Fail immediately on parse/render errors.",
)
@click.option(
    "--incremental",
    is_flag=True,
    help="Skip unchanged sessions when output already exists.",
)
@click.option(
    "--workers",
    type=click.IntRange(min=1),
    default=1,
    show_default=True,
    help="Number of parallel render workers.",
)
@click.option(
    "--search-mode",
    type=click.Choice(["inline", "external", "auto"], case_sensitive=False),
    default="auto",
    show_default=True,
    help="How to embed transcript search data in index.html.",
)
@click.option(
    "--theme",
    type=str,
    default="default",
    show_default=True,
    help="Theme name (`default`, `compact`, `high-contrast`) or custom CSS file path.",
)
@click.option(
    "--markdown",
    "markdown_enabled",
    is_flag=True,
    help="Also export transcript Markdown files for each session.",
)
@click.option(
    "--txt",
    "text_enabled",
    is_flag=True,
    help="Also export transcript text files for each session.",
)
@click.option(
    "--pdf",
    "pdf_enabled",
    is_flag=True,
    help="Also export transcript PDF files for each session (requires optional `weasyprint`).",
)
@click.option(
    "--stats-json",
    "write_stats",
    is_flag=True,
    help="Write aggregate stats report JSON (`stats.json`).",
)
@click.option(
    "--redact",
    "redact_enabled",
    is_flag=True,
    help="Enable built-in redaction defaults (emails + tokens).",
)
@click.option(
    "--redact-preset",
    "redact_presets",
    type=click.Choice(available_redaction_presets(), case_sensitive=False),
    multiple=True,
    help="Apply named redaction presets. Repeatable.",
)
@click.option(
    "--redact-pattern",
    "redact_patterns",
    multiple=True,
    help="Regex pattern to redact from rendered/exported output. Repeatable.",
)
@click.option(
    "--from-date",
    type=click.DateTime(formats=["%Y-%m-%d"]),
    help="Filter sessions from this date (inclusive, YYYY-MM-DD).",
)
@click.option(
    "--to-date",
    type=click.DateTime(formats=["%Y-%m-%d"]),
    help="Filter sessions up to this date (inclusive, YYYY-MM-DD).",
)
@click.option(
    "--tool",
    "tool_filters",
    multiple=True,
    help="Filter archive sessions by tool name (repeatable).",
)
@click.option(
    "--error-only",
    is_flag=True,
    help="Only include sessions containing error tool outputs.",
)
@click.option(
    "--repo",
    "repo_filter",
    type=str,
    help="Filter sessions by repository substring.",
)
@click.option(
    "--branch",
    "branch_filter",
    type=str,
    help="Filter sessions by branch substring.",
)
def all_cmd(
    source,
    output,
    include_json,
    open_browser,
    quiet,
    skip_bad_files,
    strict,
    incremental,
    workers,
    search_mode,
    theme,
    markdown_enabled,
    text_enabled,
    pdf_enabled,
    write_stats,
    redact_enabled,
    redact_presets,
    redact_patterns,
    from_date,
    to_date,
    tool_filters,
    error_only,
    repo_filter,
    branch_filter,
):
    """Convert local Codex sessions to a browsable HTML archive."""
    if source is None:
        source_dir = Path.home() / ".codex" / "sessions"
    else:
        source_dir = Path(source)
    if not source_dir.exists():
        raise click.ClickException(f"Source directory not found: {source_dir}")

    output_dir = Path(output)
    if not quiet:
        click.echo(f"Scanning {source_dir}...")

    def on_progress(_project_name, _session_name, current, total):
        if not quiet and current % 10 == 0:
            click.echo(f"  Processed {current}/{total} sessions...")

    resolved_redaction_patterns = resolve_redaction_patterns(
        redact_enabled,
        redact_presets,
        redact_patterns,
    )

    try:
        stats = generate_batch_html(
            source_dir,
            output_dir,
            include_json=include_json,
            progress_callback=on_progress,
            skip_bad_files=skip_bad_files,
            strict=strict,
            incremental=incremental,
            workers=workers,
            search_mode=_resolve_search_mode(search_mode),
            redact_patterns=resolved_redaction_patterns,
            theme=theme,
            export_markdown=markdown_enabled,
            export_txt=text_enabled,
            export_pdf=pdf_enabled,
            from_date=from_date.date() if from_date else None,
            to_date=to_date.date() if to_date else None,
            tool_filters=tool_filters,
            error_only=error_only,
            repo_filter=repo_filter,
            branch_filter=branch_filter,
        )
    except RuntimeError as exc:
        raise click.ClickException(str(exc)) from exc

    if not stats["total_sessions"] and not stats["failed_sessions"] and not stats["scan_failures"]:
        if not quiet:
            click.echo("No sessions found.")
        return

    if stats["scan_failures"]:
        click.echo(f"\nWarning: {len(stats['scan_failures'])} session file(s) failed to parse:")
        for failure in stats["scan_failures"]:
            click.echo(f"  {failure['path']}: {failure['error']}")

    if stats["failed_sessions"]:
        click.echo(f"\nWarning: {len(stats['failed_sessions'])} session(s) failed:")
        for failure in stats["failed_sessions"]:
            click.echo(f"  {failure['project']}/{failure['session']}: {failure['error']}")

    stats_path = _write_stats_if_requested(
        write_stats,
        output_dir,
        list(stats.get("session_stats", [])),
    )

    if not quiet:
        click.echo(
            f"\nGenerated archive with {stats['total_projects']} projects, "
            f"{stats['total_sessions']} sessions"
        )
        if stats["skipped_sessions"]:
            click.echo(f"Skipped unchanged sessions: {stats['skipped_sessions']}")
        click.echo(f"Output: {output_dir.resolve()}")
        if stats_path:
            click.echo(f"Stats: {stats_path.resolve()}")

    if open_browser:
        open_or_print_url((output_dir / "index.html").resolve().as_uri())


@cli.command("diff")
@click.argument("session_a", type=click.Path(exists=True))
@click.argument("session_b", type=click.Path(exists=True))
@click.option(
    "-o",
    "--output",
    type=click.Path(),
    help="Output directory for diff report (default: temp directory).",
)
@click.option(
    "--open",
    "open_browser",
    is_flag=True,
    help="Open the generated diff report in your default browser.",
)
@click.option(
    "--theme",
    type=str,
    default="default",
    show_default=True,
    help="Theme name (`default`, `compact`, `high-contrast`) or custom CSS file path.",
)
@click.option(
    "--stats-json",
    "write_stats",
    is_flag=True,
    help="Write stats report JSON (`stats.json`) for both compared sessions.",
)
@click.option(
    "--force-cross-project",
    is_flag=True,
    help="Allow diffing sessions from different projects.",
)
@click.option(
    "--redact",
    "redact_enabled",
    is_flag=True,
    help="Enable built-in redaction defaults (emails + tokens).",
)
@click.option(
    "--redact-preset",
    "redact_presets",
    type=click.Choice(available_redaction_presets(), case_sensitive=False),
    multiple=True,
    help="Apply named redaction presets. Repeatable.",
)
@click.option(
    "--redact-pattern",
    "redact_patterns",
    multiple=True,
    help="Regex pattern to redact from diff output. Repeatable.",
)
def diff_cmd(
    session_a,
    session_b,
    output,
    open_browser,
    theme,
    write_stats,
    force_cross_project,
    redact_enabled,
    redact_presets,
    redact_patterns,
):
    """Generate a diff view between two transcript sessions."""
    path_a = Path(session_a)
    path_b = Path(session_b)
    data_a = parse_session_file(path_a)
    data_b = parse_session_file(path_b)

    project_a, _display_a = resolve_project_key(data_a)
    project_b, _display_b = resolve_project_key(data_b)
    if not force_cross_project and project_a != project_b:
        raise click.ClickException(
            "Sessions are from different projects. Use --force-cross-project to override."
        )

    resolved_redaction_patterns = resolve_redaction_patterns(
        redact_enabled,
        redact_presets,
        redact_patterns,
    )
    if resolved_redaction_patterns:
        data_a = redact_session_data(data_a, resolved_redaction_patterns)
        data_b = redact_session_data(data_b, resolved_redaction_patterns)

    if output:
        output_dir = Path(output)
    else:
        output_dir = Path(tempfile.gettempdir()) / f"codex-diff-{path_a.stem}-vs-{path_b.stem}"

    index_path, diff_data = generate_diff_report(
        data_a,
        data_b,
        output_dir,
        source_a=path_a,
        source_b=path_b,
        theme=theme,
    )
    click.echo(f"Output: {output_dir.resolve()}")

    if write_stats:
        report = build_stats_report(
            [
                collect_session_metrics(data_a, source_path=path_a),
                collect_session_metrics(data_b, source_path=path_b),
            ]
        )
        report["diff_summary"] = diff_data.get("summary", {})
        stats_path = write_stats_report(report, output_dir / "stats.json")
        click.echo(f"Stats: {stats_path.resolve()}")

    if open_browser:
        open_or_print_url(index_path.resolve().as_uri())


@cli.command("serve")
@click.argument("directory", type=click.Path(exists=True), required=False, default=".")
@click.option("-p", "--port", type=int, default=8000, show_default=True)
def serve_cmd(directory, port):
    """Serve a transcript directory over HTTP."""
    directory_path = Path(directory).resolve()
    handler = functools.partial(SimpleHTTPRequestHandler, directory=str(directory_path))
    url = f"http://127.0.0.1:{port}/"

    click.echo(f"Serving {directory_path}")
    click.echo("Press Ctrl+C to stop.")
    open_or_print_url(url)

    with ThreadingHTTPServer(("127.0.0.1", port), handler) as httpd:
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            click.echo("\nStopped server.")
