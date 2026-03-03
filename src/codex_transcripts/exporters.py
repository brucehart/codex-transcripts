"""Transcript export helpers for markdown/text/pdf output."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import markdown

from .common import extract_github_repo
from .parser import SessionData


def _render_tool_value(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    return json.dumps(value, indent=2, ensure_ascii=False)


def session_to_markdown(session: SessionData) -> str:
    git = session.git if isinstance(session.git, dict) else {}
    repo_url = git.get("repository_url") if isinstance(git, dict) else None
    repo = extract_github_repo(repo_url) or repo_url or "(unknown)"
    branch = git.get("branch") if isinstance(git, dict) else None
    commit = git.get("commit_hash") if isinstance(git, dict) else None

    lines: list[str] = [
        "# Codex transcript",
        "",
        f"- Session: `{session.session_id}`",
        f"- Started: `{session.started_at or '(unknown)'}`",
        f"- Repo: `{repo}`",
        f"- Branch: `{branch or '(unknown)'}`",
        f"- Commit: `{commit or '(unknown)'}`",
        f"- CWD: `{session.cwd or '(unknown)'}`",
        "",
    ]

    if session.instructions:
        lines.extend(
            [
                "## System instructions",
                "",
                session.instructions.strip(),
                "",
            ]
        )

    for idx, entry in enumerate(session.entries, start=1):
        ts = entry.timestamp or "(unknown time)"
        if entry.entry_type == "message":
            role = "User" if entry.role == "user" else "Assistant"
            lines.extend(
                [
                    f"## {idx}. {role} [{ts}]",
                    "",
                    (entry.content or "").strip(),
                    "",
                ]
            )
            continue

        if entry.entry_type == "tool_call":
            lines.extend(
                [
                    f"## {idx}. Tool call `{entry.tool_name or 'unknown'}` [{ts}]",
                    "",
                    "```",
                    _render_tool_value(entry.tool_input),
                    "```",
                    "",
                ]
            )
            continue

        if entry.entry_type == "tool_output":
            lines.extend(
                [
                    f"## {idx}. Tool output `{entry.tool_name or 'unknown'}` [{ts}]",
                    "",
                    "```",
                    _render_tool_value(entry.tool_output),
                    "```",
                    "",
                ]
            )

    return "\n".join(lines).rstrip() + "\n"


def session_to_text(session: SessionData) -> str:
    lines: list[str] = [
        "Codex transcript",
        f"Session: {session.session_id}",
        f"Started: {session.started_at or '(unknown)'}",
        f"CWD: {session.cwd or '(unknown)'}",
        "",
    ]

    if session.instructions:
        lines.extend(
            [
                "[System instructions]",
                session.instructions.strip(),
                "",
            ]
        )

    for idx, entry in enumerate(session.entries, start=1):
        ts = entry.timestamp or "(unknown time)"
        if entry.entry_type == "message":
            role = "USER" if entry.role == "user" else "ASSISTANT"
            lines.extend(
                [
                    f"[{idx}] {role} @ {ts}",
                    (entry.content or "").strip(),
                    "",
                ]
            )
            continue

        if entry.entry_type == "tool_call":
            lines.extend(
                [
                    f"[{idx}] TOOL CALL {entry.tool_name or 'unknown'} @ {ts}",
                    _render_tool_value(entry.tool_input),
                    "",
                ]
            )
            continue

        if entry.entry_type == "tool_output":
            lines.extend(
                [
                    f"[{idx}] TOOL OUTPUT {entry.tool_name or 'unknown'} @ {ts}",
                    _render_tool_value(entry.tool_output),
                    "",
                ]
            )

    return "\n".join(lines).rstrip() + "\n"


def _markdown_to_pdf(markdown_text: str, output_path: Path) -> None:
    try:
        from weasyprint import HTML
    except Exception as exc:  # pragma: no cover - dependency optional
        raise RuntimeError(
            "PDF export requires the optional dependency `weasyprint`."
        ) from exc

    html_body = markdown.markdown(markdown_text, extensions=["fenced_code", "tables"])
    html_doc = f"""<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8">
    <style>
      body {{ font-family: "IBM Plex Sans", "Segoe UI", sans-serif; font-size: 12px; line-height: 1.5; color: #1f1f1f; }}
      pre {{ background: #f4f4f4; padding: 8px; border-radius: 6px; white-space: pre-wrap; }}
      code {{ font-family: "IBM Plex Mono", monospace; }}
      h1, h2, h3 {{ page-break-after: avoid; }}
    </style>
  </head>
  <body>{html_body}</body>
</html>"""
    HTML(string=html_doc).write_pdf(str(output_path))


def write_transcript_exports(
    session: SessionData,
    output_dir: str | Path,
    *,
    markdown_enabled: bool = False,
    text_enabled: bool = False,
    pdf_enabled: bool = False,
) -> dict[str, Path]:
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    written: dict[str, Path] = {}
    markdown_text: str | None = None

    if markdown_enabled:
        markdown_text = session_to_markdown(session)
        md_path = output_dir / "transcript.md"
        md_path.write_text(markdown_text, encoding="utf-8")
        written["markdown"] = md_path

    if text_enabled:
        txt_text = session_to_text(session)
        txt_path = output_dir / "transcript.txt"
        txt_path.write_text(txt_text, encoding="utf-8")
        written["txt"] = txt_path

    if pdf_enabled:
        if markdown_text is None:
            markdown_text = session_to_markdown(session)
        pdf_path = output_dir / "transcript.pdf"
        _markdown_to_pdf(markdown_text, pdf_path)
        written["pdf"] = pdf_path

    return written
