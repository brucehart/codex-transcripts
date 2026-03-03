"""HTML rendering for Codex transcripts."""

from __future__ import annotations

import html
import json
import shutil
from pathlib import Path
from typing import Any

import bleach
from jinja2 import Environment, PackageLoader
import markdown

from .common import COMMIT_PATTERN, detect_error_from_output, extract_github_repo, format_json, is_json_like
from .parser import Entry, SessionData, parse_session_file


PROMPTS_PER_PAGE = 5
LONG_TEXT_THRESHOLD = 300


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


CSS = """
:root { --bg-color: #f5f5f5; --card-bg: #ffffff; --user-bg: #e3f2fd; --user-border: #1976d2; --assistant-bg: #f5f5f5; --assistant-border: #9e9e9e; --thinking-bg: #fff8e1; --thinking-border: #ffc107; --thinking-text: #666; --tool-bg: #f3e5f5; --tool-border: #9c27b0; --tool-result-bg: #e8f5e9; --tool-error-bg: #ffebee; --text-color: #212121; --text-muted: #757575; --code-bg: #263238; --code-text: #aed581; }
* { box-sizing: border-box; }
body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; background: var(--bg-color); color: var(--text-color); margin: 0; padding: 16px; line-height: 1.6; }
.container { max-width: 800px; margin: 0 auto; }
h1 { font-size: 1.5rem; margin-bottom: 24px; padding-bottom: 8px; border-bottom: 2px solid var(--user-border); }
.header-row { display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 12px; border-bottom: 2px solid var(--user-border); padding-bottom: 8px; margin-bottom: 16px; }
.header-row h1 { border-bottom: none; padding-bottom: 0; margin-bottom: 0; flex: 1; min-width: 200px; }
.session-meta { display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 12px; background: var(--card-bg); padding: 12px 16px; border-radius: 10px; border-left: 4px solid var(--assistant-border); box-shadow: 0 1px 3px rgba(0,0,0,0.08); margin-bottom: 16px; }
.session-meta .meta-item { font-size: 0.9rem; color: var(--text-muted); }
.session-meta .meta-label { display: block; font-size: 0.75rem; text-transform: uppercase; letter-spacing: 0.5px; color: var(--assistant-border); }
.system-instructions { background: #fffbe6; border: 1px solid #ffe082; border-radius: 10px; margin-bottom: 16px; overflow: hidden; }
.system-instructions summary { cursor: pointer; padding: 10px 14px; font-weight: 600; color: #ef6c00; background: #fff3cd; }
.system-instructions-content { padding: 12px 16px; }
.message { margin-bottom: 16px; border-radius: 12px; overflow: hidden; box-shadow: 0 1px 3px rgba(0,0,0,0.1); }
.message.user { background: var(--user-bg); border-left: 4px solid var(--user-border); }
.message.assistant { background: var(--card-bg); border-left: 4px solid var(--assistant-border); }
.message.tool-call { background: #f3e5f5; border-left: 4px solid var(--tool-border); }
.message.tool-reply { background: #fff8e1; border-left: 4px solid #ff9800; }
.tool-reply .role-label { color: #e65100; }
.tool-reply .tool-result { background: transparent; padding: 0; margin: 0; }
.tool-reply .tool-result .truncatable.truncated::after { background: linear-gradient(to bottom, transparent, #fff8e1); }
.message-header { display: flex; justify-content: space-between; align-items: center; padding: 8px 16px; background: rgba(0,0,0,0.03); font-size: 0.85rem; }
.role-label { font-weight: 600; text-transform: uppercase; letter-spacing: 0.5px; }
.user .role-label { color: var(--user-border); }
.tool-call .role-label { color: var(--tool-border); }
time { color: var(--text-muted); font-size: 0.8rem; }
.timestamp-link { color: inherit; text-decoration: none; }
.timestamp-link:hover { text-decoration: underline; }
.message:target { animation: highlight 2s ease-out; }
@keyframes highlight { 0% { background-color: rgba(25, 118, 210, 0.2); } 100% { background-color: transparent; } }
.message-content { padding: 16px; }
.message-content p { margin: 0 0 12px 0; }
.message-content p:last-child { margin-bottom: 0; }
.thinking { background: var(--thinking-bg); border: 1px solid var(--thinking-border); border-radius: 8px; padding: 12px; margin: 12px 0; font-size: 0.9rem; color: var(--thinking-text); }
.thinking-label { font-size: 0.75rem; font-weight: 600; text-transform: uppercase; color: #f57c00; margin-bottom: 8px; }
.thinking p { margin: 8px 0; }
.assistant-text { margin: 8px 0; }
.tool-use { background: var(--tool-bg); border: 1px solid var(--tool-border); border-radius: 8px; padding: 12px; margin: 12px 0; }
.tool-header { font-weight: 600; color: var(--tool-border); margin-bottom: 8px; display: flex; align-items: center; gap: 8px; }
.tool-icon { font-size: 1.1rem; }
.tool-description { font-size: 0.9rem; color: var(--text-muted); margin-bottom: 8px; font-style: italic; }
.tool-result { background: var(--tool-result-bg); border-radius: 8px; padding: 12px; margin: 12px 0; }
.tool-result.tool-error { background: var(--tool-error-bg); }
.file-tool { border-radius: 8px; padding: 12px; margin: 12px 0; }
.write-tool { background: linear-gradient(135deg, #e3f2fd 0%, #e8f5e9 100%); border: 1px solid #4caf50; }
.edit-tool { background: linear-gradient(135deg, #fff3e0 0%, #fce4ec 100%); border: 1px solid #ff9800; }
.patch-tool { background: linear-gradient(135deg, #ede7f6 0%, #e3f2fd 100%); border: 1px solid #5c6bc0; }
.file-tool-header { font-weight: 600; margin-bottom: 4px; display: flex; align-items: center; gap: 8px; font-size: 0.95rem; }
.write-header { color: #2e7d32; }
.edit-header { color: #e65100; }
.patch-header { color: #3949ab; }
.file-tool-icon { font-size: 1rem; }
.file-tool-path { font-family: monospace; background: rgba(0,0,0,0.08); padding: 2px 8px; border-radius: 4px; }
.file-tool-fullpath { font-family: monospace; font-size: 0.8rem; color: var(--text-muted); margin-bottom: 8px; word-break: break-all; }
.file-content { margin: 0; }
.edit-section { display: flex; margin: 4px 0; border-radius: 4px; overflow: hidden; }
.edit-label { padding: 8px 12px; font-weight: bold; font-family: monospace; display: flex; align-items: flex-start; }
.edit-old { background: #fce4ec; }
.edit-old .edit-label { color: #b71c1c; background: #f8bbd9; }
.edit-old .edit-content { color: #880e4f; }
.edit-new { background: #e8f5e9; }
.edit-new .edit-label { color: #1b5e20; background: #a5d6a7; }
.edit-new .edit-content { color: #1b5e20; }
.edit-content { margin: 0; flex: 1; background: transparent; font-size: 0.85rem; }
.edit-replace-all { font-size: 0.75rem; font-weight: normal; color: var(--text-muted); }
.write-tool .truncatable.truncated::after { background: linear-gradient(to bottom, transparent, #e6f4ea); }
.edit-tool .truncatable.truncated::after { background: linear-gradient(to bottom, transparent, #fff0e5); }
.patch-tool .truncatable.truncated::after { background: linear-gradient(to bottom, transparent, #ede7f6); }
.todo-list { background: linear-gradient(135deg, #e8f5e9 0%, #f1f8e9 100%); border: 1px solid #81c784; border-radius: 8px; padding: 12px; margin: 12px 0; }
.todo-header { font-weight: 600; color: #2e7d32; margin-bottom: 10px; display: flex; align-items: center; gap: 8px; font-size: 0.95rem; }
.todo-items { list-style: none; margin: 0; padding: 0; }
.todo-item { display: flex; align-items: flex-start; gap: 10px; padding: 6px 0; border-bottom: 1px solid rgba(0,0,0,0.06); font-size: 0.9rem; }
.todo-item:last-child { border-bottom: none; }
.todo-icon { flex-shrink: 0; width: 20px; height: 20px; display: flex; align-items: center; justify-content: center; font-weight: bold; border-radius: 50%; }
.todo-completed .todo-icon { color: #2e7d32; background: rgba(46, 125, 50, 0.15); }
.todo-completed .todo-content { color: #558b2f; text-decoration: line-through; }
.todo-in-progress .todo-icon { color: #f57c00; background: rgba(245, 124, 0, 0.15); }
.todo-in-progress .todo-content { color: #e65100; font-weight: 500; }
.todo-pending .todo-icon { color: #757575; background: rgba(0,0,0,0.05); }
.todo-pending .todo-content { color: #616161; }
.plan-update { background: linear-gradient(135deg, #e8eaf6 0%, #ede7f6 100%); border: 1px solid #7986cb; border-radius: 8px; padding: 12px; margin: 12px 0; }
.plan-header { font-weight: 600; color: #3949ab; margin-bottom: 8px; display: flex; align-items: center; gap: 8px; font-size: 0.95rem; }
.plan-explanation { color: var(--text-muted); font-size: 0.9rem; margin-bottom: 8px; }
.plan-items { list-style: none; margin: 0; padding: 0; }
.plan-item { display: flex; align-items: flex-start; gap: 10px; padding: 6px 0; border-bottom: 1px solid rgba(0,0,0,0.06); font-size: 0.9rem; }
.plan-item:last-child { border-bottom: none; }
.plan-icon { flex-shrink: 0; width: 20px; height: 20px; display: flex; align-items: center; justify-content: center; font-weight: bold; border-radius: 50%; }
.plan-completed .plan-icon { color: #2e7d32; background: rgba(46, 125, 50, 0.15); }
.plan-in-progress .plan-icon { color: #f57c00; background: rgba(245, 124, 0, 0.15); }
.plan-pending .plan-icon { color: #757575; background: rgba(0,0,0,0.05); }
pre { background: var(--code-bg); color: var(--code-text); padding: 12px; border-radius: 6px; overflow-x: auto; font-size: 0.85rem; line-height: 1.5; margin: 8px 0; white-space: pre-wrap; word-wrap: break-word; }
pre.json { color: #e0e0e0; }
code { background: rgba(0,0,0,0.08); padding: 2px 6px; border-radius: 4px; font-size: 0.9em; }
pre code { background: none; padding: 0; }
.user-content { margin: 0; }
.truncatable { position: relative; }
.truncatable.truncated .truncatable-content { max-height: 200px; overflow: hidden; }
.truncatable.truncated::after { content: ''; position: absolute; bottom: 32px; left: 0; right: 0; height: 60px; background: linear-gradient(to bottom, transparent, var(--card-bg)); pointer-events: none; }
.message.user .truncatable.truncated::after { background: linear-gradient(to bottom, transparent, var(--user-bg)); }
.message.tool-reply .truncatable.truncated::after { background: linear-gradient(to bottom, transparent, #fff8e1); }
.tool-use .truncatable.truncated::after { background: linear-gradient(to bottom, transparent, var(--tool-bg)); }
.tool-result .truncatable.truncated::after { background: linear-gradient(to bottom, transparent, var(--tool-result-bg)); }
.expand-btn { display: none; width: 100%; padding: 8px 16px; margin-top: 4px; background: rgba(0,0,0,0.05); border: 1px solid rgba(0,0,0,0.1); border-radius: 6px; cursor: pointer; font-size: 0.85rem; color: var(--text-muted); }
.expand-btn:hover { background: rgba(0,0,0,0.1); }
.truncatable.truncated .expand-btn, .truncatable.expanded .expand-btn { display: block; }
.pagination { display: flex; justify-content: center; gap: 8px; margin: 24px 0; flex-wrap: wrap; }
.pagination a, .pagination span { padding: 5px 10px; border-radius: 6px; text-decoration: none; font-size: 0.85rem; }
.pagination a { background: var(--card-bg); color: var(--user-border); border: 1px solid var(--user-border); }
.pagination a:hover { background: var(--user-bg); }
.pagination .current { background: var(--user-border); color: white; }
.pagination .disabled { color: var(--text-muted); border: 1px solid #ddd; }
.pagination .index-link { background: var(--user-border); color: white; }
.index-item { margin-bottom: 16px; border-radius: 12px; overflow: hidden; box-shadow: 0 1px 3px rgba(0,0,0,0.1); background: var(--user-bg); border-left: 4px solid var(--user-border); }
.index-item a { display: block; text-decoration: none; color: inherit; }
.index-item a:hover { background: rgba(25, 118, 210, 0.1); }
.index-item-header { display: flex; justify-content: space-between; align-items: center; padding: 8px 16px; background: rgba(0,0,0,0.03); font-size: 0.85rem; }
.index-item-number { font-weight: 600; color: var(--user-border); }
.index-item-content { padding: 16px; }
.index-item-stats { padding: 8px 16px 12px 32px; font-size: 0.85rem; color: var(--text-muted); border-top: 1px solid rgba(0,0,0,0.06); }
.index-item-long-text { margin-top: 8px; padding: 12px; background: var(--card-bg); border-radius: 8px; border-left: 3px solid var(--assistant-border); }
.index-item-long-text .truncatable.truncated::after { background: linear-gradient(to bottom, transparent, var(--card-bg)); }
.index-item-long-text-content { color: var(--text-color); }
.commit-card { margin: 8px 0; padding: 10px 14px; background: #fff3e0; border-left: 4px solid #ff9800; border-radius: 6px; }
.commit-card a { text-decoration: none; color: #5d4037; display: block; }
.commit-card a:hover { color: #e65100; }
.commit-card-hash { font-family: monospace; color: #e65100; font-weight: 600; margin-right: 8px; }
.index-commit { margin-bottom: 12px; padding: 10px 16px; background: #fff3e0; border-left: 4px solid #ff9800; border-radius: 8px; box-shadow: 0 1px 2px rgba(0,0,0,0.05); }
.index-commit a { display: block; text-decoration: none; color: inherit; }
.index-commit a:hover { background: rgba(255, 152, 0, 0.1); margin: -10px -16px; padding: 10px 16px; border-radius: 8px; }
.index-commit-header { display: flex; justify-content: space-between; align-items: center; font-size: 0.85rem; margin-bottom: 4px; }
.index-commit-hash { font-family: monospace; color: #e65100; font-weight: 600; }
.index-commit-msg { color: #5d4037; }
#search-box { display: none; align-items: center; gap: 8px; }
#search-box input { padding: 6px 12px; border: 1px solid var(--assistant-border); border-radius: 6px; font-size: 16px; width: 180px; }
#search-box button, #modal-search-btn, #modal-close-btn { background: var(--user-border); color: white; border: none; border-radius: 6px; padding: 6px 10px; cursor: pointer; display: flex; align-items: center; justify-content: center; }
#search-box button:hover, #modal-search-btn:hover { background: #1565c0; }
#modal-close-btn { background: var(--text-muted); margin-left: 8px; }
#modal-close-btn:hover { background: #616161; }
#search-modal[open] { border: none; border-radius: 12px; box-shadow: 0 4px 24px rgba(0,0,0,0.2); padding: 0; width: 90vw; max-width: 900px; height: 80vh; max-height: 80vh; display: flex; flex-direction: column; }
#search-modal::backdrop { background: rgba(0,0,0,0.5); }
.search-modal-header { display: flex; align-items: center; gap: 8px; padding: 16px; border-bottom: 1px solid var(--assistant-border); background: var(--bg-color); border-radius: 12px 12px 0 0; }
.search-modal-header input { flex: 1; padding: 8px 12px; border: 1px solid var(--assistant-border); border-radius: 6px; font-size: 16px; }
#search-status { padding: 8px 16px; font-size: 0.85rem; color: var(--text-muted); border-bottom: 1px solid rgba(0,0,0,0.06); }
#search-results { flex: 1; overflow-y: auto; padding: 16px; }
.search-result { margin-bottom: 16px; border-radius: 8px; overflow: hidden; box-shadow: 0 1px 3px rgba(0,0,0,0.1); }
.search-result a { display: block; text-decoration: none; color: inherit; }
.search-result a:hover { background: rgba(25, 118, 210, 0.05); }
.search-result-page { padding: 6px 12px; background: rgba(0,0,0,0.03); font-size: 0.8rem; color: var(--text-muted); border-bottom: 1px solid rgba(0,0,0,0.06); }
.search-result-content { padding: 12px; }
.search-result mark { background: #fff59d; padding: 1px 2px; border-radius: 2px; }
@media (max-width: 600px) { body { padding: 8px; } .message, .index-item { border-radius: 8px; } .message-content, .index-item-content { padding: 12px; } pre { font-size: 0.8rem; padding: 8px; } #search-box input { width: 120px; } #search-modal[open] { width: 95vw; height: 90vh; } }
"""

JS = """
document.querySelectorAll('time[data-timestamp]').forEach(function(el) {
    var timestamp = el.getAttribute('data-timestamp');
    if (!timestamp) return;
    var date = new Date(timestamp);
    if (isNaN(date.getTime())) return;
    var now = new Date();
    var isToday = date.toDateString() === now.toDateString();
    var timeStr = date.toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit' });
    if (isToday) { el.textContent = timeStr; }
    else { el.textContent = date.toLocaleDateString(undefined, { month: 'short', day: 'numeric' }) + ' ' + timeStr; }
});
document.querySelectorAll('pre.json').forEach(function(el) {
    var text = el.textContent;
    text = text.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
    text = text.replace(/"([^"]+)":/g, '<span style="color: #ce93d8">"$1"</span>:');
    text = text.replace(/: "([^"]*)"/g, ': <span style="color: #81d4fa">"$1"</span>');
    text = text.replace(/: (\\d+)/g, ': <span style="color: #ffcc80">$1</span>');
    text = text.replace(/: (true|false|null)/g, ': <span style="color: #f48fb1">$1</span>');
    el.innerHTML = text;
});
document.querySelectorAll('.truncatable').forEach(function(wrapper) {
    var content = wrapper.querySelector('.truncatable-content');
    var btn = wrapper.querySelector('.expand-btn');
    if (!content || !btn) return;
    if (content.scrollHeight > 250) {
        wrapper.classList.add('truncated');
        btn.addEventListener('click', function() {
            if (wrapper.classList.contains('truncated')) { wrapper.classList.remove('truncated'); wrapper.classList.add('expanded'); btn.textContent = 'Show less'; }
            else { wrapper.classList.remove('expanded'); wrapper.classList.add('truncated'); btn.textContent = 'Show more'; }
        });
    }
});
"""


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
        if entry.entry_type == "message" and entry.role == "assistant":
            if entry.content and len(entry.content) >= LONG_TEXT_THRESHOLD:
                long_texts.append(entry.content)
        if entry.entry_type == "tool_output":
            output = entry.tool_output
            if isinstance(output, str):
                for match in COMMIT_PATTERN.finditer(output):
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
        short_name = abbrev.get(name, name.lower())
        parts.append(f"{count} {short_name}")

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
        patch_text = (
            tool_input if isinstance(tool_input, str) else json.dumps(tool_input, indent=2)
        )
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
    # Keep search index as plain text to avoid preserving raw HTML-like payloads.
    return bleach.clean(text, tags=[], attributes={}, strip=True)


def generate_html(json_path: str | Path, output_dir: str | Path, include_json: bool = False):
    output_dir = Path(output_dir)
    output_dir.mkdir(exist_ok=True, parents=True)

    session = parse_session_file(json_path)

    git = session.git or {}
    repo_url = git.get("repository_url") if isinstance(git, dict) else None
    github_repo = extract_github_repo(repo_url)

    session_meta = build_session_meta(session)

    # Group entries into conversations by user prompt
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

    total_convs = len(conversations)
    total_pages = (total_convs + PROMPTS_PER_PAGE - 1) // PROMPTS_PER_PAGE

    instructions_html = None
    if session.instructions:
        rendered = render_markdown_text(session.instructions)
        instructions_html = _macros.system_instructions(rendered, session.instruction_repeats)

    if any(session_meta.values()):
        session_meta_html = _macros.session_meta(session_meta)
    else:
        session_meta_html = ""

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
                    search_text = _sanitize_search_text(search_text)
                    msg_id = make_msg_id(entry.timestamp, entry.index)
                    search_items.append(
                        {
                            "page": page_filename,
                            "anchor": msg_id,
                            "role": _entry_search_role(entry),
                            "timestamp": entry.timestamp or "",
                            "text": search_text[:5000],
                        }
                    )

        pagination_html = _macros.pagination(page_num, total_pages)
        page_template = get_template("page.html")
        page_content = page_template.render(
            css=CSS,
            js=JS,
            page_num=page_num,
            total_pages=total_pages,
            pagination_html=pagination_html,
            messages_html="".join(messages_html),
            session_meta_html=session_meta_html,
            system_instructions_html=instructions_html,
        )
        (output_dir / page_filename).write_text(page_content, encoding="utf-8")

    # Build index timeline
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
        long_texts_html = ""
        for long_text in stats["long_texts"]:
            rendered_long_text = render_markdown_text(long_text)
            long_texts_html += _macros.index_long_text(rendered_long_text)
        stats_html = _macros.index_stats(tool_stats_str, long_texts_html)
        item_html = _macros.index_item(
            prompt_num, link, conv["timestamp"], rendered_content, stats_html
        )
        timeline_items.append((conv_index, conv["timestamp"], item_html))

        for commit_hash, commit_msg, commit_ts in stats["commits"]:
            all_commits.append((conv_index, commit_ts, commit_hash, commit_msg))

    for conv_index, commit_ts, commit_hash, commit_msg in all_commits:
        item_html = _macros.index_commit(commit_hash, commit_msg, commit_ts, github_repo)
        timeline_items.append((conv_index, commit_ts, item_html))

    def sort_key(item):
        conv_index, ts, _ = item
        if ts:
            return (ts, conv_index)
        return ("", conv_index)

    timeline_items.sort(key=sort_key)
    index_items = [item[2] for item in timeline_items]

    search_index_data = {
        "total_pages": total_pages,
        "items": search_items,
    }

    index_pagination = _macros.index_pagination(total_pages)
    index_template = get_template("index.html")
    index_content = index_template.render(
        css=CSS,
        js=JS,
        pagination_html=index_pagination,
        prompt_num=prompt_num,
        total_messages=total_messages,
        total_tool_calls=sum(total_tool_counts.values()),
        total_commits=len(all_commits),
        total_pages=total_pages,
        index_items_html="".join(index_items),
        session_meta_html=session_meta_html,
        system_instructions_html=instructions_html,
        search_index_data=search_index_data,
    )
    index_path = output_dir / "index.html"
    index_path.write_text(index_content, encoding="utf-8")

    (output_dir / "search-index.json").write_text(
        json.dumps(search_index_data, ensure_ascii=False),
        encoding="utf-8",
    )

    if include_json:
        shutil.copy(json_path, output_dir / Path(json_path).name)

    return index_path
