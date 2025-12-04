#!/usr/bin/env python3
import os
import sys
import json
from pathlib import Path
from typing import Optional


def load_env_value(env_file: Path, key: str) -> Optional[str]:
    """Minimal .env parser: KEY=VALUE lines, ignoring comments and quotes."""
    if not env_file.exists():
        return None
    value = None
    try:
        for raw_line in env_file.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" not in line:
                continue
            k, v = line.split("=", 1)
            k = k.strip()
            v = v.strip()
            if v and ((v[0] == v[-1]) and v[0] in ('"', "'")):
                v = v[1:-1]
            if k == key:
                value = v
                break
    except Exception:
        return None
    return value


def human_mb(num_bytes: int) -> str:
    return f"{num_bytes / (1024 * 1024):.2f}"


def format_row(columns, widths):
    parts = []
    for i, col in enumerate(columns):
        text = str(col) if col is not None else ""
        parts.append(text.ljust(widths[i]))
    return "  ".join(parts)


def main():
    project_root = Path(__file__).resolve().parent
    print(project_root)
    dotenv_path = project_root / ".env"
    # Allow override via process env; otherwise read from .env
    data_path = os.getenv("DATA_PATH")
    if not data_path:
        data_path = load_env_value(dotenv_path, "DATA_PATH")

    if not data_path:
        print("ERROR: DATA_PATH is not set in environment or .env", file=sys.stderr)
        sys.exit(1)

    base = Path(data_path) / "ambilight"
    binaries_dir = base / "binaries"
    items_dir = base / "items"

    if not binaries_dir.exists():
        print(f"ERROR: binaries directory not found: {binaries_dir}", file=sys.stderr)
        sys.exit(2)

    # Collect rows
    rows = []
    total_size = 0
    for bin_file in sorted(binaries_dir.glob("*.bin")):
        item_id = bin_file.stem
        item_json = items_dir / f"{item_id}.json"
        if not item_json.exists():
            continue
        try:
            obj = json.loads(item_json.read_text(encoding="utf-8"))
            filepath = obj.get("filepath", "")
            filename = Path(filepath).name if filepath else ""
            title = obj.get("name", "")
            kind = obj.get("kind") or ("Serie" if (obj.get("type") or "").lower() in ("episode","series","season") else (obj.get("type") or "Video"))
            season = obj.get("season") if kind == "Serie" else None
            episode = obj.get("episode") if kind == "Serie" else None
            # Infer series name and S/E if missing, using path patterns
            series_name = ""
            if kind == "Serie":
                try:
                    p = Path(filepath) if filepath else None
                    # Expect .../Series/<SeriesName>/Season X/<file>
                    if p and p.parent and p.parent.parent:
                        series_name = p.parent.parent.name
                except Exception:
                    series_name = ""
                # Fallback parse SxxExx from filename
                if season is None or episode is None:
                    try:
                        import re
                        m = re.search(r"[sS](\d{1,2})[eE](\d{1,2})", filename or filepath)
                        if m:
                            if season is None:
                                season = int(m.group(1))
                            if episode is None:
                                episode = int(m.group(2))
                    except Exception:
                        pass
            size_bytes = bin_file.stat().st_size
            total_size += size_bytes
            size_mb = human_mb(size_bytes)
            # Include hidden sort metadata at end: series_name, season_num, episode_num
            rows.append([kind, season if season is not None else "", episode if episode is not None else "", title, filename, size_mb, series_name, season if season is not None else -1, episode if episode is not None else -1])
        except Exception as e:
            print(f"WARN: failed to read {item_json}: {e}", file=sys.stderr)

    # Determine column widths
    headers = ["Kind", "Season", "Episode", "Title", "Filename", "Size (MB)"]
    widths = [len(h) for h in headers]
    for row in rows:
        for i, cell in enumerate(row[:6]):
            widths[i] = max(widths[i], len(str(cell)))

    # Sort rows: group series by series_name, then season, episode; others by kind then title
    def sort_key(r):
        kind_val = r[0]
        is_series = 0 if (kind_val == "Serie") else 1
        # For series: (0, series_name, season_num, episode_num)
        if is_series == 0:
            series_name = (r[6] or "").lower()
            season_num = r[7] if isinstance(r[7], int) else -1
            episode_num = r[8] if isinstance(r[8], int) else -1
            return (0, series_name, season_num, episode_num)
        # Non-series: (1, kind_lower, title_lower)
        return (1, (kind_val or "").lower(), (r[3] or "").lower())

    rows.sort(key=sort_key)

    # Print table
    if rows:
        print()
        print(format_row(headers, widths))
        print(format_row(["-" * w for w in widths], widths))
        for row in rows:
            print(format_row(row[:6], widths))
        print()
        print(f"Total size: {human_mb(total_size)} MB across {len(rows)} file(s)")
    else:
        print("No binaries found.")


if __name__ == "__main__":
    main()
