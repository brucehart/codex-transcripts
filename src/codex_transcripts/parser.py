"""Session parsing for Codex transcript JSONL logs."""

from __future__ import annotations

from dataclasses import dataclass
import json
import re
from pathlib import Path
from typing import Any


@dataclass
class Entry:
    index: int
    timestamp: str | None
    entry_type: str
    role: str | None = None
    content: str | None = None
    tool_name: str | None = None
    tool_input: Any = None
    tool_output: Any = None
    call_id: str | None = None


@dataclass
class SessionData:
    session_id: str
    started_at: str | None
    cwd: str | None
    git: dict[str, Any] | None
    instructions: str | None
    entries: list[Entry]
    source_path: Path
    instruction_repeats: int = 1


def extract_text_from_content(content: Any) -> str:
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if not isinstance(block, dict):
                continue
            text = block.get("text")
            if text:
                parts.append(text)
        return "\n".join(parts).strip()
    return ""


def parse_arguments(raw: Any) -> Any:
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


def extract_cwd_from_text(text: str | None) -> str | None:
    if not text:
        return None
    match = re.search(r"<cwd>(.*?)</cwd>", text, flags=re.DOTALL)
    if match:
        return match.group(1).strip()
    return None


def normalize_text_for_match(text: str | None) -> str:
    if not text:
        return ""
    return re.sub(r"\s+", "", text).lower()


def is_instruction_repeat(message_text: str | None, instructions_text: str | None) -> bool:
    if not message_text or not instructions_text:
        return False
    return normalize_text_for_match(instructions_text) in normalize_text_for_match(
        message_text
    )


def _normalize_user_content(
    role: str | None, content_text: str, instructions: str | None
) -> str:
    if role == "user" and is_instruction_repeat(content_text, instructions):
        return "System instructions repeated. See [system instructions](#system-instructions)."
    return content_text


def _append_message(
    entries: list[Entry],
    timestamp: str | None,
    role: str,
    content_text: str,
) -> None:
    entries.append(
        Entry(
            index=len(entries),
            timestamp=timestamp,
            entry_type="message",
            role=role,
            content=content_text,
        )
    )


def _append_tool_call(
    entries: list[Entry],
    timestamp: str | None,
    tool_name: str | None,
    tool_input: Any,
    call_id: str | None,
) -> None:
    entries.append(
        Entry(
            index=len(entries),
            timestamp=timestamp,
            entry_type="tool_call",
            tool_name=tool_name,
            tool_input=tool_input,
            call_id=call_id,
        )
    )


def _append_tool_output(
    entries: list[Entry],
    timestamp: str | None,
    tool_name: str | None,
    tool_output: Any,
    call_id: str | None,
) -> None:
    entries.append(
        Entry(
            index=len(entries),
            timestamp=timestamp,
            entry_type="tool_output",
            tool_name=tool_name,
            tool_output=tool_output,
            call_id=call_id,
        )
    )


def parse_session_file(filepath: str | Path) -> SessionData:
    filepath = Path(filepath)
    entries: list[Entry] = []
    session_id = filepath.stem
    started_at: str | None = None
    cwd: str | None = None
    git: dict[str, Any] | None = None
    instructions: str | None = None
    instruction_repeats = 0
    tool_name_by_call_id: dict[str, str | None] = {}
    seen_messages: set[tuple[str, str, str | None]] = set()

    with open(filepath, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue

            obj_type = obj.get("type")
            timestamp = obj.get("timestamp")

            if obj_type == "session_meta":
                payload = obj.get("payload", {})
                session_id = payload.get("id", session_id)
                started_at = payload.get("timestamp") or timestamp
                cwd = payload.get("cwd", cwd)
                git = payload.get("git", git)
                new_instructions = payload.get("instructions")
                if new_instructions:
                    if instructions is None:
                        instructions = new_instructions
                    instruction_repeats += 1
                continue

            if obj_type == "response_item":
                payload = obj.get("payload", {})
                payload_type = payload.get("type")

                if payload_type == "message":
                    role = payload.get("role")
                    content_text = extract_text_from_content(payload.get("content", []))
                    content_text = _normalize_user_content(role, content_text, instructions)
                    if content_text:
                        key = (str(role), content_text, timestamp)
                        seen_messages.add(key)
                        _append_message(entries, timestamp, str(role), content_text)
                    if not cwd:
                        cwd = extract_cwd_from_text(content_text) or cwd
                elif payload_type == "function_call":
                    name = payload.get("name")
                    call_id = payload.get("call_id")
                    tool_input = parse_arguments(payload.get("arguments"))
                    if call_id:
                        tool_name_by_call_id[call_id] = name
                    _append_tool_call(entries, timestamp, name, tool_input, call_id)
                elif payload_type == "function_call_output":
                    call_id = payload.get("call_id")
                    tool_name = tool_name_by_call_id.get(call_id)
                    _append_tool_output(
                        entries,
                        timestamp,
                        tool_name,
                        payload.get("output"),
                        call_id,
                    )
                elif payload_type == "custom_tool_call":
                    name = payload.get("name")
                    call_id = payload.get("call_id")
                    if call_id:
                        tool_name_by_call_id[call_id] = name
                    _append_tool_call(entries, timestamp, name, payload.get("input"), call_id)
                continue

            if obj_type == "event_msg":
                payload = obj.get("payload", {})
                payload_type = payload.get("type")

                if payload_type == "user_message":
                    content_text = payload.get("message", "")
                    content_text = _normalize_user_content("user", content_text, instructions)
                    key = ("user", content_text, timestamp)
                    if content_text and key not in seen_messages:
                        _append_message(entries, timestamp, "user", content_text)
                elif payload_type == "agent_message":
                    content_text = payload.get("message", "")
                    key = ("assistant", content_text, timestamp)
                    if content_text and key not in seen_messages:
                        _append_message(entries, timestamp, "assistant", content_text)
                continue

            # Legacy format metadata row
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

            # Legacy message/tool entries
            if obj_type == "message":
                role = obj.get("role")
                content_text = extract_text_from_content(obj.get("content", []))
                content_text = _normalize_user_content(role, content_text, instructions)
                if content_text:
                    _append_message(entries, timestamp, str(role), content_text)
                if not cwd:
                    cwd = extract_cwd_from_text(content_text) or cwd
            elif obj_type == "function_call":
                name = obj.get("name")
                call_id = obj.get("call_id")
                tool_input = parse_arguments(obj.get("arguments"))
                if call_id:
                    tool_name_by_call_id[call_id] = name
                _append_tool_call(entries, timestamp, name, tool_input, call_id)
            elif obj_type == "function_call_output":
                call_id = obj.get("call_id")
                tool_name = tool_name_by_call_id.get(call_id)
                _append_tool_output(
                    entries, timestamp, tool_name, obj.get("output"), call_id
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


def get_session_summary_from_session(session: SessionData, max_length: int = 200) -> str:
    for entry in session.entries:
        if entry.entry_type != "message" or entry.role != "user":
            continue
        text = entry.content or ""
        if not text:
            continue
        if "<environment_context>" in text:
            continue
        if text.strip().startswith("# AGENTS.md instructions"):
            continue
        if text.startswith("System instructions repeated."):
            continue
        return text[: max_length - 3] + "..." if len(text) > max_length else text
    return "(no summary)"
