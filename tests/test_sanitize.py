from pathlib import Path

from codex_transcripts import generate_html


def test_generate_html_sanitizes_transcript_content(tmp_path):
    session_file = tmp_path / "session.jsonl"
    session_file.write_text(
        "\n".join(
            [
                '{"timestamp":"2025-01-01T00:00:00Z","type":"session_meta","payload":{"id":"abc123","timestamp":"2025-01-01T00:00:00Z"}}',
                '{"timestamp":"2025-01-01T00:00:01Z","type":"response_item","payload":{"type":"message","role":"user","content":[{"type":"input_text","text":"Hello <script>alert(1)</script> [x](javascript:alert(2)) <img src=x onerror=alert(3)>"}]}}',
            ]
        ),
        encoding="utf-8",
    )

    output_dir = tmp_path / "output"
    index_path = generate_html(session_file, output_dir)
    page_content = (output_dir / "page-001.html").read_text(encoding="utf-8")
    index_content = index_path.read_text(encoding="utf-8")

    for content in (page_content, index_content):
        assert "<script" not in content
        assert "javascript:" not in content
        assert "onerror" not in content
