"""Archive/session discovery and aggregate HTML generation."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime
import json
from pathlib import Path
from typing import Any, Sequence

from .common import extract_github_repo, format_project_label, slugify
from .parser import SessionData, get_session_summary_from_session, parse_session_file
from .renderer import CSS, JS, SearchMode, generate_html_from_session, get_template


INCREMENTAL_CACHE_FILENAME = ".codex-transcripts-cache.json"
INCREMENTAL_CACHE_VERSION = 1


@dataclass
class LocalSessionRecord:
    path: Path
    summary: str
    session: SessionData
    mtime: float
    size: int


def resolve_project_key(session: SessionData):
    git = session.git or {}
    repo_url = git.get("repository_url") if isinstance(git, dict) else None
    repo_name = extract_github_repo(repo_url) if repo_url else None
    if repo_name:
        return repo_name, repo_name
    if session.cwd:
        return session.cwd, session.cwd
    return "unknown", "Unknown"


def build_local_session_label(session: SessionData, summary: str, max_length: int = 80):
    project_key, display_name = resolve_project_key(session)
    project_label = format_project_label(display_name or project_key)
    label = summary
    if project_label:
        label = f"{project_label} — {label}"
    if max_length and len(label) > max_length:
        return label[: max_length - 3] + "..."
    return label


def get_session_summary(filepath: str | Path, max_length: int = 200):
    filepath = Path(filepath)
    try:
        session = parse_session_file(filepath)
    except Exception:
        return "(no summary)"
    return get_session_summary_from_session(session, max_length=max_length)


def find_local_session_records(folder: str | Path, limit: int = 10):
    folder = Path(folder)
    if not folder.exists():
        return []

    results: list[LocalSessionRecord] = []
    for json_file in folder.glob("**/*.jsonl"):
        try:
            session = parse_session_file(json_file)
        except Exception:
            continue
        summary = get_session_summary_from_session(session)
        if summary == "(no summary)":
            continue
        stat = json_file.stat()
        results.append(
            LocalSessionRecord(
                path=json_file,
                summary=summary,
                session=session,
                mtime=stat.st_mtime,
                size=stat.st_size,
            )
        )

    results.sort(key=lambda item: item.mtime, reverse=True)
    return results[:limit]


def find_local_sessions(folder: str | Path, limit: int = 10):
    records = find_local_session_records(folder, limit=limit)
    return [(record.path, record.summary) for record in records]


def scan_all_sessions(folder: str | Path, skip_bad_files: bool = True):
    folder = Path(folder)
    if not folder.exists():
        return [], []

    projects: dict[str, dict[str, Any]] = {}
    scan_failures: list[dict[str, str]] = []

    for session_file in folder.glob("**/*.jsonl"):
        try:
            session = parse_session_file(session_file)
        except Exception as exc:
            failure = {
                "path": str(session_file),
                "error": str(exc),
            }
            if skip_bad_files:
                scan_failures.append(failure)
                continue
            raise RuntimeError(
                f"Failed to parse session file {session_file}: {exc}"
            ) from exc

        project_key, display_name = resolve_project_key(session)
        project_slug = slugify(project_key)

        if project_slug not in projects:
            projects[project_slug] = {
                "key": project_key,
                "name": display_name,
                "sessions": [],
            }

        stat = session_file.stat()
        projects[project_slug]["sessions"].append(
            {
                "path": session_file,
                "summary": get_session_summary_from_session(session),
                "mtime": stat.st_mtime,
                "size": stat.st_size,
                "session_id": session.session_id,
                "parsed_session": session,
            }
        )

    for project in projects.values():
        project["sessions"].sort(key=lambda s: s["mtime"], reverse=True)

    result = list(projects.values())
    result.sort(
        key=lambda p: p["sessions"][0]["mtime"] if p["sessions"] else 0,
        reverse=True,
    )

    return result, scan_failures


def find_all_sessions(folder: str | Path):
    projects, _scan_failures = scan_all_sessions(folder, skip_bad_files=True)
    return projects


def _generate_project_index(
    project: dict[str, Any],
    output_dir: str | Path,
    failed_sessions: list[dict[str, str]] | None = None,
):
    template = get_template("project_index.html")

    sessions_data = []
    for session in project["sessions"]:
        mod_time = datetime.fromtimestamp(session["mtime"])
        sessions_data.append(
            {
                "name": session["path"].stem,
                "summary": session["summary"],
                "date": mod_time.strftime("%Y-%m-%d %H:%M"),
                "size_kb": session["size"] / 1024,
            }
        )

    failed_data: list[dict[str, str]] = []
    for failure in failed_sessions or []:
        failed_data.append(
            {
                "name": failure["session"],
                "error": failure["error"],
            }
        )

    html_content = template.render(
        project_name=project["name"],
        sessions=sessions_data,
        session_count=len(sessions_data),
        failed_sessions=failed_data,
        failed_count=len(failed_data),
        css=CSS,
        js=JS,
    )

    output_path = Path(output_dir) / "index.html"
    output_path.write_text(html_content, encoding="utf-8")


def _generate_master_index(projects, output_dir: str | Path):
    template = get_template("master_index.html")

    projects_data = []
    total_sessions = 0
    total_failed_sessions = 0

    for project in projects:
        session_count = len(project["sessions"])
        failed_count = len(project.get("failed_sessions", []))
        total_sessions += session_count
        total_failed_sessions += failed_count
        if project["sessions"]:
            most_recent = datetime.fromtimestamp(project["sessions"][0]["mtime"])
            recent_date = most_recent.strftime("%Y-%m-%d")
        else:
            recent_date = "N/A"
        projects_data.append(
            {
                "name": project["name"],
                "slug": slugify(project["key"]),
                "session_count": session_count,
                "failed_count": failed_count,
                "recent_date": recent_date,
            }
        )

    html_content = template.render(
        projects=projects_data,
        total_projects=len(projects),
        total_sessions=total_sessions,
        total_failed_sessions=total_failed_sessions,
        css=CSS,
        js=JS,
    )

    output_path = Path(output_dir) / "index.html"
    output_path.write_text(html_content, encoding="utf-8")


def _session_cache_key(path: Path) -> str:
    return str(path.resolve())


def _load_incremental_cache(
    output_dir: Path,
    *,
    include_json: bool,
    search_mode: SearchMode,
    redact_patterns: Sequence[str],
) -> dict[str, dict[str, float | int]]:
    cache_path = output_dir / INCREMENTAL_CACHE_FILENAME
    if not cache_path.exists():
        return {}

    try:
        raw = json.loads(cache_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}

    if not isinstance(raw, dict):
        return {}
    if raw.get("version") != INCREMENTAL_CACHE_VERSION:
        return {}

    options = raw.get("options")
    if not isinstance(options, dict):
        return {}
    if options.get("include_json") != include_json:
        return {}
    if options.get("search_mode") != search_mode:
        return {}
    if options.get("redact_patterns") != list(redact_patterns):
        return {}

    sessions = raw.get("sessions")
    if not isinstance(sessions, dict):
        return {}

    validated: dict[str, dict[str, float | int]] = {}
    for key, value in sessions.items():
        if not isinstance(key, str) or not isinstance(value, dict):
            continue
        mtime = value.get("mtime")
        size = value.get("size")
        if isinstance(mtime, (int, float)) and isinstance(size, int):
            validated[key] = {"mtime": mtime, "size": size}
    return validated


def _write_incremental_cache(
    output_dir: Path,
    sessions: dict[str, dict[str, float | int]],
    *,
    include_json: bool,
    search_mode: SearchMode,
    redact_patterns: Sequence[str],
) -> None:
    payload = {
        "version": INCREMENTAL_CACHE_VERSION,
        "options": {
            "include_json": include_json,
            "search_mode": search_mode,
            "redact_patterns": list(redact_patterns),
        },
        "sessions": sessions,
    }
    cache_path = output_dir / INCREMENTAL_CACHE_FILENAME
    cache_path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


def generate_batch_html(
    source_folder: str | Path,
    output_dir: str | Path,
    include_json: bool = False,
    progress_callback=None,
    skip_bad_files: bool = True,
    strict: bool = False,
    incremental: bool = False,
    workers: int = 1,
    search_mode: SearchMode = "auto",
    redact_patterns: Sequence[str] | None = None,
):
    source_folder = Path(source_folder)
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    effective_skip_bad_files = skip_bad_files and not strict
    projects, scan_failures = scan_all_sessions(
        source_folder,
        skip_bad_files=effective_skip_bad_files,
    )

    total_session_count = sum(len(p["sessions"]) for p in projects)
    processed_count = 0
    failed_sessions: list[dict[str, str]] = []
    skipped_sessions = 0
    normalized_redact_patterns = tuple(redact_patterns or ())

    cache_by_session: dict[str, dict[str, float | int]] = {}
    if incremental:
        cache_by_session = _load_incremental_cache(
            output_dir,
            include_json=include_json,
            search_mode=search_mode,
            redact_patterns=normalized_redact_patterns,
        )
    updated_cache = dict(cache_by_session)

    project_results: dict[str, dict[str, Any]] = {}
    project_order: list[str] = []
    tasks: list[dict[str, Any]] = []

    for project in projects:
        project_slug = slugify(project["key"])
        project_dir = output_dir / project_slug
        project_dir.mkdir(exist_ok=True)
        project_order.append(project_slug)
        project_results[project_slug] = {
            "key": project["key"],
            "name": project["name"],
            "sessions": [],
            "failed_sessions": [],
        }

        for session in project["sessions"]:
            tasks.append(
                {
                    "project_slug": project_slug,
                    "project_name": project["name"],
                    "project_dir": project_dir,
                    "session": session,
                }
            )

    def cache_state_for(session: dict[str, Any]) -> dict[str, float | int]:
        return {
            "mtime": float(session["mtime"]),
            "size": int(session["size"]),
        }

    def mark_success(task: dict[str, Any], cache_state: dict[str, float | int], skipped: bool):
        nonlocal skipped_sessions
        project_slug = task["project_slug"]
        session = task["session"]
        project_results[project_slug]["sessions"].append(
            {
                "path": session["path"],
                "summary": session["summary"],
                "mtime": session["mtime"],
                "size": session["size"],
                "session_id": session["session_id"],
            }
        )
        updated_cache[_session_cache_key(session["path"])] = cache_state
        if skipped:
            skipped_sessions += 1

    def mark_failure(task: dict[str, Any], error: str):
        project_slug = task["project_slug"]
        session = task["session"]
        failure = {
            "project": task["project_name"],
            "session": session["path"].stem,
            "error": error,
        }
        failed_sessions.append(failure)
        project_results[project_slug]["failed_sessions"].append(failure)

    def render_task(task: dict[str, Any]):
        session = task["session"]
        session_path = Path(session["path"])
        session_dir = Path(task["project_dir"]) / session_path.stem
        cache_state = cache_state_for(session)
        cache_key = _session_cache_key(session_path)

        if incremental:
            cached = cache_by_session.get(cache_key)
            if (
                cached == cache_state
                and (session_dir / "index.html").exists()
                and (session_dir / "search-index.json").exists()
            ):
                return {"skipped": True, "cache_state": cache_state}

        generate_html_from_session(
            session["parsed_session"],
            session_dir,
            source_path=session_path,
            include_json=include_json,
            search_mode=search_mode,
            redact_patterns=normalized_redact_patterns,
        )
        return {"skipped": False, "cache_state": cache_state}

    def on_task_complete(task: dict[str, Any], result: dict[str, Any] | None, error: Exception | None):
        nonlocal processed_count
        if error is None and result is not None:
            mark_success(task, result["cache_state"], skipped=bool(result["skipped"]))
        elif error is not None:
            mark_failure(task, str(error))

        processed_count += 1
        if progress_callback:
            progress_callback(
                task["project_name"],
                task["session"]["path"].stem,
                processed_count,
                total_session_count,
            )

    if strict:
        for task in tasks:
            try:
                result = render_task(task)
            except Exception as exc:
                on_task_complete(task, None, exc)
                raise RuntimeError(
                    f"Failed to render {task['session']['path']}: {exc}"
                ) from exc
            on_task_complete(task, result, None)
    elif workers > 1 and tasks:
        with ThreadPoolExecutor(max_workers=workers) as executor:
            future_to_task = {executor.submit(render_task, task): task for task in tasks}
            for future in as_completed(future_to_task):
                task = future_to_task[future]
                try:
                    result = future.result()
                except Exception as exc:
                    on_task_complete(task, None, exc)
                else:
                    on_task_complete(task, result, None)
    else:
        for task in tasks:
            try:
                result = render_task(task)
            except Exception as exc:
                on_task_complete(task, None, exc)
            else:
                on_task_complete(task, result, None)

    ordered_projects: list[dict[str, Any]] = []
    for project_slug in project_order:
        project = project_results[project_slug]
        project["sessions"].sort(key=lambda s: s["mtime"], reverse=True)
        project_dir = output_dir / project_slug
        _generate_project_index(
            project,
            project_dir,
            failed_sessions=project["failed_sessions"],
        )
        ordered_projects.append(project)

    _generate_master_index(ordered_projects, output_dir)

    if incremental:
        _write_incremental_cache(
            output_dir,
            updated_cache,
            include_json=include_json,
            search_mode=search_mode,
            redact_patterns=normalized_redact_patterns,
        )

    total_successful_sessions = sum(len(project["sessions"]) for project in ordered_projects)

    return {
        "total_projects": len(ordered_projects),
        "total_sessions": total_successful_sessions,
        "failed_sessions": failed_sessions,
        "scan_failures": scan_failures,
        "skipped_sessions": skipped_sessions,
        "output_dir": output_dir,
    }
