"""Archive/session discovery and aggregate HTML generation."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from .common import extract_github_repo, format_project_label, slugify
from .parser import SessionData, get_session_summary_from_session, parse_session_file
from .renderer import CSS, JS, generate_html, get_template


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


def find_all_sessions(folder: str | Path):
    folder = Path(folder)
    if not folder.exists():
        return []

    projects: dict[str, dict] = {}
    for session_file in folder.glob("**/*.jsonl"):
        session = parse_session_file(session_file)
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
            }
        )

    for project in projects.values():
        project["sessions"].sort(key=lambda s: s["mtime"], reverse=True)

    result = list(projects.values())
    result.sort(
        key=lambda p: p["sessions"][0]["mtime"] if p["sessions"] else 0,
        reverse=True,
    )

    return result


def _generate_project_index(project, output_dir: str | Path):
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

    html_content = template.render(
        project_name=project["name"],
        sessions=sessions_data,
        session_count=len(sessions_data),
        css=CSS,
        js=JS,
    )

    output_path = Path(output_dir) / "index.html"
    output_path.write_text(html_content, encoding="utf-8")


def _generate_master_index(projects, output_dir: str | Path):
    template = get_template("master_index.html")

    projects_data = []
    total_sessions = 0

    for project in projects:
        session_count = len(project["sessions"])
        total_sessions += session_count
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
                "recent_date": recent_date,
            }
        )

    html_content = template.render(
        projects=projects_data,
        total_projects=len(projects),
        total_sessions=total_sessions,
        css=CSS,
        js=JS,
    )

    output_path = Path(output_dir) / "index.html"
    output_path.write_text(html_content, encoding="utf-8")


def generate_batch_html(
    source_folder: str | Path,
    output_dir: str | Path,
    include_json: bool = False,
    progress_callback=None,
):
    source_folder = Path(source_folder)
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    projects = find_all_sessions(source_folder)

    total_session_count = sum(len(p["sessions"]) for p in projects)
    processed_count = 0
    successful_sessions = 0
    failed_sessions = []

    for project in projects:
        project_dir = output_dir / slugify(project["key"])
        project_dir.mkdir(exist_ok=True)

        for session in project["sessions"]:
            session_name = session["path"].stem
            session_dir = project_dir / session_name

            try:
                generate_html(session["path"], session_dir, include_json=include_json)
                successful_sessions += 1
            except Exception as e:
                failed_sessions.append(
                    {
                        "project": project["name"],
                        "session": session_name,
                        "error": str(e),
                    }
                )

            processed_count += 1
            if progress_callback:
                progress_callback(
                    project["name"],
                    session_name,
                    processed_count,
                    total_session_count,
                )

        _generate_project_index(project, project_dir)

    _generate_master_index(projects, output_dir)

    return {
        "total_projects": len(projects),
        "total_sessions": successful_sessions,
        "failed_sessions": failed_sessions,
        "output_dir": output_dir,
    }
