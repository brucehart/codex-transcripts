"""HTML rendering for Codex transcripts."""

from __future__ import annotations

import html
import json
import shutil
from pathlib import Path
from typing import Any, Literal, Sequence

import bleach
from jinja2 import Environment, PackageLoader
import markdown

from .assets import ensure_output_assets, read_asset_text
from .common import COMMIT_PATTERN, detect_error_from_output, extract_github_repo, format_json, is_json_like
from .parser import Entry, SessionData, parse_session_file
from .redaction import redact_session_data
from .search_index import write_search_index


PROMPTS_PER_PAGE = 5
LONG_TEXT_THRESHOLD = 300
AUTO_INLINE_SEARCH_ITEM_THRESHOLD = 400
SEARCH_MODES = {"inline", "external", "auto"}
SearchMode = Literal["inline", "external", "auto"]

_jinja_env = Environment(
    loader=PackageLoader("codex_transcripts", "templates"),
    autoescape=True,
)

_macros_template = _jinja_env.get_template("macros.html")
_macros = _macros_template.module

_ALLOWED_TAGS = [
    "a",
    "blockquote",
    "br",
    "code",
    "em",
    "h1",
    "h2",
    "h3",
    "h4",
    "h5",
    "h6",
    "hr",
    "li",
    "ol",
    "p",
    "pre",
    "strong",
    "table",
    "tbody",
    "td",
    "th",
    "thead",
    "tr",
    "ul",
]
_ALLOWED_ATTRIBUTES = {
    "a": ["href", "title"],
    "code": ["class"],
    "pre": ["class"],
}
_ALLOWED_PROTOCOLS = ["http", "https", "mailto"]

# Backwards-compatible exports used by public package API.
CSS = read_asset_text("base.css")
JS = read_asset_text("runtime.js")


def get_template(name: str):
    return _jinja_env.get_template(name)


def sanitize_html(content_html: str) -> str:
    return bleach.clean(
        content_html,
        tags=_ALLOWED_TAGS,
        attributes=_ALLOWED_ATTRIBUTES,
        protocols=_ALLOWED_PROTOCOLS,
        strip=True,
        strip_comments=True,
    )


def render_markdown_text(text: str | None) -> str:
    if not text:
        return ""
    rendered = markdown.markdown(text, extensions=["fenced_code", "tables"])
    return sanitize_html(rendered)


def analyze_conversation(entries: list[Entry]):
    tool_counts: dict[str, int] = {}
    long_texts: list[str] = []
    commits: list[tuple[str, str, str | None]] = []

    for entry in entries:
        if entry.entry_type == "tool_call" and entry.tool_name:
            tool_counts[entry.tool_name] = tool_counts.get(entry.tool_name, 0) + 1
        if (
            entry.entry_type == "message"
            and entry.role == "assistant"
            and entry.content
            and len(entry.content) >= LONG_TEXT_THRESHOLD
        ):
            long_texts.append(entry.content)
        if entry.entry_type == "tool_output" and isinstance(entry.tool_output, str):
            for match in COMMIT_PATTERN.finditer(entry.tool_output):
                commits.append((match.group(1), match.group(2), entry.timestamp))

    return {
        "tool_counts": tool_counts,
        "long_texts": long_texts,
        "commits": commits,
    }


def format_tool_stats(tool_counts: dict[str, int]) -> str:
    if not tool_counts:
        return ""

    abbrev = {
        "shell": "shell",
        "shell_command": "shell",
        "apply_patch": "patch",
        "update_plan": "plan",
    }
    parts: list[str] = []
    for name, count in sorted(tool_counts.items(), key=lambda x: -x[1]):
        parts.append(f"{count} {abbrev.get(name, name.lower())}")
    return " | ".join(parts)


def make_msg_id(timestamp: str | None, idx: int) -> str:
    if not timestamp:
        return f"msg-{idx}"
    safe = timestamp.replace(":", "-").replace(".", "-")
    return f"msg-{safe}-{idx}"


def render_tool_call(entry: Entry) -> str:
    tool_name = entry.tool_name or "Unknown tool"
    tool_input = entry.tool_input
    tool_id = entry.call_id or ""

    if tool_name in ("shell", "shell_command"):
        command = ""
        workdir = ""
        if isinstance(tool_input, dict):
            command = tool_input.get("command", "")
            workdir = tool_input.get("workdir", "")
        else:
            command = tool_input
        if isinstance(command, list):
            command = " ".join(str(part) for part in command)
        return _macros.shell_tool(str(command), str(workdir), tool_id)

    if tool_name == "apply_patch":
        patch_text = tool_input if isinstance(tool_input, str) else json.dumps(tool_input, indent=2)
        return _macros.patch_tool(patch_text, tool_id)

    if tool_name == "update_plan":
        plan: list[dict[str, Any]] = []
        explanation = ""
        if isinstance(tool_input, dict):
            plan = tool_input.get("plan", [])
            explanation = tool_input.get("explanation", "")
        return _macros.plan_update(plan, explanation, tool_id)

    if tool_input is None:
        input_json = "{}"
    elif isinstance(tool_input, str):
        input_json = tool_input
    else:
        input_json = json.dumps(tool_input, indent=2, ensure_ascii=False)
    return _macros.tool_use(tool_name, "", input_json, tool_id)


def render_tool_output(entry: Entry, github_repo: str | None) -> str:
    output = entry.tool_output
    is_error = detect_error_from_output(output)

    if isinstance(output, str):
        commits_found = list(COMMIT_PATTERN.finditer(output))
        if commits_found:
            parts: list[str] = []
            last_end = 0
            for match in commits_found:
                before = output[last_end : match.start()].strip()
                if before:
                    parts.append(f"<pre>{html.escape(before)}</pre>")
                commit_hash = match.group(1)
                commit_msg = match.group(2)
                parts.append(_macros.commit_card(commit_hash, commit_msg, github_repo))
                last_end = match.end()
            after = output[last_end:].strip()
            if after:
                parts.append(f"<pre>{html.escape(after)}</pre>")
            content_html = "".join(parts)
        elif is_json_like(output):
            content_html = format_json(output)
        else:
            content_html = f"<pre>{html.escape(output)}</pre>"
    else:
        content_html = format_json(output)

    return _macros.tool_result(content_html, is_error)


def render_message(entry: Entry, github_repo: str | None) -> str:
    if entry.entry_type == "message":
        content_html = render_markdown_text(entry.content)
        role_class = "assistant" if entry.role == "assistant" else "user"
        role_label = "Assistant" if entry.role == "assistant" else "User"
    elif entry.entry_type == "tool_call":
        content_html = render_tool_call(entry)
        role_class = "tool-call"
        role_label = "Tool"
    elif entry.entry_type == "tool_output":
        content_html = render_tool_output(entry, github_repo)
        role_class = "tool-reply"
        role_label = "Tool result"
    else:
        return ""

    msg_id = make_msg_id(entry.timestamp, entry.index)
    timestamp = entry.timestamp or ""
    return _macros.message(role_class, role_label, msg_id, timestamp, content_html)


def build_session_meta(session: SessionData):
    git = session.git or {}
    repo_url = git.get("repository_url") if isinstance(git, dict) else None
    repo_name = extract_github_repo(repo_url) or repo_url
    return {
        "session_id": session.session_id,
        "started_at": session.started_at,
        "cwd": session.cwd,
        "repo": repo_name,
        "branch": git.get("branch") if isinstance(git, dict) else None,
        "commit": git.get("commit_hash") if isinstance(git, dict) else None,
        "repo_url": repo_url,
    }


def _entry_search_text(entry: Entry) -> str:
    if entry.entry_type == "message":
        return (entry.content or "").strip()
    if entry.entry_type == "tool_call":
        tool_name = entry.tool_name or "Unknown tool"
        if isinstance(entry.tool_input, str):
            input_text = entry.tool_input
        elif entry.tool_input is None:
            input_text = ""
        else:
            input_text = json.dumps(entry.tool_input, ensure_ascii=False)
        return f"Tool call: {tool_name}\n{input_text}".strip()
    if entry.entry_type == "tool_output":
        if isinstance(entry.tool_output, str):
            output_text = entry.tool_output
        elif entry.tool_output is None:
            output_text = ""
        else:
            output_text = json.dumps(entry.tool_output, ensure_ascii=False)
        return f"Tool result\n{output_text}".strip()
    return ""


def _entry_search_role(entry: Entry) -> str:
    if entry.entry_type == "message":
        return "Assistant" if entry.role == "assistant" else "User"
    if entry.entry_type == "tool_call":
        return "Tool"
    if entry.entry_type == "tool_output":
        return "Tool result"
    return "Entry"


def _sanitize_search_text(text: str) -> str:
    if not text:
        return ""
    return bleach.clean(text, tags=[], attributes={}, strip=True)


def _select_inline_search_index(
    search_mode: SearchMode,
    search_index_data: dict[str, Any],
) -> dict[str, Any] | None:
    if search_mode == "inline":
        return search_index_data
    if search_mode == "external":
        return None
    items = search_index_data.get("items", [])
    if isinstance(items, list) and len(items) <= AUTO_INLINE_SEARCH_ITEM_THRESHOLD:
        return search_index_data
    return None


def _conversations_from_session(session: SessionData) -> list[dict[str, Any]]:
    conversations: list[dict[str, Any]] = []
    current_conv: dict[str, Any] | None = None
    for entry in session.entries:
        if entry.entry_type == "message" and entry.role == "user" and entry.content:
            if current_conv:
                conversations.append(current_conv)
            current_conv = {
                "user_text": entry.content,
                "timestamp": entry.timestamp,
                "entries": [entry],
            }
        elif current_conv:
            current_conv["entries"].append(entry)
    if current_conv:
        conversations.append(current_conv)
    return conversations


def generate_html_from_session(
    session: SessionData,
    output_dir: str | Path,
    *,
    source_path: str | Path | None = None,
    include_json: bool = False,
    search_mode: SearchMode = "auto",
    redact_patterns: Sequence[str] | None = None,
    theme: str | None = None,
):
    if search_mode not in SEARCH_MODES:
        raise ValueError(f"Invalid search_mode: {search_mode}")

    if redact_patterns:
        session = redact_session_data(session, redact_patterns)

    output_dir = Path(output_dir)
    output_dir.mkdir(exist_ok=True, parents=True)
    ensure_output_assets(output_dir, theme=theme)

    git = session.git or {}
    repo_url = git.get("repository_url") if isinstance(git, dict) else None
    github_repo = extract_github_repo(repo_url)
    session_meta = build_session_meta(session)

    conversations = _conversations_from_session(session)
    total_convs = len(conversations)
    total_pages = max(1, (total_convs + PROMPTS_PER_PAGE - 1) // PROMPTS_PER_PAGE)

    instructions_html = None
    if session.instructions:
        rendered = render_markdown_text(session.instructions)
        instructions_html = _macros.system_instructions(rendered, session.instruction_repeats)
    session_meta_html = _macros.session_meta(session_meta) if any(session_meta.values()) else ""

    search_items: list[dict[str, str]] = []

    for page_num in range(1, total_pages + 1):
        page_filename = f"page-{page_num:03d}.html"
        start_idx = (page_num - 1) * PROMPTS_PER_PAGE
        end_idx = min(start_idx + PROMPTS_PER_PAGE, total_convs)
        page_convs = conversations[start_idx:end_idx]
        messages_html: list[str] = []

        for conv in page_convs:
            for entry in conv["entries"]:
                msg_html = render_message(entry, github_repo)
                if msg_html:
                    messages_html.append(msg_html)

                search_text = _entry_search_text(entry)
                if search_text:
                    search_items.append(
                        {
                            "page": page_filename,
                            "anchor": make_msg_id(entry.timestamp, entry.index),
                            "role": _entry_search_role(entry),
                            "timestamp": entry.timestamp or "",
                            "text": _sanitize_search_text(search_text)[:5000],
                        }
                    )

        pagination_html = _macros.pagination(page_num, total_pages)
        page_template = get_template("page.html")
        page_content = page_template.render(
            page_num=page_num,
            total_pages=total_pages,
            pagination_html=pagination_html,
            messages_html="".join(messages_html),
            session_meta_html=session_meta_html,
            system_instructions_html=instructions_html,
        )
        (output_dir / page_filename).write_text(page_content, encoding="utf-8")

    total_tool_counts: dict[str, int] = {}
    total_messages = sum(len(c["entries"]) for c in conversations)
    all_commits: list[tuple[int, str | None, str, str]] = []
    timeline_items: list[tuple[int, str | None, str]] = []

    prompt_num = 0
    for conv_index, conv in enumerate(conversations):
        prompt_num += 1
        page_num = (conv_index // PROMPTS_PER_PAGE) + 1
        msg_id = make_msg_id(conv["timestamp"], conv["entries"][0].index)
        link = f"page-{page_num:03d}.html#{msg_id}"
        rendered_content = render_markdown_text(conv["user_text"])
        stats = analyze_conversation(conv["entries"])
        for tool, count in stats["tool_counts"].items():
            total_tool_counts[tool] = total_tool_counts.get(tool, 0) + count
        tool_stats_str = format_tool_stats(stats["tool_counts"])
        long_texts_html = "".join(
            _macros.index_long_text(render_markdown_text(long_text))
            for long_text in stats["long_texts"]
        )
        stats_html = _macros.index_stats(tool_stats_str, long_texts_html)
        timeline_items.append(
            (
                conv_index,
                conv["timestamp"],
                _macros.index_item(prompt_num, link, conv["timestamp"], rendered_content, stats_html),
            )
        )
        for commit_hash, commit_msg, commit_ts in stats["commits"]:
            all_commits.append((conv_index, commit_ts, commit_hash, commit_msg))

    for conv_index, commit_ts, commit_hash, commit_msg in all_commits:
        timeline_items.append(
            (
                conv_index,
                commit_ts,
                _macros.index_commit(commit_hash, commit_msg, commit_ts, github_repo),
            )
        )

    timeline_items.sort(key=lambda item: ((item[1] or ""), item[0]))
    index_items = [item[2] for item in timeline_items]

    search_index_data = {
        "total_pages": total_pages,
        "items": search_items,
    }
    inline_search_index = _select_inline_search_index(search_mode, search_index_data)

    index_template = get_template("index.html")
    index_content = index_template.render(
        pagination_html=_macros.index_pagination(total_pages),
        prompt_num=prompt_num,
        total_messages=total_messages,
        total_tool_calls=sum(total_tool_counts.values()),
        total_commits=len(all_commits),
        total_pages=total_pages,
        index_items_html="".join(index_items),
        session_meta_html=session_meta_html,
        system_instructions_html=instructions_html,
        inline_search_index=inline_search_index,
    )
    index_path = output_dir / "index.html"
    index_path.write_text(index_content, encoding="utf-8")

    write_search_index(
        output_dir,
        total_pages=total_pages,
        items=search_items,
    )

    if include_json and source_path:
        source_path = Path(source_path)
        if source_path.exists():
            shutil.copy(source_path, output_dir / source_path.name)

    return index_path


def generate_html(
    json_path: str | Path,
    output_dir: str | Path,
    include_json: bool = False,
    search_mode: SearchMode = "auto",
    redact_patterns: Sequence[str] | None = None,
    theme: str | None = None,
):
    session = parse_session_file(json_path)
    return generate_html_from_session(
        session,
        output_dir,
        source_path=json_path,
        include_json=include_json,
        search_mode=search_mode,
        redact_patterns=redact_patterns,
        theme=theme,
    )
