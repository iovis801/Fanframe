"""Per-user GUI preferences (custom fan names).

Unprivileged and entirely client-side: stored as JSON under the XDG config dir
(default ``~/.config/fanframe/labels.json``). Keys are sysfs fan names
("fan1"), values are the user's chosen display names.
"""
from __future__ import annotations

import json
import os

APP_NAME = "fanframe"
LABELS_FILE = "labels.json"


def config_dir() -> str:
    base = os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config")
    return os.path.join(base, APP_NAME)


def labels_path() -> str:
    return os.path.join(config_dir(), LABELS_FILE)


def load_labels(path: str | None = None) -> dict[str, str]:
    """Return saved fan names, or an empty mapping if missing/unreadable."""
    target = path or labels_path()
    try:
        with open(target, "r") as handle:
            data = json.load(handle)
    except (OSError, ValueError):
        return {}
    if not isinstance(data, dict):
        return {}
    return {str(key): str(value) for key, value in data.items()}


def save_labels(labels: dict[str, str], path: str | None = None) -> None:
    """Persist fan names atomically (write to a temp file, then replace)."""
    target = path or labels_path()
    os.makedirs(os.path.dirname(target), exist_ok=True)
    tmp = target + ".tmp"
    with open(tmp, "w") as handle:
        json.dump(labels, handle, indent=2, sort_keys=True)
    os.replace(tmp, target)
