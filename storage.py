"""File-based persistence for Hermit Watch state, incidents, and digests."""

from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path

DATA_DIR = Path(__file__).parent / "data"


def ensure_data_dirs():
    """Create data directories if they don't exist."""
    for sub in ("", "incidents", "digests"):
        (DATA_DIR / sub).mkdir(parents=True, exist_ok=True)


# ---------------------------------------------------------------------------
# Current state
# ---------------------------------------------------------------------------

def write_current_state(state: dict) -> None:
    """Atomically write data/current-state.json."""
    ensure_data_dirs()
    path = DATA_DIR / "current-state.json"
    _atomic_write_json(path, state)


def read_current_state() -> dict | None:
    """Read data/current-state.json, or None if missing."""
    path = DATA_DIR / "current-state.json"
    return _read_json(path)


# ---------------------------------------------------------------------------
# Incidents
# ---------------------------------------------------------------------------

def write_incident(timestamp: str, data: dict) -> None:
    """Write data/incidents/{timestamp}.json."""
    ensure_data_dirs()
    path = DATA_DIR / "incidents" / f"{_safe_filename(timestamp)}.json"
    _atomic_write_json(path, data)


def read_incident(timestamp: str) -> dict | None:
    """Read a specific incident snapshot."""
    path = DATA_DIR / "incidents" / f"{_safe_filename(timestamp)}.json"
    return _read_json(path)


def list_incidents() -> list[str]:
    """Return incident timestamps, newest first."""
    return _list_timestamps(DATA_DIR / "incidents", ".json")


# ---------------------------------------------------------------------------
# Digests
# ---------------------------------------------------------------------------

def write_digest(timestamp: str, content: str, obs_type: str = "scheduled") -> None:
    """Write data/digests/{timestamp}.json."""
    ensure_data_dirs()
    path = DATA_DIR / "digests" / f"{_safe_filename(timestamp)}.json"
    data = {"generated_at": timestamp, "type": obs_type, "content": content}
    _atomic_write_json(path, data)


def read_digest(timestamp: str) -> dict | None:
    """Read a digest as {generated_at, type, content}."""
    # Try JSON first, fall back to legacy .md files
    json_path = DATA_DIR / "digests" / f"{_safe_filename(timestamp)}.json"
    if json_path.exists():
        return _read_json(json_path)
    md_path = DATA_DIR / "digests" / f"{_safe_filename(timestamp)}.md"
    if md_path.exists():
        content = md_path.read_text(encoding="utf-8")
        return {"generated_at": timestamp, "type": "scheduled", "content": content}
    return None


def read_latest_digest() -> dict | None:
    """Read the most recent digest."""
    timestamps = list_digests()
    if not timestamps:
        return None
    return read_digest(timestamps[0])


def list_digests() -> list[str]:
    """Return digest timestamps, newest first."""
    # Support both .json and legacy .md files
    dirpath = DATA_DIR / "digests"
    if not dirpath.exists():
        return []
    names = []
    for f in dirpath.iterdir():
        if f.suffix in (".json", ".md"):
            names.append(f.stem.replace(".", ":"))
    return sorted(set(names), reverse=True)


# ---------------------------------------------------------------------------
# Cleanup
# ---------------------------------------------------------------------------

def cleanup_old_files(retention_days: int) -> None:
    """Delete incident and digest files older than retention_days (legacy single-value API)."""
    cleanup(incident_retention_days=retention_days, digest_retention_days=retention_days)


def cleanup(incident_retention_days: int = 1, digest_retention_days: int = 7) -> None:
    """Delete incident and digest files with separate retention periods."""
    _cleanup_dir(DATA_DIR / "incidents", incident_retention_days)
    _cleanup_dir(DATA_DIR / "digests", digest_retention_days)


def _cleanup_dir(dirpath: Path, retention_days: int) -> None:
    """Delete files in a directory older than retention_days."""
    if retention_days <= 0 or not dirpath.exists():
        return
    cutoff = datetime.now(timezone.utc).timestamp() - (retention_days * 86400)
    for f in dirpath.iterdir():
        ts_str = f.stem.replace(".", ":")  # unsanitize dots back to colons
        try:
            file_dt = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
            if file_dt.timestamp() < cutoff:
                f.unlink()
        except (ValueError, OSError):
            pass


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _safe_filename(timestamp: str) -> str:
    """Sanitize timestamp for use as filename (replace colons with dots)."""
    return timestamp.replace(":", ".")


def _atomic_write_json(path: Path, data: dict) -> None:
    """Write JSON atomically via temp file + rename."""
    fd, tmp = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(data, f, indent=2)
            f.write("\n")
        os.replace(tmp, path)
    except Exception:
        os.unlink(tmp)
        raise


def _atomic_write_text(path: Path, content: str) -> None:
    """Write text atomically via temp file + rename."""
    fd, tmp = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as f:
            f.write(content)
        os.replace(tmp, path)
    except Exception:
        os.unlink(tmp)
        raise


def _read_json(path: Path) -> dict | None:
    """Read a JSON file, returning None if missing."""
    if not path.exists():
        return None
    with open(path) as f:
        return json.load(f)


def _list_timestamps(dirpath: Path, suffix: str) -> list[str]:
    """List filenames as timestamps, newest first."""
    if not dirpath.exists():
        return []
    names = []
    for f in dirpath.iterdir():
        if f.suffix == suffix:
            # Restore colons from dot-sanitized filename
            names.append(f.stem.replace(".", ":"))
    return sorted(names, reverse=True)
