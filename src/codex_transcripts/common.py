"""Shared helpers for transcript rendering and CLI flows."""

from __future__ import annotations

import html
import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any

import click


COMMIT_PATTERN = re.compile(r"\[[\w\-/]+ ([a-f0-9]{7,})\] (.+?)(?:\n|$)")
GITHUB_REPO_PATTERN = re.compile(
    r"(?:https?://)?(?:api\.)?github\.com[:/](?:repos/)?"
    r"(?P<owner>[A-Za-z0-9_.-]+)/(?P<repo>[A-Za-z0-9_.-]+)(?:\.git)?"
)


def is_json_like(text: str | None) -> bool:
    if not text or not isinstance(text, str):
        return False
    text = text.strip()
    return (text.startswith("{") and text.endswith("}")) or (
        text.startswith("[") and text.endswith("]")
    )


def format_json(obj: Any) -> str:
    try:
        if isinstance(obj, str):
            obj = json.loads(obj)
        formatted = json.dumps(obj, indent=2, ensure_ascii=False)
        return f'<pre class="json">{html.escape(formatted)}</pre>'
    except (json.JSONDecodeError, TypeError, ValueError):
        return f"<pre>{html.escape(str(obj))}</pre>"


def extract_github_repo(repo_url: str | None) -> str | None:
    if not repo_url:
        return None
    match = GITHUB_REPO_PATTERN.search(repo_url)
    if not match:
        return None
    owner = match.group("owner")
    repo = match.group("repo")
    if repo.endswith(".git"):
        repo = repo[:-4]
    return f"{owner}/{repo}"


def slugify(text: str | None) -> str:
    if not text:
        return "unknown"
    slug = re.sub(r"[^A-Za-z0-9._-]+", "-", text)
    return slug.strip("-") or "unknown"


def is_path_like(text: str | None) -> bool:
    if not text:
        return False
    if text.startswith(("/", "~")):
        return True
    if re.match(r"^[A-Za-z]:[\\\\/]", text):
        return True
    if "\\" in text:
        return True
    return False


def format_project_label(display_name: str | None) -> str | None:
    if not display_name or display_name == "Unknown":
        return None
    if is_path_like(display_name):
        return Path(display_name).name or display_name
    return display_name


def detect_error_from_output(output: Any) -> bool:
    if isinstance(output, dict):
        metadata = output.get("metadata")
        if isinstance(metadata, dict) and metadata.get("exit_code") not in (0, None):
            return True
        return bool(output.get("is_error"))
    if isinstance(output, str):
        match = re.search(r"Exit code:\s*(\d+)", output)
        if match and match.group(1) != "0":
            return True
    return False


def open_or_print_url(url: str) -> None:
    click.echo("Open this URL in your browser:")
    click.echo(url)


def format_session_timestamp(timestamp: str | None) -> str | None:
    if not timestamp:
        return None
    try:
        cleaned = timestamp.replace("Z", "+00:00")
        parsed = datetime.fromisoformat(cleaned)
        return parsed.strftime("%Y-%m-%d %H:%M")
    except ValueError:
        return timestamp
