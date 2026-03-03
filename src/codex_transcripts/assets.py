"""Static asset and theme helpers for generated transcript output."""

from __future__ import annotations

from pathlib import Path
import shutil


ASSET_ROOT = Path(__file__).parent / "templates" / "assets"
BUILTIN_THEMES: dict[str, str] = {
    "default": "themes/default.css",
    "compact": "themes/compact.css",
    "high-contrast": "themes/high-contrast.css",
}
DEFAULT_THEME = "default"


def read_asset_text(relative_path: str) -> str:
    return (ASSET_ROOT / relative_path).read_text(encoding="utf-8")


def _resolve_theme_source(theme: str | None) -> Path:
    selected = (theme or DEFAULT_THEME).strip()
    builtin = BUILTIN_THEMES.get(selected.lower())
    if builtin:
        return ASSET_ROOT / builtin

    candidate = Path(selected).expanduser()
    if candidate.exists() and candidate.is_file():
        return candidate

    valid = ", ".join(sorted(BUILTIN_THEMES.keys()))
    raise ValueError(
        f"Unknown theme `{selected}`. Use one of [{valid}] or provide a CSS file path."
    )


def ensure_output_assets(output_dir: str | Path, theme: str | None = None) -> Path:
    """Copy runtime assets and resolved theme CSS to the target output directory."""
    output_dir = Path(output_dir)
    assets_dir = output_dir / "assets"
    assets_dir.mkdir(parents=True, exist_ok=True)

    static_files = (
        "base.css",
        "runtime.js",
        "search.js",
        "archive-filters.js",
    )
    for filename in static_files:
        shutil.copy2(ASSET_ROOT / filename, assets_dir / filename)

    theme_source = _resolve_theme_source(theme)
    shutil.copy2(theme_source, assets_dir / "theme.css")

    return assets_dir
