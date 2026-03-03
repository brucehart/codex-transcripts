"""Session and archive metrics for transcript dashboards."""

from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any, Sequence

from .common import COMMIT_PATTERN, detect_error_from_output, extract_github_repo
from .parser import SessionData


STATS_SCHEMA_VERSION = 1


def _resolve_repo_branch(session: SessionData) -> tuple[str | None, str | None]:
    git = session.git or {}
    if not isinstance(git, dict):
        return None, None
    repo_url = git.get("repository_url")
    repo = extract_github_repo(repo_url) or repo_url
    branch = git.get("branch")
    return repo, branch


def _resolve_project_key(session: SessionData) -> str:
    repo, _branch = _resolve_repo_branch(session)
    if repo:
        return repo
    if session.cwd:
        return session.cwd
    return "unknown"


def collect_session_metrics(
    session: SessionData,
    *,
    source_path: str | Path | None = None,
) -> dict[str, Any]:
    prompt_count = 0
    user_messages = 0
    assistant_messages = 0
    tool_calls = 0
    tool_outputs = 0
    error_turns = 0
    commit_mentions = 0
    tool_counts: dict[str, int] = {}

    for entry in session.entries:
        if entry.entry_type == "message":
            if entry.role == "user":
                user_messages += 1
                prompt_count += 1
            elif entry.role == "assistant":
                assistant_messages += 1
        elif entry.entry_type == "tool_call":
            tool_calls += 1
            name = (entry.tool_name or "unknown").strip()
            tool_counts[name] = tool_counts.get(name, 0) + 1
        elif entry.entry_type == "tool_output":
            tool_outputs += 1
            if detect_error_from_output(entry.tool_output):
                error_turns += 1
            if isinstance(entry.tool_output, str):
                commit_mentions += len(list(COMMIT_PATTERN.finditer(entry.tool_output)))

    repo, branch = _resolve_repo_branch(session)
    metrics = {
        "schema_version": STATS_SCHEMA_VERSION,
        "session_id": session.session_id,
        "source_path": str(source_path) if source_path else str(session.source_path),
        "project_key": _resolve_project_key(session),
        "repo": repo,
        "branch": branch,
        "started_at": session.started_at,
        "counts": {
            "entries": len(session.entries),
            "prompts": prompt_count,
            "messages_total": user_messages + assistant_messages,
            "user_messages": user_messages,
            "assistant_messages": assistant_messages,
            "tool_calls": tool_calls,
            "tool_outputs": tool_outputs,
        },
        "tools": {
            "counts": dict(sorted(tool_counts.items())),
            "unique": sorted(tool_counts.keys()),
        },
        "errors": {
            "tool_output_errors": error_turns,
        },
        "commits": {
            "mentions": commit_mentions,
        },
    }
    return metrics


def build_stats_report(session_metrics: Sequence[dict[str, Any]]) -> dict[str, Any]:
    sessions = list(session_metrics)
    summary = {
        "total_sessions": len(sessions),
        "total_prompts": 0,
        "total_messages": 0,
        "total_tool_calls": 0,
        "total_tool_outputs": 0,
        "total_error_turns": 0,
        "total_commit_mentions": 0,
    }
    tool_counts: dict[str, int] = {}

    for metric in sessions:
        counts = metric.get("counts", {})
        summary["total_prompts"] += int(counts.get("prompts", 0))
        summary["total_messages"] += int(counts.get("messages_total", 0))
        summary["total_tool_calls"] += int(counts.get("tool_calls", 0))
        summary["total_tool_outputs"] += int(counts.get("tool_outputs", 0))
        summary["total_error_turns"] += int(metric.get("errors", {}).get("tool_output_errors", 0))
        summary["total_commit_mentions"] += int(metric.get("commits", {}).get("mentions", 0))
        for name, count in metric.get("tools", {}).get("counts", {}).items():
            tool_counts[name] = tool_counts.get(name, 0) + int(count)

    return {
        "schema_version": STATS_SCHEMA_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "summary": {
            **summary,
            "tool_counts": dict(sorted(tool_counts.items())),
        },
        "sessions": sessions,
    }


def write_stats_report(report: dict[str, Any], output_path: str | Path) -> Path:
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(report, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    return output_path
