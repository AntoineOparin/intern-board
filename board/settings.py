"""Secrets in the project's .env file (never sent to the browser, never committed).

Real environment variables win over the file, so `PROSPEO_API_KEY=... ./run.sh` also works.
"""

import os
import re
import threading
from pathlib import Path

ENV_PATH = Path(__file__).resolve().parent.parent / ".env"
_lock = threading.Lock()
_KEY_RE = re.compile(r"^\s*([A-Z][A-Z0-9_]*)\s*=\s*(.*?)\s*$")


def _read() -> dict[str, str]:
    values = {}
    try:
        lines = ENV_PATH.read_text().splitlines()
    except FileNotFoundError:
        return values
    for line in lines:
        if line.lstrip().startswith("#"):
            continue
        if m := _KEY_RE.match(line):
            values[m.group(1)] = m.group(2).strip("'\"")
    return values


def get(name: str) -> str | None:
    return os.environ.get(name) or _read().get(name) or None


def set(name: str, value: str | None) -> None:
    """Set (or with None, remove) one variable in .env, keeping other lines and comments."""
    with _lock:
        try:
            lines = ENV_PATH.read_text().splitlines()
        except FileNotFoundError:
            lines = ["# Local secrets for Intern Board. Never commit this file."]
        lines = [l for l in lines if not ((m := _KEY_RE.match(l)) and m.group(1) == name)]
        if value is not None:
            lines.append(f"{name}={value}")
        # Create with owner-only permissions before writing the secret.
        fd = os.open(ENV_PATH, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w") as f:
            f.write("\n".join(lines) + "\n")
        os.chmod(ENV_PATH, 0o600)
