import json

from codex_transcripts.search_index import write_search_index


def test_write_search_index_writes_shards_when_threshold_exceeded(tmp_path):
    items = [
        {
            "page": "page-001.html",
            "anchor": f"msg-{i}",
            "role": "User",
            "timestamp": "2025-01-01T00:00:00Z",
            "text": f"item {i}",
        }
        for i in range(7)
    ]

    payload = write_search_index(
        tmp_path,
        total_pages=2,
        items=items,
        shard_threshold=3,
        shard_size=2,
    )

    assert payload["sharded"] is True
    assert (tmp_path / "search-index.js").exists()
    assert (tmp_path / "search-index-0000.js").exists()
    assert (tmp_path / "search-index-0001.js").exists()

    json_payload = json.loads((tmp_path / "search-index.json").read_text(encoding="utf-8"))
    assert json_payload["sharded"] is True
    assert "items" not in json_payload
