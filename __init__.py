"""PRSN ID for Hermes.

PRSN ID binds an AI agent to a signing key on its device and to a human guardian who answers for
it, so that anyone can check it is bound and current. This plugin connects a Hermes agent to its
PRSN ID through PRSN Connect, the desktop app that holds the key.

It offers five of PRSN Connect's identity tools, two that read and three that seal. Hermes asks
the human before every Seal. At the first turn, and again after a compaction, it tells the agent
who it is, read live. It looks up no other agent. ``/prsn`` shows the state.
"""

from __future__ import annotations

import json
import logging
import threading
import time
from collections import OrderedDict
from pathlib import Path
from typing import Any, Optional

from . import prsn_gateway as pg
from . import words
from .fingerprint import code_fingerprint

logger = logging.getLogger(__name__)

PLUGIN_ID = "prsn-id"
STATUS_FILE = "status.json"
SERVER_LOG_FILE = "server.log"
_ROOT = Path(__file__).resolve().parent

# Computed when this code is imported, so it names the code this process loaded.
CODE_FINGERPRINT = code_fingerprint(_ROOT)


def plugin_version() -> str:
    for line in (_ROOT / "plugin.yaml").read_text(encoding="utf-8").splitlines():
        if line.startswith("version:"):
            return line.split(":", 1)[1].strip().strip('"')
    return "unknown"


def data_dir() -> Path:
    """This plugin's own data folder in the profile, as Hermes gives it."""
    try:
        from plugins.plugin_storage import plugin_data_dir
        return Path(plugin_data_dir(PLUGIN_ID))
    except Exception:
        from hermes_constants import get_hermes_home
        folder = Path(get_hermes_home()) / "plugin-data" / PLUGIN_ID
        folder.mkdir(parents=True, exist_ok=True)
        return folder


def write_status(state: dict[str, Any], folder: Optional[Path] = None) -> None:
    """Keep the last state read, for the Desktop status item. Never a token: a name, a yes or
    no, a heartbeat time, and words."""
    error = state.get("error")
    record = {
        "name": state.get("name"),
        "verified": state.get("verified"),
        "last_beat": state.get("last_beat"),
        "error_code": error.code if isinstance(error, pg.GatewayError) else None,
        "error_words": words.for_error(error) if isinstance(error, pg.GatewayError) else None,
        "checked_at": time.time(),
    }
    record["word"] = words.status_word(record)
    record["line"] = words.status_line(record)
    try:
        folder = folder or data_dir()
        tmp = folder / (STATUS_FILE + ".tmp")
        tmp.write_text(json.dumps(record), encoding="utf-8")
        tmp.replace(folder / STATUS_FILE)
    except Exception:  # the status item is a convenience; a failed write never breaks a turn
        logger.debug("prsn-id: status not written", exc_info=True)

TOOLSET = "prsn_id"
EMOJI = "🪪"

# Hermes tool name -> PRSN Connect's gateway tool. Nothing else is offered.
TOOLS = {
    "prsn_id_profile": "get_profile",
    "prsn_id_status": "get_gateway_status",
    "prsn_id_seal_message": "seal_message",
    "prsn_id_seal_email": "seal_email",
    "prsn_id_seal_file": "seal_file",
}
SEAL_TOOLS = {"prsn_id_seal_message", "prsn_id_seal_email", "prsn_id_seal_file"}

# A hook callback past 30 seconds is skipped by Hermes; the turn's reads stay well inside it.
HOOK_BUDGET_SECONDS = 20.0
HOOK_CALL_TIMEOUT = 6.0
MAX_SESSIONS_REMEMBERED = 200


def _load_tool_schemas() -> dict[str, dict[str, Any]]:
    """The five tools' input schemas as PRSN Connect's server gave them, with plain descriptions."""
    data = json.loads(Path(__file__).with_name("gateway_tools.json").read_text(encoding="utf-8"))
    schemas = {}
    for hermes_name, gateway_name in TOOLS.items():
        tool = data["tools"][gateway_name]
        parameters = json.loads(json.dumps(
            {k: v for k, v in tool["inputSchema"].items() if k not in ("$schema", "title")}))
        parameters.setdefault("type", "object")
        parameters.setdefault("properties", {})
        for (tool_name, param), text in words.PARAMETER_DESCRIPTIONS.items():
            if tool_name == gateway_name and param in parameters["properties"]:
                parameters["properties"][param]["description"] = text
        schemas[hermes_name] = {"name": hermes_name,
                                "description": words.TOOL_DESCRIPTIONS[gateway_name],
                                "parameters": parameters}
    return schemas


class _Sessions:
    """Per-session memory: whether the identity line is due."""

    def __init__(self) -> None:
        self._data: OrderedDict[str, dict[str, Any]] = OrderedDict()
        self._lock = threading.Lock()

    def get(self, session_id: str) -> dict[str, Any]:
        with self._lock:
            state = self._data.get(session_id)
            if state is None:
                state = {"identity_due": True}
                self._data[session_id] = state
                while len(self._data) > MAX_SESSIONS_REMEMBERED:
                    self._data.popitem(last=False)
            else:
                self._data.move_to_end(session_id)
            return state

    def mark_identity_due(self, session_id: str) -> None:
        self.get(session_id)["identity_due"] = True


class Runtime:
    """One per profile: the gateway, the session memory, and the plugin's settings."""

    def __init__(self, ctx: Any, gateway: Optional[pg.Gateway] = None,
                 status_folder: Optional[Path] = None, record_status: bool = True):
        self.ctx = ctx
        self.gateway = gateway or pg.Gateway(prsn_name=self.prsn_name, server_log=self.server_log_path)
        self.sessions = _Sessions()
        self.status_folder = status_folder
        self.record_status = record_status

    def setting(self, key: str, default: Any = None) -> Any:
        try:
            return self.ctx.get_config(key, default=default)
        except Exception:  # a settings read must never break a turn
            return default

    def prsn_name(self) -> Optional[str]:
        value = (self.setting("prsn_name", "") or "").strip()
        return value or None

    def server_log_path(self) -> Optional[Path]:
        """PRSN Connect's server log, kept only when the server_log setting is on."""
        if not self.setting("server_log", False):
            return None
        try:
            return (self.status_folder or data_dir()) / SERVER_LOG_FILE
        except Exception:
            return None

    def current_prsn(self) -> Optional[str]:
        entry = self.gateway.entry
        return entry.ens_name if entry else self.prsn_name()

    # -- reads -------------------------------------------------------------------------------

    def state(self, timeout: float = pg.CALL_TIMEOUT_SECONDS,
              deadline: Optional[float] = None) -> dict[str, Any]:
        """Name, verified or not, and the heartbeat, read live in one call. Errors become a code.

        The profile carries this PRSN's own `verified`, by the platform's rule (v0.2.1, BUG-229).
        A platform without the field gives None (unknown), never a guess. *deadline* is kept for
        callers; one read needs no budget of its own.
        """
        try:
            profile = self.gateway.call("get_profile", timeout=timeout) or {}
            identity = profile.get("identity") or {}
            hwbeat = profile.get("hwbeat") or {}
            raw = identity.get("verified")
            state = {"name": identity.get("ensName"),
                     "verified": raw if isinstance(raw, bool) else None,
                     "last_beat": hwbeat.get("lastBeatAt")}
        except pg.GatewayError as exc:
            state = {"error": exc}
        if self.record_status:
            write_status(state, self.status_folder)
        return state

    # -- tools -------------------------------------------------------------------------------

    def handle_tool(self, hermes_name: str, args: dict[str, Any]) -> str:
        gateway_name = TOOLS[hermes_name]
        if hermes_name in SEAL_TOOLS:
            refusal = self._unverified_refusal()
            if refusal:
                return json.dumps({"error": refusal})
        try:
            result = self.gateway.call(gateway_name, args or {})
        except pg.GatewayError as exc:
            return json.dumps({"error": words.for_error(exc)})
        return json.dumps(result if isinstance(result, (dict, list)) else {"result": result})

    def _unverified_refusal(self) -> Optional[str]:
        """Say plainly, before trying, that a PRSN not yet verified cannot seal."""
        state = self.state()
        if "error" in state:
            return None  # let the Seal call report PRSN Connect's own words
        if state.get("verified") is False:
            return words.seal_refusal(state.get("last_beat"))
        return None

    # -- hooks -------------------------------------------------------------------------------

    def pre_tool_call(self, tool_name: str = "", args: Optional[dict] = None, **kwargs: Any):
        if tool_name not in SEAL_TOOLS:
            return None
        return {
            "action": "approve",
            "message": words.approve_seal(TOOLS[tool_name], args or {}, self.current_prsn()),
            "rule_key": f"prsn-id:{tool_name}",
        }

    def pre_llm_call(self, session_id: str = "", user_message: Any = None,
                     is_first_turn: bool = False, **kwargs: Any):
        deadline = time.monotonic() + HOOK_BUDGET_SECONDS
        session = self.sessions.get(session_id or "-")
        lines: list[str] = []
        own_name: Optional[str] = None

        if is_first_turn or session["identity_due"]:
            state = self.state(timeout=HOOK_CALL_TIMEOUT, deadline=deadline)
            error = state.get("error")
            if error is not None and error.code in (pg.NO_DISCOVERY, pg.NO_PRSN):
                lines.append(words.identity_line(None, None, reason=words.for_error(error)))
            elif error is not None:
                # Say why, so the agent can tell its human what to fix.
                lines.append(words.identity_line("", None, reason=words.for_error(error)))
            else:
                own_name = state.get("name")
                lines.append(words.identity_line(
                    own_name, state.get("verified"),
                    (self.setting("guardian", "") or "").strip() or None,
                    last_beat_at=state.get("last_beat")))
            session["identity_due"] = False

        return {"context": "\n".join([words.CONTEXT_LABEL, *lines])} if lines else None

    def post_compaction(self, session_id: str = "", **kwargs: Any) -> None:
        # The return is ignored by Hermes, so the line comes on the next turn.
        if session_id:
            self.sessions.mark_identity_due(session_id)
        old = kwargs.get("old_session_id")
        if old:
            self.sessions.mark_identity_due(old)

    # -- /prsn ---------------------------------------------------------------------------------

    def command(self, raw_args: str = "", **kwargs: Any) -> str:
        parts = (raw_args or "").split()
        verb = parts[0].lower() if parts else "status"
        if verb == "status":
            return self.status_text()
        if verb == "setup":
            return words.SETUP
        if verb == "about":
            return words.about(plugin_version(), CODE_FINGERPRINT)
        return words.HELP

    def status_text(self) -> str:
        state = self.state()
        error = state.get("error")
        if error is not None:
            if error.code in (pg.NO_DISCOVERY, pg.NO_PRSN):
                return f"{words.STATE_NONE_HERE}\n{words.for_error(error)}\n/prsn setup shows how."
            return words.for_error(error)
        name, verified = state.get("name") or "This PRSN", state.get("verified")
        if verified is None:
            return f"PRSN ID {name}\nIts verified state could not be read just now. Try again in a moment."
        if not verified:
            return f"PRSN ID {name}\n{words.not_verified_now(state.get('last_beat'))}"
        beat = words.heartbeat_ago(state.get("last_beat"))
        return f"PRSN ID {name}\n{words.STATE_VERIFIED}" + (f" {beat}" if beat else "")


def register(ctx: Any) -> None:
    runtime = Runtime(ctx)
    schemas = _load_tool_schemas()

    def make_handler(hermes_name: str):
        def handler(args: dict, **kwargs: Any) -> str:
            return runtime.handle_tool(hermes_name, args)
        return handler

    for hermes_name, schema in schemas.items():
        ctx.register_tool(name=hermes_name, toolset=TOOLSET, schema=schema,
                          handler=make_handler(hermes_name), description=schema["description"],
                          emoji=EMOJI)

    ctx.register_hook("pre_tool_call", runtime.pre_tool_call)
    ctx.register_hook("pre_llm_call", runtime.pre_llm_call)
    ctx.register_hook("post_compaction", runtime.post_compaction)
    ctx.register_command("prsn", runtime.command,
                         description="This agent's PRSN ID, and how to set one up",
                         args_hint="[status | setup | about]")
