"""Write the deterministic Kei tool manifest: ``uv run python -m app.triage``."""

from pathlib import Path

from app.triage.tools import export_tool_manifest

MANIFEST_PATH = Path(__file__).resolve().parents[2] / "kei" / "tool-manifest.json"

if __name__ == "__main__":
    MANIFEST_PATH.parent.mkdir(parents=True, exist_ok=True)
    MANIFEST_PATH.write_text(export_tool_manifest(), encoding="utf-8")
    print(f"wrote {MANIFEST_PATH}")
