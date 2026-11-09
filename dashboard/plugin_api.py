"""The one answer the Desktop status item asks for: this agent's PRSN ID state.

It only reads. It returns the state the agent half last wrote. When that is missing or more than
fifteen minutes old, it reads the state live through PRSN Connect, the same way the agent half
does. Nothing here seals, and no token is read or returned.

The PRSN's name comes from the plugin's setting, read afresh each time, and else from the last
record. A live read starts PRSN Connect's own prsn-gateway-mcp for this process's life.
"""

from __future__ import annotations

import importlib.util
import json
import sys
import threading
import time
from pathlib import Path
from typing import Callable, Optional

from fastapi import APIRouter

router = APIRouter()
_ROOT = Path(__file__).resolve().parent.parent
PLUGIN_ID = "prsn-id"
FRESH_SECONDS = 900
LIVE_TIMEOUT = 6.0
ANSWER_KEYS = ("word", "line", "verified", "checked_at")


def _load():
    """Import the plugin package by path, whatever name Hermes gave it."""
    name = "prsn_id_plugin"
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(
        name, _ROOT / "__init__.py", submodule_search_locations=[str(_ROOT)])
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def setting_prsn_name() -> Optional[str]:
    """The prsn_name setting as Hermes's own settings page reads it, each time."""
    try:
        from hermes_cli.plugins_settings import plugin_settings_fields
        for field in plugin_settings_fields(PLUGIN_ID, _ROOT):
            if field.get("key") == "prsn_name":
                value = str(field.get("value") or "").strip()
                return value or None
    except Exception:
        return None
    return None


class _Settings:
    """The dashboard has no plugin ctx; it answers prsn_name from the name chosen for this read."""

    def __init__(self, prsn_name: Optional[str]):
        self.prsn_name = prsn_name

    def get_config(self, key, default=None):
        return self.prsn_name if key == "prsn_name" and self.prsn_name else default


_runtime = None
_runtime_name: Optional[str] = None
_lock = threading.Lock()  # two overlapping polls must not both build a runtime (Gwen)


def _read_record(folder: Path):
    try:
        return json.loads((folder / "status.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _answer(record) -> dict:
    return {k: (record or {}).get(k) for k in ANSWER_KEYS}


def status_answer(folder: Optional[Path] = None, now: Optional[float] = None,
                  setting: Callable[[], Optional[str]] = setting_prsn_name,
                  discovery: Optional[Path] = None) -> dict:
    global _runtime, _runtime_name
    plugin = _load()
    folder = folder or plugin.data_dir()
    now = now or time.time()
    record = _read_record(folder)
    if record and now - float(record.get("checked_at") or 0) < FRESH_SECONDS:
        return _answer(record)

    with _lock:
        record = _read_record(folder)  # another poll may have just refreshed it
        if record and now - float(record.get("checked_at") or 0) < FRESH_SECONDS:
            return _answer(record)
        name = setting() or (record or {}).get("name") or None
        if _runtime is None or name != _runtime_name:
            if _runtime is not None:
                _runtime.gateway.close()
            settings = _Settings(name)
            gateway = plugin.pg.Gateway(prsn_name=lambda: settings.prsn_name, path=discovery)
            _runtime = plugin.Runtime(settings, gateway=gateway, status_folder=folder)
            _runtime_name = name
        _runtime.state(timeout=LIVE_TIMEOUT)  # writes status.json
        return _answer(_read_record(folder))


@router.get("/status")
def status():
    # A plain def, so Starlette runs it in its threadpool, which carries the request's context.
    # An async def would block Hermes's own web server for the live read's length when this
    # route runs in-process, as it does for a launch profile (Gwen).
    return status_answer()
