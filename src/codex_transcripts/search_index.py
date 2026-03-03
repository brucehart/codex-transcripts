"""Static search index generation helpers."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Sequence


SEARCH_INDEX_SCHEMA_VERSION = 2
DEFAULT_SHARD_THRESHOLD = 4000
DEFAULT_SHARD_SIZE = 1500


def _chunked(items: Sequence[dict[str, Any]], chunk_size: int):
    for offset in range(0, len(items), chunk_size):
        yield offset // chunk_size, items[offset : offset + chunk_size]


def build_search_index_payload(
    *,
    total_pages: int,
    items: Sequence[dict[str, Any]],
    shard_threshold: int = DEFAULT_SHARD_THRESHOLD,
    shard_size: int = DEFAULT_SHARD_SIZE,
) -> tuple[dict[str, Any], list[tuple[str, list[dict[str, Any]]]]]:
    item_list = list(items)
    base: dict[str, Any] = {
        "schema_version": SEARCH_INDEX_SCHEMA_VERSION,
        "total_pages": total_pages,
        "item_count": len(item_list),
    }

    if len(item_list) <= shard_threshold:
        payload = {
            **base,
            "sharded": False,
            "items": item_list,
        }
        return payload, []

    shards: list[tuple[str, list[dict[str, Any]]]] = []
    shard_manifest: list[dict[str, Any]] = []
    for shard_num, chunk in _chunked(item_list, max(1, shard_size)):
        filename = f"search-index-{shard_num:04d}.js"
        shards.append((filename, chunk))
        shard_manifest.append(
            {
                "file": filename,
                "count": len(chunk),
            }
        )

    payload = {
        **base,
        "sharded": True,
        "shards": shard_manifest,
    }
    return payload, shards


def write_search_index(
    output_dir: str | Path,
    *,
    total_pages: int,
    items: Sequence[dict[str, Any]],
    shard_threshold: int = DEFAULT_SHARD_THRESHOLD,
    shard_size: int = DEFAULT_SHARD_SIZE,
) -> dict[str, Any]:
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    for stale_file in output_dir.glob("search-index-*.js"):
        stale_file.unlink()

    payload, shards = build_search_index_payload(
        total_pages=total_pages,
        items=items,
        shard_threshold=shard_threshold,
        shard_size=shard_size,
    )

    (output_dir / "search-index.json").write_text(
        json.dumps(payload, ensure_ascii=False),
        encoding="utf-8",
    )

    if payload.get("sharded"):
        loader = f"window.__SEARCH_INDEX_MANIFEST__ = {json.dumps(payload, ensure_ascii=False)};"
        (output_dir / "search-index.js").write_text(loader, encoding="utf-8")
        for filename, chunk in shards:
            shard_payload = (
                "window.__SEARCH_INDEX_SHARDS__ = window.__SEARCH_INDEX_SHARDS__ || {};"
                f"window.__SEARCH_INDEX_SHARDS__[{json.dumps(filename)}] = "
                f"{json.dumps(chunk, ensure_ascii=False)};"
            )
            (output_dir / filename).write_text(shard_payload, encoding="utf-8")
    else:
        loader = f"window.__SEARCH_INDEX_PAYLOAD__ = {json.dumps(payload, ensure_ascii=False)};"
        (output_dir / "search-index.js").write_text(loader, encoding="utf-8")

    return payload
