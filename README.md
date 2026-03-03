# codex-transcripts

Convert Codex session JSONL files from `~/.codex/` into clean, mobile-friendly HTML transcripts with pagination.

Inspired by https://github.com/simonw/claude-code-transcripts.

## Installation

Use `uv` to install the tool:

```bash
uv tool install codex-transcripts
```

Or run without installing:

```bash
uvx codex-transcripts --help
```

## Usage

This tool supports five commands:

- `local` (default) - pick from recent local sessions in `~/.codex/sessions`
- `json` - convert a specific JSONL file
- `all` - convert all sessions into a browsable archive
- `diff` - compare prompts/tool calls between two sessions
- `serve` - serve generated output over local HTTP

### Convert a recent local session

```bash
codex-transcripts
# or explicitly
codex-transcripts local
```

### Create a GitHub gist

```bash
codex-transcripts local --gist
codex-transcripts json ~/.codex/sessions/2025/12/24/rollout-...jsonl --gist-public
```

This prints a GitHub gist URL plus a `gistpreview.github.io` link that renders the HTML.
The gist uses a descriptive HTML filename based on the session details.

### Convert a specific file

```bash
codex-transcripts json ~/.codex/sessions/2025/12/24/rollout-...jsonl -o ./output
```

### Convert all sessions

```bash
codex-transcripts all -o ./codex-archive
```

### Diff two sessions from the same project

```bash
codex-transcripts diff ~/.codex/sessions/.../run-a.jsonl ~/.codex/sessions/.../run-b.jsonl -o ./diff-report
```

### Output options

`local` and `json` support:

- `-o, --output DIRECTORY` - output directory (default: temporary directory for `local`/`json`)
- `-a, --output-auto` - auto-name a subdirectory based on the session filename
- `--open` - open the generated `index.html` in your default browser
- `--json` - include the source JSONL file in the output directory
- `--search-mode inline|external|auto` - control whether search data is embedded inline or loaded from `search-index.json`
- `--theme default|compact|high-contrast|PATH.css` - use a built-in theme or custom CSS file
- `--markdown` - also export `transcript.md`
- `--txt` - also export `transcript.txt`
- `--pdf` - also export `transcript.pdf` (requires optional `weasyprint`)
- `--stats-json` - write `stats.json`
- `--redact` - enable default redaction presets (`emails`, `tokens`)
- `--redact-preset PRESET` - apply preset redaction patterns (`emails`, `tokens`, `paths`, `hostnames`; repeatable)
- `--redact-pattern REGEX` - apply custom regex redaction (repeatable)
- `--strict-rows` - fail on malformed JSON rows instead of skipping them with warnings
- `--gist` - create a GitHub gist from the generated HTML and output a preview URL (requires the `gh` CLI)
- `--gist-public` - create a public gist instead of a secret gist

Generated outputs include static search artifacts (`search-index.json`, `search-index.js`, and shards when needed), so search works with `file://` and scales better for large transcripts.

### Archive reliability and scale options

For large archives, `all` additionally supports:

- `--skip-bad-files / --no-skip-bad-files` - skip malformed session files during scan (default: skip)
- `--strict` - fail immediately on parse/render errors
- `--strict-rows` - fail parsing individual session files when malformed JSON rows are encountered
- `--incremental` - skip unchanged sessions using a cache file in the archive output directory
- `--workers N` - parallelize session rendering
- `--theme ...`, `--markdown`, `--txt`, `--pdf`, `--stats-json`
- `--from-date YYYY-MM-DD` / `--to-date YYYY-MM-DD`
- `--tool TOOL_NAME` (repeatable)
- `--error-only`
- `--repo PATTERN`
- `--branch PATTERN`

Archive and project index pages include built-in filtering controls for date range, tool name, error-only sessions, repo, and branch.

### Serve local output over HTTP

For reliable search and navigation in browser environments that restrict `file://` access:

```bash
codex-transcripts serve ./codex-archive -p 8000
```

Then open `http://127.0.0.1:8000/`.

If no browser is available, the CLI prints a `file://` URL you can open locally (useful for WSL2).

## Development

Run tests with:

```bash
uv run python -m pytest
```
