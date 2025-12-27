"""Convert Codex session JSONL to clean, mobile-friendly HTML pages with pagination."""

import html
import json
import os
import re
import shutil
import tempfile
import subprocess
import webbrowser
from datetime import datetime
from pathlib import Path

import click
from click_default_group import DefaultGroup
from jinja2 import Environment, PackageLoader
import markdown
import questionary

PROMPTS_PER_PAGE = 5
LONG_TEXT_THRESHOLD = 300

COMMIT_PATTERN = re.compile(r"\[[\w\-/]+ ([a-f0-9]{7,})\] (.+?)(?:\n|$)")
GITHUB_REPO_PATTERN = re.compile(
    r"(?:https?://)?(?:api\.)?github\.com[:/](?:repos/)?"
    r"(?P<owner>[A-Za-z0-9_.-]+)/(?P<repo>[A-Za-z0-9_.-]+)(?:\.git)?"
)

_jinja_env = Environment(
    loader=PackageLoader("codex_transcripts", "templates"),
    autoescape=True,
)

_macros_template = _jinja_env.get_template("macros.html")
_macros = _macros_template.module


def get_template(name):
    return _jinja_env.get_template(name)


def render_markdown_text(text):
    if not text:
        return ""
    return markdown.markdown(text, extensions=["fenced_code", "tables"])


def is_json_like(text):
    if not text or not isinstance(text, str):
        return False
    text = text.strip()
    return (text.startswith("{") and text.endswith("}")) or (
        text.startswith("[") and text.endswith("]")
    )


def format_json(obj):
    try:
        if isinstance(obj, str):
            obj = json.loads(obj)
        formatted = json.dumps(obj, indent=2, ensure_ascii=False)
        return f'<pre class="json">{html.escape(formatted)}</pre>'
    except (json.JSONDecodeError, TypeError, ValueError):
        return f"<pre>{html.escape(str(obj))}</pre>"


def extract_text_from_content(content):
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        parts = []
        for block in content:
            if not isinstance(block, dict):
                continue
            text = block.get("text")
            if text:
                parts.append(text)
        return "\n".join(parts).strip()
    return ""


def parse_arguments(raw):
    if raw is None:
        return None
    if isinstance(raw, dict):
        return raw
    if not isinstance(raw, str):
        return raw
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return raw


def extract_cwd_from_text(text):
    if not text:
        return None
    match = re.search(r"<cwd>(.*?)</cwd>", text, flags=re.DOTALL)
    if match:
        return match.group(1).strip()
    return None


def normalize_text_for_match(text):
    if not text:
        return ""
    return re.sub(r"\s+", "", text).lower()


def is_instruction_repeat(message_text, instructions_text):
    if not message_text or not instructions_text:
        return False
    return normalize_text_for_match(instructions_text) in normalize_text_for_match(
        message_text
    )


def extract_github_repo(repo_url):
    if not repo_url:
        return None
    match = GITHUB_REPO_PATTERN.search(repo_url)
    if not match:
        return None
    owner = match.group("owner")
    repo = match.group("repo")
    return f"{owner}/{repo}"


def slugify(text):
    if not text:
        return "unknown"
    slug = re.sub(r"[^A-Za-z0-9._-]+", "-", text)
    return slug.strip("-") or "unknown"


def detect_error_from_output(output):
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


class SessionData:
    def __init__(
        self,
        session_id,
        started_at,
        cwd,
        git,
        instructions,
        entries,
        source_path,
        instruction_repeats=1,
    ):
        self.session_id = session_id
        self.started_at = started_at
        self.cwd = cwd
        self.git = git
        self.instructions = instructions
        self.entries = entries
        self.source_path = source_path
        self.instruction_repeats = instruction_repeats


class Entry:
    def __init__(
        self,
        index,
        timestamp,
        entry_type,
        role=None,
        content=None,
        tool_name=None,
        tool_input=None,
        tool_output=None,
        call_id=None,
    ):
        self.index = index
        self.timestamp = timestamp
        self.entry_type = entry_type
        self.role = role
        self.content = content
        self.tool_name = tool_name
        self.tool_input = tool_input
        self.tool_output = tool_output
        self.call_id = call_id


# Module-level variable for GitHub repo (set by generate_html)
_github_repo = None


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
    text = text.replace(/"([^"]+)":/g, '<span style="color: #ce93d8">"$1"</span>:');
    text = text.replace(/: "([^"]*)"/g, ': <span style="color: #81d4fa">"$1"</span>');
    text = text.replace(/: (\d+)/g, ': <span style="color: #ffcc80">$1</span>');
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

# JavaScript to fix relative URLs when served via gistpreview.github.io
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


def parse_session_file(filepath):
    filepath = Path(filepath)
    entries = []
    session_id = filepath.stem
    started_at = None
    cwd = None
    git = None
    instructions = None
    instruction_repeats = 0
    tool_name_by_call_id = {}
    seen_messages = set()

    with open(filepath, "r", encoding="utf-8") as f:
        for line_index, line in enumerate(f):
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue

            # Current format
            if obj.get("type") == "session_meta":
                payload = obj.get("payload", {})
                session_id = payload.get("id", session_id)
                started_at = payload.get("timestamp") or obj.get("timestamp")
                cwd = payload.get("cwd", cwd)
                git = payload.get("git", git)
                new_instructions = payload.get("instructions")
                if new_instructions:
                    if instructions is None:
                        instructions = new_instructions
                    instruction_repeats += 1
                continue

            if obj.get("type") == "response_item":
                payload = obj.get("payload", {})
                payload_type = payload.get("type")
                timestamp = obj.get("timestamp")
                if payload_type == "message":
                    role = payload.get("role")
                    content_text = extract_text_from_content(payload.get("content", []))
                    if role == "user" and is_instruction_repeat(
                        content_text, instructions
                    ):
                        content_text = (
                            "System instructions repeated. See [system instructions](#system-instructions)."
                        )
                    if content_text:
                        key = (role, content_text, timestamp)
                        seen_messages.add(key)
                        entries.append(
                            Entry(
                                index=len(entries),
                                timestamp=timestamp,
                                entry_type="message",
                                role=role,
                                content=content_text,
                            )
                        )
                    if not cwd:
                        cwd = extract_cwd_from_text(content_text) or cwd
                elif payload_type == "function_call":
                    name = payload.get("name")
                    call_id = payload.get("call_id")
                    tool_input = parse_arguments(payload.get("arguments"))
                    if call_id:
                        tool_name_by_call_id[call_id] = name
                    entries.append(
                        Entry(
                            index=len(entries),
                            timestamp=timestamp,
                            entry_type="tool_call",
                            tool_name=name,
                            tool_input=tool_input,
                            call_id=call_id,
                        )
                    )
                elif payload_type == "function_call_output":
                    call_id = payload.get("call_id")
                    tool_name = tool_name_by_call_id.get(call_id)
                    entries.append(
                        Entry(
                            index=len(entries),
                            timestamp=timestamp,
                            entry_type="tool_output",
                            tool_name=tool_name,
                            tool_output=payload.get("output"),
                            call_id=call_id,
                        )
                    )
                elif payload_type == "custom_tool_call":
                    name = payload.get("name")
                    call_id = payload.get("call_id")
                    if call_id:
                        tool_name_by_call_id[call_id] = name
                    tool_input = payload.get("input")
                    entries.append(
                        Entry(
                            index=len(entries),
                            timestamp=timestamp,
                            entry_type="tool_call",
                            tool_name=name,
                            tool_input=tool_input,
                            call_id=call_id,
                        )
                    )
                continue

            if obj.get("type") == "event_msg":
                payload = obj.get("payload", {})
                payload_type = payload.get("type")
                timestamp = obj.get("timestamp")
                if payload_type == "user_message":
                    content_text = payload.get("message", "")
                    if is_instruction_repeat(content_text, instructions):
                        content_text = (
                            "System instructions repeated. See [system instructions](#system-instructions)."
                        )
                    key = ("user", content_text, timestamp)
                    if content_text and key not in seen_messages:
                        entries.append(
                            Entry(
                                index=len(entries),
                                timestamp=timestamp,
                                entry_type="message",
                                role="user",
                                content=content_text,
                            )
                        )
                elif payload_type == "agent_message":
                    content_text = payload.get("message", "")
                    key = ("assistant", content_text, timestamp)
                    if content_text and key not in seen_messages:
                        entries.append(
                            Entry(
                                index=len(entries),
                                timestamp=timestamp,
                                entry_type="message",
                                role="assistant",
                                content=content_text,
                            )
                        )
                continue

            # Legacy format
            if "id" in obj and "timestamp" in obj and "git" in obj:
                session_id = obj.get("id", session_id)
                started_at = obj.get("timestamp", started_at)
                git = obj.get("git", git)
                new_instructions = obj.get("instructions")
                if new_instructions:
                    if instructions is None:
                        instructions = new_instructions
                    instruction_repeats += 1
                continue

            if obj.get("record_type") == "state":
                continue

            entry_type = obj.get("type")
            timestamp = obj.get("timestamp")

            if entry_type == "message":
                role = obj.get("role")
                content_text = extract_text_from_content(obj.get("content", []))
                if role == "user" and is_instruction_repeat(content_text, instructions):
                    content_text = (
                        "System instructions repeated. See [system instructions](#system-instructions)."
                    )
                if content_text:
                    entries.append(
                        Entry(
                            index=len(entries),
                            timestamp=timestamp,
                            entry_type="message",
                            role=role,
                            content=content_text,
                        )
                    )
                if not cwd:
                    cwd = extract_cwd_from_text(content_text) or cwd
            elif entry_type == "function_call":
                name = obj.get("name")
                call_id = obj.get("call_id")
                tool_input = parse_arguments(obj.get("arguments"))
                if call_id:
                    tool_name_by_call_id[call_id] = name
                entries.append(
                    Entry(
                        index=len(entries),
                        timestamp=timestamp,
                        entry_type="tool_call",
                        tool_name=name,
                        tool_input=tool_input,
                        call_id=call_id,
                    )
                )
            elif entry_type == "function_call_output":
                call_id = obj.get("call_id")
                tool_name = tool_name_by_call_id.get(call_id)
                entries.append(
                    Entry(
                        index=len(entries),
                        timestamp=timestamp,
                        entry_type="tool_output",
                        tool_name=tool_name,
                        tool_output=obj.get("output"),
                        call_id=call_id,
                    )
                )

    if not instructions:
        instructions = None
        instruction_repeats = 0
    elif instruction_repeats == 0:
        instruction_repeats = 1

    return SessionData(
        session_id=session_id,
        started_at=started_at,
        cwd=cwd,
        git=git,
        instructions=instructions,
        entries=entries,
        source_path=filepath,
        instruction_repeats=instruction_repeats,
    )


def analyze_conversation(entries):
    tool_counts = {}
    long_texts = []
    commits = []

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


def format_tool_stats(tool_counts):
    if not tool_counts:
        return ""

    abbrev = {
        "shell": "shell",
        "shell_command": "shell",
        "apply_patch": "patch",
        "update_plan": "plan",
    }

    parts = []
    for name, count in sorted(tool_counts.items(), key=lambda x: -x[1]):
        short_name = abbrev.get(name, name.lower())
        parts.append(f"{count} {short_name}")

    return " | ".join(parts)


def make_msg_id(timestamp, idx):
    if not timestamp:
        return f"msg-{idx}"
    safe = timestamp.replace(":", "-").replace(".", "-")
    return f"msg-{safe}-{idx}"


def render_tool_call(entry):
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
        plan = []
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


def render_tool_output(entry):
    output = entry.tool_output
    is_error = detect_error_from_output(output)

    if isinstance(output, str):
        commits_found = list(COMMIT_PATTERN.finditer(output))
        if commits_found:
            parts = []
            last_end = 0
            for match in commits_found:
                before = output[last_end : match.start()].strip()
                if before:
                    parts.append(f"<pre>{html.escape(before)}</pre>")
                commit_hash = match.group(1)
                commit_msg = match.group(2)
                parts.append(_macros.commit_card(commit_hash, commit_msg, _github_repo))
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


def render_message(entry):
    if entry.entry_type == "message":
        content_html = render_markdown_text(entry.content)
        role_class = "assistant" if entry.role == "assistant" else "user"
        role_label = "Assistant" if entry.role == "assistant" else "User"
    elif entry.entry_type == "tool_call":
        content_html = render_tool_call(entry)
        role_class = "tool-call"
        role_label = "Tool"
    elif entry.entry_type == "tool_output":
        content_html = render_tool_output(entry)
        role_class = "tool-reply"
        role_label = "Tool result"
    else:
        return ""

    msg_id = make_msg_id(entry.timestamp, entry.index)
    timestamp = entry.timestamp or ""
    return _macros.message(role_class, role_label, msg_id, timestamp, content_html)


def build_session_meta(session):
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


def generate_html(json_path, output_dir, include_json=False):
    output_dir = Path(output_dir)
    output_dir.mkdir(exist_ok=True, parents=True)

    session = parse_session_file(json_path)

    git = session.git or {}
    repo_url = git.get("repository_url") if isinstance(git, dict) else None
    github_repo = extract_github_repo(repo_url)

    global _github_repo
    _github_repo = github_repo

    session_meta = build_session_meta(session)

    # Group entries into conversations by user prompt
    conversations = []
    current_conv = None
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

    for page_num in range(1, total_pages + 1):
        start_idx = (page_num - 1) * PROMPTS_PER_PAGE
        end_idx = min(start_idx + PROMPTS_PER_PAGE, total_convs)
        page_convs = conversations[start_idx:end_idx]
        messages_html = []
        for conv in page_convs:
            for entry in conv["entries"]:
                msg_html = render_message(entry)
                if msg_html:
                    messages_html.append(msg_html)
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
        (output_dir / f"page-{page_num:03d}.html").write_text(
            page_content, encoding="utf-8"
        )

    # Build index timeline
    total_tool_counts = {}
    total_messages = sum(len(c["entries"]) for c in conversations)
    all_commits = []
    timeline_items = []

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
        for lt in stats["long_texts"]:
            rendered_lt = render_markdown_text(lt)
            long_texts_html += _macros.index_long_text(rendered_lt)
        stats_html = _macros.index_stats(tool_stats_str, long_texts_html)
        item_html = _macros.index_item(
            prompt_num, link, conv["timestamp"], rendered_content, stats_html
        )
        timeline_items.append((conv_index, conv["timestamp"], item_html))

        for commit_hash, commit_msg, commit_ts in stats["commits"]:
            all_commits.append((conv_index, commit_ts, commit_hash, commit_msg))

    for conv_index, commit_ts, commit_hash, commit_msg in all_commits:
        item_html = _macros.index_commit(commit_hash, commit_msg, commit_ts, _github_repo)
        timeline_items.append((conv_index, commit_ts, item_html))

    def sort_key(item):
        conv_index, ts, _ = item
        if ts:
            return (ts, conv_index)
        return ("", conv_index)

    timeline_items.sort(key=sort_key)
    index_items = [item[2] for item in timeline_items]

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
    )
    index_path = output_dir / "index.html"
    index_path.write_text(index_content, encoding="utf-8")

    if include_json:
        shutil.copy(json_path, output_dir / Path(json_path).name)

    return index_path


def get_session_summary(filepath, max_length=200):
    filepath = Path(filepath)
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except json.JSONDecodeError:
                    continue

                if obj.get("type") == "response_item":
                    payload = obj.get("payload", {})
                    if payload.get("type") == "message" and payload.get("role") == "user":
                        text = extract_text_from_content(payload.get("content", []))
                        if not text:
                            continue
                        if "<environment_context>" in text:
                            continue
                        if text.strip().startswith("# AGENTS.md instructions"):
                            continue
                        return text[: max_length - 3] + "..." if len(text) > max_length else text

                if obj.get("type") == "message" and obj.get("role") == "user":
                    text = extract_text_from_content(obj.get("content", []))
                    if not text:
                        continue
                    if "<environment_context>" in text:
                        continue
                    if text.strip().startswith("# AGENTS.md instructions"):
                        continue
                    return text[: max_length - 3] + "..." if len(text) > max_length else text
    except Exception:
        return "(no summary)"

    return "(no summary)"


def find_local_sessions(folder, limit=10):
    folder = Path(folder)
    if not folder.exists():
        return []

    results = []
    for f in folder.glob("**/*.jsonl"):
        summary = get_session_summary(f)
        if summary == "(no summary)":
            continue
        results.append((f, summary))

    results.sort(key=lambda x: x[0].stat().st_mtime, reverse=True)
    return results[:limit]


def resolve_project_key(session):
    git = session.git or {}
    repo_url = git.get("repository_url") if isinstance(git, dict) else None
    repo_name = extract_github_repo(repo_url) if repo_url else None
    if repo_name:
        return repo_name, repo_name
    if session.cwd:
        return session.cwd, session.cwd
    return "unknown", "Unknown"


def find_all_sessions(folder):
    folder = Path(folder)
    if not folder.exists():
        return []

    projects = {}
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
                "summary": get_session_summary(session_file),
                "mtime": stat.st_mtime,
                "size": stat.st_size,
                "session_id": session.session_id,
            }
        )

    for project in projects.values():
        project["sessions"].sort(key=lambda s: s["mtime"], reverse=True)

    result = list(projects.values())
    result.sort(
        key=lambda p: p["sessions"][0]["mtime"] if p["sessions"] else 0, reverse=True
    )

    return result


def _generate_project_index(project, output_dir):
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

    output_path = output_dir / "index.html"
    output_path.write_text(html_content, encoding="utf-8")


def _generate_master_index(projects, output_dir):
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

    output_path = output_dir / "index.html"
    output_path.write_text(html_content, encoding="utf-8")


def generate_batch_html(source_folder, output_dir, include_json=False, progress_callback=None):
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
                    project["name"], session_name, processed_count, total_session_count
                )

        _generate_project_index(project, project_dir)

    _generate_master_index(projects, output_dir)

    return {
        "total_projects": len(projects),
        "total_sessions": successful_sessions,
        "failed_sessions": failed_sessions,
        "output_dir": output_dir,
    }


def open_or_print_url(url):
    try:
        opened = webbrowser.open(url)
    except Exception:
        opened = False
    if not opened:
        click.echo("Open this URL in your browser:")
        click.echo(url)


def format_session_timestamp(timestamp):
    if not timestamp:
        return None
    try:
        cleaned = timestamp.replace("Z", "+00:00")
        parsed = datetime.fromisoformat(cleaned)
        return parsed.strftime("%Y-%m-%d %H:%M")
    except ValueError:
        return timestamp


def build_gist_label(session, source_path):
    parts = []
    started_at = format_session_timestamp(session.started_at)
    if started_at:
        parts.append(started_at)
    if session.session_id:
        parts.append(session.session_id)
    else:
        parts.append(Path(source_path).stem)
    label = " ".join(parts).strip()
    return label or Path(source_path).stem


def build_gist_description(session, source_path):
    return f"Codex transcript: {build_gist_label(session, source_path)}"


def build_gist_index_filename(session, source_path):
    label = build_gist_label(session, source_path)
    slug = slugify(f"codex-transcript-{label}")
    return f"{slug}.html"


def inject_gist_preview_js(output_dir):
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


def stage_gist_files(output_dir, include_json, index_filename, staging_dir=None):
    output_dir = Path(output_dir)
    html_files = sorted(output_dir.glob("*.html"))
    if not html_files:
        raise click.ClickException(f"No transcript files found in {output_dir}")

    if staging_dir:
        staging_dir = Path(staging_dir)
    else:
        staging_dir = Path(tempfile.mkdtemp(prefix="codex-gist-"))
    staged_files = []
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


def extract_gist_id(gist_url):
    if not gist_url:
        return None
    return gist_url.rstrip("/").split("/")[-1]


def create_gist_from_output(output_dir, description, public, include_json, index_filename):
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


@click.group(cls=DefaultGroup, default="local", default_if_no_args=True)
@click.version_option(None, "-v", "--version", package_name="codex-transcripts")
def cli():
    """Convert Codex session JSONL to mobile-friendly HTML pages."""
    pass


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
    results = find_local_sessions(sessions_folder, limit=limit)

    if not results:
        click.echo("No local sessions found.")
        return

    choices = []
    for filepath, summary in results:
        stat = filepath.stat()
        mod_time = datetime.fromtimestamp(stat.st_mtime)
        size_kb = stat.st_size / 1024
        date_str = mod_time.strftime("%Y-%m-%d %H:%M")
        if len(summary) > 50:
            summary = summary[:47] + "..."
        display = f"{date_str}  {size_kb:5.0f} KB  {summary}"
        choices.append(questionary.Choice(title=display, value=filepath))

    selected = questionary.select(
        "Select a session to convert:",
        choices=choices,
    ).ask()

    if selected is None:
        click.echo("No session selected.")
        return

    session_file = selected

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
        session = parse_session_file(session_file)
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
def json_cmd(json_file, output, output_auto, include_json, create_gist, gist_public, open_browser):
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

    def on_progress(project_name, session_name, current, total):
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
            click.echo(
                f"  {failure['project']}/{failure['session']}: {failure['error']}"
            )

    if not quiet:
        click.echo(
            f"\nGenerated archive with {stats['total_projects']} projects, "
            f"{stats['total_sessions']} sessions"
        )
        click.echo(f"Output: {output.resolve()}")

    if open_browser:
        index_url = (output / "index.html").resolve().as_uri()
        open_or_print_url(index_url)


def main():
    cli()


if __name__ == "__main__":
    main()
