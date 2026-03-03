"""Session diff report generation."""

from __future__ import annotations

from difflib import SequenceMatcher
import json
from pathlib import Path
from typing import Any

from .assets import ensure_output_assets
from .parser import SessionData
from .renderer import build_session_meta, get_template


def _normalize_tool_input(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    return json.dumps(value, sort_keys=True, ensure_ascii=False)


def _user_prompts(session: SessionData) -> list[str]:
    prompts: list[str] = []
    for entry in session.entries:
        if entry.entry_type == "message" and entry.role == "user" and entry.content:
            prompts.append(entry.content.strip())
    return prompts


def _tool_calls(session: SessionData) -> list[str]:
    calls: list[str] = []
    for entry in session.entries:
        if entry.entry_type != "tool_call":
            continue
        tool_name = (entry.tool_name or "unknown").strip()
        calls.append(f"{tool_name} {_normalize_tool_input(entry.tool_input)}".strip())
    return calls


def _diff_blocks(left: list[str], right: list[str]) -> list[dict[str, Any]]:
    matcher = SequenceMatcher(a=left, b=right)
    blocks: list[dict[str, Any]] = []
    for tag, a0, a1, b0, b1 in matcher.get_opcodes():
        if tag == "equal":
            continue
        blocks.append(
            {
                "tag": tag,
                "left_items": left[a0:a1],
                "right_items": right[b0:b1],
                "left_range": f"{a0 + 1}-{a1}",
                "right_range": f"{b0 + 1}-{b1}",
            }
        )
    return blocks


def build_session_diff(session_a: SessionData, session_b: SessionData) -> dict[str, Any]:
    prompts_a = _user_prompts(session_a)
    prompts_b = _user_prompts(session_b)
    tools_a = _tool_calls(session_a)
    tools_b = _tool_calls(session_b)

    prompt_blocks = _diff_blocks(prompts_a, prompts_b)
    tool_blocks = _diff_blocks(tools_a, tools_b)

    return {
        "summary": {
            "prompt_count_a": len(prompts_a),
            "prompt_count_b": len(prompts_b),
            "tool_call_count_a": len(tools_a),
            "tool_call_count_b": len(tools_b),
            "prompt_changes": len(prompt_blocks),
            "tool_call_changes": len(tool_blocks),
        },
        "prompt_blocks": prompt_blocks,
        "tool_blocks": tool_blocks,
    }


def generate_diff_report(
    session_a: SessionData,
    session_b: SessionData,
    output_dir: str | Path,
    *,
    source_a: str | Path | None = None,
    source_b: str | Path | None = None,
    theme: str | None = None,
) -> tuple[Path, dict[str, Any]]:
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    ensure_output_assets(output_dir, theme=theme)

    diff_data = build_session_diff(session_a, session_b)
    diff_data["session_a"] = {
        "source": str(source_a) if source_a else str(session_a.source_path),
        "meta": build_session_meta(session_a),
    }
    diff_data["session_b"] = {
        "source": str(source_b) if source_b else str(session_b.source_path),
        "meta": build_session_meta(session_b),
    }

    template = get_template("diff.html")
    html = template.render(diff=diff_data)
    index_path = output_dir / "index.html"
    index_path.write_text(html, encoding="utf-8")

    (output_dir / "diff.json").write_text(
        json.dumps(diff_data, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    return index_path, diff_data
