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
    find_all_sessions,
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
    index_path = generate_html(session_file, output, include_json=include_json)

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
def json_cmd(
    json_file,
    output,
    output_auto,
    include_json,
    create_gist,
    gist_public,
    open_browser,
):
    """Convert a Codex session JSONL file to HTML."""
    auto_open = output is None and not output_auto
    if output_auto:
        parent_dir = Path(output) if output else Path(".")
        output = parent_dir / Path(json_file).stem
    elif output is None:
        output = Path(tempfile.gettempdir()) / f"codex-session-{Path(json_file).stem}"

    output = Path(output)
    index_path = generate_html(json_file, output, include_json=include_json)

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
def all_cmd(source, output, include_json, open_browser, quiet):
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

    projects = find_all_sessions(source)

    if not projects:
        if not quiet:
            click.echo("No sessions found.")
        return

    total_sessions = sum(len(p["sessions"]) for p in projects)

    if not quiet:
        click.echo(f"Found {len(projects)} projects with {total_sessions} sessions")

    def on_progress(_project_name, _session_name, current, total):
        if not quiet and current % 10 == 0:
            click.echo(f"  Processed {current}/{total} sessions...")

    stats = generate_batch_html(
        source,
        output,
        include_json=include_json,
        progress_callback=on_progress,
    )

    if stats["failed_sessions"]:
        click.echo(f"\nWarning: {len(stats['failed_sessions'])} session(s) failed:")
        for failure in stats["failed_sessions"]:
            click.echo(f"  {failure['project']}/{failure['session']}: {failure['error']}")

    if not quiet:
        click.echo(
            f"\nGenerated archive with {stats['total_projects']} projects, "
            f"{stats['total_sessions']} sessions"
        )
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
