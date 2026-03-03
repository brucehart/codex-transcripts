"""GitHub gist export helpers."""

from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path

import click

from .common import format_session_timestamp, slugify
from .parser import SessionData


GIST_PREVIEW_JS = r"""
(function() {
    if (window.location.hostname !== 'gistpreview.github.io') return;
    // URL format: https://gistpreview.github.io/?GIST_ID/filename.html
    var match = window.location.search.match(/^\?([^/]+)/);
    if (!match) return;
    var gistId = match[1];
    document.querySelectorAll('a[href]').forEach(function(link) {
        var href = link.getAttribute('href');
        // Skip external links and anchors
        if (!href || href.startsWith('http') || href.startsWith('#')) return;
        var parts = href.split('#');
        var filename = parts[0];
        var anchor = parts.length > 1 ? '#' + parts[1] : '';
        link.setAttribute('href', '?' + gistId + '/' + filename + anchor);
    });

    // Handle fragment navigation after dynamic content loads
    // gistpreview.github.io loads content dynamically, so the browser's
    // native fragment navigation fails because the element doesn't exist yet
    function scrollToFragment() {
        var hash = window.location.hash;
        if (!hash) return;
        var element = document.querySelector(hash);
        if (element) {
            element.scrollIntoView();
        } else {
            setTimeout(scrollToFragment, 100);
        }
    }
    scrollToFragment();
})();
"""


def build_gist_label(session: SessionData, source_path: str | Path) -> str:
    parts: list[str] = []
    started_at = format_session_timestamp(session.started_at)
    if started_at:
        parts.append(started_at)
    if session.session_id:
        parts.append(session.session_id)
    else:
        parts.append(Path(source_path).stem)
    label = " ".join(parts).strip()
    return label or Path(source_path).stem


def build_gist_description(session: SessionData, source_path: str | Path) -> str:
    return f"Codex transcript: {build_gist_label(session, source_path)}"


def build_gist_index_filename(session: SessionData, source_path: str | Path) -> str:
    label = build_gist_label(session, source_path)
    slug = slugify(f"codex-transcript-{label}")
    return f"{slug}.html"


def inject_gist_preview_js(output_dir: str | Path) -> None:
    output_dir = Path(output_dir)
    for html_file in output_dir.glob("*.html"):
        content = html_file.read_text(encoding="utf-8")
        if "gistpreview.github.io" in content:
            continue
        if "</body>" in content:
            content = content.replace(
                "</body>", f"<script>{GIST_PREVIEW_JS}</script>\n</body>"
            )
            html_file.write_text(content, encoding="utf-8")


def stage_gist_files(
    output_dir: str | Path,
    include_json: bool,
    index_filename: str,
    staging_dir: str | Path | None = None,
):
    output_dir = Path(output_dir)
    html_files = sorted(output_dir.glob("*.html"))
    if not html_files:
        raise click.ClickException(f"No transcript files found in {output_dir}")

    if staging_dir:
        staging_dir = Path(staging_dir)
    else:
        staging_dir = Path(tempfile.mkdtemp(prefix="codex-gist-"))
    staged_files: list[Path] = []
    index_target = staging_dir / index_filename

    for html_file in html_files:
        content = html_file.read_text(encoding="utf-8")
        content = content.replace('href="index.html"', f'href="{index_filename}"')
        content = content.replace("href='index.html'", f"href='{index_filename}'")
        if html_file.name == "index.html":
            index_target.write_text(content, encoding="utf-8")
        else:
            target = staging_dir / html_file.name
            target.write_text(content, encoding="utf-8")
            staged_files.append(target)

    staged_files.insert(0, index_target)
    if not index_target.exists():
        raise click.ClickException("Missing index.html in transcript output.")

    if include_json:
        for json_file in sorted(output_dir.glob("*.jsonl")):
            target = staging_dir / json_file.name
            shutil.copy(json_file, target)
            staged_files.append(target)

    inject_gist_preview_js(staging_dir)

    return staged_files, index_target, staging_dir


def extract_gist_id(gist_url: str | None) -> str | None:
    if not gist_url:
        return None
    return gist_url.rstrip("/").split("/")[-1]


def create_gist_from_output(
    output_dir: str | Path,
    description: str,
    public: bool,
    include_json: bool,
    index_filename: str,
):
    gh_path = shutil.which("gh")
    if not gh_path:
        raise click.ClickException(
            "GitHub CLI 'gh' not found. Install it from https://cli.github.com/ "
            "and run `gh auth login`."
        )

    with tempfile.TemporaryDirectory(prefix="codex-gist-") as temp_dir:
        files, index_target, _ = stage_gist_files(
            output_dir,
            include_json,
            index_filename,
            staging_dir=temp_dir,
        )

        cmd = [gh_path, "gist", "create", *[str(path) for path in files]]
        if description:
            cmd.extend(["--desc", description])
        if public:
            cmd.append("--public")

        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            error = result.stderr.strip() or result.stdout.strip() or "Unknown error"
            raise click.ClickException(f"Failed to create gist: {error}")

        gist_url = result.stdout.strip().splitlines()[-1] if result.stdout else ""
        gist_id = extract_gist_id(gist_url)
        preview_url = None
        if gist_id:
            preview_url = f"https://gistpreview.github.io/?{gist_id}/{index_target.name}"
        return gist_url, preview_url
