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
)
from .common import open_or_print_url
from .gist import (
    build_gist_description,
    build_gist_index_filename,
    create_gist_from_output,
)
from .parser import parse_session_file
from .renderer import generate_html

REDACTION_PRESETS: dict[str, tuple[str, ...]] = {
    "basic": (
        r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}",
        r"\b(?:ghp|github_pat)_[A-Za-z0-9_]{20,}\b",
        r"\bsk-[A-Za-z0-9]{20,}\b",
    ),
}


def resolve_redaction_patterns(
    redact_presets: tuple[str, ...],
    redact_patterns: tuple[str, ...],
) -> tuple[str, ...]:
    resolved: list[str] = []
    seen: set[str] = set()

    for preset in redact_presets:
        for pattern in REDACTION_PRESETS.get(preset.lower(), ()):
            if pattern not in seen:
                seen.add(pattern)
                resolved.append(pattern)

    for pattern in redact_patterns:
        if pattern not in seen:
            seen.add(pattern)
            resolved.append(pattern)

    return tuple(resolved)


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
    "--redact",
    "redact_presets",
    type=click.Choice(sorted(REDACTION_PRESETS.keys()), case_sensitive=False),
    multiple=True,
    help="Apply a built-in redaction preset before rendering.",
)
@click.option(
    "--redact-pattern",
    "redact_patterns",
    multiple=True,
    help="Regex pattern to redact from rendered output. Repeatable.",
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
    record_by_path = {}
    for record in records:
        filepath = record.path
        mod_time = datetime.fromtimestamp(record.mtime)
        size_kb = record.size / 1024
        date_str = mod_time.strftime("%Y-%m-%d %H:%M")
        display_summary = build_local_session_label(record.session, record.summary, max_length=80)
        display = f"{date_str}  {size_kb:5.0f} KB  {display_summary}"
        choices.append(questionary.Choice(title=display, value=filepath))
        record_by_path[filepath] = record

    selected = questionary.select(
        "Select a session to convert:",
        choices=choices,
    ).ask()

    if selected is None:
        click.echo("No session selected.")
        return

    session_file = Path(selected)

    auto_open = output is None and not output_auto
    if output_auto:
        parent_dir = Path(output) if output else Path(".")
        output = parent_dir / session_file.stem
    elif output is None:
        output = Path(tempfile.gettempdir()) / f"codex-session-{session_file.stem}"

    output = Path(output)
    resolved_redaction_patterns = resolve_redaction_patterns(
        redact_presets,
        redact_patterns,
    )
    index_path = generate_html(
        session_file,
        output,
        include_json=include_json,
        search_mode=search_mode.lower(),
        redact_patterns=resolved_redaction_patterns,
    )

    click.echo(f"Output: {output.resolve()}")

    if create_gist or gist_public:
        selected_record = record_by_path.get(session_file)
        session = selected_record.session if selected_record else parse_session_file(session_file)
        description = build_gist_description(session, session_file)
        index_filename = build_gist_index_filename(session, session_file)
        click.echo("Creating GitHub gist...")
        gist_url, preview_url = create_gist_from_output(
            output,
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
    "--redact",
    "redact_presets",
    type=click.Choice(sorted(REDACTION_PRESETS.keys()), case_sensitive=False),
    multiple=True,
    help="Apply a built-in redaction preset before rendering.",
)
@click.option(
    "--redact-pattern",
    "redact_patterns",
    multiple=True,
    help="Regex pattern to redact from rendered output. Repeatable.",
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
    redact_presets,
    redact_patterns,
):
    """Convert a Codex session JSONL file to HTML."""
    auto_open = output is None and not output_auto
    if output_auto:
        parent_dir = Path(output) if output else Path(".")
        output = parent_dir / Path(json_file).stem
    elif output is None:
        output = Path(tempfile.gettempdir()) / f"codex-session-{Path(json_file).stem}"

    output = Path(output)
    resolved_redaction_patterns = resolve_redaction_patterns(
        redact_presets,
        redact_patterns,
    )
    index_path = generate_html(
        json_file,
        output,
        include_json=include_json,
        search_mode=search_mode.lower(),
        redact_patterns=resolved_redaction_patterns,
    )

    click.echo(f"Output: {output.resolve()}")

    if create_gist or gist_public:
        session = parse_session_file(json_file)
        description = build_gist_description(session, json_file)
        index_filename = build_gist_index_filename(session, json_file)
        click.echo("Creating GitHub gist...")
        gist_url, preview_url = create_gist_from_output(
            output,
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
    "--redact",
    "redact_presets",
    type=click.Choice(sorted(REDACTION_PRESETS.keys()), case_sensitive=False),
    multiple=True,
    help="Apply a built-in redaction preset before rendering.",
)
@click.option(
    "--redact-pattern",
    "redact_patterns",
    multiple=True,
    help="Regex pattern to redact from rendered output. Repeatable.",
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
    redact_presets,
    redact_patterns,
):
    """Convert all local Codex sessions to a browsable HTML archive."""
    if source is None:
        source = Path.home() / ".codex" / "sessions"
    else:
        source = Path(source)

    if not source.exists():
        raise click.ClickException(f"Source directory not found: {source}")

    output = Path(output)

    if not quiet:
        click.echo(f"Scanning {source}...")

    def on_progress(_project_name, _session_name, current, total):
        if not quiet and current % 10 == 0:
            click.echo(f"  Processed {current}/{total} sessions...")

    try:
        resolved_redaction_patterns = resolve_redaction_patterns(
            redact_presets,
            redact_patterns,
        )
        stats = generate_batch_html(
            source,
            output,
            include_json=include_json,
            progress_callback=on_progress,
            skip_bad_files=skip_bad_files,
            strict=strict,
            incremental=incremental,
            workers=workers,
            search_mode=search_mode.lower(),
            redact_patterns=resolved_redaction_patterns,
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

    if not quiet:
        click.echo(
            f"\nGenerated archive with {stats['total_projects']} projects, "
            f"{stats['total_sessions']} sessions"
        )
        if stats["skipped_sessions"]:
            click.echo(f"Skipped unchanged sessions: {stats['skipped_sessions']}")
        click.echo(f"Output: {output.resolve()}")

    if open_browser:
        index_url = (output / "index.html").resolve().as_uri()
        open_or_print_url(index_url)


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
