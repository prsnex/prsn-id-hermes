"""A short fingerprint of the plugin's code, to prove which code a running Hermes has loaded.

Hermes keeps the code a plugin host loaded until the host restarts, so new files on disk are not
proof of what runs. The plugin computes this when it is imported and shows it in /prsn about.
The same function run over a checkout gives the value to expect.

    python3 fingerprint.py [folder]      prints the fingerprint of the folder (default: here)

Standard library only, with no relative imports, so it runs on its own.
"""

from __future__ import annotations

import hashlib
import sys
from pathlib import Path

# Every file that is the plugin's behaviour. Tests, the README and the licence are not.
CODE_FILES = (
    "__init__.py",
    "dashboard/manifest.json",
    "dashboard/plugin_api.py",
    "desktop/plugin.js",
    "fingerprint.py",
    "gateway_tools.json",
    "plugin.yaml",
    "prsn_gateway.py",
    "words.py",
)


def code_fingerprint(root: Path) -> str:
    """Twelve hex characters over each code file's path and bytes, in a fixed order."""
    digest = hashlib.sha256()
    for name in CODE_FILES:
        digest.update(name.encode("utf-8") + b"\0")
        path = root / name
        digest.update(path.read_bytes() if path.is_file() else b"<missing>")
        digest.update(b"\0")
    return digest.hexdigest()[:12]


if __name__ == "__main__":
    folder = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).resolve().parent
    print(code_fingerprint(folder))
