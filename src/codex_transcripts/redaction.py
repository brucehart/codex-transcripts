"""Redaction helpers for transcript rendering/export pipelines."""

from __future__ import annotations

from dataclasses import replace
import re
from typing import Any, Sequence

from .parser import Entry, SessionData


REDACTION_PLACEHOLDER = "[REDACTED]"
DEFAULT_REDACTION_PRESETS = ("emails", "tokens")
REDACTION_PRESETS: dict[str, tuple[str, ...]] = {
    "emails": (
        r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}",
    ),
    "tokens": (
        r"\b(?:ghp|github_pat)_[A-Za-z0-9_]{20,}\b",
        r"\bsk-[A-Za-z0-9]{20,}\b",
        r"\bAKIA[0-9A-Z]{16}\b",
        r"\b(?:xox[pbar]-[A-Za-z0-9-]{10,})\b",
    ),
    "paths": (
        r"\b[A-Za-z]:\\(?:[^\\\s\"']+\\)+[^\\\s\"']+\b",
        r"(?<![:\w])\/(?:[A-Za-z0-9._-]+\/){1,}[A-Za-z0-9._-]+",
        r"~\/(?:[A-Za-z0-9._-]+\/){1,}[A-Za-z0-9._-]+",
    ),
    "hostnames": (
        r"\b(?:[A-Za-z0-9-]+\.)+[A-Za-z]{2,}\b",
    ),
}

# Legacy alias for compatibility with previous CLI docs/usage.
REDACTION_PRESETS["basic"] = (
    *REDACTION_PRESETS["emails"],
    *REDACTION_PRESETS["tokens"],
)


def available_redaction_presets() -> tuple[str, ...]:
    return tuple(sorted(REDACTION_PRESETS.keys()))


def resolve_redaction_patterns(
    redact_enabled: bool,
    redact_presets: Sequence[str],
    redact_patterns: Sequence[str],
) -> tuple[str, ...]:
    resolved: list[str] = []
    seen: set[str] = set()

    selected_presets = [preset.lower() for preset in redact_presets]
    if redact_enabled and not selected_presets:
        selected_presets = list(DEFAULT_REDACTION_PRESETS)

    for preset in selected_presets:
        for pattern in REDACTION_PRESETS.get(preset, ()):
            if pattern not in seen:
                seen.add(pattern)
                resolved.append(pattern)

    for pattern in redact_patterns:
        if pattern not in seen:
            seen.add(pattern)
            resolved.append(pattern)

    return tuple(resolved)


def compile_redaction_patterns(patterns: Sequence[str]) -> list[re.Pattern[str]]:
    compiled: list[re.Pattern[str]] = []
    for pattern in patterns:
        try:
            compiled.append(re.compile(pattern))
        except re.error as exc:
            raise ValueError(f"Invalid redaction pattern `{pattern}`: {exc}") from exc
    return compiled


def redact_text(text: str, patterns: Sequence[re.Pattern[str]]) -> str:
    redacted = text
    for pattern in patterns:
        redacted = pattern.sub(REDACTION_PLACEHOLDER, redacted)
    return redacted


def redact_value(value: Any, patterns: Sequence[re.Pattern[str]]) -> Any:
    if isinstance(value, str):
        return redact_text(value, patterns)
    if isinstance(value, list):
        return [redact_value(item, patterns) for item in value]
    if isinstance(value, dict):
        return {key: redact_value(item, patterns) for key, item in value.items()}
    return value


def redact_session_data(
    session: SessionData,
    pattern_strings: Sequence[str],
) -> SessionData:
    if not pattern_strings:
        return session

    compiled = compile_redaction_patterns(pattern_strings)
    redacted_entries: list[Entry] = []
    for entry in session.entries:
        redacted_entries.append(
            replace(
                entry,
                content=redact_text(entry.content, compiled) if entry.content else entry.content,
                tool_input=redact_value(entry.tool_input, compiled),
                tool_output=redact_value(entry.tool_output, compiled),
            )
        )

    return replace(
        session,
        cwd=redact_text(session.cwd, compiled) if session.cwd else session.cwd,
        instructions=(
            redact_text(session.instructions, compiled)
            if session.instructions
            else session.instructions
        ),
        entries=redacted_entries,
    )
