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

This tool supports three commands:

- `local` (default) - pick from recent local sessions in `~/.codex/sessions`
- `json` - convert a specific JSONL file
- `all` - convert all sessions into a browsable archive

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

### Output options

All commands support:

- `-o, --output DIRECTORY` - output directory (default: temporary directory for `local`/`json`)
- `-a, --output-auto` - auto-name a subdirectory based on the session filename
- `--open` - open the generated `index.html` in your default browser
- `--json` - include the source JSONL file in the output directory
- `--gist` - create a GitHub gist from the generated HTML and output a preview URL (requires the `gh` CLI)
- `--gist-public` - create a public gist instead of a secret gist

If no browser is available, the CLI prints a `file://` URL you can open locally (useful for WSL2).

## Development

Run tests with:

```bash
uv run pytest
```
